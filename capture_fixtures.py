"""Development-only: export app-widget PNGs and a synthetic dataset fixture.

This does not produce video. Use capture_demo.py for official simulator recording.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import shutil
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from main import EgoGaze

ROOT = Path(__file__).resolve().parent


def main():
    qt = QApplication([])
    now = [0]
    with tempfile.TemporaryDirectory() as output:
        widget = EgoGaze(clock=lambda: now[0], output=output)
        widget.timer.stop()
        widget.show()
        screenshots = {50: '01-ready.png', 150: '02-recording.png',
                       305: '03-complete.png', 355: '04-replay-export.png'}
        for tick in range(400):
            now[0] = tick * 20_000_000
            if tick == 100:
                widget.toggle_record()
                widget.session.manifest['clock'] = 'Deterministic simulator nanoseconds (fixture harness)'
            elif tick == 300:
                widget.stop_recording()
            elif tick == 315:
                widget.review()
            elif tick == 330:
                widget.export()
            widget.tick()
            qt.processEvents()
            if tick in screenshots:
                assert widget.app.grab().save(str(ROOT / 'media' / screenshots[tick]))
        assert widget.session.closed and widget.last_export.exists()
        destination = ROOT / 'sample-session'
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(widget.session.path, destination)
        widget.shutdown()
        widget.close()
    print('Updated development PNG fixtures and the synthetic sample session. No video was generated.')


if __name__ == '__main__':
    main()
