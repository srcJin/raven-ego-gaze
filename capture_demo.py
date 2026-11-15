"""Render actual EgoGaze recording, replay and export with narration-aligned chapters."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtCore import QRectF
from main import EgoGaze

FPS=25
media=Path('media')
timeline=json.loads((media/'timeline.json').read_text())
chapters=timeline['chapters']
qt=QApplication([])
now=[0]
with tempfile.TemporaryDirectory() as output:
    widget=EgoGaze(clock=lambda:now[0],output=output)
    widget.timer.stop()
    widget.show()
    qt.processEvents()
    record_at=round(chapters[1]['start']*FPS)
    stop_at=round(chapters[2]['start']*FPS)
    review_at=stop_at+40
    export_at=stop_at+80
    screenshots={25:'01-ready.png',record_at+60:'02-recording.png',stop_at+15:'03-complete.png',export_at+20:'04-replay-export.png'}
    encoder=subprocess.Popen(['ffmpeg','-y','-f','rawvideo','-pixel_format','rgba','-video_size','1280x900','-framerate',str(FPS),'-i','-','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart','media/demo-silent.mp4'],stdin=subprocess.PIPE,stderr=subprocess.DEVNULL)
    captions=[('EgoGaze','Human attention, recorded for robot learning.'),('Record what matters.','Raw frames + gaze + host timing.'),('Inspect. Replay. Export.','An open, documented session format.'),('Calibration stays explicit.','Real SDK gaze is not yet scene-camera supervision.')]
    for frame in range(round(timeline['duration']*FPS)):
        now[0]=frame*40_000_000
        if frame==record_at:
            widget.toggle_record()
            widget.session.manifest["clock"]="Deterministic simulator nanoseconds (media harness)"
        if frame==stop_at:
            widget.stop_recording()
        if frame==review_at:
            widget.review()
        if frame==export_at:
            widget.export()
        widget.tick()
        now[0]+=20_000_000
        widget.tick()
        qt.processEvents()
        shot=widget.app.grab().toImage()
        if frame in screenshots:
            assert shot.save(str(media/screenshots[frame]))
        canvas=QImage(1280,900,QImage.Format.Format_RGBA8888)
        canvas.fill(QColor('#0A120B'))
        painter=QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(QRectF(320,45,640,640),shot)
        painter.setPen(QColor('#D3F780'))
        painter.setFont(QFont('Helvetica',12))
        painter.drawText(48,52,'RAVEN MINI HACK  /  EGOGAZE')
        painter.drawText(48,855,'SIMULATOR DEMO · SYNTHETIC SCENE AND GAZE · NO DEVICE FOOTAGE')
        chapter=max(index for index,value in enumerate(chapters) if now[0]/1e9>=value['start'])
        painter.setPen(QColor('#EEF2E9'))
        painter.setFont(QFont('Helvetica',25,QFont.Weight.Medium))
        painter.drawText(320,743,captions[chapter][0])
        painter.setPen(QColor('#A1AFA6'))
        painter.setFont(QFont('Helvetica',16))
        painter.drawText(320,783,captions[chapter][1])
        painter.end()
        encoder.stdin.write(bytes(canvas.constBits()))
    encoder.stdin.close()
    assert encoder.wait()==0
    assert widget.session.closed and widget.session.frame_count>10
    assert widget.last_export.exists()
    # Public sample contains only our original synthetic scene and synthetic gaze.
    destination=Path('sample-session')
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(widget.session.path,destination)
    widget.shutdown()
subprocess.run(['ffmpeg','-y','-i','media/demo-silent.mp4','-i','media/narration.wav','-c:v','copy','-c:a','aac','-b:a','160k','-shortest','-movflags','+faststart','media/demo.mp4'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('Rendered four screenshots and a narrated demo. Verified recording, replay and ZIP export.')
