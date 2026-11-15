import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from dataset import Session, associate, gaze_sample

class DatasetTests(unittest.TestCase):
    def sample(self,point=(200,200),timestamp=100_000_000,source='simulator'):
        return gaze_sample(point,timestamp-1_000_000,timestamp,source)

    def test_nearest_association_preserves_signed_delta(self):
        samples=[self.sample(timestamp=90_000_000),self.sample(timestamp=110_000_000)]
        paired=associate(samples,108_000_000,100_000_000)
        self.assertTrue(paired['valid'])
        self.assertEqual(paired['delta_ns'],2_000_000)

    def test_stale_gaze_is_not_substituted(self):
        paired=associate([self.sample()],160_000_000)
        self.assertFalse(paired['valid'])
        self.assertEqual(paired['reason'],'timing_limit')

    def test_missing_latest_sample_is_not_replaced_with_old_valid_sample(self):
        paired=associate([self.sample(timestamp=90_000_000),self.sample(None,100_000_000)],100_000_000)
        self.assertFalse(paired['valid'])
        self.assertIsNone(paired['gaze']['xy'])

    def test_malformed_and_out_of_bounds(self):
        for raw in [None,3,(),(1,),(1,2,3),(True,2),(float('nan'),2),(-1,2),(960,2),(2,500)]:
            with self.subTest(raw=raw):
                self.assertFalse(self.sample(raw)['valid'])
        self.assertFalse(self.sample((720,200),source='device')['valid'])

    def test_invalid_or_slow_timing(self):
        self.assertFalse(gaze_sample((1,2),10,5,'device')['valid'])
        sample=self.sample()
        self.assertEqual(associate([sample],100_000_000,110_000_000)['reason'],'timestamp_order')
        sample=self.sample(timestamp=200_000_000)
        self.assertEqual(associate([sample],200_000_000,0)['reason'],'slow_capture_call')

    def test_device_never_has_scene_projection(self):
        with tempfile.TemporaryDirectory() as root:
            session=Session(root,'device',0)
            sample=self.sample(source='device')
            session.add_gaze(sample)
            row=session.add_frame(b'fixture',640,480,90_000_000,100_000_000,associate([sample],100_000_000))
            self.assertTrue(row['association']['valid'])
            self.assertIsNone(row['scene_gaze_xy'])
            self.assertFalse(row['scene_projection_valid'])
            session.finish(200_000_000)
            archive=session.export()
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(set(bundle.namelist()),{'manifest.json','gaze.jsonl','frames.jsonl','frames/000000.jpg'})
            manifest=json.loads((session.path/'manifest.json').read_text())
            self.assertEqual(manifest['status'],'complete')
            self.assertEqual(manifest['frame_count'],1)
            self.assertFalse(manifest['calibration']['scene_projection_valid'])
            with self.assertRaises(RuntimeError):
                session.add_gaze(sample)

    def test_unfinished_session_reports_recording(self):
        with tempfile.TemporaryDirectory() as root:
            session=Session(root,'simulator',0)
            self.assertEqual(json.loads((session.path/'manifest.json').read_text())['status'],'recording')
            with self.assertRaises(RuntimeError):
                session.export()
            session.finish(200_000_000,error='Test interruption')
            self.assertEqual(session.manifest['status'],'error')
