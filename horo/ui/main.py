"""Editor controller. Model snapshots are the authority; widgets are projections."""
from __future__ import annotations
import copy
from dataclasses import replace
import logging
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QMimeData, QEvent
from PySide6.QtGui import QAction, QKeySequence, QDrag, QImageReader, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QListWidget, QListWidgetItem, QPushButton, QTabWidget,
    QFormLayout, QLineEdit, QDoubleSpinBox, QComboBox, QLabel, QScrollArea,
    QMenu, QMessageBox, QFileDialog, QInputDialog, QDialog, QPlainTextEdit, QTextEdit)
from ..model import Project, Graph, SceneNode, Variable, TYPE_LABELS, uid
from ..history import History
from ..physics import SHAPES, BODIES
from ..storage import save_project, load_project, import_asset, asset_path, PROJECT_FILE
from ..validation import connect, validate_project, region_ancestors, node_availability, connection_error
from ..errors import Diagnostic, GraphError
from ..runtime import Runtime
from ..ports import LOOPS
from .scene import SceneEditor
from .graph import GraphEditor, Catalog
from .dialogs import ProjectDialog, VariableDialog, ParameterDialog
from .game import GameWindow
from .console import ConsolePanel
from .. import __version__

THEME = '''
QWidget { background: #101925; color: #e5eefb; font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 12px; }
QMainWindow::separator { background: #304b6b; width: 5px; height: 5px; }
QDockWidget::title { background: #20334a; padding: 7px; }
QMenuBar, QMenu, QToolBar { background: #17263a; }
QMenu::item:selected { background: #2e5179; }
QPushButton { background: #263e59; border: 1px solid #3c5e84; border-radius: 4px; padding: 5px 9px; }
QPushButton:hover { background: #35597f; }
QPushButton:disabled { color: #74859a; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { background: #0d1520; border: 1px solid #3b526e; padding: 4px; }
QTreeWidget, QListWidget, QScrollArea { background: #121f30; border: 1px solid #243951; }
QTreeWidget::item:disabled, QListWidget::item:disabled { color: #74859a; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #2d537e; color: white; }
QTabBar::tab { background: #1c2f45; padding: 7px 12px; }
QTabBar::tab:selected { background: #2c4f74; }
QToolTip { background: #20334a; color: #ffffff; border: 1px solid #54779c; }
'''

class ResourceTree(QTreeWidget):
    def __init__(self):
        super().__init__(); self.setHeaderHidden(True); self.setDragEnabled(True)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if data and data[0] == 'asset':
            mime = QMimeData(); mime.setData('application/x-horo-asset', data[1].encode('utf-8'))
            drag = QDrag(self); drag.setMimeData(mime); drag.exec(Qt.DropAction.CopyAction)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1420, 900); QApplication.instance().setStyleSheet(THEME)
        self.project = Project(); self.folder = None; self.saved = self.project.to_dict()
        self.history = History(); self.selected = None; self.graph_id = None; self.region = None
        self.graph_object_id = None; self.last_run_error = False
        self.game = None; self.loading = False; self.resource_warnings = set(); self.pending_edits = []
        log_dir = Path.home()/'.horo'; log_dir.mkdir(exist_ok=True)
        logging.basicConfig(filename=log_dir/'horo.log', level=logging.ERROR, encoding='utf-8')
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.scene_editor = SceneEditor(); self.graph_editor = GraphEditor()
        self.tabs.addTab(self.scene_editor, 'Сцена'); self.tabs.addTab(self.graph_editor, 'Граф')
        self.create_panels(); self.create_actions(); self.wire()
        self.resizeDocks([d for d in self.docks if d.objectName() in ('resources', 'console')], [180, 180], Qt.Orientation.Vertical)
        self.default_layout = self.saveState()
        self.refresh(); self.scene_editor.fit()

    def dock(self, title, name, widget, area):
        dock = QDockWidget(title, self); dock.setObjectName(name)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setWidget(widget); self.addDockWidget(area, dock)
        self.docks.append(dock); return dock

    def create_panels(self):
        self.docks = []
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True)
        tree_panel = QWidget(); layout = QVBoxLayout(tree_panel); layout.setContentsMargins(4, 4, 4, 4)
        add = QPushButton('+ Объект'); add.clicked.connect(lambda: self.add_scene('sprite'))
        layout.addWidget(add); layout.addWidget(self.tree)
        self.dock('Дерево сцены', 'scene-tree', tree_panel, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.props = QWidget(); self.props_form = QFormLayout(self.props)
        props_body = QWidget(); props_layout = QVBoxLayout(props_body); props_layout.setContentsMargins(0,0,0,0)
        self.props_heading = QLabel(); props_layout.addWidget(self.props_heading); props_layout.addWidget(self.props)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setMinimumWidth(260); scroll.setWidget(props_body)
        self.dock('Свойства объекта', 'properties', scroll, Qt.DockWidgetArea.RightDockWidgetArea)
        self.resources = ResourceTree(); resource_panel = QWidget(); layout = QVBoxLayout(resource_panel)
        tools = QHBoxLayout()
        for label, callback in [('Импорт…', self.import_image), ('+ Поведение', lambda: self.new_graph('behavior')),
                                ('+ Функция', lambda: self.new_graph('function'))]:
            button = QPushButton(label); button.clicked.connect(callback); tools.addWidget(button)
        layout.addLayout(tools); layout.addWidget(self.resources)
        resources_dock = self.dock('Ресурсы', 'resources', resource_panel, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.console_panel = ConsolePanel(); self.console = self.console_panel.list
        console_dock = self.dock('Консоль — нажмите сообщение для перехода', 'console', self.console_panel, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.tabifyDockWidget(resources_dock, console_dock); resources_dock.raise_()
        self.catalog = Catalog(); catalog_panel = QWidget(); catalog_layout = QVBoxLayout(catalog_panel)
        catalog_layout.setContentsMargins(4,4,4,4); catalog_layout.addWidget(self.catalog.search)
        catalog_layout.addWidget(self.catalog.show_unavailable); catalog_layout.addWidget(self.catalog.reason); catalog_layout.addWidget(self.catalog)
        self.dock('Категории узлов — перетащите в граф', 'catalog', catalog_panel, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.variables = QTreeWidget(); self.variables.setHeaderHidden(True)
        variable_panel = QWidget(); layout = QVBoxLayout(variable_panel); layout.addWidget(self.variables)
        buttons = QHBoxLayout()
        add_var = QPushButton('+ Переменная'); add_var.clicked.connect(lambda: self.create_variable())
        param = QPushButton('+ Вход'); param.clicked.connect(lambda: self.add_parameter(False))
        result = QPushButton('+ Результат'); result.clicked.connect(lambda: self.add_parameter(True))
        buttons.addWidget(add_var); buttons.addWidget(param); buttons.addWidget(result); layout.addLayout(buttons)
        var_dock = self.dock('Переменные и сигнатура функции', 'variables', variable_panel, Qt.DockWidgetArea.RightDockWidgetArea)
        self.tabifyDockWidget(self.docks[1], var_dock); self.docks[1].raise_()

    def action(self, menu, title, callback, shortcut=None):
        action = QAction(title, self); action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut); action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        menu.addAction(action); return action

    def create_actions(self):
        file = self.menuBar().addMenu('Проект')
        self.action(file, 'Создать…', self.new_project, 'Ctrl+N')
        self.action(file, 'Открыть…', self.open_project, 'Ctrl+O')
        self.action(file, 'Сохранить', self.save, 'Ctrl+S')
        self.action(file, 'Размер экрана и имя…', self.project_settings)
        self.action(file, 'Выход', self.close)
        edit = self.menuBar().addMenu('Правка')
        self.action(edit, 'Отменить', self.undo, 'Ctrl+Z')
        self.action(edit, 'Повторить', self.redo, 'Ctrl+Shift+Z')
        view = self.menuBar().addMenu('Вид')
        for dock in self.docks:
            view.addAction(dock.toggleViewAction())
        self.action(view, 'Вернуть все панели', lambda: [dock.show() for dock in self.docks])
        self.action(view, 'Сбросить компоновку', self.reset_layout)
        scene_menu = self.menuBar().addMenu('Сцена')
        self.action(scene_menu, 'Добавить 2D-преобразование', lambda: self.add_scene('transform'))
        self.action(scene_menu, 'Добавить изображение', lambda: self.add_scene('sprite'))
        self.action(scene_menu, 'Удалить выбранный объект', self.remove_scene)
        for kind,title in [('static_body','Неподвижное тело'),('controlled_body','Управляемое тело'),('dynamic_body','Динамическое тело'),('platform_body','Движущаяся платформа'),('rect_shape','Прямоугольная форма'),('circle_shape','Круглая форма'),('polygon_shape','Многоугольная форма')]:
            self.action(scene_menu,title,lambda checked=False,k=kind:self.add_scene(k))
        self.action(scene_menu,'Редактировать контур',lambda:self.scene_editor.canvas.contour.begin(self.selected))
        self.action(scene_menu,'Нарисовать новый контур',lambda:self.scene_editor.canvas.contour.begin(self.selected,True))
        self.action(scene_menu,'Завершить контур',lambda:self.scene_editor.canvas.contour.finish())
        self.action(scene_menu,'Отменить черновик контура',lambda:self.scene_editor.canvas.contour.cancel())
        run = self.menuBar().addMenu('Игра')
        self.run_action = self.action(run, 'Запустить', self.run_game, 'F5')
        self.stop_action = self.action(run, 'Остановить', self.stop_game, 'F6')
        help_menu = self.menuBar().addMenu('Помощь')
        self.action(help_menu, 'Управление', lambda: QMessageBox.information(self, 'Horo '+__version__,
            'Сцена: колесо — масштаб вида; средняя кнопка — перемещение вида.\n'
            'Преобразование: выберите режим и перетащите объект.\n'
            'Граф: ПКМ на фоне — поиск; категории — drag & drop.\n'
            'Соединение: выход справа → вход слева (клики или перетаскивание).\n'
            'Delete в графе — удаление выбранных карточек/связей.\n'
            'Цикл: «Открыть тело»; источники извне слева, начните красную связь с «Тело».\n'
            'Консоль: нажмите ошибку для перехода. F5/F6 — запуск/остановка.\n'
            'Сигнатура функции/переменные: двойной щелчок — имя/значение, ПКМ — удаление.'))
        toolbar = self.addToolBar('Основное'); toolbar.setObjectName('main-toolbar'); toolbar.setMovable(False)
        toolbar.addAction(self.run_action); toolbar.addAction(self.stop_action)
        self.state_label = QLabel(); self.state_label.setWordWrap(True); self.statusBar().addPermanentWidget(self.state_label)
        self.sync_state()
        toolbar.addSeparator()
        add = QAction('+ Объект', self); add.triggered.connect(lambda: self.add_scene('sprite')); toolbar.addAction(add)
        graph = QAction('+ Граф', self); graph.triggered.connect(lambda: self.new_graph('behavior')); toolbar.addAction(graph)
        save = QAction('Сохранить', self); save.triggered.connect(self.save); toolbar.addAction(save)

    def wire(self):
        self.scene_editor.canvas.contourCommitted.connect(self.commit_contour)
        self.scene_editor.canvas.message.connect(lambda value:self.message(value,'warning'))
        self.tree.itemSelectionChanged.connect(self.tree_selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.resources.itemDoubleClicked.connect(self.resource_open)
        self.resources.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.resources.customContextMenuRequested.connect(self.resource_menu)
        self.variables.itemDoubleClicked.connect(self.edit_variable_or_parameter)
        self.variables.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.variables.customContextMenuRequested.connect(self.variable_menu)
        self.console.itemClicked.connect(self.navigate)
        self.console_panel.navigate_requested.connect(self.navigate_target)
        canvas = self.scene_editor.canvas
        canvas.chosen.connect(self.select_object); canvas.changed.connect(lambda before, label: QTimer.singleShot(0, lambda: self.commit(before, label)))
        canvas.assetDropped.connect(self.drop_image)
        graph = self.graph_editor.canvas
        graph.add_requested.connect(self.add_graph_node)
        graph.edge_requested.connect(self.add_edge)
        graph.param_requested.connect(self.set_node_param)
        graph.variable_requested.connect(self.create_variable)
        graph.output_requested.connect(self.edit_output)
        graph.region_requested.connect(self.open_region)
        graph.moved.connect(lambda key, x, y: self.deferred_edit('Положение карточки', lambda: self.move_card(key, x, y)))
        graph.expanded_requested.connect(lambda key, value: self.deferred_edit('Подробности карточки', lambda: setattr(self.current_graph().nodes[key], 'expanded', value)))
        graph.rename_requested.connect(lambda key, text: self.edit('Имя узла', lambda: setattr(self.current_graph().nodes[key], 'name', text)))
        graph.remove_requested.connect(self.remove_graph_elements)
        graph.message.connect(lambda value:self.message(value, 'warning'))
        self.catalog.availability_mode.connect(lambda value:setattr(graph,'show_unavailable',value))
        graph.availability_mode.connect(self.catalog.show_unavailable.setChecked)

    def dirty(self):
        return self.project.to_dict() != self.saved

    def current_graph(self):
        return self.project.graphs.get(self.graph_id)

    def edit(self, label, callback):
        if self.loading:
            return
        before = self.project.clone()
        try:
            callback()
            self.project.check_structure()
        except Exception as exc:
            self.project = before
            self.message(Diagnostic(str(exc)))
            self.refresh(); self.graph_editor.explain(str(exc)); return
        self.commit(before, label)

    def commit(self, before, label):
        if self.history.record(before, self.project, label):
            self.refresh()

    def deferred_edit(self, label, callback):
        # A widget may emit editingFinished while refresh removes that widget.
        self.pending_edits.append((label, callback))
        QTimer.singleShot(0, self.flush_edits)

    def flush_edits(self):
        pending, self.pending_edits = self.pending_edits, []
        for label, callback in pending:
            self.edit(label, callback)

    def undo(self):
        self.scene_editor.canvas.contour.cancel()
        widget = self.focusWidget()
        if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit)):
            widget.undo(); return
        p = self.history.undo()
        if p:
            self.project = p; self.refresh()

    def redo(self):
        self.scene_editor.canvas.contour.cancel()
        widget = self.focusWidget()
        if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit)):
            widget.redo(); return
        p = self.history.redo()
        if p:
            self.project = p; self.refresh()

    def reset_layout(self):
        self.restoreState(self.default_layout)
        for dock in self.docks:
            dock.show()

    def refresh(self):
        self.loading = True
        if self.selected not in self.project.nodes:
            self.selected = None
        if self.graph_id not in self.project.graphs:
            self.graph_id = None; self.region = None
        graph = self.current_graph()
        if graph and self.region not in graph.nodes:
            self.region = None
        self.setWindowTitle(f'Horo {__version__} — {self.project.name}' + (' *' if self.dirty() else ''))
        self.tree.blockSignals(True); self.tree.clear()
        tree_items = {}
        def add(key):
            if key in tree_items:
                return tree_items[key]
            node = self.project.nodes[key]
            item = QTreeWidgetItem([node.name + ' · ' + {'sprite':'Изображение','transform':'2D','static_body':'Неподвижное тело','controlled_body':'Управляемое тело','dynamic_body':'Динамическое тело','platform_body':'Платформа','rect_shape':'Прямоугольник','circle_shape':'Круг','polygon_shape':'Контур'}.get(node.kind,node.kind)])
            item.setData(0, Qt.ItemDataRole.UserRole, key); item.setToolTip(0, key)
            if node.parent:
                add(node.parent).addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            tree_items[key] = item; return item
        for key in self.project.nodes:
            add(key)
        self._scene_tree_items = tree_items
        self.tree.expandAll()
        if self.selected in tree_items:
            self.tree.setCurrentItem(tree_items[self.selected])
        self.tree.blockSignals(False)
        self.scene_editor.canvas.build(self.project, self.folder, self.selected)
        self.resources.clear(); graphs = QTreeWidgetItem(['Графы']); images = QTreeWidgetItem(['Изображения'])
        self.resources.addTopLevelItems([graphs, images])
        for g in self.project.graphs.values():
            item = QTreeWidgetItem([g.name+' · '+('Поведение' if g.kind == 'behavior' else 'Функция')])
            item.setData(0, Qt.ItemDataRole.UserRole, ('graph', g.id)); graphs.addChild(item)
        if self.folder and (self.folder/'assets').exists():
            for path in sorted((self.folder/'assets').iterdir()):
                if path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.xpm'):
                    relative = path.relative_to(self.folder).as_posix()
                    item = QTreeWidgetItem([path.name]); item.setData(0, Qt.ItemDataRole.UserRole, ('asset', relative))
                    item.setToolTip(0, 'Перетащите на сцену: '+relative); images.addChild(item)
        self.resources.expandAll()
        self.refresh_props(); self.refresh_variables()
        if graph:
            self.graph_editor.build(self.project, graph, self.region, self.graph_object_id)
        else:
            self.graph_editor.canvas.scene().clear(); self.graph_editor.canvas.graph = None
            self.graph_editor.breadcrumb.setText('Дважды нажмите граф в ресурсах или создайте новый')
            self.graph_editor.context.clear(); self.graph_editor.signature.hide(); self.graph_editor.feedback.hide()
        self.catalog.set_context(graph, self.region)
        self.sync_state()
        self.statusBar().showMessage(f'{len(self.project.nodes)} объектов · {len(self.project.graphs)} графов · '
                                    'Локальный проект · История: до 100 операций')
        self.loading = False

    def refresh_props(self):
        while self.props_form.count():
            item = self.props_form.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()
        node = self.project.nodes.get(self.selected)
        if not node:
            self.props_heading.clear()
            self.props_form.addRow(QLabel('Выберите объект в дереве или на сцене')); return
        key = node.id
        def section(title):
            heading=QLabel(title);heading.setWordWrap(True);heading.setStyleSheet('font-weight: bold; color: #91bee9; padding-top: 8px')
            self.props_form.addRow(heading)
        # Keep the first field in the form (legacy size-editor API); the first
        # section heading is outside the form, later sections are spanning rows.
        self.props_heading.setText('Физика' if node.kind in BODIES else 'Формы' if node.kind in SHAPES else 'Объект')
        def physical_spin(label,attr,low,high,index=None):
            spin=QDoubleSpinBox();spin.setRange(low,high);spin.setDecimals(4)
            spin.setValue(getattr(node,attr) if index is None else getattr(node,attr)[index])
            def commit():
                value=spin.value()
                if index is not None:
                    value=list(getattr(self.project.nodes[key],attr));value[index]=spin.value()
                self.defer_property(key,attr,value)
            spin.editingFinished.connect(commit);self.props_form.addRow(label,spin)
            units={'gravity':'Единицы сцены/с²; мировые координаты; Y вниз', 'velocity':'Единицы сцены/с; мировые координаты; Y вниз', 'up':'Безразмерное направление; мировые координаты при g=0', 'mass':'Общая масса всех форм тела; условные единицы массы', 'angular_velocity':'Градусы/с; положительное по часовой стрелке', 'friction':'Коэффициент трения: 0…1; безразмерный', 'restitution':'Коэффициент отскока: 0…1; безразмерный'}
            spin.setToolTip(units[attr]);self.register_reset(spin,key,attr,index=index)
        if node.kind in BODIES:
            for label,attr in [('Трение','friction'),('Отскок','restitution')]:physical_spin(label,attr,0,1)
            if node.kind=='dynamic_body':
                physical_spin('Масса','mass',.0001,1e9)
                physical_spin('Угловая скорость °/с','angular_velocity',-1e9,1e9)
            if node.kind in ('controlled_body','dynamic_body'):
                for attr,label in [('gravity','Гравитация'),('velocity','Начальная скорость')]+([('up','Вверх при g=0')] if node.kind=='controlled_body' else []):
                    for i,axis in enumerate(('X','Y')):physical_spin(label+' '+axis,attr,-1e9,1e9,i)
                self.props_form.addRow(QLabel('Скорость/гравитация — мировые. Runtime не сохраняется.'))
        if node.kind=='rect_shape':
            choice=QComboBox();choice.addItems(['Обычная','Односторонняя'])
            choice.setCurrentIndex(int(node.one_way))
            choice.currentIndexChanged.connect(lambda i:self.defer_property(key,'one_way',bool(i)))
            self.props_form.addRow('Поверхность',choice);self.register_reset(choice,key,'one_way')
            normals=[(0,-1),(0,1),(-1,0),(1,0)]
            normal=QComboBox();normal.addItems(['Вверх (0,−1)','Вниз (0,1)','Влево (−1,0)','Вправо (1,0)'])
            normal.setCurrentIndex(normals.index(tuple(node.one_way_normal)))
            normal.currentIndexChanged.connect(lambda i:self.defer_property(key,'one_way_normal',list(normals[i])))
            self.props_form.addRow('Блокирующая сторона',normal);self.register_reset(normal,key,'one_way_normal')
            normal.setEnabled(node.one_way);normal.setToolTip('Сторона применяется только для односторонней поверхности. Локальная нормаль преобразуется в мир.')
        if node.kind in SHAPES:
            fields=[('Ширина','width'),('Высота','height')] if node.kind=='rect_shape' else [('Радиус','radius')] if node.kind=='circle_shape' else []
            for label,attr in fields:
                spin=QDoubleSpinBox();spin.setRange(.25,1000000);spin.setDecimals(3);spin.setValue(getattr(node,attr))
                spin.editingFinished.connect(lambda a=attr,s=spin:self.defer_property(key,a,s.value()))
                self.props_form.addRow(label,spin);self.register_reset(spin,key,attr)
            if node.kind=='polygon_shape':
                for label,new in [('Редактировать точки',False),('Нарисовать заново',True)]:
                    button=QPushButton(label);button.clicked.connect(lambda checked=False,new=new:self.scene_editor.canvas.contour.begin(key,new))
                    self.props_form.addRow(button)
                    self.register_reset(button,key,'points')
                self.props_form.addRow(QLabel('Enter — завершить; Escape — отменить черновик.\nShift+клик по ребру — вставить; Delete — убрать точку.'))
            self.props_form.addRow(QLabel('Физика: только положительный равномерный масштаб.'))
        if node.kind in BODIES or node.kind in SHAPES:section('Объект')
        name = QLineEdit(node.name)
        name.editingFinished.connect(lambda: self.defer_property(key, 'name', name.text()))
        self.props_form.addRow('Имя', name);self.register_reset(name,key,'name')
        id_label = QLineEdit(node.id); id_label.setReadOnly(True); self.props_form.addRow('ID', id_label)
        section('Преобразование — локальное; единицы сцены, масштаб ×, угол °')
        for label, attr in [('X', 'x'), ('Y', 'y'), ('Масштаб X', 'sx'), ('Масштаб Y', 'sy'), ('Поворот °', 'rotation')]:
            spin = QDoubleSpinBox(); spin.setRange(-1e9, 1e9); spin.setDecimals(3); spin.setValue(getattr(node.transform, attr))
            spin.editingFinished.connect(lambda a=attr, s=spin: self.defer_transform(key, a, s.value()))
            self.props_form.addRow(label, spin);self.register_reset(spin,key,attr,transform=True)
        if node.kind == 'sprite':
            section('Изображение — размеры в единицах сцены')
            try:
                pix = QPixmap(str(asset_path(self.folder, node.image))) if self.folder and node.image else QPixmap()
            except ValueError:
                pix = QPixmap()
            w, h = (pix.width(), pix.height()) if not pix.isNull() else (64, 64)
            for label, attr, base in [('Ширина', 'sx', w), ('Высота', 'sy', h)]:
                spin = QDoubleSpinBox(); spin.setRange(.001, 1e9); spin.setDecimals(3)
                spin.setValue(abs(getattr(node.transform, attr))*base)
                sign = 1 if getattr(node.transform, attr) > 0 else -1
                spin.editingFinished.connect(lambda a=attr, s=spin, b=base, sign=sign: self.defer_transform(key, a, sign*s.value()/b))
                self.props_form.addRow(label, spin);self.register_reset(spin,key,attr,transform=True)
            image = QComboBox(); image.addItem('Нет изображения', None)
            if self.folder and (self.folder/'assets').exists():
                for path in sorted((self.folder/'assets').iterdir()):
                    if path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.xpm'):
                        image.addItem(path.name, path.relative_to(self.folder).as_posix())
            image.setCurrentIndex(max(0, image.findData(node.image)))
            image.currentIndexChanged.connect(lambda _: self.defer_property(key, 'image', image.currentData()))
            self.props_form.addRow('Изображение', image);self.register_reset(image,key,'image')
        parent = QComboBox(); parent.addItem('Корень сцены', None)
        excluded = {key}
        while True:
            children = {n.id for n in self.project.nodes.values() if n.parent in excluded}
            if children <= excluded:
                break
            excluded |= children
        for obj in self.project.nodes.values():
            if obj.id not in excluded:
                parent.addItem(obj.name+' ['+obj.id[:8]+']', obj.id)
        parent.setCurrentIndex(max(0, parent.findData(node.parent)))
        parent.currentIndexChanged.connect(lambda _: self.defer_property(key, 'parent', parent.currentData()))
        self.props_form.addRow('Родитель', parent);self.register_reset(parent,key,'parent')
        section('Граф — общий ресурс поведения')
        graph = QComboBox(); graph.addItem('Нет поведения', None)
        for g in self.project.graphs.values():
            if g.kind == 'behavior':
                graph.addItem(g.name, g.id)
        graph.setCurrentIndex(max(0, graph.findData(node.graph)))
        graph.currentIndexChanged.connect(lambda _: self.defer_property(key, 'graph', graph.currentData()))
        self.props_form.addRow('Поведение', graph);self.register_reset(graph,key,'graph')
        button = QPushButton('Открыть прикреплённый граф')
        button.clicked.connect(lambda: self.open_graph(self.project.nodes[key].graph,key))
        button.setEnabled(node.graph is not None)
        button.setToolTip('Нет прикреплённого поведения: выберите ресурс в поле Поведение' if node.graph is None else 'Открыть общий ресурс из контекста этого объекта')
        self.props_form.addRow(button)
        self.props_form.addRow(QLabel('Положение локальное; ось Y вниз.\nПоворот по часовой стрелке; центр — начало объекта.'))
        reset_help=QLabel('ПКМ по свойству → значение по умолчанию. Сбрасывается только выбранное поле; доступна отмена.');reset_help.setWordWrap(True);self.props_form.addRow(reset_help)
        for field in self.props.findChildren(QLineEdit):
            field.installEventFilter(self)

    def register_reset(self, widget, key, attr, transform=False, index=None):
        default=SceneNode(kind=self.project.nodes[key].kind)
        value=getattr(default.transform if transform else default,attr)
        if index is not None:value=value[index]
        widget.setToolTip(widget.toolTip()+'\nПКМ: вернуть значение по умолчанию '+str(value))
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def menu_at(pos):
            menu=widget.createStandardContextMenu() if hasattr(widget,'createStandardContextMenu') else widget.lineEdit().createStandardContextMenu() if isinstance(widget,QDoubleSpinBox) else QMenu(widget)
            menu.addSeparator();action=menu.addAction('Вернуть значение по умолчанию: '+str(value))
            action.setToolTip('Только это свойство, не последнее сохранённое значение. Можно отменить.')
            global_pos=widget.mapToGlobal(pos)
            menu.setParent(self,menu.windowFlags())
            chosen=menu.exec(global_pos)==action
            menu.deleteLater()
            if chosen:
                QTimer.singleShot(0,lambda:self.reset_property(key,attr,transform,index))
        widget.customContextMenuRequested.connect(menu_at)

    def reset_property(self, key, attr, transform=False, index=None):
        self.flush_edits()
        if key not in self.project.nodes:return
        default=SceneNode(kind=self.project.nodes[key].kind)
        value=copy.deepcopy(getattr(default.transform if transform else default,attr))
        def apply():
            target=self.project.nodes[key].transform if transform else self.project.nodes[key]
            if index is not None:
                new=list(getattr(target,attr));new[index]=value[index];setattr(target,attr,new)
            else:setattr(target,attr,value)
        # Use the same History/structure transaction as normal property edits.
        self.edit('Значение свойства по умолчанию',apply)

    def defer_property(self, key, attr, value):
        if not self.loading and key in self.project.nodes and getattr(self.project.nodes[key], attr) != value:
            self.deferred_edit('Свойство объекта', lambda: setattr(self.project.nodes[key], attr, value))

    def defer_transform(self, key, attr, value):
        if not self.loading and key in self.project.nodes and getattr(self.project.nodes[key].transform, attr) != value:
            self.deferred_edit('Преобразование объекта', lambda: setattr(self.project.nodes[key].transform, attr, value))

    def refresh_variables(self):
        self.variables.clear()
        for scope, label in [('run', 'Запуска'), ('object', 'Объекта'), ('game', 'Игры')]:
            root = QTreeWidgetItem([label]); self.variables.addTopLevelItem(root)
            for var in self.project.variables.values():
                if var.scope == scope and (scope != 'run' or var.owner == self.graph_id):
                    item = QTreeWidgetItem([var.name+' · '+TYPE_LABELS[var.type]])
                    item.setData(0, Qt.ItemDataRole.UserRole, ('variable', var.id)); root.addChild(item)
        graph = self.current_graph()
        if graph and graph.kind == 'function':
            for result, label in [(False, 'Параметры функции'), (True, 'Результаты функции')]:
                root = QTreeWidgetItem([label]); self.variables.addTopLevelItem(root)
                for param in graph.results if result else graph.parameters:
                    item = QTreeWidgetItem([param.name+' · '+TYPE_LABELS[param.type]])
                    item.setData(0, Qt.ItemDataRole.UserRole, ('result' if result else 'parameter', param.id)); root.addChild(item)
        self.variables.expandAll()

    def tree_selected(self):
        if not self.loading and self.tree.currentItem():
            self.select_object(self.tree.currentItem().data(0, Qt.ItemDataRole.UserRole))

    def select_object(self, key):
        if self.selected != key and key in self.project.nodes:
            self.selected = key
            self.loading = True
            item = getattr(self,'_scene_tree_items',{}).get(key)
            if item is not None:self.tree.setCurrentItem(item)
            scene = self.scene_editor.canvas.scene()
            scene.blockSignals(True); scene.clearSelection()
            if key in self.scene_editor.canvas.items_by_id:
                self.scene_editor.canvas.items_by_id[key].setSelected(True)
            scene.blockSignals(False)
            self.refresh_props(); self.loading = False

    def commit_contour(self,key,points):
        if key in self.project.nodes:
            self.deferred_edit('Контур формы',lambda:setattr(self.project.nodes[key],'points',points))

    def add_scene(self, kind, image=None, position=None):
        if kind in SHAPES and (self.selected not in self.project.nodes or self.project.nodes[self.selected].kind not in BODIES):
            self.message('Сначала выберите физическое тело — родителя формы','warning');return
        node = SceneNode(kind=kind, name='Изображение' if kind == 'sprite' else 'Преобразование 2D',
                         parent=None if position is not None else self.selected, image=image)
        names={'static_body':'Неподвижное тело','controlled_body':'Управляемое тело','dynamic_body':'Динамическое тело','platform_body':'Платформа','rect_shape':'Прямоугольная форма','circle_shape':'Круглая форма','polygon_shape':'Многоугольная форма'}
        node.name=names.get(kind,node.name)
        if kind in BODIES and (node.parent is not None and self.project.nodes[node.parent].kind != 'transform'):node.parent=None
        if position is not None:
            node.transform.x, node.transform.y = position.x(), position.y()
        def apply():
            self.project.nodes[node.id] = node; self.selected = node.id
        self.edit('Создание объекта', apply)

    def drop_image(self, relative, position):
        self.add_scene('sprite', relative, position)

    def remove_scene(self):
        if self.selected:
            key = self.selected
            self.edit('Удаление объекта и потомков', lambda: self.project.remove_scene(key))
            for d in validate_project(self.project):
                if 'объект' in d.message.lower() or 'ссылк' in d.message.lower():
                    self.message(d)

    def tree_menu(self, position):
        item = self.tree.itemAt(position)
        if item:
            self.selected = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self); transform = menu.addAction('Добавить дочернее 2D-преобразование')
        sprite = menu.addAction('Добавить дочернее изображение'); delete = menu.addAction('Удалить с потомками')
        action = menu.exec(self.tree.mapToGlobal(position))
        if action == transform:
            self.add_scene('transform')
        elif action == sprite:
            self.add_scene('sprite')
        elif action == delete:
            self.remove_scene()

    def new_graph(self, kind):
        name, ok = QInputDialog.getText(self, 'Новый граф', 'Имя', text='Поведение' if kind == 'behavior' else 'Функция')
        if not ok:
            return
        g = Graph(name=name.strip() or 'Граф', kind=kind); g.add('key' if kind == 'behavior' else 'entry', 0, 0)
        def apply():
            self.project.graphs[g.id] = g
            self.graph_id = g.id; self.graph_object_id=None; self.region = None
        self.edit('Создание графа', apply); self.tabs.setCurrentIndex(1)
        self.graph_editor.canvas.centerOn(150, 100)

    def open_graph(self, key, object_id=None):
        if key not in self.project.graphs:
            self.message('Граф не выбран или уже удалён','warning'); return
        self.graph_id = key; self.graph_object_id = object_id; self.region = None; self.refresh(); self.tabs.setCurrentIndex(1)

    def open_region(self, region):
        graph = self.current_graph()
        if graph and (region is None or (region in graph.nodes and graph.nodes[region].kind in LOOPS)):
            try:
                region_ancestors(graph, region)
            except ValueError as exc:
                self.message(str(exc)); return
            self.region = region; self.refresh()
            self.graph_editor.canvas.resetTransform()
            self.graph_editor.canvas.scale(.85, .85)
            self.graph_editor.canvas.centerOn(-40, 180)

    def add_graph_node(self, kind, x, y):
        graph = self.current_graph()
        reason = node_availability(graph,kind,self.region)
        if reason:
            self.graph_editor.explain(reason); self.message(reason,'warning'); return
        self.edit('Создание узла графа', lambda: self.current_graph().add(kind, x, y, self.region))

    def edit_output(self, key, action, output_id):
        gid = self.graph_id
        self.deferred_edit('Выходы узла', lambda: self.project.graphs[gid].edit_output(key, action, output_id))

    def move_card(self, key, x, y):
        node = self.current_graph().nodes[key]; node.x, node.y = x, y

    def set_node_param(self, key, param, value):
        gid = self.graph_id
        self.deferred_edit('Параметр узла', lambda: self.project.graphs[gid].nodes[key].params.__setitem__(param, value))

    def add_edge(self, edge):
        if not self.current_graph():return
        self.edit('Создание связи', lambda: connect(self.project, self.current_graph(), edge))

    def remove_graph_elements(self, nodes, edges):
        def apply():
            g = self.current_graph()
            for key in nodes:
                g.remove(key)
            g.edges[:] = [e for e in g.edges if e.id not in edges]
        self.edit('Удаление карточек/связей', apply)

    def create_variable(self, node_id=None):
        dialog = VariableDialog(self.project, self.graph_id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            var = dialog.result_variable
            def apply():
                self.project.variables[var.id] = var
                if node_id and self.current_graph() and node_id in self.current_graph().nodes:
                    self.current_graph().nodes[node_id].params['variable'] = var.id
            self.edit('Создание переменной', apply)

    def add_parameter(self, result):
        g = self.current_graph()
        if not g or g.kind != 'function':
            self.message('Параметры и результаты создаются в открытом графе-функции','warning'); return
        dialog = ParameterDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            param = dialog.result_parameter
            self.edit('Создание результата' if result else 'Создание параметра',
                      lambda: (self.current_graph().results if result else self.current_graph().parameters).append(param))

    def edit_variable_or_parameter(self, item, column=0):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, key = data
        if kind == 'variable':
            original = self.project.variables[key]
            dialog = VariableDialog(self.project, self.graph_id, original, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.edit('Изменение переменной', lambda: self.project.variables.__setitem__(key, dialog.result_variable))
        else:
            values = self.current_graph().results if kind == 'result' else self.current_graph().parameters
            original = next(v for v in values if v.id == key)
            dialog = ParameterDialog(original, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.edit('Имя параметра/результата', lambda: setattr(original, 'name', dialog.result_parameter.name))

    def variable_menu(self, position):
        item = self.variables.itemAt(position)
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not data:
            return
        menu = QMenu(self); delete = menu.addAction('Удалить (использования станут ошибками)')
        if menu.exec(self.variables.mapToGlobal(position)) != delete:
            return
        if QMessageBox.question(self, 'Удаление', 'Удалить запись? Существующие ссылки не будут подменены. Ошибки появятся в консоли.') != QMessageBox.StandardButton.Yes:
            return
        kind, key = data
        def apply():
            if kind == 'variable':
                self.project.variables.pop(key)
            else:
                values = self.current_graph().results if kind == 'result' else self.current_graph().parameters
                values[:] = [v for v in values if v.id != key]
        self.edit('Удаление переменной/параметра', apply)
        for d in validate_project(self.project):
            self.message(d)

    def resource_open(self, item, column=0):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == 'graph':
            self.open_graph(data[1])

    def resource_menu(self, position):
        item = self.resources.itemAt(position)
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not data or data[0] != 'graph':
            return
        key = data[1]; menu = QMenu(self); rename = menu.addAction('Переименовать'); delete = menu.addAction('Удалить граф')
        action = menu.exec(self.resources.mapToGlobal(position))
        if action == rename:
            name, ok = QInputDialog.getText(self, 'Имя графа', 'Имя', text=self.project.graphs[key].name)
            if ok:
                self.edit('Имя графа', lambda: setattr(self.project.graphs[key], 'name', name))
        elif action == delete:
            used = any(n.graph == key for n in self.project.nodes.values()) or any(n.params.get('function') == key for g in self.project.graphs.values() for n in g.nodes.values())
            if used:
                self.message('Граф используется. Сначала снимите привязки/вызовы','warning'); return
            def apply():
                self.project.graphs.pop(key)
                self.project.variables = {k: v for k, v in self.project.variables.items() if v.owner != key}
            self.edit('Удаление графа', apply)

    def import_image(self):
        if not self.folder and not self.save():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Импорт изображения', '', 'Изображения (*.png *.jpg *.jpeg *.bmp *.xpm)')
        if not path:
            return
        try:
            if Path(path).stat().st_size > 64*1024*1024:
                raise ValueError('Изображение больше 64 МБ: лимит прототипа')
            reader = QImageReader(path)
            size = reader.size()
            if not reader.canRead() or size.width() <= 0 or size.height() <= 0 or size.width() > 16384 or size.height() > 16384:
                raise ValueError('Не удалось прочитать изображение или его размер больше 16384')
            # Decode now so a corrupt file is not copied as a valid asset.
            if reader.read().isNull():
                raise ValueError('Изображение повреждено')
            relative = import_asset(path, self.folder)
            self.refresh(); self.message('Импортирован ресурс: '+relative)
        except (OSError, ValueError) as exc:
            self.message(Diagnostic('Ошибка импорта: '+str(exc)))

    def scan_assets(self):
        for node in self.project.nodes.values():
            if node.kind == 'sprite':
                try:
                    missing = not node.image or not self.folder or QImageReader(str(asset_path(self.folder, node.image))).read().isNull()
                except ValueError:
                    missing = True
                if missing and node.id not in self.resource_warnings:
                    self.resource_warnings.add(node.id)
                    self.message(Diagnostic('Изображение отсутствует/не читается: используется видимая замена', object_id=node.id, severity='warning'))

    def message(self, value, severity='info'):
        d=value if isinstance(value,Diagnostic) else Diagnostic(str(value),severity=severity)
        self.console_panel.add(d,self.project)
        self.statusBar().showMessage(d.message,10000)

    def navigate_target(self, diagnostic, target):
        key=getattr(diagnostic,target+'_id')
        if target=='graph':
            if key in self.project.graphs:self.open_graph(key,diagnostic.object_id)
            else:self.console_panel.notice.setText('Граф уже удалён; сообщение относится к предыдущему состоянию')
        elif key in self.project.nodes:
            self.select_object(key);self.tabs.setCurrentIndex(0)
            item=self.scene_editor.canvas.items_by_id.get(key)
            if item:self.scene_editor.canvas.centerOn(item)
        else:self.console_panel.notice.setText('Источник уже удалён; сообщение относится к предыдущему состоянию')

    def navigate(self, item):
        d = item.data(Qt.ItemDataRole.UserRole)
        g = self.project.graphs.get(d.graph_id)
        if g and d.node_id in g.nodes:
            self.graph_id = g.id; self.graph_object_id = d.object_id
            try:
                region_ancestors(g, g.nodes[d.node_id].region)
                self.region = g.nodes[d.node_id].region
            except ValueError:
                self.region = None
                self.message('Область узла повреждена; открыт внешний граф','warning')
            self.refresh(); self.tabs.setCurrentIndex(1); self.graph_editor.canvas.focus_node(d.node_id)
        elif (d.shape_id or d.object_id) in self.project.nodes:
            target=d.shape_id if d.shape_id in self.project.nodes else d.object_id
            self.select_object(target); self.tabs.setCurrentIndex(0)
            self.scene_editor.canvas.centerOn(self.scene_editor.canvas.items_by_id[target])
        elif g:
            self.open_graph(g.id,d.object_id)
            if d.node_id:self.graph_editor.explain('Узел уже удалён; открыт ресурс графа')
        elif d.graph_id or d.node_id or d.object_id or d.shape_id:
            text='Элемент уже удалён; сообщение относится к предыдущему состоянию'
            self.statusBar().showMessage(text,10000);self.console_panel.notice.setText(text)

    def maybe_save(self):
        self.flush_edits()
        if not self.dirty():
            return True
        box = QMessageBox(self); box.setWindowTitle('Несохранённые изменения'); box.setText('Сохранить изменения проекта?')
        save = box.addButton('Сохранить', QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton('Не сохранять', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('Отмена', QMessageBox.ButtonRole.RejectRole); box.exec()
        if box.clickedButton() == save:
            return self.save()
        return box.clickedButton() == discard

    def new_project(self):
        if not self.maybe_save():
            return
        dialog = ProjectDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        folder = QFileDialog.getExistingDirectory(self, 'Выберите папку нового локального проекта')
        if not folder:
            return
        folder = Path(folder)
        if (folder/PROJECT_FILE).exists():
            self.message('В папке уже есть проект: откройте его или выберите другую папку'); return
        p = Project(name=dialog.name.text(), width=dialog.width.value(), height=dialog.height.value())
        try:
            save_project(p, folder)
            self.replace_project(p, folder)
        except (OSError, ValueError) as exc:
            self.message(Diagnostic('Ошибка создания проекта: '+str(exc)))

    def replace_project(self, project, folder):
        self.scene_editor.canvas.contour.cancel()
        self.pending_edits.clear()
        self.stop_game(); self.project = project; self.folder = Path(folder)
        self.saved = project.to_dict(); self.history = History()
        self.selected = None; self.graph_id = None; self.region = None; self.resource_warnings.clear()
        self.console_panel.clear(); self.graph_object_id=None; self.last_run_error=False; self.refresh(); self.scene_editor.fit(); self.scan_assets()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Открыть проект', '', 'Horo (project.horo.json *.horo.json)')
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            p = load_project(path)  # Fully validate before touching the current document.
            if not self.maybe_save():
                return False
            folder = Path(path) if Path(path).is_dir() else Path(path).parent
            self.replace_project(p, folder); return True
        except (OSError, ValueError) as exc:
            self.message(Diagnostic('Ошибка открытия проекта: '+str(exc))); return False

    def save(self):
        self.flush_edits()
        folder = self.folder
        if folder is None:
            path = QFileDialog.getExistingDirectory(self, 'Папка локального проекта')
            if not path:
                return False
            folder = Path(path)
            if (folder/PROJECT_FILE).exists():
                self.message('В папке уже есть проект. Выберите другую папку, чтобы не перезаписать его'); return False
        try:
            save_project(self.project, folder)
            self.folder = folder; self.saved = self.project.to_dict(); self.refresh()
            self.message('Проект сохранён локально'); return True
        except (OSError, ValueError) as exc:
            self.message(Diagnostic('Ошибка сохранения: '+str(exc))); return False

    def project_settings(self):
        dialog = ProjectDialog(self.project, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            def apply():
                self.project.name = dialog.name.text(); self.project.width = dialog.width.value(); self.project.height = dialog.height.value()
            self.edit('Параметры проекта', apply)

    def run_game(self):
        self.flush_edits()
        if self.game and self.game.runtime.running:
            self.game.raise_(); self.game.activateWindow(); self.game.setFocus(); return
        if self.game:
            self.stop_game()
        errors = validate_project(self.project)
        if errors:
            self.last_run_error=True;self.sync_state()
            self.graph_editor.explain(errors[0].message)
            for d in errors:
                self.message(d)
            next(d for d in self.docks if d.objectName() == 'console').raise_()
            return
        self.scan_assets()
        try:
            self.game = GameWindow(Runtime(self.project), self.folder)
            self.last_run_error=False;self.sync_state()
            self.game.failed.connect(self.game_failed)
            self.game.finished.connect(self.game_finished)
            self.game.show(); self.game.raise_(); self.game.activateWindow(); self.game.setFocus()
            self.message('Игра запущена на отдельном снимке. Правки редактора применятся только при следующем запуске.')
        except GraphError as exc:
            self.game_failed(exc.diagnostic)

    def game_failed(self, diagnostic):
        self.last_run_error=True;self.sync_state();self.message(diagnostic)
        self.graph_editor.explain(diagnostic.message)

    def sync_state(self):
        running=bool(self.game and self.game.runtime.running)
        text="Игра запущена" if running else "Остановлено из-за ошибки" if self.last_run_error else "Редактирование"
        self.state_label.setText(text)
        self.state_label.setToolTip("Правки редактора применятся к следующему запуску, не текущему снимку" if running else text)
        self.stop_action.setEnabled(self.game is not None)
        self.stop_action.setToolTip("Остановить и закрыть игровое окно" if self.game else "Нет игрового окна для остановки")
        self.run_action.setToolTip("Перейти в уже запущенное игровое окно" if running else "Проверить проект и запустить новый снимок")

    def game_finished(self):
        self.game = None;self.sync_state()

    def stop_game(self):
        if self.game:
            game = self.game; self.game = None; game.close()
        self.sync_state()

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.ShortcutOverride
                and isinstance(watched, (QLineEdit, QPlainTextEdit, QTextEdit))):
            # Text editing owns keyboard input; menu/toolbar clicks still work.
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        if self.maybe_save():
            self.stop_game(); event.accept()
        else:
            event.ignore()
