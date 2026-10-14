"""Synchronous, bounded graph interpreter. Authoring project is never mutated."""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
from .model import initial, valid_value, number
from .errors import Diagnostic, GraphError
from .validation import validate_project

STEP_LIMIT = 10000

@dataclass
class Frame:
    graph: object
    object_id: str | None
    arguments: dict = field(default_factory=dict)
    temporary: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)

class Control(Exception):
    def __init__(self, kind, values=None):
        self.kind, self.values = kind, values

class Runtime:
    def __init__(self, project, step_limit=STEP_LIMIT):
        errors = validate_project(project)
        if errors:
            raise GraphError(errors[0])
        self.project = project.clone()
        self.step_limit = step_limit
        self.steps = 0
        self.running = True
        self.game = {v.id: copy.deepcopy(v.value) for v in project.variables.values() if v.scope == 'game'}
        self.objects = {oid: {v.id: copy.deepcopy(v.value) for v in project.variables.values()
                              if v.scope == 'object'} for oid in project.nodes}

    def stop(self):
        self.running = False

    def fail(self, frame, node, message, expected=None, received=None):
        self.running = False
        raise GraphError(Diagnostic(message, frame.graph.id, node.id if node else None,
                                    frame.object_id, expected, received))

    def tick(self, frame, node):
        self.steps += 1
        if self.steps > self.step_limit:
            self.fail(frame, node, f'Превышен лимит {self.step_limit} шагов за событие/кадр')

    def frame(self, graph, object_id, arguments=None):
        temporary = {v.id: copy.deepcopy(v.value) for v in self.project.variables.values()
                     if v.scope == 'run' and v.owner == graph.id}
        return Frame(graph, object_id, arguments or {}, temporary)

    def key_press(self, key, auto_repeat=False):
        if not self.running or auto_repeat:
            return
        # One budget for all instances reacting to this physical key event.
        self.steps = 0
        try:
            for obj in self.project.nodes.values():
                if obj.graph is None:
                    continue
                graph = self.project.graphs[obj.graph]
                start = next(n for n in graph.nodes.values() if n.kind == 'key')
                if start.params.get('key', 'Space') == key:
                    frame = self.frame(graph, obj.id)
                    self.tick(frame, start)
                    self.execute(frame, self.next(frame, start, 'next'))
        except GraphError:
            self.running = False
            raise
        except (RecursionError, OverflowError) as exc:
            self.fail(frame, start, f'Превышена допустимая глубина вычислений: {exc}')

    def next(self, frame, node, output='next'):
        edge = next((e for e in frame.graph.edges if e.source == node.id and e.output == output), None)
        return frame.graph.nodes[edge.target] if edge else None

    def check(self, frame, node, kind, value):
        if not valid_value(kind, value):
            self.fail(frame, node, 'Значение не соответствует типу', kind, repr(value))
        return value

    def input(self, frame, node, port, cache, default=...):
        edge = next((e for e in frame.graph.edges if e.target == node.id and e.input == port), None)
        if edge is None:
            if default is not ...:
                return copy.deepcopy(default)
            self.fail(frame, node, f'Не подключён обязательный вход «{port}»')
        return self.evaluate(frame, frame.graph.nodes[edge.source], edge.output, cache)

    def store(self, frame, node, cache):
        var = self.project.variables.get(node.params.get('variable'))
        if not var:
            self.fail(frame, node, 'Переменная не найдена')
        if var.scope == 'game':
            return var, self.game
        if var.scope == 'run':
            return var, frame.temporary
        oid = self.input(frame, node, 'object', cache,
                         frame.object_id if frame.graph.kind == 'behavior' else ...)
        if oid not in self.objects:
            self.fail(frame, node, 'Для переменной требуется существующий объект', 'Объект', repr(oid))
        return var, self.objects[oid]

    def evaluate(self, frame, node, output, cache):
        # Each queried pure node has one snapshot per action, not per port.
        if node.id not in cache:
            self.tick(frame, node)
            kind = node.kind
            if kind in ('number', 'text', 'bool', 'object'):
                value = node.params.get('value', initial(kind))
                values = {'value': self.check(frame, node, kind, value)}
            elif kind == 'vector':
                x = self.input(frame, node, 'x', cache, node.params.get('x', 0))
                y = self.input(frame, node, 'y', cache, node.params.get('y', 0))
                values = {'value': self.check(frame, node, 'vector', [x, y])}
            elif kind == 'key':
                values = {'object': frame.object_id}
            elif kind == 'entry':
                values = dict(frame.arguments)
            elif kind == 'read':
                var, store = self.store(frame, node, cache)
                values = {'value': copy.deepcopy(store[var.id])}
            elif kind in ('add', 'greater'):
                a = self.check(frame, node, 'number', self.input(frame, node, 'a', cache))
                b = self.check(frame, node, 'number', self.input(frame, node, 'b', cache))
                value = a+b if kind == 'add' else a > b
                values = {'value': self.check(frame, node, 'number' if kind == 'add' else 'bool', value)}
            elif kind == 'call':
                if node.id not in frame.calls:
                    self.fail(frame, node, 'Результат функции запрошен до выполнения вызова')
                values = {'result:'+k: v for k, v in frame.calls[node.id].items()}
            else:
                self.fail(frame, node, 'Этот узел не является источником данных')
            cache[node.id] = values
        if output not in cache[node.id]:
            self.fail(frame, node, 'Не найден выход данных', output, ', '.join(cache[node.id]))
        return copy.deepcopy(cache[node.id][output])

    def invoke(self, frame, node, cache):
        fn = self.project.graphs.get(node.params.get('function'))
        if not fn or fn.kind != 'function':
            self.fail(frame, node, 'Функция не найдена')
        if frame.graph.kind != 'behavior':
            self.fail(frame, node, 'Вложенные вызовы и рекурсия запрещены в 0.1')
        args = {p.id: self.check(frame, node, p.type, self.input(frame, node, 'arg:'+p.id, cache))
                for p in fn.parameters}
        nested = self.frame(fn, frame.object_id, args)
        entry = next(n for n in fn.nodes.values() if n.kind == 'entry')
        self.tick(nested, entry)
        try:
            self.execute(nested, self.next(nested, entry))
        except Control as signal:
            if signal.kind == 'return':
                return signal.values
            self.fail(nested, entry, 'Прерывание цикла вне тела')
        if fn.results:
            self.fail(nested, entry, 'Путь функции завершился без возврата заявленных результатов')
        return {}

    def execute(self, frame, node):
        while node is not None and self.running:
            self.tick(frame, node)
            cache = {}  # A new action sees preceding writes.
            kind = node.kind
            if kind == 'move':
                oid = self.input(frame, node, 'object', cache)
                if not isinstance(oid, str) or oid not in self.project.nodes:
                    self.fail(frame, node, 'Не найден объект для перемещения', 'Существующий объект', repr(oid))
                delta = self.check(frame, node, 'vector', self.input(frame, node, 'delta', cache))
                transform = self.project.nodes[oid].transform
                x, y = transform.x + delta[0], transform.y + delta[1]
                if not number(x) or not number(y):
                    self.fail(frame, node, 'Координаты вышли за допустимый числовой диапазон')
                transform.x, transform.y = x, y
            elif kind == 'write':
                var, store = self.store(frame, node, cache)
                store[var.id] = self.check(frame, node, var.type, self.input(frame, node, 'value', cache))
            elif kind == 'if':
                cond = self.check(frame, node, 'bool', self.input(frame, node, 'condition', cache))
                node = self.next(frame, node, 'yes' if cond else 'no')
                continue
            elif kind == 'call':
                frame.calls[node.id] = self.invoke(frame, node, cache)
            elif kind == 'return':
                values = {p.id: self.check(frame, node, p.type, self.input(frame, node, p.id, cache))
                          for p in frame.graph.results}
                raise Control('return', values)
            elif kind == 'repeat':
                count = self.check(frame, node, 'number', self.input(frame, node, 'n', cache))
                if count < 0 or int(count) != count:
                    self.fail(frame, node, 'N должно быть целым неотрицательным числом', '0, 1, 2, …', repr(count))
                for _ in range(int(count)):
                    self.tick(frame, node)  # Empty bodies also consume the budget.
                    try:
                        self.execute(frame, self.next(frame, node, 'body'))
                    except Control as signal:
                        if signal.kind == 'break':
                            break
                        if signal.kind == 'continue':
                            continue
                        raise  # return unwinds the entire function, even from its loop.
            elif kind in ('break', 'continue'):
                raise Control(kind)
            else:
                self.fail(frame, node, 'В красную цепочку попал неисполняемый узел')
            node = self.next(frame, node)
