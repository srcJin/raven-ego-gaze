import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from main import EgoGaze

class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def test_record_review_export_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[0]
            app=EgoGaze(clock=lambda:now[0],output=folder)
            app.timer.stop()
            app.toggle_record()
            for i in range(50):
                now[0]=i*20_000_000
                app.tick()
            app.stop_recording()
            self.assertEqual(app.phase,'complete')
            self.assertEqual(app.session.frame_count,5)
            self.assertEqual(app.session.gaze_count,50)
            rows=[json.loads(line) for line in (app.session.path/'frames.jsonl').read_text().splitlines()]
            self.assertTrue(all(row['scene_projection_valid'] for row in rows))
            for row in rows:
                self.assertFalse(QImage(str(app.session.path/row['file'])).isNull())
            app.review()
            now[0]+=200_000_000
            app.tick()
            self.assertEqual(app.phase,'review')
            self.assertEqual(app.replay_index,1)
            app.export()
            self.assertTrue(app.last_export.exists())
            app.shutdown()
            app.close()

    def test_shortcut_cannot_restart_before_worker_finishes(self):
        class BusyWorker:
            def isRunning(self):
                return True
            def requestInterruption(self):
                pass
            def wait(self):
                pass
        with tempfile.TemporaryDirectory() as folder:
            app=EgoGaze(output=folder)
            app.timer.stop()
            app.worker=BusyWorker()
            app.fail('Camera denied')
            app.toggle_record()
            self.assertIsNone(app.session)
            self.assertEqual(app.phase,'error')
            self.assertIn('Camera denied',app.message)
            app.worker=None
            app.close()

    def test_replay_uses_recorded_frame_times(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[0]
            app=EgoGaze(clock=lambda:now[0],output=folder)
            app.timer.stop()
            app.toggle_record()
            for timestamp in [0,300_000_000,900_000_000]:
                now[0]=timestamp
                app.tick()
            app.stop_recording()
            app.review()
            now[0]+=500_000_000
            app.tick()
            self.assertEqual(app.replay_index,1)
            now[0]+=450_000_000
            app.tick()
            self.assertEqual(app.replay_index,2)
            app.close()
