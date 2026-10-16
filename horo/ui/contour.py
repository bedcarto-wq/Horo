"""Scene-local polygon drafting. Drafts never enter Project until validated."""
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor,QPen,QBrush,QPainterPath
from ..geometry import validate_polygon,point_segment

class ContourTool:
    def __init__(self,canvas):
        self.canvas=canvas;self.node_id=None;self.points=[];self.drawing=False
        self.selected=None;self.dragging=False;self.overlays=[]

    def begin(self,node_id,new=False):
        node=self.canvas.project.nodes.get(node_id)
        if not node or node.kind!='polygon_shape':
            self.canvas.message.emit('Выберите многоугольную форму');return
        self.node_id=node_id;self.points=[list(p) for p in node.points] if not new else []
        self.drawing=new;self.selected=None;self.render()
        self.canvas.setFocus()
        self.canvas.message.emit('Контур: клик — точка; Shift+клик по ребру — вставка; Delete — удалить вершину; Enter — завершить; Escape — отменить черновик')

    def cancel(self):
        self.node_id=None;self.points=[];self.selected=None;self.dragging=False;self.drawing=False;self.render()

    def local(self,pos):
        item=self.canvas.items_by_id.get(self.node_id)
        if item is None:return None
        q=item.mapFromScene(self.canvas.mapToScene(pos.toPoint()))
        x,y=q.x(),q.y()
        if self.canvas.snap:x,y=round(x/16)*16,round(y/16)*16
        return [x,y]

    def valid_commit(self):
        try:validate_polygon(self.points)
        except ValueError as exc:
            self.canvas.message.emit(str(exc)+'; черновик не сохранён');return False
        self.canvas.contourCommitted.emit(self.node_id,[list(p) for p in self.points])
        return True

    def finish(self):
        if self.node_id and self.valid_commit():self.cancel()

    def render(self):
        for item in self.overlays:
            if item.scene():self.canvas.scene().removeItem(item)
        self.overlays=[]
        obj=self.canvas.items_by_id.get(self.node_id)
        if obj is None:return
        points=[obj.mapToScene(QPointF(*p)) for p in self.points]
        path=QPainterPath()
        if points:
            path.moveTo(points[0])
            for p in points[1:]:path.lineTo(p)
            if not self.drawing:path.closeSubpath()
        line=self.canvas.scene().addPath(path,QPen(QColor('#ffd271'),2));line.setZValue(1000)
        line.setAcceptedMouseButtons(Qt.MouseButton.NoButton);self.overlays.append(line)
        # Handle radius is fixed in view pixels, independent of physical scale.
        scale=self.canvas.transform().m11();r=5/max(.1,scale)
        for i,p in enumerate(points):
            item=self.canvas.scene().addEllipse(p.x()-r,p.y()-r,2*r,2*r,QPen(QColor('#152235')),QBrush(QColor('#ffffff' if i==self.selected else '#ffd271')))
            item.setZValue(1001);item.setAcceptedMouseButtons(Qt.MouseButton.NoButton);self.overlays.append(item)

    def press(self,event):
        if not self.node_id:return False
        if event.button()!=Qt.MouseButton.LeftButton:return False
        p=self.local(event.position())
        if p is None:self.cancel();return True
        if self.drawing:
            self.points.append(p);self.selected=len(self.points)-1;self.render();return True
        obj=self.canvas.items_by_id[self.node_id]
        mouse=event.position()
        for i,v in enumerate(self.points):
            screen=self.canvas.mapFromScene(obj.mapToScene(QPointF(*v)))
            if (QPointF(screen)-mouse).manhattanLength()<12:
                self.selected=i;self.dragging=True;self.render();return True
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            options=[]
            for i,a in enumerate(self.points):
                b=self.points[(i+1)%len(self.points)]
                sa=self.canvas.mapFromScene(obj.mapToScene(QPointF(*a)));sb=self.canvas.mapFromScene(obj.mapToScene(QPointF(*b)))
                options.append((point_segment((mouse.x(),mouse.y()),(sa.x(),sa.y()),(sb.x(),sb.y())),i))
            dist,i=min(options)
            if dist<12:
                self.points.insert(i+1,p);self.selected=i+1;self.valid_commit();self.render()
        return True

    def move(self,event):
        if not self.node_id or not self.dragging:return False
        p=self.local(event.position())
        if p is not None:self.points[self.selected]=p;self.render()
        return True

    def release(self,event):
        if not self.node_id or not self.dragging:return False
        self.dragging=False;self.valid_commit();self.render();return True

    def key(self,event):
        if not self.node_id:return False
        if event.key()==Qt.Key.Key_Escape:self.cancel()
        elif event.key() in (Qt.Key.Key_Enter,Qt.Key.Key_Return):self.finish()
        elif event.key()==Qt.Key.Key_Delete and self.selected is not None:
            del self.points[self.selected];self.selected=None
            if not self.drawing:self.valid_commit()
            self.render()
        else:return False
        return True
