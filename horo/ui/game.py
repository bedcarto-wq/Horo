from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtWidgets import QWidget, QVBoxLayout
from .scene import SceneCanvas
from ..errors import GraphError, Diagnostic
import traceback
import logging

class GameWindow(QWidget):
    failed = Signal(object)
    finished = Signal()

    def __init__(self, runtime, folder):
        super().__init__()
        self.runtime = runtime; self.folder = folder; self.held = set()
        self.setWindowTitle('Horo — Игра (отдельное состояние)')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.canvas = SceneCanvas(editable=False); self.canvas.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.addWidget(self.canvas)
        self.resize(min(runtime.project.width+20, 1280), min(runtime.project.height+20, 900))
        self.canvas.build(runtime.project, folder)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        p = self.runtime.project
        self.canvas.fitInView(QRectF(0, 0, p.width, p.height), Qt.AspectRatioMode.KeepAspectRatio)

    @staticmethod
    def key_name(event):
        mapping = {Qt.Key.Key_Space: 'Space', Qt.Key.Key_Left: 'Left', Qt.Key.Key_Right: 'Right',
                   Qt.Key.Key_Up: 'Up', Qt.Key.Key_Down: 'Down', Qt.Key.Key_Return: 'Return',
                   Qt.Key.Key_Enter: 'Return', Qt.Key.Key_Escape: 'Escape'}
        if event.key() in mapping:
            return mapping[event.key()]
        if Qt.Key.Key_A <= event.key() <= Qt.Key.Key_Z or Qt.Key.Key_0 <= event.key() <= Qt.Key.Key_9:
            return chr(event.key())
        return None

    def keyPressEvent(self, event):
        name = self.key_name(event)
        if not name or event.isAutoRepeat() or event.key() in self.held:
            event.accept(); return
        self.held.add(event.key())
        try:
            self.runtime.key_press(name)
            self.canvas.build(self.runtime.project, self.folder)
        except GraphError as exc:
            self.runtime.stop(); self.failed.emit(exc.diagnostic)
            self.setWindowTitle('Horo — Ошибка: игра остановлена')
        except Exception:
            # Unexpected defects are visible and recorded, never treated as successful execution.
            logging.exception('Unexpected runtime error')
            self.runtime.stop(); self.failed.emit(Diagnostic('Внутренняя ошибка выполнения. Подробности в локальном логе.'))
            self.setWindowTitle('Horo — Внутренняя ошибка: игра остановлена')
        event.accept()

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat():
            self.held.discard(event.key())
        event.accept()

    def focusOutEvent(self, event):
        self.held.clear(); super().focusOutEvent(event)

    def closeEvent(self, event):
        self.runtime.stop(); self.held.clear(); self.finished.emit(); event.accept()
