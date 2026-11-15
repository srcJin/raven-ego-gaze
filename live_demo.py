"""Play the EgoGaze demo inside the official, visible Raven simulator.

This script drives application actions with Qt timers. Record the actual simulator
window separately. It does not render, capture, composite, or modify video frames.
"""
import argparse
import json
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit
from raven_framework import RunApp
from main import EgoGaze

ROOT = Path(__file__).resolve().parent


class LiveDemo(EgoGaze):
    def __init__(self, timeline, preroll_seconds=2.0, output=None, record=False, record_output=None):
        super().__init__(output=output or ROOT / '.demo-recordings')
        self.record_output = record_output
        self.record_simulator = record
        self.save_watch = None
        self.timeline = timeline
        self.preroll_seconds = preroll_seconds
        self.demo_timers = []
        self.demo_started = False
        self.ready_watch = QTimer(self)
        self.ready_watch.setInterval(50)
        self.ready_watch.timeout.connect(self.wait_for_simulator)
        self.ready_watch.start()

    def wait_for_simulator(self):
        window = self.window()
        if not window.isVisible() or 'Raven App' not in window.windowTitle():
            return
        self.ready_watch.stop()
        print(
            f'DEMO_READY window={window.windowTitle()!r} '
            f'preroll_seconds={self.preroll_seconds:.2f} '
            f'monotonic_ns={time.monotonic_ns()}',
            flush=True,
        )
        if self.record_simulator:
            self.schedule(self.preroll_seconds - 0.5, self.start_simulator_recording)
        self.schedule(self.preroll_seconds, self.begin_demo)

    def schedule(self, seconds, action):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.timeout.connect(action)
        timer.start(round(seconds * 1000))
        self.demo_timers.append(timer)

    def start_simulator_recording(self):
        window = self.window()
        self.simulator_record_start_ns = time.monotonic_ns()
        window._record_button.click()
        print(f"RECORD_T0 monotonic_ns={self.simulator_record_start_ns}", flush=True)

    def begin_demo(self):
        self.demo_started = True
        self.demo_start_ns = time.monotonic_ns()
        print(f'DEMO_T0 monotonic_ns={self.demo_start_ns}', flush=True)
        chapters = self.timeline['chapters']
        self.schedule(chapters[1]['start'], self.toggle_record)
        self.schedule(chapters[2]['start'], self.stop_recording)
        self.schedule(chapters[2]['start'] + 1.6, self.review)
        self.schedule(chapters[2]['start'] + 3.2, self.export)
        self.schedule(self.timeline['duration'], self.demo_finished)

    def save_recording_dialog(self):
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog, QFileDialog) and dialog.isVisible() and dialog.windowTitle() == "Save recording":
                self.save_watch.stop()
                dialog.setDirectory(str(self.record_output.parent))
                dialog.selectFile(self.record_output.name)
                # Qt may ignore selectFile for a new filename while the dialog is visible.
                filename = dialog.findChild(QLineEdit, "fileNameEdit")
                if filename is not None:
                    filename.setText(self.record_output.name)
                dialog.accept()
                self.schedule(0.2, self.report_saved_recording)
                return

    def report_saved_recording(self):
        if self.record_output.is_file():
            print(f"RECORD_SAVED path={self.record_output} bytes={self.record_output.stat().st_size}", flush=True)
        else:
            print("RECORD_SAVE_PENDING check official simulator save status", flush=True)

    def demo_finished(self):
        frames = self.session.frame_count if self.session else 0
        print(
            f'DEMO_DONE elapsed_seconds={(time.monotonic_ns()-self.demo_start_ns)/1e9:.3f} '
            f'frames={frames} export={getattr(self, "last_export", None)}',
            flush=True,
        )
        if self.record_simulator:
            if self.record_output:
                self.save_watch = QTimer(self)
                self.save_watch.setInterval(100)
                self.save_watch.timeout.connect(self.save_recording_dialog)
                self.save_watch.start()
            print(f"RECORD_STOP monotonic_ns={time.monotonic_ns()}", flush=True)
            self.window()._record_button.click()
        # The official simulator opens its normal Save recording dialog.
        # Keep the window visible so the user or recorder can save the result.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preroll', type=float, default=2.0,
                        help='Seconds between visible simulator detection and narration time zero.')
    parser.add_argument('--record', action='store_true',
                        help='Use the official simulator Record button, then show its Save recording dialog.')
    parser.add_argument('--record-output', type=Path,
                        help='Save the official recording to a new MP4 file using its Qt save dialog. Implies --record.')
    parser.add_argument('--output', type=Path, default=ROOT / '.demo-recordings',
                        help='Directory for synthetic demo sessions and ZIP exports.')
    args = parser.parse_args()
    if args.record_output:
        args.record = True
        args.record_output = args.record_output.expanduser().resolve()
        if args.record_output.exists():
            parser.error("--record-output must name a new file")
        args.record_output.parent.mkdir(parents=True, exist_ok=True)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    if args.preroll < 0:
        parser.error('--preroll must be nonnegative')
    if args.record and args.preroll < 0.5:
        parser.error('--record requires at least 0.5 seconds of preroll')
    timeline = json.loads((ROOT / 'media' / 'timeline.json').read_text())
    RunApp.run(lambda: LiveDemo(timeline, args.preroll, args.output, args.record, args.record_output), app_id='', app_key='')


if __name__ == '__main__':
    main()
