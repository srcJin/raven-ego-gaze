"""Record the visible official Raven simulator, then trim preroll and add narration.

Requires a graphical desktop, FFmpeg, and media/narration.wav from narrate.mjs.
The video contains only the official simulator's recorded frames.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def recording_offset(log):
    started = re.search(r'^RECORD_T0 monotonic_ns=(\d+)$', log, re.MULTILINE)
    demo = re.search(r'^DEMO_T0 monotonic_ns=(\d+)$', log, re.MULTILINE)
    if not started or not demo:
        raise RuntimeError('The official recorder did not report its start timestamps.')
    offset = (int(demo.group(1)) - int(started.group(1))) / 1e9
    if not 0 <= offset <= 5:
        raise RuntimeError(f'Unexpected recording preroll: {offset:.3f} seconds')
    return offset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'media/demo.mp4')
    args = parser.parse_args()
    if os.environ.get('QT_QPA_PLATFORM') in ('offscreen', 'minimal'):
        parser.error('Use a graphical desktop for official simulator recording.')
    audio = ROOT / 'media/narration.wav'
    if not audio.is_file():
        parser.error('Generate the Cartesia narration first with node narrate.mjs.')
    timeline = json.loads((ROOT / 'media/timeline.json').read_text())
    destination = args.output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='egogaze-official-') as folder:
        temporary = Path(folder)
        raw = temporary / 'official-recording.mp4'
        command = [sys.executable, '-u', str(ROOT / 'live_demo.py'),
                   '--preroll', '2', '--record-output', str(raw),
                   '--output', str(temporary / 'synthetic-sessions'), '--exit-after-save']
        print('Opening the official Raven simulator and recording the live demo.', flush=True)
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeline['duration'] + 90)
        if result.returncode or not raw.is_file():
            raise RuntimeError('Official simulator recording failed.\n' + result.stdout[-4000:])
        offset = recording_offset(result.stdout)
        subprocess.run([
            'ffmpeg', '-y', '-ss', f'{offset:.9f}', '-i', str(raw), '-i', str(audio),
            '-map', '0:v:0', '-map', '1:a:0', '-t', str(timeline['duration']),
            '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart',
            str(destination),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print(f'Saved official simulator recording with English narration to {destination}')
        print(f'Trimmed {offset:.3f} seconds of preroll. No external titles or overlays were added.')


if __name__ == '__main__':
    main()
