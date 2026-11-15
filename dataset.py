"""Local recording and explicit host-time association for gaze + scene datasets."""
import json
import math
from numbers import Real
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MAX_ASSOCIATION_NS = 50_000_000


def gaze_sample(raw, started_ns, received_ns, source):
    dimensions = (960, 500) if source == 'simulator' else (720, 720)
    shape_valid = isinstance(raw, (tuple, list)) and len(raw) == 2
    numeric = shape_valid and all(isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) for value in raw)
    coordinates = [float(value) for value in raw] if numeric else None
    bounds_valid = numeric and all(0 <= value < bound for value, bound in zip(coordinates, dimensions))
    timestamps_valid = 0 <= started_ns <= received_ns
    valid = bool(bounds_valid and timestamps_valid)
    return {
        'query_started_ns': started_ns,
        'host_received_ns': received_ns,
        'query_duration_ns': received_ns-started_ns,
        'xy': coordinates if valid else None,
        'raw_xy': coordinates,
        'valid': valid,
        'invalid_reason': None if valid else ('coordinate_or_missing' if not bounds_valid else 'timestamp_order'),
        'confidence': None,
        'coordinate_space': 'synthetic_scene_pixels' if source == 'simulator' else 'sdk_gaze_pixels_unverified',
        'coordinate_bounds_assumption': list(dimensions),
        'source': source,
    }


def associate(samples, frame_received_ns, capture_started_ns=None):
    """Nearest host-receipt sample, never an asserted exposure-time alignment."""
    if not samples:
        return {'gaze': None, 'delta_ns': None, 'valid': False, 'reason': 'no_sample'}
    nearest = min(samples, key=lambda sample: abs(sample['host_received_ns']-frame_received_ns))
    delta = nearest['host_received_ns']-frame_received_ns
    duration = nearest['query_duration_ns']
    capture_duration = frame_received_ns-capture_started_ns if capture_started_ns is not None else 0
    reason = 'accepted'
    if not nearest['valid']:
        reason = 'missing_or_invalid_gaze'
    elif frame_received_ns < 0 or capture_duration < 0 or duration < 0:
        reason = 'timestamp_order'
    elif capture_duration > 150_000_000:
        reason = 'slow_capture_call'
    elif abs(delta) > MAX_ASSOCIATION_NS or duration > MAX_ASSOCIATION_NS:
        reason = 'timing_limit'
    return {'gaze': nearest, 'delta_ns': delta, 'valid': reason == 'accepted', 'reason': reason}


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n')
    temporary.replace(path)


class Session:
    def __init__(self, root, source, started_ns=None):
        self.path = Path(root)/('session-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid4().hex[:8])
        (self.path/'frames').mkdir(parents=True)
        self.started_ns = started_ns if started_ns is not None else time.monotonic_ns()
        self.frame_count = 0
        self.gaze_count = 0
        self.accepted_count = 0
        self.closed = False
        self.delta_ms = []
        self.manifest = {
            'schema_version':'1.0', 'session_id':self.path.name,
            'created_at_utc':datetime.now(timezone.utc).isoformat(),
            'status':'recording', 'source':source,
            'clock':'Python time.monotonic_ns, same process, host receipt',
            'started_ns':self.started_ns,
            'camera_exposure_timestamp_available':False,
            'association':'nearest observed gaze host receipt; no exposure-time synchronization guarantee',
            'maximum_association_delta_ms':50,
            'maximum_gaze_query_ms':50,
            'maximum_capture_call_ms':150,
            'gaze_coordinate_space':'synthetic_scene_pixels' if source=='simulator' else 'sdk_gaze_pixels_unverified',
            'sdk_display_resolution':[720,720],
            'calibration':{'status':'synthetic_identity' if source=='simulator' else 'unavailable','scene_projection_valid':source=='simulator'},
            'confidence_available':False,
            'robot_actions_available':False,
            'files':{'gaze':'gaze.jsonl','frames':'frames.jsonl'},
        }
        atomic_json(self.path/'manifest.json',self.manifest)
        self.gaze_file = (self.path/'gaze.jsonl').open('w')
        self.frame_file = (self.path/'frames.jsonl').open('w')

    def add_gaze(self, sample):
        if self.closed:
            raise RuntimeError('Session is finalized')
        self.gaze_file.write(json.dumps(sample,allow_nan=False)+'\n')
        self.gaze_file.flush()
        self.gaze_count += 1

    def add_frame(self, jpeg, width, height, started_ns, received_ns, association):
        if self.closed:
            raise RuntimeError('Session is finalized')
        name = f'frames/{self.frame_count:06d}.jpg'
        path = self.path/name
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(jpeg)
        temporary.replace(path)
        gaze = association['gaze']
        projected = self.manifest['source']=='simulator' and association['valid']
        row = {
            'frame_index':self.frame_count,'file':name,'width':width,'height':height,
            'request_started_ns':started_ns,'host_received_ns':received_ns,
            'capture_call_duration_ns':received_ns-started_ns,
            'camera_exposure_timestamp_ns':None,
            'association':association,
            'scene_gaze_xy':gaze['xy'] if projected else None,
            'scene_projection_valid':projected,
        }
        self.frame_file.write(json.dumps(row,allow_nan=False)+'\n')
        self.frame_file.flush()
        self.frame_count += 1
        self.accepted_count += int(association['valid'])
        if association['delta_ns'] is not None:
            self.delta_ms.append(abs(association['delta_ns'])/1e6)
        self.last_frame = row
        return row

    def finish(self, ended_ns=None, error=None):
        if self.closed:
            return self.path
        self.closed = True
        for stream in [self.gaze_file,self.frame_file]:
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
        ended_ns = ended_ns if ended_ns is not None else time.monotonic_ns()
        self.manifest.update({
            'status':'error' if error else 'complete', 'error':error,
            'ended_ns':ended_ns,'duration_seconds':max(0,(ended_ns-self.started_ns)/1e9),
            'frame_count':self.frame_count,'gaze_sample_count':self.gaze_count,
            'accepted_association_count':self.accepted_count,
            'association_coverage':self.accepted_count/self.frame_count if self.frame_count else 0,
            'max_observed_delta_ms':max(self.delta_ms) if self.delta_ms else None,
        })
        atomic_json(self.path/'manifest.json',self.manifest)
        return self.path

    def export(self):
        if not self.closed:
            raise RuntimeError('Stop recording before export')
        destination = self.path.with_suffix('.zip')
        temporary = destination.with_suffix('.zip.tmp')
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(self.path.rglob('*')):
                if file.is_file() and file.suffix != '.tmp':
                    archive.write(file,arcname=str(file.relative_to(self.path)))
        temporary.replace(destination)
        return destination
