"""Graph canvas: cards, typed ports, searchable catalog and explicit loop regions."""
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer, QMimeData
from PySide6.QtGui import QColor, QPen, QBrush, QPainterPath, QPainter, QDrag
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsPathItem, QGraphicsProxyWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QComboBox, QPushButton, QLabel, QMenu, QInputDialog,
    QListWidget, QListWidgetItem, QDialog, QDialogButtonBox, QTreeWidget, QTreeWidgetItem, QCheckBox)
from ..model import Edge, initial
from ..ports import LABELS, CATEGORIES, ports, STARTS, LOOPS, DESCRIPTIONS, port_help
from ..validation import region_ancestors, node_availability, validate_graph
from .dialogs import typed_value, format_value

EXEC_COLOR = QColor('#ff7d88')
DATA_COLOR = QColor('#69b6ff')

class PortItem(QGraphicsItem):
    def __init__(self, port, card, index, enabled=True):
        super().__init__(card)
        self.port, self.card, self.enabled = port, card, enabled
        self.setPos(0 if port.direction == 'in' else card.width, 50+index*25)
        self.setZValue(3); self.setToolTip(port_help(card.view.project, card.view.graph, card.node, port) +
            ('\nИсточник из внешней области; порт недоступен в этом представлении' if not enabled else ''))

    def boundingRect(self):
        return QRectF(-9, -9, 18, 18)

    def paint(self, painter, option, widget=None):
        color = EXEC_COLOR if self.port.type == 'exec' else DATA_COLOR
        if not self.enabled:
            color = QColor('#526275')
        painter.setPen(QPen(color, 1)); painter.setBrush(color)
        if self.port.type == 'exec':
            path = QPainterPath(); path.moveTo(-6, -6); path.lineTo(7, 0); path.lineTo(-6, 6); path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawEllipse(QRectF(-5, -5, 10, 10))

    def mousePressEvent(self, event):
        if self.enabled:
            self.card.view.port_clicked(self)
        event.accept()

class EdgeItem(QGraphicsPathItem):
    def __init__(self, edge, source, target, view):
        super().__init__()
        self.edge, self.source, self.target, self.view = edge, source, target, view
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(-1)
        self.update_path()

    def update_path(self):
        a, b = self.source.scenePos(), self.target.scenePos()
        distance = max(60, abs(b.x()-a.x())*.5)
        path = QPainterPath(a); path.cubicTo(a+QPointF(distance, 0), b-QPointF(distance, 0), b)
        self.setPath(path)
        color = EXEC_COLOR if self.source.port.type == 'exec' else DATA_COLOR
        self.setPen(QPen(color, 4 if self.isSelected() else 2.5))

    def contextMenuEvent(self, event):
        menu = QMenu(); action = menu.addAction('Удалить связь')
        if menu.exec(event.screenPos()) == action:
            self.view.remove_requested.emit([], [self.edge.id])

class CardItem(QGraphicsItem):
    width = 310
    def __init__(self, node, view, boundary=False, display_pos=None):
        super().__init__()
        self.node, self.view, self.boundary = node, view, boundary
        self.port_items = {}
        self.issues = view.issues.get(node.id, [])
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not boundary)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(display_pos or QPointF(node.x, node.y))
        self.setZValue(1)
        grouped = {d: [p for p in ports(view.project, view.graph, node) if p.direction == d] for d in ('in', 'out')}
        self.rows = max(len(grouped['in']), len(grouped['out']), 1)
        for direction, values in grouped.items():
            for i, port in enumerate(values):
                enabled = not boundary or (direction == 'out' and
                    (port.type != 'exec' or (node.id == view.region and port.key == 'body')))
                self.port_items[(direction, port.key)] = PortItem(port, self, i, enabled)
        self.height = 70 + self.rows*25
        if node.expanded and not boundary:
            widget = self.make_fields()
            if widget:
                widget.adjustSize()
                proxy = QGraphicsProxyWidget(self); proxy.setWidget(widget)
                proxy.setPos(12, self.height)
                self.height += widget.sizeHint().height()+12
                if boundary:
                    widget.setEnabled(False)
        self.setToolTip(f'{node.id}\n' + ('Источник из внешней области' if boundary else 'Перетащите заголовок; порты: выход → вход')+'\n'+'\n'.join(self.issues))

    def boundingRect(self):
        return QRectF(-10, 0, self.width+20, self.height)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(QColor('#69b6ff') if self.isSelected() else QColor('#354d6d'), 2 if self.isSelected() else 1))
        painter.setBrush(QColor('#17263a') if not self.boundary else QColor('#16202d'))
        painter.drawRoundedRect(QRectF(0, 0, self.width, self.height), 7, 7)
        painter.fillRect(QRectF(1, 1, self.width-2, 30), QColor('#223a57'))
        painter.setPen(QColor('#eff5ff'))
        title = ('⚠ ' if self.issues else '') + (self.node.name or LABELS.get(self.node.kind, self.node.kind))
        painter.drawText(QRectF(10, 4, self.width-48, 24), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, self.width-48))
        if not self.boundary:
            painter.drawText(QRectF(self.width-32, 4, 26, 24), Qt.AlignmentFlag.AlignCenter,
                             '−' if self.node.expanded else '+')
        for (direction, key), portitem in self.port_items.items():
            painter.setPen(QColor('#d4e4f7') if portitem.enabled else QColor('#657992'))
            x = 12 if direction == 'in' else self.width/2
            align = Qt.AlignmentFlag.AlignLeft if direction == 'in' else Qt.AlignmentFlag.AlignRight
            connected = direction == 'in' and any(e.target == self.node.id and e.input == key for e in self.view.graph.edges)
            text = painter.fontMetrics().elidedText(portitem.port.label+(' ← линия' if connected else ''), Qt.TextElideMode.ElideRight, 140)
            painter.drawText(QRectF(x, portitem.y()-10, self.width/2-12, 20), align | Qt.AlignmentFlag.AlignVCenter, text)

    def update_param(self, key, value):
        self.view.param_requested.emit(self.node.id, key, value)

    def make_fields(self):
        node = self.node
        widget = QWidget(); widget.setFixedWidth(self.width-24)
        form = QFormLayout(widget); form.setContentsMargins(0, 3, 0, 3)
        def text_field(label, key, kind, default):
            edit = QLineEdit(format_value(node.params.get(key, default), kind))
            edit.installEventFilter(self.view.window())
            if any(e.target==node.id and e.input==key for e in self.view.graph.edges):
                edit.setToolTip('Сейчас значение приходит по линии; это поле применяется только без подключения')
            def finish():
                try:
                    value = typed_value(edit.text(), kind)
                    if node.params.get(key, default) != value:
                        self.update_param(key, value)
                except ValueError as exc:
                    self.view.message.emit(str(exc))
                    edit.setText(format_value(node.params.get(key, default), kind))
            edit.editingFinished.connect(finish); form.addRow(label, edit)
        if node.kind in ('number', 'text', 'bool'):
            text_field('Значение', 'value', node.kind, initial(node.kind))
        elif node.kind == 'object':
            combo = QComboBox(); combo.addItem('Пустая ссылка', None)
            for obj in self.view.project.nodes.values():
                combo.addItem(obj.name+' ['+obj.id[:8]+']', obj.id)
            combo.setCurrentIndex(max(0, combo.findData(node.params.get('value'))))
            combo.currentIndexChanged.connect(lambda _: self.update_param('value', combo.currentData()))
            form.addRow('Объект', combo)
        elif node.kind == 'vector':
            text_field('X по умолчанию', 'x', 'number', 0)
            text_field('Y по умолчанию', 'y', 'number', 0)
        elif node.kind == 'direction':
            for label,key,default in [('Влево','left','A'),('Вправо','right','D'),('Вверх','up','W'),('Вниз','down','S')]:
                combo = QComboBox(); combo.addItems(['Space','Left','Right','Up','Down','Return','Escape']+list('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'))
                combo.setCurrentText(node.params.get(key,default))
                combo.currentTextChanged.connect(lambda value,k=key: self.update_param(k,value))
                form.addRow(label,combo)
        elif node.kind in ('key', 'key_release', 'held'):
            combo = QComboBox(); combo.addItems(['Space', 'Left', 'Right', 'Up', 'Down', 'Return', 'Escape']+list('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'))
            combo.setCurrentText(node.params.get('key', 'Space'))
            combo.currentTextChanged.connect(lambda value: self.update_param('key', value))
            form.addRow('Клавиша', combo)
        elif node.kind in ('read', 'write'):
            combo = QComboBox(); combo.addItem('Выберите переменную', None)
            for var in self.view.project.variables.values():
                if var.scope != 'run' or var.owner == self.view.graph.id:
                    combo.addItem(var.name+' · '+var.scope, var.id)
            combo.setCurrentIndex(max(0, combo.findData(node.params.get('variable'))))
            combo.currentIndexChanged.connect(lambda _: self.update_param('variable', combo.currentData()))
            form.addRow('Переменная', combo)
            create = QPushButton('Создать переменную…')
            create.clicked.connect(lambda: self.view.variable_requested.emit(node.id))
            form.addRow(create)
        elif node.kind == 'call':
            combo = QComboBox(); combo.addItem('Выберите функцию', None)
            for fn in self.view.project.graphs.values():
                if fn.kind == 'function':
                    combo.addItem(fn.name, fn.id)
            combo.setCurrentIndex(max(0, combo.findData(node.params.get('function'))))
            combo.currentIndexChanged.connect(lambda _: self.update_param('function', combo.currentData()))
            form.addRow('Функция', combo)
        elif node.kind in LOOPS:
            button = QPushButton('Открыть тело цикла →')
            button.clicked.connect(lambda: self.view.region_requested.emit(node.id))
            form.addRow(button)
        elif node.kind == 'wait':
            text_field('Секунд (если нет входа)', 'n', 'number', 1)
        elif node.kind in ('sequence', 'fork'):
            for index, output_id in enumerate(node.outputs):
                row = QWidget(); layout = QHBoxLayout(row); layout.setContentsMargins(0, 0, 0, 0)
                layout.addWidget(QLabel(str(index+1)))
                for text, action, enabled in [('↑', 'up', index > 0), ('↓', 'down', index < len(node.outputs)-1),
                                              ('×', 'remove', len(node.outputs) > 2)]:
                    button = QPushButton(text); button.setEnabled(enabled)
                    button.setToolTip('Переместить выход' if action in ('up','down') and enabled else 'Удалить выход' if enabled else 'Выход уже на границе списка' if action in ('up','down') else 'Нужно минимум два выхода')
                    button.clicked.connect(lambda checked=False, a=action, key=output_id:
                                           self.view.output_requested.emit(node.id, a, key))
                    layout.addWidget(button)
                form.addRow(row)
            button = QPushButton('+ Выход')
            button.clicked.connect(lambda: self.view.output_requested.emit(node.id, 'add', None))
            form.addRow(button)
        description = QPushButton('Описание ▾' if node.id in self.view.description_ids else 'Описание ▸')
        description.clicked.connect(lambda: self.view.toggle_description(node.id))
        form.addRow(description)
        if node.id in self.view.description_ids:
            help_text = QLabel(DESCRIPTIONS.get(node.kind,'Неизвестный вид узла: проверьте ресурс графа')); help_text.setWordWrap(True)
            form.addRow(help_text)
        if self.issues:
            problem = QLabel('⚠ ' + '\n'.join(self.issues)); problem.setWordWrap(True)
            problem.setToolTip('Это диагностика текущей конфигурации, не обязательно запрет добавления. Неполный граф можно сохранить.')
            form.addRow(problem)
        return widget

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in getattr(self.view, 'edge_items', []):
                edge.update_path()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if not self.boundary and event.pos().y() < 30 and event.pos().x() > self.width-36:
            self.view.expanded_requested.emit(self.node.id, not self.node.expanded)
            event.accept(); return
        self.start_pos = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if not self.boundary and hasattr(self, 'start_pos') and self.pos() != self.start_pos:
            self.view.moved.emit(self.node.id, self.pos().x(), self.pos().y())

    def contextMenuEvent(self, event):
        if self.boundary:
            return
        menu = QMenu(); rename = menu.addAction('Переименовать'); delete = menu.addAction('Удалить узел')
        action = menu.exec(event.screenPos())
        if action == delete:
            self.view.remove_requested.emit([self.node.id], [])
        elif action == rename:
            text, ok = QInputDialog.getText(self.view, 'Имя узла', 'Имя', text=self.node.name or LABELS[self.node.kind])
            if ok:
                self.view.rename_requested.emit(self.node.id, text)

class NodeSearch(QDialog):
    def __init__(self, graph, region, parent):
        super().__init__(parent); self.setWindowTitle('Добавить узел'); self.resize(460, 500)
        self.graph, self.region = graph, region
        layout=QVBoxLayout(self); self.search=QLineEdit();self.search.setPlaceholderText('Поиск узла…');layout.addWidget(self.search)
        self.show_unavailable=QCheckBox('Показать недоступные');self.show_unavailable.setChecked(parent.show_unavailable)
        layout.addWidget(self.show_unavailable);self.list=QListWidget();layout.addWidget(self.list)
        self.reason=QLabel('');self.reason.setWordWrap(True);layout.addWidget(self.reason)
        self.kind=None
        self.search.textChanged.connect(self.populate);self.show_unavailable.toggled.connect(self.populate)
        self.show_unavailable.toggled.connect(parent.availability_mode.emit)
        self.list.itemDoubleClicked.connect(self.finish)
        self.list.currentItemChanged.connect(self.explain)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.ok_button=buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.populate()

    def populate(self,*_):
        self.list.clear();text=self.search.text().casefold()
        for kind,label in LABELS.items():
            reason=node_availability(self.graph,kind,self.region)
            if text not in label.casefold() or (reason and not self.show_unavailable.isChecked()):continue
            item=QListWidgetItem(label+(' — '+reason if reason else ''));item.setData(Qt.ItemDataRole.UserRole,kind)
            item.setToolTip(reason or DESCRIPTIONS[kind])
            if reason:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(item)
        self.list.setCurrentRow(next((i for i in range(self.list.count()) if self.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled),-1))
        self.explain()

    def explain(self,*_):
        item=self.list.currentItem();kind=item.data(Qt.ItemDataRole.UserRole) if item else None
        reason=node_availability(self.graph,kind,self.region) if kind else 'Нет доступного узла для выбранного поиска'
        self.ok_button.setEnabled(bool(item) and not reason)
        self.reason.setText(reason or DESCRIPTIONS[kind])

    def finish(self,*_):
        item=self.list.currentItem()
        if item:
            kind=item.data(Qt.ItemDataRole.UserRole)
            reason=node_availability(self.graph,kind,self.region)
            if reason:self.reason.setText(reason);return
            self.kind=kind;self.accept()


class Catalog(QTreeWidget):
    availability_mode=Signal(bool)
    def __init__(self):
        super().__init__();self.setHeaderHidden(True);self.setDragEnabled(True)
        self.graph=None;self.region=None
        self.reason=QLabel('');self.reason.setWordWrap(True);self.reason.hide()
        self.setMouseTracking(True);self.itemEntered.connect(self.explain_item)
        self.currentItemChanged.connect(self.explain_item)
        self.search=QLineEdit();self.search.setPlaceholderText('Найти блок…')
        self.show_unavailable=QCheckBox('Показать недоступные')
        self.search.textChanged.connect(self.populate);self.show_unavailable.toggled.connect(self.populate)
        self.show_unavailable.toggled.connect(self.availability_mode.emit)
        self.populate()

    def explain_item(self,item,*_):
        kind=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        reason=node_availability(self.graph,kind,self.region) if kind else None
        self.reason.setText(reason or '');self.reason.setVisible(bool(reason))

    def set_context(self,graph,region):
        self.graph,self.region=graph,region;self.populate()

    def populate(self,*_):
        self.clear();self.reason.hide();text=self.search.text().casefold()
        for category,kinds in CATEGORIES.items():
            parent=QTreeWidgetItem([category])
            for kind in kinds:
                reason=node_availability(self.graph,kind,self.region)
                if text not in LABELS[kind].casefold() or (reason and not self.show_unavailable.isChecked()):continue
                item=QTreeWidgetItem([LABELS[kind]+(' — '+reason if reason else '')]);item.setData(0,Qt.ItemDataRole.UserRole,kind)
                item.setToolTip(0,reason or DESCRIPTIONS[kind])
                if reason:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsDragEnabled)
                parent.addChild(item)
            if parent.childCount():self.addTopLevelItem(parent)
        self.expandAll()

    def startDrag(self,supportedActions):
        item=self.currentItem();kind=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        if kind and not node_availability(self.graph,kind,self.region):
            mime=QMimeData();mime.setData('application/x-horo-node',kind.encode())
            drag=QDrag(self);drag.setMimeData(mime);drag.exec(Qt.DropAction.CopyAction)

class GraphCanvas(QGraphicsView):
    availability_mode = Signal(bool)
    add_requested = Signal(str, float, float)
    edge_requested = Signal(object)
    param_requested = Signal(str, str, object)
    variable_requested = Signal(str)
    output_requested = Signal(str, str, object)
    region_requested = Signal(object)
    moved = Signal(str, float, float)
    expanded_requested = Signal(str, bool)
    rename_requested = Signal(str, str)
    remove_requested = Signal(object, object)
    message = Signal(str)

    def __init__(self):
        super().__init__(); self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAcceptDrops(True); self.setBackgroundBrush(QColor('#0c1420'))
        self.project = None; self.graph = None; self.region = None
        self.show_unavailable = False; self.description_ids = set(); self.issues = {}
        self.card_items = {}; self.edge_items = []; self.pending = None; self.preview = None; self.panning = False

    def build(self, project, graph, region=None):
        selected = [item.node.id for item in self.scene().selectedItems() if isinstance(item, CardItem)]
        self.pending = None; self.preview = None
        self.project, self.graph, self.region = project, graph, region
        self.card_items = {}; self.edge_items = []; self.scene().clear()
        self.issues = {}
        for d in validate_graph(project, graph):
            if d.node_id:self.issues.setdefault(d.node_id, []).append(d.message)
        external_index = 0
        for node in graph.nodes.values():
            boundary = node.region != region
            display = None
            if boundary:
                if region is None:
                    continue
                if node.id == region:
                    display = QPointF(-400, 0)
                elif node.region in [None]+region_ancestors(graph, graph.nodes[region].region) and any(p.direction == 'out' and p.type != 'exec' for p in ports(project, graph, node)):
                    display = QPointF(-400, 220+external_index*190); external_index += 1
                else:
                    continue
            item = CardItem(node, self, boundary, display)
            self.scene().addItem(item); self.card_items[node.id] = item
            if node.id in selected and not boundary:
                item.setSelected(True)
        for edge in graph.edges:
            a, b = self.card_items.get(edge.source), self.card_items.get(edge.target)
            if not a or not b or b.boundary:
                continue
            source = a.port_items.get(('out', edge.output)); target = b.port_items.get(('in', edge.input))
            if source and target and source.enabled:
                item = EdgeItem(edge, source, target, self)
                self.scene().addItem(item); self.edge_items.append(item)
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-600, -600, 1200, 1200))

    def toggle_description(self, key):
        if key in self.description_ids:self.description_ids.remove(key)
        else:self.description_ids.add(key)
        QTimer.singleShot(0, lambda:self.build(self.project,self.graph,self.region) if self.graph else None)

    def allowed(self):
        return [kind for kind in LABELS if not node_availability(self.graph,kind,self.region)]

    def port_clicked(self, port):
        if self.pending is None:
            if port.port.direction != 'out':
                self.message.emit('Начните соединение с выхода (справа), затем выберите вход (слева)'); return
            self.pending = port
            self.preview = QGraphicsPathItem(); self.preview.setPen(QPen(EXEC_COLOR if port.port.type == 'exec' else DATA_COLOR, 2))
            self.preview.setZValue(-1); self.scene().addItem(self.preview)
            return
        source = self.pending
        self.cancel_connection()
        if port.port.direction != 'in':
            self.message.emit('Линия должна идти от выхода к входу'); return
        edge = Edge(source=source.card.node.id, output=source.port.key,
                    target=port.card.node.id, input=port.port.key)
        self.edge_requested.emit(edge)

    def cancel_connection(self):
        self.pending = None
        if self.preview is not None:
            self.scene().removeItem(self.preview); self.preview = None

    def mouseMoveEvent(self, event):
        if self.pending:
            a, b = self.pending.scenePos(), self.mapToScene(event.position().toPoint())
            path = QPainterPath(a); path.cubicTo(a+QPointF(80, 0), b-QPointF(80, 0), b)
            self.preview.setPath(path)
        if self.panning:
            delta = event.position()-self.pan_start; self.pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-int(delta.y()))
            return
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = True; self.pan_start = event.position(); event.accept(); return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = False; return
        super().mouseReleaseEvent(event)
        # Dragging from an output to an input is equivalent to clicking both.
        if self.pending:
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, PortItem) and item is not self.pending and item.port.direction == 'in':
                self.port_clicked(item)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
        if (factor > 1 and self.transform().m11() < 3) or (factor < 1 and self.transform().m11() > .15):
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse); self.scale(factor, factor)

    def contextMenuEvent(self, event):
        if not self.graph:
            return
        item = self.itemAt(event.pos())
        if item:
            super().contextMenuEvent(event); return
        self.cancel_connection()
        dialog = NodeSearch(self.graph, self.region, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pos = self.mapToScene(event.pos()); self.add_requested.emit(dialog.kind, pos.x(), pos.y())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_connection(); return
        if event.key() == Qt.Key.Key_Delete:
            nodes = [item.node.id for item in self.scene().selectedItems() if isinstance(item, CardItem) and not item.boundary]
            edges = [item.edge.id for item in self.scene().selectedItems() if isinstance(item, EdgeItem)]
            self.remove_requested.emit(nodes, edges); return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-horo-node'):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        kind = bytes(event.mimeData().data('application/x-horo-node')).decode()
        if kind in self.allowed():
            pos = self.mapToScene(event.position().toPoint()); self.add_requested.emit(kind, pos.x(), pos.y())
            event.acceptProposedAction()
        else:
            self.message.emit(node_availability(self.graph,kind,self.region) or 'Не удалось добавить узел')

    def focus_node(self, node_id):
        self.scene().clearSelection()
        item = self.card_items.get(node_id)
        if item:
            item.setSelected(True); self.centerOn(item)
            return True
        return False

class GraphEditor(QWidget):
    def __init__(self):
        super().__init__(); layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout(); self.breadcrumb = QLabel('Выберите граф в ресурсах'); self.breadcrumb.setWordWrap(True)
        self.back = QPushButton('← Внешний граф'); self.back.setVisible(False)
        self.fit = QPushButton('Показать всё')
        tools.addWidget(self.back); tools.addWidget(self.breadcrumb); tools.addStretch(); tools.addWidget(self.fit)
        layout.addLayout(tools)
        self.context = QLabel(); self.context.setWordWrap(True); layout.addWidget(self.context)
        self.signature = QLabel(); self.signature.setWordWrap(True); layout.addWidget(self.signature)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.hide(); layout.addWidget(self.feedback)
        self.canvas = GraphCanvas(); layout.addWidget(self.canvas)
        self.canvas.message.connect(self.explain)
        self.back.clicked.connect(self.go_back)
        self.fit.clicked.connect(lambda: self.canvas.fitInView(self.canvas.scene().itemsBoundingRect().adjusted(-30, -30, 30, 30), Qt.AspectRatioMode.KeepAspectRatio))

    def explain(self, text):
        self.feedback.setText('⚠ '+text); self.feedback.show()

    def go_back(self):
        owner = self.canvas.graph.nodes.get(self.canvas.region) if self.canvas.graph else None
        self.canvas.region_requested.emit(owner.region if owner else None)

    def build(self, project, graph, region, object_id=None):
        self.feedback.hide()
        self.back.setVisible(region is not None)
        path = [graph.name] + [graph.nodes[key].name or LABELS[graph.nodes[key].kind]
                               for key in reversed(region_ancestors(graph, region))]
        self.breadcrumb.setText(' → '.join(path) + ' · ПКМ: добавить; Delete: удалить')
        kind = 'Поведение' if graph.kind == 'behavior' else 'Функция'
        obj = project.nodes.get(object_id)
        context = f'Сцена: {project.name} · Объект: {obj.name} [{obj.id[:8]}]' if obj and obj.graph == graph.id else f'Сцена: {project.name} · Ресурс графа'
        self.context.setText(context + f' · {kind}: {graph.name}\nОбщий ресурс: правки действуют для всех использующих его объектов. Переменные объекта у экземпляров раздельны.')
        from ..model import TYPE_LABELS
        def listing(values):return ', '.join(f'{v.name}: {TYPE_LABELS[v.type]}' for v in values) or 'нет'
        self.signature.setVisible(graph.kind == 'function')
        self.signature.setText('Параметры → Вход функции: ' + listing(graph.parameters) + '\nРезультаты → Вернуть результат: ' + listing(graph.results))
        self.signature.setToolTip('Редактирование сигнатуры — панель «Переменные и сигнатура функции»; порты находятся на Вход функции и Вернуть результат.')
        self.canvas.build(project, graph, region)
