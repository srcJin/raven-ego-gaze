# EgoGaze dataset format

Schema version `1.0` is intended for inspection and downstream conversion. No robot controller actions are included.

```text
session-<UTC date>-<unique id>/
  manifest.json
  gaze.jsonl
  frames.jsonl
  frames/
    000000.jpg
    000001.jpg
```

## Timing and pairing

The live app uses one process's `time.monotonic_ns()` clock. Each gaze query records start and return times. Each camera call records start and return times. The camera return timestamp precedes color conversion and UI delivery.

When a frame reaches the recorder, it chooses the gaze sample with the nearest host-return timestamp from the currently available buffer. Its signed `delta_ns` is `gaze.host_received_ns - frame.host_received_ns`. Pairing does not wait for future observations. Camera acquisition latency and sensor buffering can differ even when this delta is small.

Acceptance requires a valid gaze coordinate, nonnegative call durations, absolute host delta at most 50 ms, gaze query duration at most 50 ms, and camera call duration at most 150 ms. An invalid nearest sample remains invalid; an older valid observation is not substituted. Frames with rejected associations remain in the dataset with a reason code.

The default synthetic loop emits images at 5 Hz and samples gaze at 50 Hz. Actual rates depend on scheduling and camera latency. Playback follows the recorded frame timestamps. The generated media sample instead uses a deterministic virtual nanosecond clock and identifies that clock in its manifest.

## Gaze observations

Each `gaze.jsonl` line contains:

| Field | Meaning |
| --- | --- |
| `query_started_ns`, `host_received_ns` | Host monotonic call boundaries |
| `query_duration_ns` | Return minus start |
| `raw_xy` | Finite numeric coordinates if available, including out-of-bounds values |
| `xy` | Valid coordinates, otherwise `null` |
| `valid`, `invalid_reason` | Basic type, range and timestamp-order checks |
| `confidence` | Always `null`; unavailable from this SDK |
| `coordinate_space` | `synthetic_scene_pixels` or `sdk_gaze_pixels_unverified` |
| `coordinate_bounds_assumption` | `[960,500]` for this synthetic scene; `[720,720]` for SDK display assumptions |
| `source` | `simulator`, `device`, or `desktop_camera` |

Booleans, malformed pairs, negative coordinates, out-of-range coordinates, NaN, and infinity cannot become valid gaze. Desktop webcam capture intentionally records unavailable eye tracking. It does not label a mouse cursor as a person's gaze.

## Frame records

Each `frames.jsonl` line names the raw JPEG and records its actual dimensions, frame index, camera call boundaries, and call duration. `camera_exposure_timestamp_ns` is `null` because the API does not provide it.

The nested `association` includes the selected gaze observation, signed time delta, acceptance flag, and a reason (`accepted`, `no_sample`, `missing_or_invalid_gaze`, `timestamp_order`, `slow_capture_call`, or `timing_limit`).

`scene_gaze_xy` and `scene_projection_valid` describe usable image-space supervision. They are available only for valid synthetic associations. Real-device records always have `null` and `false` respectively. Passing the host-time quality gates does not enable scene projection.

## Manifest

The manifest records schema version, source, clock definition, start/end times, completion state, filenames, bounds assumption, calibration state, quality thresholds, frame/sample counts, accepted-association count, coverage, and maximum observed absolute host delta.

`calibration.status` is `synthetic_identity` for the demo and `unavailable` for real capture. `robot_actions_available` and `confidence_available` are false. `camera_exposure_timestamp_available` is false.

A new session writes a `recording` manifest immediately. On stop, metadata changes to `complete` or `error`. A process interruption may leave a `recording` manifest and an unindexed JPEG or temporary file. Downstream consumers should use indexed frames and require a completed session, or deliberately inspect partial data before recovery.

## Example consumer

This reads only accepted, explicitly projected synthetic examples. The same gate deliberately excludes uncalibrated device data.

```python
import json
from pathlib import Path

session = Path('sample-session')
manifest = json.loads((session / 'manifest.json').read_text())
assert manifest['status'] == 'complete'

examples = []
for line in (session / 'frames.jsonl').read_text().splitlines():
    frame = json.loads(line)
    if not frame['association']['valid'] or not frame['scene_projection_valid']:
        continue
    x, y = frame['scene_gaze_xy']
    examples.append({
        'image': str(session / frame['file']),
        'attention_xy_normalized': [x / frame['width'], y / frame['height']],
        'source': manifest['source'],
    })
print(f'{len(examples)} synthetic attention examples')
```

## Before real attention supervision

Measure gaze-to-camera calibration using the actual device's coordinate convention, camera intrinsics and eye/camera geometry. Validate projection over relevant distances, including parallax. Characterize eye and camera buffering or acquire hardware timestamps. Preserve calibration identity and uncertainty in any derived dataset. Do not obtain real frame labels by merely scaling the SDK's display coordinates to camera resolution.
