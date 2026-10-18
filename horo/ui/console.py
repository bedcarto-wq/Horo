"""Bounded, session-only diagnostics; no runtime values or clipboard side effects."""
from collections import OrderedDict
import hashlib
import json
from dataclasses import replace
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QListWidget,QListWidgetItem,
    QCheckBox,QPushButton,QPlainTextEdit,QApplication,QLabel)

LEVELS = {'error':'Ошибка','warning':'Предупреждение','info':'Сообщение'}
LIMIT = 1000
NOTICE = 'До 1000 записей. Значения переменных и входов не раскрываются.'


class ConsolePanel(QWidget):
    navigate_requested = Signal(object,str)
    def __init__(self):
        super().__init__(); self.records=OrderedDict()
        layout=QVBoxLayout(self);layout.setContentsMargins(4,4,4,4)
        tools=QHBoxLayout();self.filters={}
        for level,title in LEVELS.items():
            check=QCheckBox(title);check.setChecked(True);check.toggled.connect(self.apply_filters)
            self.filters[level]=check;tools.addWidget(check)
        self.clear_button=QPushButton('Очистить');self.clear_button.clicked.connect(self.clear)
        tools.addWidget(self.clear_button);layout.addLayout(tools)
        self.targets={}
        sources=QHBoxLayout()
        for kind,title in [('graph','К графу'),('object','К объекту'),('shape','К форме')]:
            button=QPushButton(title);button.clicked.connect(lambda checked=False,k=kind:self.navigate_target(k))
            sources.addWidget(button);self.targets[kind]=button
        layout.addLayout(sources)
        self.list=QListWidget();self.list.setWordWrap(True);layout.addWidget(self.list)
        row=QHBoxLayout();self.technical=QCheckBox('Технические сведения');row.addWidget(self.technical)
        self.copy_button=QPushButton('Копировать подробности');row.addWidget(self.copy_button);layout.addLayout(row)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(160);self.details.hide()
        layout.addWidget(self.details)
        self.notice=QLabel(NOTICE);self.notice.setWordWrap(True);layout.addWidget(self.notice)
        self.technical.toggled.connect(self.details.setVisible)
        self.list.currentItemChanged.connect(self.show_details)
        self.copy_button.clicked.connect(self.copy_details)
        self.show_details();self.copy_button.setEnabled(False);self.copy_button.setToolTip('Выберите сообщение для копирования безопасных подробностей')

    def add(self,d,project):
        self.notice.setText(NOTICE)
        # A call/frame identity is part of the key; different instances/calls do
        # not silently collapse into one. Values affect equality, never output.
        key=hashlib.sha256(json.dumps([d.severity,d.message,d.graph_id,d.node_id,d.object_id,d.shape_id,d.expected,d.received,d.invocation],ensure_ascii=False).encode('utf-8')).digest()
        if key in self.records:
            item,count,text=self.records[key];count+=1
            self.records[key]=(item,count,text);self.records.move_to_end(key)
        else:
            safe=replace(d,received=None)
            text=safe.describe(project,include_values=False)
            item=QListWidgetItem();item.setData(Qt.ItemDataRole.UserRole,safe)
            self.list.addItem(item);count=1;self.records[key]=(item,count,text)
        source=' · '.join(label for label in [
            ('Граф: '+project.graphs[d.graph_id].name) if d.graph_id in project.graphs else '',
            ('Объект: '+project.nodes[d.object_id].name+' ['+d.object_id[:8]+']') if d.object_id in project.nodes else '',
            ('Форма: '+project.nodes[d.shape_id].name) if d.shape_id in project.nodes else '',
            ('Вызов: '+d.invocation[:8]+'/'+d.invocation.rsplit('/',1)[-1]) if d.invocation else ''] if label)
        item.setText(f'{LEVELS.get(d.severity,"Сообщение")} · {d.message}'+(f' ×{count}' if count>1 else '') + ('\n'+source if source else ''))
        item.setToolTip(text)
        while len(self.records)>LIMIT:
            _,(old,_,_)=self.records.popitem(last=False);self.list.takeItem(self.list.row(old))
        self.apply_filters();self.show_details();self.list.scrollToBottom()

    def apply_filters(self,*_):
        for item,_,_ in self.records.values():
            d=item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(not self.filters.get(d.severity,self.filters['info']).isChecked())

    def show_details(self,*_):
        item=self.list.currentItem();self.copy_button.setEnabled(item is not None)
        text=next((text+(f'\nПовторов: {count}' if count>1 else '') for i,count,text in self.records.values() if i is item),'')
        self.details.setPlainText(text)
        d=item.data(Qt.ItemDataRole.UserRole) if item else None
        for kind,button in self.targets.items():
            present=bool(d and getattr(d,kind+'_id'))
            button.setEnabled(present);button.setToolTip('Перейти к источнику; удалённый источник будет объяснён' if present else 'У сообщения нет этого источника')

    def navigate_target(self,kind):
        item=self.list.currentItem()
        if item:self.navigate_requested.emit(item.data(Qt.ItemDataRole.UserRole),kind)

    def copy_details(self):
        self.show_details()
        if self.list.currentItem():QApplication.clipboard().setText(self.details.toPlainText())

    def clear(self):
        self.notice.setText(NOTICE)
        self.records.clear();self.list.clear();self.details.clear();self.copy_button.setEnabled(False);self.show_details()
