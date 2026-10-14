"""Small reusable forms. All values are typed, never eval'd."""
import json
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                              QComboBox, QDialogButtonBox, QMessageBox, QSpinBox)
from ..model import TYPES, TYPE_LABELS, Variable, Parameter, initial, valid_value


def typed_value(text, kind):
    if kind == 'text':
        return text
    if kind == 'object':
        return text.strip() or None
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError('Введите число, true/false или вектор [x, y] в формате JSON') from exc
    if not valid_value(kind, value):
        raise ValueError('Значение не соответствует выбранному типу')
    return value


def format_value(value, kind):
    if kind == 'text':
        return value
    if kind == 'object':
        return value or ''
    return json.dumps(value, ensure_ascii=False)

class VariableDialog(QDialog):
    def __init__(self, project, graph_id, variable=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Переменная'); self.project = project; self.graph_id = graph_id
        self.original = variable; self.result_variable = None
        outer = QVBoxLayout(self); form = QFormLayout(); outer.addLayout(form)
        self.name = QLineEdit(variable.name if variable else 'Переменная')
        self.type = QComboBox()
        for kind in TYPES:
            self.type.addItem(TYPE_LABELS[kind], kind)
        self.scope = QComboBox()
        for label, key in [('Запуска (текущий граф)', 'run'), ('Объекта', 'object'), ('Игры', 'game')]:
            self.scope.addItem(label, key)
        self.value = QLineEdit()
        form.addRow('Имя', self.name); form.addRow('Тип', self.type)
        form.addRow('Область', self.scope); form.addRow('Начальное значение', self.value)
        self.value.setToolTip('Число: 0; логическое: true/false; вектор: [0, 0]; объект: ID или пусто')
        self.type.currentIndexChanged.connect(self.default_value)
        if variable:
            self.type.setCurrentIndex(TYPES.index(variable.type))
            self.scope.setCurrentIndex(self.scope.findData(variable.scope))
            self.value.setText(format_value(variable.value, variable.type))
            # Type/scope edits of referenced variables require deliberate delete/recreate.
            self.type.setEnabled(False); self.scope.setEnabled(False)
        else:
            self.default_value()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        outer.addWidget(buttons); buttons.accepted.connect(self.finish); buttons.rejected.connect(self.reject)

    def default_value(self):
        kind = self.type.currentData()
        self.value.setText(format_value(initial(kind), kind))

    def finish(self):
        try:
            kind, scope = self.type.currentData(), self.scope.currentData()
            value = typed_value(self.value.text(), kind)
            if scope == 'run' and self.graph_id not in self.project.graphs:
                raise ValueError('Сначала откройте граф для переменной запуска')
            if kind == 'object' and value is not None and value not in self.project.nodes:
                raise ValueError('Такого ID объекта нет в сцене')
            if not self.name.text().strip():
                raise ValueError('Укажите имя')
            kwargs = dict(name=self.name.text().strip(), type=kind, scope=scope, value=value,
                          owner=self.original.owner if self.original else self.graph_id if scope == 'run' else None)
            if self.original:
                kwargs['id'] = self.original.id
            self.result_variable = Variable(**kwargs)
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, 'Переменная', str(exc))

class ParameterDialog(QDialog):
    def __init__(self, parameter=None, parent=None):
        super().__init__(parent); self.setWindowTitle('Параметр / результат')
        self.original = parameter; self.result_parameter = None
        outer = QVBoxLayout(self); form = QFormLayout(); outer.addLayout(form)
        self.name = QLineEdit(parameter.name if parameter else 'Значение')
        self.type = QComboBox()
        for kind in TYPES:
            self.type.addItem(TYPE_LABELS[kind], kind)
        if parameter:
            self.type.setCurrentIndex(TYPES.index(parameter.type)); self.type.setEnabled(False)
        form.addRow('Имя', self.name); form.addRow('Тип', self.type)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        outer.addWidget(buttons); buttons.accepted.connect(self.finish); buttons.rejected.connect(self.reject)

    def finish(self):
        if not self.name.text().strip():
            return
        kw = dict(name=self.name.text().strip(), type=self.type.currentData())
        if self.original:
            kw['id'] = self.original.id
        self.result_parameter = Parameter(**kw); self.accept()

class ProjectDialog(QDialog):
    def __init__(self, project=None, parent=None):
        super().__init__(parent); self.setWindowTitle('Параметры проекта')
        outer = QVBoxLayout(self); form = QFormLayout(); outer.addLayout(form)
        self.name = QLineEdit(project.name if project else 'Новый проект')
        self.width = QSpinBox(); self.width.setRange(1, 16384); self.width.setValue(project.width if project else 800)
        self.height = QSpinBox(); self.height.setRange(1, 16384); self.height.setValue(project.height if project else 600)
        form.addRow('Имя', self.name); form.addRow('Ширина экрана', self.width); form.addRow('Высота экрана', self.height)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        outer.addWidget(buttons); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
