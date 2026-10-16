"""Cooperative, bounded graph interpreter. Authoring project is never mutated."""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
import heapq
import itertools
import time
from collections import deque
from .scheduling import Scope, Task
from .ports import PHYSICS_READ, PHYSICS_ACTION
from .physics import PhysicsWorld, PhysicsError, BODIES
from .geometry import unit
from .ports import STARTS, LOOPS
from .model import initial, valid_value, number
from .errors import Diagnostic, GraphError
from .validation import validate_project

STEP_LIMIT = 10000
TASK_LIMIT = 1024
CALL_LIMIT = 64

@dataclass
class Frame:
    graph: object
    object_id: str | None
    arguments: dict = field(default_factory=dict)
    temporary: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    event: dict = field(default_factory=dict)
    depth: int = 0

class Control(Exception):
    def __init__(self, kind, values=None):
        self.kind, self.values = kind, values

class Runtime:
    def __init__(self, project, step_limit=STEP_LIMIT, clock=None, task_limit=TASK_LIMIT, call_limit=CALL_LIMIT):
        errors = validate_project(project)
        if errors:
            raise GraphError(errors[0])
        self.project = project.clone()
        if not all(type(value) is int and value > 0 for value in (step_limit, task_limit, call_limit)):
            raise ValueError('Лимиты должны быть положительными целыми числами')
        self.clock = clock or time.monotonic
        self.now = self.clock()
        if not number(self.now):
            raise ValueError('Источник времени должен вернуть конечное число')
        self.origin_time = self.last_update = self.now
        self.epoch = 0; self.started = False
        self.task_limit, self.call_limit = task_limit, call_limit
        self.tasks = {}; self.scopes = {}; self.ready = deque(); self.sleepers = []
        self._ids = itertools.count(1); self._wake_order = itertools.count(1)
        self.step_limit = step_limit
        self.steps = 0
        self.running = True
        self.held = set(); self.contact_queue = []; self.physics = None
        if any(n.kind in BODIES for n in self.project.nodes.values()):
            try:
                self.physics = PhysicsWorld(self.project)
            except PhysicsError as exc:
                raise GraphError(Diagnostic(str(exc), object_id=exc.body, shape_id=exc.shape)) from exc
        self.game = {v.id: copy.deepcopy(v.value) for v in project.variables.values() if v.scope == 'game'}
        self.objects = {oid: {v.id: copy.deepcopy(v.value) for v in project.variables.values()
                              if v.scope == 'object'} for oid in project.nodes}

    def stop(self):
        self.running = False
        self.held.clear(); self.contact_queue.clear()
        if self.physics: self.physics.stop()
        for scope in self.scopes.values():
            scope.cancelled = True; scope.done = True; scope.children.clear()
        self.tasks.clear(); self.scopes.clear(); self.ready.clear(); self.sleepers.clear()

    def fail(self, frame, node, message, expected=None, received=None):
        self.stop()
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
            if kind in PHYSICS_READ:
                oid=self.input(frame,node,'object',cache)
                try:
                    if self.physics is None:raise PhysicsError('В сцене нет физических тел')
                    value=self.physics.dynamics.read(kind,oid)
                except PhysicsError as exc:self.fail(frame,node,str(exc))
                values={'value':value}
            elif kind in ('dot','vector_add','vector_sub'):
                a=self.check(frame,node,'vector',self.input(frame,node,'a',cache))
                b=self.check(frame,node,'vector',self.input(frame,node,'b',cache))
                value=sum(x*y for x,y in zip(a,b)) if kind=='dot' else [a[i]+b[i] if kind=='vector_add' else a[i]-b[i] for i in (0,1)]
                values={'value':self.check(frame,node,'number' if kind=='dot' else 'vector',value)}
            elif kind == 'held':
                values = {'value': node.params.get('key','Space') in self.held}
            elif kind == 'direction':
                keys = {k: node.params.get(k,d) in self.held for k,d in [('left','A'),('right','D'),('up','W'),('down','S')]}
                values = {'value': [int(keys['right'])-int(keys['left']),int(keys['down'])-int(keys['up'])]}
            elif kind in ('normalize','vector_scale'):
                v = self.check(frame,node,'vector',self.input(frame,node,'vector',cache))
                if kind == 'normalize': result = list(unit(v))
                else:
                    factor = self.check(frame,node,'number',self.input(frame,node,'factor',cache))
                    result = [v[0]*factor,v[1]*factor]
                values = {'value': self.check(frame,node,'vector',result)}
            elif kind in ('number', 'text', 'bool', 'object'):
                value = node.params.get('value', initial(kind))
                values = {'value': self.check(frame, node, kind, value)}
            elif kind == 'vector':
                x = self.input(frame, node, 'x', cache, node.params.get('x', 0))
                y = self.input(frame, node, 'y', cache, node.params.get('y', 0))
                values = {'value': self.check(frame, node, 'vector', [x, y])}
            elif kind in STARTS:
                if frame.event.get('start', node.id) != node.id:
                    self.fail(frame, node, 'Данные другого старта недоступны в этом запуске')
                values = {'object': frame.object_id, 'time': frame.event.get('time', 0),
                          'key': frame.event.get('key', node.params.get('key', 'Space')),
                          'delta': frame.event.get('delta', 0), 'other': frame.event.get('other')}
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

    def _new_scope(self, kind, frame, parent=None, on_complete=None):
        scope = Scope(next(self._ids), kind, frame, parent, on_complete)
        self.scopes[scope.id] = scope
        if parent:
            parent.children.add(('scope', scope.id))
        return scope

    def _spawn(self, scope, node, origin=None):
        if len(self.tasks) >= self.task_limit:
            self.fail(scope.frame, origin or node, f'Превышен лимит {self.task_limit} живых задач')
        task = Task(next(self._ids), scope.frame, node, scope, origin or node)
        self.tasks[task.id] = task
        scope.children.add(('task', task.id))
        self._ready(task)
        return task

    def _ready(self, task):
        if task.id in self.tasks:
            task.waiting = False
            self.ready.append(('task', task.id, None))

    def _seal(self, scope):
        scope.sealed = True
        if not scope.children:
            self._complete(scope)

    def _complete(self, scope):
        if scope.done:
            return
        if scope.kind == 'call' and scope.frame.graph.results and not scope.returned and not scope.cancelled:
            entry = next(n for n in scope.frame.graph.nodes.values() if n.kind == 'entry')
            self.fail(scope.frame, entry, 'Путь функции завершился без возврата заявленных результатов')
        scope.done = True
        self.scopes.pop(scope.id, None)
        if scope.parent:
            scope.parent.children.discard(('scope', scope.id))
        if scope.on_complete and not scope.cancelled:
            owner, callback = scope.on_complete
            if owner in self.tasks:
                self.ready.append(('callback', owner, lambda: callback(scope)))
        if scope.parent and scope.parent.sealed and not scope.parent.children:
            self._complete(scope.parent)

    def _finish_task(self, task):
        self.tasks.pop(task.id, None)
        task.scope.children.discard(('task', task.id))
        if task.scope.sealed and not task.scope.children:
            self._complete(task.scope)

    def _terminate(self, scope, outcome=None, values=None):
        """Cancel descendants without firing their completion handlers; finish just the owner."""
        if scope.done:
            return
        stack = [scope]
        scopes, removed = [], set()
        while stack:
            current = stack.pop()
            scopes.append(current)
            # Traversal order does not execute user work or select a winner.
            for kind, key in current.children:
                if kind == 'scope' and key in self.scopes:
                    stack.append(self.scopes[key])
                elif kind == 'task':
                    removed.add(key)
        for key in removed:
            self.tasks.pop(key, None)
        for current in scopes[1:]:
            current.cancelled = True; current.done = True
            current.children.clear(); self.scopes.pop(current.id, None)
        scope.children.clear()
        scope.outcome = outcome
        if values is not None:
            scope.returned = True; scope.results = values
        self.ready = deque(work for work in self.ready if work[1] not in removed)
        self.sleepers = [wake for wake in self.sleepers if wake[3] not in removed]
        heapq.heapify(self.sleepers)
        self._complete(scope)

    def cancel(self, scope):
        """Public idempotent cancellation of one launch/call handle."""
        if scope.done:
            return
        scope.cancelled = True
        self._terminate(scope)

    def _drain(self):
        while self.ready and self.running:
            kind, key, callback = self.ready.popleft()
            task = self.tasks.get(key)
            if task is None:
                continue
            try:
                if kind == 'callback':
                    self.tick(task.frame, task.node or task.origin)
                    callback()
                elif not task.waiting:
                    self._step(task)
            except (RecursionError, OverflowError) as exc:
                self.fail(task.frame, task.node or task.origin,
                          f'Превышена допустимая глубина/числовой диапазон вычислений: {exc}')

    def _refresh_time(self):
        value = self.clock()
        if not number(value) or value < self.now:
            self.stop()
            raise GraphError(Diagnostic('Источник времени должен быть конечным и монотонным'))
        self.now = value

    def _dispatch(self, kind, key=None, delta=0):
        for obj in self.project.nodes.values():
            if obj.graph is None:
                continue
            graph = self.project.graphs[obj.graph]
            for node in graph.nodes.values():
                if node.kind != kind or (kind in ('key', 'key_release') and node.params.get('key', 'Space') != key):
                    continue
                frame = self.frame(graph, obj.id)
                frame.event = {'start': node.id, 'key': key, 'time': self.now-self.origin_time, 'delta': delta}
                scope = self._new_scope('run', frame)
                self._spawn(scope, node)
                self._seal(scope)

    def start(self):
        if self.started or not self.running:
            return
        self.started = True
        self._refresh_time()
        self._dispatch('start')
        self._drain()

    def key_press(self, key, auto_repeat=False):
        if auto_repeat or not self.running:
            return
        self.held.add(key)
        self.start(); self._refresh_time()
        self._dispatch('key', key)
        self._drain()

    def key_release(self, key, auto_repeat=False):
        if auto_repeat or not self.running:
            return
        self.held.discard(key)
        self.start(); self._refresh_time()
        self._dispatch('key_release', key)
        self._drain()

    def update(self):
        """One game update: one shared budget, wake due tasks, then frame events."""
        if not self.running:
            return
        self.steps = 0; self.epoch += 1
        self.start(); self._refresh_time()
        delta = self.now-self.last_update
        self.last_update = self.now
        deferred = []
        while self.sleepers and self.sleepers[0][0] <= self.now:
            deadline, order, epoch, task_id = heapq.heappop(self.sleepers)
            task = self.tasks.get(task_id)
            if task is None:
                continue
            if epoch > self.epoch:
                deferred.append((deadline, order, epoch, task_id))
            else:
                self._ready(task)
        for wake in deferred:
            heapq.heappush(self.sleepers, wake)
        pending, self.contact_queue = self.contact_queue, []
        for kind,pair in pending:
            self._dispatch_contact(kind,pair)
        self._dispatch('frame', delta=delta)
        self._drain()
        if self.running and self.physics:
            contexts = {**{k:(None,v) for k,v in self.physics.dynamics.contexts.items()},**self.physics.commands}
            try:
                self.contact_queue.extend(self.physics.update(delta))
            except PhysicsError as exc:
                context = contexts.get(exc.body, (None,None))[1]
                self.stop()
                frame,node = context if context else (None,None)
                raise GraphError(Diagnostic(str(exc), frame.graph.id if frame else None,
                    node.id if node else None, exc.body, shape_id=exc.shape)) from exc

    def _dispatch_contact(self,kind,pair):
        for oid,other in (pair,tuple(reversed(pair))):
            obj = self.project.nodes.get(oid)
            if obj is None or obj.graph is None: continue
            graph = self.project.graphs.get(obj.graph)
            if graph is None: continue
            for node in graph.nodes.values():
                if node.kind != kind: continue
                frame = self.frame(graph,oid)
                frame.event = {'start':node.id,'time':self.now-self.origin_time,'other':other}
                scope = self._new_scope('run',frame); self._spawn(scope,node); self._seal(scope)

    def execute(self, frame, node):
        """Compatibility entry: ready work completes now; waits return a cancellable handle."""
        if not self.running:
            return None
        scope = self._new_scope('run', frame)
        self._spawn(scope, node)
        self._seal(scope); self._drain()
        return scope

    def _call_scope(self, frame, node, cache, parent=None, on_complete=None):
        fn = self.project.graphs.get(node.params.get('function'))
        if not fn or fn.kind != 'function':
            self.fail(frame, node, 'Функция не найдена')
        if frame.depth >= self.call_limit:
            self.fail(frame, node, f'Превышен лимит {self.call_limit} уровней вызова функций')
        args = {p.id: self.check(frame, node, p.type, self.input(frame, node, 'arg:'+p.id, cache))
                for p in fn.parameters}
        nested = self.frame(fn, frame.object_id, args)
        nested.depth = frame.depth+1
        scope = self._new_scope('call', nested, parent, on_complete)
        entry = next(n for n in fn.nodes.values() if n.kind == 'entry')
        self._spawn(scope, entry, node)
        self._seal(scope)
        return scope

    def invoke(self, frame, node, cache):
        scope = self._call_scope(frame, node, cache)
        self._drain()
        return scope.results if scope.done else scope

    def _child(self, task, node, kind, callback, loop_task=None):
        scope = self._new_scope(kind, task.frame, task.scope, (task.id, callback))
        scope.loop_task = loop_task
        self._spawn(scope, node, task.node)
        self._seal(scope)
        return scope

    def _next_task(self, task, output='next'):
        task.node = self.next(task.frame, task.node, output)
        task.state.clear()
        self._ready(task)

    def _start_iteration(self, task):
        node, frame = task.node, task.frame
        self.tick(frame, node)  # Every check/iteration, including empty bodies.
        if node.kind == 'repeat':
            again = task.state['index'] < task.state['count']
        else:
            again = self.check(frame, node, 'bool', self.input(frame, node, 'condition', {}))
        if not again:
            self._next_task(task)
            return
        task.state['index'] += 1; task.waiting = True
        def finished(scope):
            if scope.outcome == 'break':
                self._next_task(task)
            else:
                self._ready(task)
        self._child(task, self.next(frame, node, 'body'), 'iteration', finished, task.id)

    def _nearest(self, task, kind):
        scope = task.scope
        while scope is not None:
            if scope.kind == kind:
                return scope
            if kind == 'iteration' and scope.kind in ('call', 'run'):
                break
            scope = scope.parent
        return None

    def _step(self, task):
        node, frame = task.node, task.frame
        if node is None:
            self._finish_task(task)
            return
        if task.state.get('mode') == 'loop':
            self._start_iteration(task)
            return
        if task.state.get('mode') == 'sequence':
            index = task.state['index']
            if index >= len(node.outputs):
                self._finish_task(task)
                return
            task.state['index'] += 1; task.waiting = True
            self.tick(frame, node)
            self._child(task, self.next(frame, node, node.outputs[index]), 'branch', lambda scope: self._ready(task))
            return
        self.tick(frame, node)
        cache = {}  # The existing one-action snapshot rule is unchanged.
        kind = node.kind
        if kind in STARTS or kind == 'entry':
            self._next_task(task)
        elif kind == 'move':
            oid = self.input(frame, node, 'object', cache)
            if not isinstance(oid, str) or oid not in self.project.nodes:
                self.fail(frame, node, 'Не найден объект для перемещения', 'Существующий объект', repr(oid))
            delta = self.check(frame, node, 'vector', self.input(frame, node, 'delta', cache))
            transform = self.project.nodes[oid].transform
            x, y = transform.x+delta[0], transform.y+delta[1]
            if not number(x) or not number(y):
                self.fail(frame, node, 'Координаты вышли за допустимый числовой диапазон')
            transform.x, transform.y = x, y
            if self.physics:self.physics.dynamics.teleported(oid)
            self._next_task(task)
        elif kind in PHYSICS_ACTION:
            oid=self.input(frame,node,'object',cache)
            value=self.check(frame,node,PHYSICS_ACTION[kind][1],self.input(frame,node,'value',cache))
            point=self.input(frame,node,'point',cache,None) if kind=='impulse' else None
            try:
                if self.physics is None:raise PhysicsError('В сцене нет физических тел')
                self.physics.dynamics.action(kind,oid,value,point,(frame,node))
            except PhysicsError as exc:self.fail(frame,node,str(exc))
            self._next_task(task)
        elif kind == 'body_move':
            oid = self.input(frame,node,'object',cache)
            velocity = self.check(frame,node,'vector',self.input(frame,node,'velocity',cache))
            try:
                if self.physics is None: raise PhysicsError('В сцене нет управляемого тела')
                self.physics.command(oid,velocity,(frame,node))
            except PhysicsError as exc:
                self.fail(frame,node,str(exc))
            self._next_task(task)
        elif kind == 'write':
            var, store = self.store(frame, node, cache)
            store[var.id] = self.check(frame, node, var.type, self.input(frame, node, 'value', cache))
            self._next_task(task)
        elif kind == 'if':
            condition = self.check(frame, node, 'bool', self.input(frame, node, 'condition', cache))
            self._next_task(task, 'yes' if condition else 'no')
        elif kind == 'wait':
            duration = self.check(frame, node, 'number', self.input(frame, node, 'n', cache, node.params.get('n', 1)))
            if duration < 0:
                self.fail(frame, node, 'Ожидание не может быть отрицательным', 'N ≥ 0', repr(duration))
            self._refresh_time()  # Start the delay when the wait is reached, not at stale frame time.
            deadline = self.now+duration
            if not number(deadline):
                self.fail(frame, node, 'Срок ожидания вышел за числовой диапазон')
            task.origin = node
            task.node = self.next(frame, node)
            task.waiting = True
            heapq.heappush(self.sleepers, (deadline, next(self._wake_order), self.epoch+1, task.id))
        elif kind == 'call':
            frame.calls.pop(node.id, None)
            task.waiting = True
            def returned(scope):
                frame.calls[node.id] = copy.deepcopy(scope.results)
                self._next_task(task)
            self._call_scope(frame, node, cache, task.scope, (task.id, returned))
        elif kind == 'return':
            scope = self._nearest(task, 'call')
            if scope is None:
                self.fail(frame, node, 'Возврат вне вызова функции')
            values = {p.id: self.check(frame, node, p.type, self.input(frame, node, p.id, cache))
                      for p in frame.graph.results}
            self._terminate(scope, 'return', values)
        elif kind in LOOPS:
            count = None
            if kind == 'repeat':
                count = self.check(frame, node, 'number', self.input(frame, node, 'n', cache))
                if count < 0 or int(count) != count:
                    self.fail(frame, node, 'N должно быть целым неотрицательным числом', '0, 1, 2, …', repr(count))
            task.state = {'mode': 'loop', 'count': count, 'index': 0}
            self._ready(task)
        elif kind in ('break', 'continue'):
            iteration = self._nearest(task, 'iteration')
            if iteration is None:
                self.fail(frame, node, 'Прерывание/продолжение вне цикла текущего графа')
            self._terminate(iteration, kind)
        elif kind == 'sequence':
            task.state = {'mode': 'sequence', 'index': 0}
            self._ready(task)
        elif kind == 'fork':
            task.waiting = True
            task.state = {'remaining': len(node.outputs)}
            def joined(scope):
                task.state['remaining'] -= 1
                if task.state['remaining'] == 0:
                    self._finish_task(task)
            for output in node.outputs:
                self.tick(frame, node)
                self._child(task, self.next(frame, node, output), 'branch', joined)
        else:
            self.fail(frame, node, 'В красную цепочку попал неисполняемый узел')
