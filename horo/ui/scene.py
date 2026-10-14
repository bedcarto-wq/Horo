from __future__ import annotations
import math
from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPen, QBrush, QPixmap, QTransform, QPainter
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem, QWidget,
                              QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox, QPushButton)
from ..storage import asset_path

class ObjectItem(QGraphicsItem):
    def __init__(self, node, canvas, parent=None):
        super().__init__(parent)
        self.node, self.canvas = node, canvas
        self.pixmap = QPixmap()
        if node.kind == 'sprite' and node.image and canvas.folder:
            try:
                self.pixmap = QPixmap(str(asset_path(canvas.folder, node.image)))
            except ValueError:
                pass  # Reported by editor's resource scan; placeholder is intentional.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, canvas.editable)
        self.setZValue(1)
        self.sync()

    def sync(self):
        t = self.node.transform
        self.setPos(t.x, t.y)
        self.setRotation(t.rotation)
        self.setTransform(QTransform.fromScale(t.sx, t.sy))

    def boundingRect(self):
        if self.node.kind == 'sprite':
            if not self.pixmap.isNull():
                return QRectF(0, 0, self.pixmap.width(), self.pixmap.height())
            return QRectF(0, 0, 64, 64)
        return QRectF(-12, -12, 24, 24)

    def paint(self, painter, option, widget=None):
        rect = self.boundingRect()
        if self.node.kind == 'sprite':
            if not self.pixmap.isNull():
                painter.drawPixmap(0, 0, self.pixmap)
            else:
                painter.fillRect(rect, QColor('#294568'))
                painter.setPen(QColor('#f3b4b4'))
                painter.drawLine(rect.topLeft(), rect.bottomRight())
                painter.drawLine(rect.topRight(), rect.bottomLeft())
        elif self.canvas.editable:
            painter.setPen(QPen(QColor('#7c9fcb'), 1))
            painter.drawLine(-10, 0, 10, 0); painter.drawLine(0, -10, 0, 10)
        if self.isSelected():
            painter.setPen(QPen(QColor('#63a9ff'), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(rect)
            # Mode marker: transformations apply around the local origin.
            painter.setBrush(QColor('#63a9ff')); painter.drawEllipse(QPointF(0, 0), 3, 3)

    def mousePressEvent(self, event):
        if not self.canvas.editable:
            return super().mousePressEvent(event)
        self.canvas.before = self.canvas.project.clone()
        self.start_scene = event.scenePos()
        self.start = self.node.transform.__class__(**vars(self.node.transform))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.canvas.editable or event.buttons() != Qt.MouseButton.LeftButton:
            return super().mouseMoveEvent(event)
        if self.parentItem():
            delta = self.parentItem().mapFromScene(event.scenePos()) - self.parentItem().mapFromScene(self.start_scene)
        else:
            delta = event.scenePos() - self.start_scene
        t = self.node.transform
        if self.canvas.mode == 'move':
            t.x, t.y = self.start.x + delta.x(), self.start.y + delta.y()
            if self.canvas.snap:
                t.x, t.y = round(t.x / 16) * 16, round(t.y / 16) * 16
        elif self.canvas.mode == 'scale':
            factor = max(0.01, 1 + (event.scenePos().x() - self.start_scene.x()) / 100)
            t.sx, t.sy = self.start.sx*factor, self.start.sy*factor
        else:
            center = self.mapToScene(QPointF(0, 0))
            a = self.start_scene - center; b = event.scenePos() - center
            t.rotation = self.start.rotation + math.degrees(math.atan2(b.y(), b.x()) - math.atan2(a.y(), a.x()))
        self.sync()
        self.canvas.scene().update()
        event.accept()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.canvas.before is not None:
            before, self.canvas.before = self.canvas.before, None
            self.canvas.changed.emit(before, 'Преобразование объекта')

class SceneCanvas(QGraphicsView):
    changed = Signal(object, str)
    chosen = Signal(str)
    assetDropped = Signal(str, object)

    def __init__(self, editable=True):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAcceptDrops(editable)
        self.editable = editable
        self.project = None; self.folder = None; self.items_by_id = {}
        self.grid = True; self.snap = False; self.mode = 'move'; self.before = None
        self.panning = False
        self.setBackgroundBrush(QColor('#0d1520'))
        self.scene().selectionChanged.connect(self.selection_changed)

    def selection_changed(self):
        selected = self.scene().selectedItems()
        if selected and isinstance(selected[0], ObjectItem):
            self.chosen.emit(selected[0].node.id)

    def build(self, project, folder, selected=None):
        self.project, self.folder = project, folder
        self.scene().blockSignals(True)
        self.scene().clear(); self.items_by_id = {}
        def add(key):
            if key in self.items_by_id:
                return self.items_by_id[key]
            node = project.nodes[key]
            parent = add(node.parent) if node.parent else None
            item = ObjectItem(node, self, parent)
            if not parent:
                self.scene().addItem(item)
            self.items_by_id[key] = item
            return item
        for key in project.nodes:
            add(key)
        border = self.scene().addRect(0, 0, project.width, project.height,
                                     QPen(QColor('#446b96'), 1))
        border.setZValue(-1)
        self.scene().setSceneRect(QRectF(-1000, -1000, project.width+2000, project.height+2000))
        if selected in self.items_by_id:
            self.items_by_id[selected].setSelected(True)
        self.scene().blockSignals(False)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        if not self.grid or not self.editable or self.transform().m11() < .3:
            return
        painter.setPen(QPen(QColor('#1b293a'), 0))
        left, top = math.floor(rect.left()/16)*16, math.floor(rect.top()/16)*16
        for x in range(left, int(rect.right())+1, 16):
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for y in range(top, int(rect.bottom())+1, 16):
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def wheelEvent(self, event):
        if self.editable:
            factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
            if .1 <= self.transform().m11()*factor <= 8:
                self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
                self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self.editable:
            self.panning = True; self.pan_start = event.position()
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.panning:
            delta = event.position() - self.pan_start; self.pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-int(delta.y()))
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = False
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-horo-asset'):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat('application/x-horo-asset'):
            path = bytes(event.mimeData().data('application/x-horo-asset')).decode('utf-8')
            self.assetDropped.emit(path, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()

class SceneEditor(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(['Перемещение', 'Масштаб', 'Поворот'])
        tools.addWidget(self.mode)
        self.grid = QCheckBox('Сетка'); self.grid.setChecked(True); tools.addWidget(self.grid)
        self.snap = QCheckBox('Привязка 16'); tools.addWidget(self.snap)
        fit = QPushButton('Экран проекта'); tools.addWidget(fit); tools.addStretch()
        layout.addLayout(tools)
        self.canvas = SceneCanvas(); layout.addWidget(self.canvas)
        self.mode.currentIndexChanged.connect(lambda i: setattr(self.canvas, 'mode', ['move', 'scale', 'rotate'][i]))
        self.grid.toggled.connect(self.toggle_grid)
        self.snap.toggled.connect(lambda value: setattr(self.canvas, 'snap', value))
        fit.clicked.connect(self.fit)

    def toggle_grid(self, value):
        self.canvas.grid = value; self.canvas.viewport().update()

    def fit(self):
        if self.canvas.project:
            p = self.canvas.project
            self.canvas.fitInView(QRectF(-20, -20, p.width+40, p.height+40), Qt.AspectRatioMode.KeepAspectRatio)
