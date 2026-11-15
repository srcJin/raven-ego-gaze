"""EgoGaze — inspectable egocentric attention recording for Raven."""
import json
from bisect import bisect_right
import math
import os
import sys
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import QApplication, QWidget
from raven_framework import Button, RavenApp, RunApp, VerticalContainer
from raven_framework.helpers.font_utils import load_font_family
from raven_framework.helpers.utils_light import is_raven_device
from dataset import Session, associate, gaze_sample

LIME = '#D3F780'
WHITE = '#EEF2E9'
GREY = '#A1AFA6'


def synthetic_scene():
    image = QImage(960,500,QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    background = QLinearGradient(0,0,960,500)
    background.setColorAt(0,QColor('#25332C'))
    background.setColorAt(1,QColor('#101B16'))
    painter.fillRect(image.rect(),background)
    painter.setPen(QPen(QColor('#35443B'),1))
    for x in range(-200,1200,90):
        painter.drawLine(x,0,x+200,500)
    for y in range(50,500,70):
        painter.drawLine(0,y,960,y)
    painter.setPen(Qt.PenStyle.NoPen)
    for x,y,width in [(220,300,160),(490,290,165),(750,300,150)]:
        painter.setBrush(QColor(0,0,0,70))
        painter.drawEllipse(QRectF(x-width/2,y+50,width,50))
    # Original, synthetic tabletop objects; exported frames contain no gaze overlay.
    painter.setBrush(QColor('#C17651'))
    painter.drawRoundedRect(QRectF(150,150,150,160),18,18)
    painter.setBrush(QColor('#E5A777'))
    painter.drawEllipse(QRectF(150,125,150,70))
    painter.setBrush(QColor('#905239'))
    painter.drawEllipse(QRectF(178,142,94,36))
    painter.setPen(QPen(QColor('#C17651'),20))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(278,180,65,80))
    painter.setPen(Qt.PenStyle.NoPen)
    top=QPainterPath(QPointF(420,155))
    for point in [(535,120),(600,165),(485,205)]:
        top.lineTo(*point)
    top.closeSubpath()
    painter.fillPath(top,QColor('#DBEAA8'))
    left=QPainterPath(QPointF(420,155))
    for point in [(485,205),(485,340),(420,290)]:
        left.lineTo(*point)
    left.closeSubpath()
    painter.fillPath(left,QColor('#728759'))
    right=QPainterPath(QPointF(485,205))
    for point in [(600,165),(600,300),(485,340)]:
        right.lineTo(*point)
    right.closeSubpath()
    painter.fillPath(right,QColor('#AFC57C'))
    painter.setBrush(QColor('#7299A0'))
    painter.drawRoundedRect(QRectF(705,180,95,160),18,18)
    painter.setBrush(QColor('#B0D1CE'))
    painter.drawEllipse(QRectF(705,155,95,50))
    painter.setBrush(QColor('#46696B'))
    painter.drawEllipse(QRectF(725,169,55,23))
    painter.end()
    return image


def simulated_gaze(seconds):
    targets=[(230,230),(510,225),(750,245),(510,225)]
    step=int(seconds/1.4)%len(targets)
    x,y=targets[step]
    return x+math.sin(seconds*2)*8,y+math.cos(seconds*2)*6


def jpeg_bytes(image):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer,'JPG',92):
        raise OSError('Frame encoding failed')
    return bytes(buffer.data())


class CameraStream(QThread):
    frame = Signal(object,object,object)
    failed = Signal(str)

    def run(self):
        camera = None
        try:
            import cv2
            from raven_framework.peripherals.camera import Camera
            camera = Camera(app_id=os.getenv('RAVEN_APP_ID',''),app_key=os.getenv('RAVEN_APP_KEY',''))
            if is_raven_device() and camera.sensorlib_client is None:
                raise RuntimeError('Raven camera sensor unavailable.')
            camera.open_camera()
            if not camera.is_camera_open():
                raise RuntimeError('Camera unavailable. Check device permissions.')
            while not self.isInterruptionRequested():
                started = time.monotonic_ns()
                array = camera.capture_camera_image()
                received = time.monotonic_ns()
                if array is None:
                    raise RuntimeError('Camera returned no frame.')
                rgb=cv2.cvtColor(array,cv2.COLOR_BGR2RGB)
                height,width,_=rgb.shape
                image=QImage(rgb.data,width,height,rgb.strides[0],QImage.Format.Format_RGB888).copy()
                self.frame.emit(image,started,received)
                self.msleep(200)
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if camera:
                camera.close_camera()


class SceneView(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner=owner
        self.setFixedSize(600,480)
        self.setAccessibleName('EgoGaze recording dashboard')

    def paintEvent(self,event):
        app=self.owner
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        def text(x,y,value,size=20,color=WHITE,bold=False):
            font=QFont('Inter 24pt')
            font.setPixelSize(size)
            font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(QColor(color))
            painter.drawText(x,y,value)
        text(8,27,'EGOGAZE',21,WHITE,True)
        source='SIMULATOR' if app.source=='simulator' else ('DEVICE' if app.source=='device' else 'WEBCAM')
        text(463,27,source,15,LIME,True)
        painter.setPen(QPen(QColor('#314332'),1))
        painter.drawLine(8,44,590,44)
        headings={'ready':'Teach where to look.','recording':'Attention, captured.','complete':'A session you can inspect.','review':'Replay the human focus.','error':'Check the connection.','stopping':'Finishing this session.'}
        text(8,86,headings[app.phase],31,WHITE,True)
        frame=QRectF(8,110,582,280)
        path=QPainterPath()
        path.addRoundedRect(frame,14,14)
        painter.save()
        painter.setClipPath(path)
        if app.image is not None:
            # Fit image to keep both exported and displayed coordinates interpretable.
            image=app.image
            scale=min(frame.width()/image.width(),frame.height()/image.height())
            target=QRectF(frame.center().x()-image.width()*scale/2,frame.center().y()-image.height()*scale/2,image.width()*scale,image.height()*scale)
            painter.fillRect(frame,QColor('#0C1710'))
            painter.drawImage(target,image)
            if app.source=='simulator' and app.gaze_xy is not None:
                point=QPointF(target.x()+app.gaze_xy[0]*scale,target.y()+app.gaze_xy[1]*scale)
                painter.setPen(QPen(QColor(LIME),2))
                painter.setBrush(QColor(211,247,128,30))
                painter.drawEllipse(point,20,20)
                painter.setBrush(QColor(LIME))
                painter.drawEllipse(point,4,4)
                for previous in app.trace:
                    painter.setBrush(QColor(211,247,128,70))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(QPointF(target.x()+previous[0]*scale,target.y()+previous[1]*scale),2,2)
        else:
            painter.fillRect(frame,QColor('#101D15'))
            text(144,240,'Camera starts on Record',22,GREY)
        painter.restore()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(LIME if app.phase=='recording' else '#7C8B7F'))
        painter.drawEllipse(QPointF(25,128),4,4)
        text(37,134,'REC' if app.phase=='recording' else 'VIEW',12,LIME)
        text(20,377,'SYNTHETIC SCENE + GAZE' if app.source=='simulator' else 'RAW CAMERA · GAZE PROJECTION UNAVAILABLE',13,WHITE)
        session=app.session
        count=session.frame_count if session else 0
        coverage=round(100*session.accepted_count/count) if count else 0
        delta=session.delta_ms[-1] if session and session.delta_ms else None
        for x,value,label in [(8,str(count),'FRAMES'),(210,f'{coverage}%','TIME MATCHED'),(425,f'{delta:.0f} ms' if delta is not None else '—','HOST Δ')]:
            text(x,420,value,30,LIME,True)
            text(x,444,label,13,GREY)
        font=QFont('Inter 24pt')
        font.setPixelSize(14)
        painter.setFont(font)
        status=painter.fontMetrics().elidedText(app.message,Qt.TextElideMode.ElideMiddle,582)
        text(8,473,status,14,LIME if app.phase=='complete' else GREY)
        painter.end()


class EgoGaze(RavenApp):
    def __init__(self,parent=None,clock=time.monotonic_ns,output=None):
        load_font_family('inter')
        super().__init__(parent)
        self.clock=clock
        self.output=Path(output or os.getenv('GAZE_RECORDINGS_DIR',str(Path.home()/'Documents'/'EgoGaze')))
        self.source='simulator'
        self.phase='ready'
        self.message='R to record · Local frames + gaze JSONL'
        self.image=synthetic_scene()
        self.scene=self.image
        self.gaze_xy=simulated_gaze(0)
        self.trace=deque(maxlen=45)
        self.samples=deque(maxlen=300)
        self.session=None
        self.worker=None
        self.eye=None
        self.last_frame_ns=0
        self.recording_start_ns=0
        self.replay_rows=[]
        self.replay_index=0
        self.replay_started_ns=0
        self.replay_offsets=[]
        self.replay_duration_ns=1
        root=VerticalContainer(width=640,height=640,inner_margin=(20,15),spacing=10,is_main_container=True,background_color='#000000',border_width=0)
        self.view=SceneView(self)
        panel=QWidget()
        panel.setFixedSize(600,120)
        self.record_button=self.make_button(panel,'Record',424,0,176,self.toggle_record)
        self.review_button=self.make_button(panel,'Review',252,0,160,self.review)
        self.export_button=self.make_button(panel,'Export ZIP',424,62,176,self.export)
        self.mode_button=self.make_button(panel,'Use camera',220,62,192,self.change_mode)
        self.review_button.set_disabled(True)
        self.export_button.set_disabled(True)
        root.add(self.view,panel)
        self.app.add(root)
        self.record_shortcut=QShortcut(QKeySequence('R'),self)
        self.record_shortcut.activated.connect(self.toggle_record)
        self.export_shortcut=QShortcut(QKeySequence('E'),self)
        self.export_shortcut.activated.connect(self.export)
        self.timer=QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(20)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def make_button(self,parent,label,x,y,width,callback):
        button=Button(center_text=label,width=width,height=52,text_size=23,background_color='#25371A')
        button.setParent(parent)
        button.move(x,y)
        button.on_clicked(callback)
        return button

    def change_mode(self):
        if self.phase in ('recording','stopping'):
            return
        self.source='simulator' if self.source!='simulator' else ('device' if is_raven_device() else 'desktop_camera')
        self.mode_button.set_text('Use camera' if self.source=='simulator' else 'Use demo')
        self.image=self.scene if self.source=='simulator' else None
        self.gaze_xy=None
        self.session=None
        self.phase='ready'
        self.message='Synthetic eye + scene input' if self.source=='simulator' else ('Live camera + SDK gaze' if self.source=='device' else 'Webcam only · gaze unavailable')
        self.review_button.set_disabled(True)
        self.export_button.set_disabled(True)
        self.samples.clear()
        self.trace.clear()
        if self.source=='device':
            from raven_framework.peripherals.eye_control import EyeControl
            self.eye=EyeControl(app_id=os.getenv('RAVEN_APP_ID',''),app_key=os.getenv('RAVEN_APP_KEY',''))
            if self.eye.sensorlib_client is None:
                self.eye=None
        else:
            self.eye=None
        self.view.update()

    def toggle_record(self):
        if self.phase=='recording':
            self.stop_recording()
            return
        if self.phase=='stopping' or (self.worker and self.worker.isRunning()):
            return
        self.samples.clear()
        self.trace.clear()
        self.recording_start_ns=self.clock()
        try:
            self.session=Session(self.output,self.source,self.recording_start_ns)
        except Exception as error:
            self.fail(str(error))
            return
        self.phase='recording'
        self.message='Recording locally · R to stop'
        self.export_button.set_text('Export ZIP')
        self.record_button.set_text('Stop')
        self.mode_button.set_disabled(True)
        self.review_button.set_disabled(True)
        self.export_button.set_disabled(True)
        self.last_frame_ns=self.recording_start_ns-200_000_000
        if self.source!='simulator':
            self.worker=CameraStream(self)
            self.worker.frame.connect(self.receive_frame)
            self.worker.failed.connect(self.fail)
            self.worker.finished.connect(self.finish_stop)
            self.worker.start()
        self.view.update()

    def tick(self):
        now=self.clock()
        if self.phase=='recording':
            started=self.clock()
            elapsed=(now-self.recording_start_ns)/1e9
            if self.source=='simulator':
                raw=simulated_gaze(elapsed)
            elif self.eye:
                try:
                    raw=self.eye.get_gaze_position()
                except Exception:
                    raw=None
            else:
                # Desktop camera recordings carry unavailable gaze, never cursor-as-eye labels.
                raw=None
            sample=gaze_sample(raw,started,self.clock(),self.source)
            self.samples.append(sample)
            self.gaze_xy=sample['xy']
            if self.gaze_xy:
                self.trace.append(self.gaze_xy)
            try:
                self.session.add_gaze(sample)
                if self.source=='simulator' and now-self.last_frame_ns>=200_000_000:
                    self.last_frame_ns=now
                    self.receive_frame(self.scene,now,now)
            except Exception as error:
                self.fail(str(error))
        elif self.phase=='review':
            elapsed=(now-self.replay_started_ns)%self.replay_duration_ns
            index=max(0,bisect_right(self.replay_offsets,elapsed)-1)
            if index!=self.replay_index:
                if index<self.replay_index:
                    self.trace.clear()
                row=self.replay_rows[index]
                self.image=QImage(str(self.session.path/row['file']))
                self.gaze_xy=row['scene_gaze_xy']
                if self.gaze_xy:
                    self.trace.append(self.gaze_xy)
                self.replay_index=index
        self.view.update()

    def receive_frame(self,image,started,received):
        if self.phase!='recording':
            return
        try:
            association=associate(self.samples,received,started)
            self.session.add_frame(jpeg_bytes(image),image.width(),image.height(),started,received,association)
            self.image=image
        except Exception as error:
            self.fail(str(error))

    def stop_recording(self):
        if self.phase!='recording':
            return
        self.phase='stopping'
        self.record_button.set_disabled(True)
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
        else:
            self.finish_stop()

    def finish_stop(self):
        if self.phase not in ('stopping','error'):
            return
        try:
            if self.session and not self.session.closed:
                self.session.finish(self.clock(),getattr(self,'last_error',None) if self.phase=='error' else None)
        except Exception as error:
            self.phase='error'
            self.last_error=str(error)
        if self.phase!='error':
            self.phase='complete'
            self.message='Saved · '+self.session.path.name
            self.view.setToolTip(str(self.session.path))
        self.record_button.set_text('Record')
        self.record_button.set_disabled(False)
        self.mode_button.set_disabled(False)
        usable=bool(self.session and self.session.closed and self.session.frame_count)
        self.review_button.set_disabled(not usable)
        self.export_button.set_disabled(not usable)
        self.view.update()

    def fail(self,message):
        self.last_error=message
        self.message='Error · '+message
        self.phase='error'
        print('Recording error:',message,file=sys.stderr)
        if self.worker and self.worker.isRunning():
            self.record_button.set_disabled(True)
            self.worker.requestInterruption()
        else:
            self.finish_stop()

    def review(self):
        if not self.session or not self.session.closed or not self.session.frame_count:
            return
        self.replay_rows=[json.loads(line) for line in (self.session.path/'frames.jsonl').read_text().splitlines()]
        self.replay_index=-1
        first=self.replay_rows[0]['host_received_ns']
        self.replay_offsets=[row['host_received_ns']-first for row in self.replay_rows]
        tail=self.replay_offsets[-1]-self.replay_offsets[-2] if len(self.replay_offsets)>1 else 200_000_000
        self.replay_duration_ns=self.replay_offsets[-1]+max(tail,1)
        self.replay_started_ns=self.clock()
        self.trace.clear()
        self.phase='review'
        self.message='Replay · original host receipt timing'
        self.view.update()

    def export(self):
        if not self.session or not self.session.closed:
            return
        try:
            self.last_export=self.session.export()
            self.export_button.set_text('Exported ✓')
            self.message='ZIP saved · '+self.last_export.name
            self.view.setToolTip(str(self.last_export))
            print('Exported session:',self.last_export)
        except Exception as error:
            self.fail(str(error))

    def shutdown(self):
        self.timer.stop()
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        if self.session and not self.session.closed:
            self.session.finish(self.clock())

    def closeEvent(self,event):
        self.shutdown()
        super().closeEvent(event)


if __name__=='__main__':
    RunApp.run(lambda:EgoGaze(),app_id=os.getenv('RAVEN_APP_ID',''),app_key=os.getenv('RAVEN_APP_KEY',''))
