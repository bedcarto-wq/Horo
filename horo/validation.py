"""Reject unsafe or ambiguous topology before playing. Incomplete graphs may be saved."""
from .ports import ports, port_map, LABELS, STARTS, LOOPS
from .model import valid_value, number
from .errors import Diagnostic


def region_ancestors(graph, region):
    result = []
    while region is not None:
        if region in result:
            raise ValueError('Цикл владельцев областей тела')
        result.append(region)
        owner = graph.nodes.get(region)
        if owner is None or owner.kind not in LOOPS:
            raise ValueError('Не найдена область тела цикла')
        region = owner.region
    return result


def node_availability(graph, kind, region=None, adding=True):
    """One structural policy for catalog, search, drop, controller and validator.

    Missing input values are NOT an availability restriction: incomplete graphs
    remain editable/savable. `adding` only adds the existing single-entry guard.
    """
    if graph is None:
        return 'Сначала откройте ресурс графа'
    if kind not in LABELS:
        return 'Неизвестный вид узла'
    if graph.kind == 'behavior' and kind in ('entry', 'return'):
        return ('Вход функции' if kind == 'entry' else 'Вернуть результат') + ' используется в графе-функции'
    if graph.kind == 'function' and kind in STARTS:
        return 'События используются только в графе-поведении'
    if region is not None:
        try:
            region_ancestors(graph, region)
        except ValueError as exc:
            return str(exc)
        if kind in STARTS or kind == 'entry':
            return 'Старт события/вход функции размещается во внешней области графа'
    if kind in ('break', 'continue') and region is None:
        return 'Для ' + ('Продолжить' if kind == 'continue' else 'Прервать цикл') + ' требуется контекст цикла (доступно только в теле цикла текущего графа)'
    if adding and kind == 'entry' and any(n.kind == 'entry' for n in graph.nodes.values()):
        return 'У функции один вход; сначала удалите существующий'
    return None


def connection_error(project, graph, edge):
    a, b = graph.nodes.get(edge.source), graph.nodes.get(edge.target)
    if a is None or b is None:
        return 'Связь ссылается на удалённый узел'
    source = port_map(project, graph, a).get(('out', edge.output))
    target = port_map(project, graph, b).get(('in', edge.input))
    if source is None or target is None:
        return 'Направление связи или ID порта неверны: нужен выход → вход'
    if source.type != target.type:
        from .model import TYPE_LABELS
        return f'Несовместимые типы. Ожидается {TYPE_LABELS.get(target.type, target.type)}, получено {TYPE_LABELS.get(source.type, source.type)}'
    if any(e.id != edge.id and e.target == edge.target and e.input == edge.input for e in graph.edges):
        return 'У этого входа уже есть источник'
    if source.type == 'exec':
        if any(e.id != edge.id and e.source == edge.source and e.output == edge.output for e in graph.edges):
            return 'У выхода выполнения уже есть следующая команда'
        expected_region = a.id if a.kind in LOOPS and edge.output == 'body' else a.region
        if b.region != expected_region:
            return 'Красная связь не может пересекать границу тела цикла'
    elif a.region is not None:
        try:
            if a.region not in region_ancestors(graph, b.region):
                return 'Данные тела цикла нельзя читать за пределами его области'
        except ValueError as exc:
            return str(exc)
    return None


def cycle_nodes(project, graph, exec_only=None):
    adjacency = {k: [] for k in graph.nodes}
    for e in graph.edges:
        if e.source not in graph.nodes or e.target not in graph.nodes:
            continue
        port = port_map(project, graph, graph.nodes[e.source]).get(('out', e.output))
        if port and (exec_only is None or (port.type == 'exec') == exec_only):
            adjacency[e.source].append(e.target)
    # Iterative DFS avoids recursion-limit crashes with long user graphs.
    visited, active = set(), set()
    for root in adjacency:
        if root in visited:
            continue
        stack = [(root, False)]
        while stack:
            key, leave = stack.pop()
            if leave:
                active.discard(key); visited.add(key)
                continue
            if key in active:
                return key
            if key in visited:
                continue
            active.add(key); stack.append((key, True))
            stack.extend((child, False) for child in adjacency[key])
    return None


def validate_graph(project, graph):
    errors = []
    def err(message, node=None):
        errors.append(Diagnostic(message, graph.id, node))
    starts = [n for n in graph.nodes.values() if n.kind in STARTS or n.kind == 'entry']
    if graph.kind == 'behavior':
        if not starts or any(n.kind not in STARTS or n.region is not None for n in starts):
            err('Нужен хотя бы один старт события во внешней области поведения')
    elif len(starts) != 1 or starts[0].kind != 'entry' or starts[0].region is not None:
        err('Нужен ровно один вход функции')
    for node in graph.nodes.values():
        if node.kind not in LABELS:
            err('Неизвестный вид узла', node.id); continue
        reason = node_availability(graph, node.kind, node.region, adding=False)
        if reason:
            err(reason, node.id)
        if node.kind in ('sequence', 'fork') and len(node.outputs) < 2:
            err('Нужно минимум два нумерованных выхода', node.id)
        if node.kind not in ('sequence', 'fork') and node.outputs:
            err('Этот узел не поддерживает редактируемые выходы', node.id)
        if node.kind == 'wait' and not number(node.params.get('n', 1)):
            err('Поле ожидания должно быть конечным числом', node.id)
        if node.kind in ('key', 'key_release', 'held', 'direction'):
            keys = [node.params.get('key', 'Space')] if node.kind != 'direction' else [node.params.get(k,d) for k,d in [('left','A'),('right','D'),('up','W'),('down','S')]]
            key = keys[0]
            allowed = ['Space', 'Left', 'Right', 'Up', 'Down', 'Return', 'Escape'] + list('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
            if any(k not in allowed for k in keys):
                err('Клавиша не поддерживается', node.id)
        if node.kind in ('number', 'text', 'bool', 'object'):
            from .model import initial
            value = node.params.get('value', initial(node.kind))
            if not valid_value(node.kind, value):
                err('Значение не соответствует типу узла', node.id)
            elif node.kind == 'object' and value is not None and value not in project.nodes:
                err('Ссылка на отсутствующий объект', node.id)
        if node.kind == 'vector' and not all(number(node.params.get(k, 0)) for k in ('x', 'y')):
            err('Поля вектора должны быть числами', node.id)
        if node.kind in ('read', 'write'):
            var = project.variables.get(node.params.get('variable'))
            if var is None:
                err('Переменная удалена или не выбрана', node.id)
            elif var.scope == 'run' and var.owner != graph.id:
                err('Переменная запуска принадлежит другому графу', node.id)
        if node.kind == 'call':
            fn = project.graphs.get(node.params.get('function'))
            if fn is None or fn.kind != 'function':
                err('Выберите существующий граф-функцию', node.id)
        for port in ports(project, graph, node):
            if port.direction == 'in' and port.type != 'exec' and port.required:
                if not any(e.target == node.id and e.input == port.key for e in graph.edges):
                    err(f'Обязательный вход «{port.label}» не подключён', node.id)
    for e in graph.edges:
        message = connection_error(project, graph, e)
        if message:
            err(message, e.target)
    # Separate dependency cycles: data edges from a key to a move do not form an exec loop.
    for mode in (True, False):
        cyc = cycle_nodes(project, graph, mode)
        if cyc:
            err('Обнаружен цикл связей выполнения' if mode else 'Обнаружен цикл данных', cyc)
    return errors


def validate_project(project):
    errors = []
    try:
        project.check_structure()
    except (ValueError, TypeError) as exc:
        return [Diagnostic(str(exc))]
    for node in project.nodes.values():
        if node.graph is not None:
            graph = project.graphs.get(node.graph)
            if graph is None or graph.kind != 'behavior':
                errors.append(Diagnostic('К объекту должен быть прикреплён существующий граф поведения',
                                         node.graph, object_id=node.id))
    for var in project.variables.values():
        if var.type == 'object' and var.value is not None and var.value not in project.nodes:
            errors.append(Diagnostic(f'Начальная ссылка переменной «{var.name}» ведёт к отсутствующему объекту'))
    for graph in project.graphs.values():
        diagnostics = validate_graph(project, graph)
        objects = [o.id for o in project.nodes.values() if o.graph == graph.id]
        for d in diagnostics:
            if len(objects) == 1:
                d.object_id = objects[0]
        errors.extend(diagnostics)
    errors.extend(function_dependency_errors(project))
    return errors


def connect(project, graph, edge):
    reason = connection_error(project, graph, edge)
    if reason:
        raise ValueError(reason)
    graph.edges.append(edge)
    if cycle_nodes(project, graph, True) or cycle_nodes(project, graph, False):
        graph.edges.pop()
        raise ValueError('Связь создаёт запрещённый цикл')


def function_dependency_errors(project):
    adjacency = {g.id: [(n.params.get('function'), n.id) for n in g.nodes.values()
                       if n.kind == 'call' and n.params.get('function') in project.graphs]
                 for g in project.graphs.values()}
    visited, active = set(), set()
    for root in adjacency:
        if root in visited:
            continue
        active.add(root)
        stack = [(root, iter(adjacency[root]))]
        while stack:
            current, children = stack[-1]
            try:
                target, node_id = next(children)
            except StopIteration:
                active.remove(current); visited.add(current); stack.pop(); continue
            if target in active:
                return [Diagnostic('Прямая или косвенная рекурсия функций запрещена', current, node_id)]
            if target not in visited:
                active.add(target); stack.append((target, iter(adjacency[target])))
    return []
