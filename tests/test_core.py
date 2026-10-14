import copy
import json
import math
import shutil
from pathlib import Path
import pytest
from horo.model import Project, SceneNode, Transform, Graph, GraphNode, Edge, Variable, Parameter, valid_value
from horo.examples import basic, counter, function_loop, link, write_examples
from horo.ports import port_map
from horo.validation import connect, validate_project, validate_graph
from horo.runtime import Runtime, STEP_LIMIT
from horo.history import History
from horo.errors import GraphError
from horo.storage import save_project, load_project, asset_path, import_asset


def find(project, kind, graph_kind='behavior'):
    graph = next(g for g in project.graphs.values() if g.kind == graph_kind)
    return graph, next(n for n in graph.nodes.values() if n.kind == kind)


def test_parent_child_world_transform():
    p = Project(); a = SceneNode(transform=Transform(10, 20, 2, 3, 90)); b = SceneNode(parent=a.id, transform=Transform(5, 7))
    p.nodes = {a.id: a, b.id: b}
    matrix = p.world_matrix(b.id)
    assert matrix[4:] == pytest.approx((-11, 30))
    assert matrix[:4] == pytest.approx((0, 2, -3, 0))
    a.transform.x += 10
    assert p.world_matrix(b.id)[4:] == pytest.approx((-1, 30))


def test_screen_size_does_not_change_coordinates():
    p = basic(); before = [copy.deepcopy(n.transform) for n in p.nodes.values()]
    p.width, p.height = 1920, 1080
    assert before == [n.transform for n in p.nodes.values()]

@pytest.mark.parametrize('factory', [basic, counter, function_loop])
def test_serialization(factory, tmp_path):
    p = factory(); save_project(p, tmp_path/'Проект с пробелами')
    q = load_project(tmp_path/'Проект с пробелами')
    assert p.to_dict() == q.to_dict()
    assert not validate_project(q)
    a, b = Runtime(p), Runtime(q)
    a.key_press('Space'); b.key_press('Space')
    assert a.project.to_dict() == b.project.to_dict()


def test_resource_copy_and_project_move(tmp_path):
    from horo.examples import test_png
    source = tmp_path/'original.png'; source.write_bytes(test_png())
    old = tmp_path/'old'; old.mkdir()
    p = basic(); relative = import_asset(source, old); next(iter(p.nodes.values())).image = relative
    save_project(p, old); shutil.move(old, tmp_path/'Новая папка'); source.unlink()
    q = load_project(tmp_path/'Новая папка')
    assert asset_path(tmp_path/'Новая папка', next(iter(q.nodes.values())).image).exists()

@pytest.mark.parametrize('relative', ['../secret', '/etc/passwd', '../../x'])
def test_path_escape(relative, tmp_path):
    with pytest.raises(ValueError):
        asset_path(tmp_path, relative)


def test_port_type_direction_and_single_source():
    p = basic(); g, move = find(p, 'move'); key = next(n for n in g.nodes.values() if n.kind == 'key')
    with pytest.raises(ValueError, match='Направление'):
        connect(p, g, Edge(move.id, 'in', key.id, 'next'))
    num = g.add('number', value=1)
    with pytest.raises(ValueError, match='Несовместимые'):
        connect(p, g, Edge(num.id, 'value', move.id, 'object'))
    vector = g.add('vector', x=3, y=4)
    with pytest.raises(ValueError, match='источник'):
        connect(p, g, Edge(vector.id, 'value', move.id, 'delta'))
    move2 = g.add('move')
    with pytest.raises(ValueError, match='следующая'):
        connect(p, g, Edge(key.id, 'next', move2.id, 'in'))
    connect(p, g, Edge(key.id, 'object', move2.id, 'object'))  # multi-consumer data


def test_data_cycle_and_dangling_edge():
    p = Project(); g = Graph(); p.graphs[g.id] = g
    a, b = g.add('add'), g.add('add')
    connect(p, g, Edge(a.id, 'value', b.id, 'a'))
    with pytest.raises(ValueError, match='цикл'):
        connect(p, g, Edge(b.id, 'value', a.id, 'a'))
    g.edges.append(Edge('absent', 'value', a.id, 'b'))
    assert any('удалённый' in d.message for d in validate_graph(p, g))


def test_exec_cycle():
    p = basic(); g, move = find(p, 'move')
    g.edges = [e for e in g.edges if not (e.target == move.id and e.input == 'in')]
    other = g.add('move')
    connect(p, g, Edge(move.id, 'next', other.id, 'in'))
    with pytest.raises(ValueError, match='цикл'):
        connect(p, g, Edge(other.id, 'next', move.id, 'in'))


def test_key_move_authoring_isolation_and_autorepeat():
    p = basic(); original = p.to_dict(); oid = next(iter(p.nodes)); r = Runtime(p)
    r.key_press('A'); assert r.project.nodes[oid].transform.x == 80
    r.key_press('Space', auto_repeat=True); assert r.project.nodes[oid].transform.x == 80
    r.key_press('Space'); assert r.project.nodes[oid].transform.x == 110
    assert p.to_dict() == original
    r.stop(); r.key_press('Space'); assert r.project.nodes[oid].transform.x == 110
    assert Runtime(p).project.nodes[oid].transform.x == 80


def test_shared_graph_separate_object_contexts():
    p = basic(); obj = next(iter(p.nodes.values())); other = copy.deepcopy(obj); other.id = 'second'; other.transform.x = 200
    p.nodes[other.id] = other; r = Runtime(p); g, key = find(p, 'key')
    f = r.frame(r.project.graphs[g.id], obj.id)
    start = r.project.graphs[g.id].nodes[key.id]
    r.execute(f, r.next(f, start))
    assert r.project.nodes[obj.id].transform.x == 110
    assert r.project.nodes[other.id].transform.x == 200
    r.key_press('Space')
    assert r.project.nodes[obj.id].transform.x == 140
    assert r.project.nodes[other.id].transform.x == 230


def test_missing_input_structured_error():
    p = basic(); g, move = find(p, 'move')
    g.edges = [e for e in g.edges if e.input != 'delta']
    with pytest.raises(GraphError) as raised:
        Runtime(p)
    d = raised.value.diagnostic
    assert d.graph_id == g.id and d.node_id == move.id and d.object_id == next(iter(p.nodes))
    assert 'Смещение' in d.message


def test_empty_and_missing_object_runtime_error():
    p = basic(); g, move = find(p, 'move')
    g.edges = [e for e in g.edges if e.input != 'object']
    empty = g.add('object', value=None); link(g, empty, 'value', move, 'object')
    r = Runtime(p)
    with pytest.raises(GraphError) as raised:
        r.key_press('Space')
    assert 'Не найден объект' in raised.value.diagnostic.message
    assert raised.value.diagnostic.received == 'None'
    empty.params['value'] = 'deleted'
    assert any('отсутствующий' in d.message for d in validate_project(p))


def test_counter_read_after_write_and_reset():
    p = counter(); oid = next(iter(p.nodes)); var = next(iter(p.variables)); r = Runtime(p)
    for _ in range(2):
        r.key_press('Space')
    assert r.project.nodes[oid].transform.x == 80
    r.key_press('Space'); assert r.project.nodes[oid].transform.x == 100
    assert r.objects[oid][var] == 3
    assert Runtime(p).objects[oid][var] == 0
    assert p.variables[var].value == 0

@pytest.mark.parametrize('scope,expected', [('object', [1, 1]), ('game', [2, 2]), ('run', [0, 0])])
def test_variable_scopes(scope, expected):
    p = counter(); g = next(iter(p.graphs.values())); var = next(iter(p.variables.values()))
    var.scope = scope; var.owner = g.id if scope == 'run' else None
    first = next(iter(p.nodes.values())); second = copy.deepcopy(first); second.id = 'other'; p.nodes[second.id] = second
    r = Runtime(p); r.key_press('Space')
    if scope == 'object':
        actual = [r.objects[o][var.id] for o in (first.id, second.id)]
    elif scope == 'game':
        actual = [r.game[var.id]]*2
    else:
        actual = [r.frame(r.project.graphs[g.id], o).temporary[var.id] for o in (first.id, second.id)]
    assert actual == expected


def test_pure_read_does_not_change_state_and_cached_snapshot():
    p = counter(); r = Runtime(p); g, read = find(p, 'read'); oid = next(iter(p.nodes)); vid = next(iter(p.variables))
    frame = r.frame(r.project.graphs[g.id], oid); node = frame.graph.nodes[read.id]
    cache = {}; assert r.evaluate(frame, node, 'value', cache) == 0
    assert r.objects[oid][vid] == 0
    r.objects[oid][vid] = 5
    assert r.evaluate(frame, node, 'value', cache) == 0
    assert r.evaluate(frame, node, 'value', {}) == 5


def test_if_type_and_single_branch():
    p = counter(); r = Runtime(p); oid = next(iter(p.nodes))
    r.key_press('Space'); assert r.project.nodes[oid].transform.x == 80
    g, cond = find(p, 'if'); one = next(n for n in g.nodes.values() if n.kind == 'number')
    g.edges = [e for e in g.edges if e.target != cond.id or e.input != 'condition']
    with pytest.raises(ValueError, match='Несовместимые'):
        connect(p, g, Edge(one.id, 'value', cond.id, 'condition'))

@pytest.mark.parametrize('n,dx', [(0, 0), (1, 15), (3, 45)])
def test_function_two_results_and_loop(n, dx):
    p = function_loop(n); r = Runtime(p); oid = next(iter(p.nodes)); r.key_press('Space')
    assert r.project.nodes[oid].transform.x == 80+dx
    assert r.project.nodes[oid].transform.y == 100+dx/3
    r.key_press('Space'); assert r.project.nodes[oid].transform.x == 80+2*dx

@pytest.mark.parametrize('n', [-1, 1.5])
def test_invalid_loop_count(n):
    r = Runtime(function_loop(n))
    with pytest.raises(GraphError, match='целым неотрицательным'):
        r.key_press('Space')
    assert not r.running

@pytest.mark.parametrize('control,dx', [('continue', 45), ('break', 15)])
def test_continue_break(control, dx):
    p = function_loop(control=control); r = Runtime(p); oid = next(iter(p.nodes)); r.key_press('Space')
    assert r.project.nodes[oid].transform.x == 80+dx


def test_return_in_function_loop_unwinds_call():
    p = function_loop(return_in_function=True); r = Runtime(p); oid = next(iter(p.nodes)); r.key_press('Space')
    assert r.project.nodes[oid].transform.x == 125


def test_result_before_call_is_error():
    p = function_loop(); g, call = find(p, 'call'); r = Runtime(p)
    frame = r.frame(r.project.graphs[g.id], next(iter(p.nodes)))
    output = next(port.key for port in port_map(p, g, call).values() if port.key.startswith('result:'))
    with pytest.raises(GraphError, match='до выполнения'):
        r.evaluate(frame, frame.graph.nodes[call.id], output, {})


def test_missing_return_and_argument():
    p = function_loop(); fn, entry = find(p, 'entry', 'function'); fn.edges = [e for e in fn.edges if e.source != entry.id or e.output != 'next']
    r = Runtime(p)
    with pytest.raises(GraphError, match='без возврата') as exc:
        r.key_press('Space')
    assert exc.value.diagnostic.graph_id == fn.id
    p = function_loop(); g, call = find(p, 'call'); g.edges = [e for e in g.edges if not e.input.startswith('arg:')]
    assert any('Обязательный вход' in d.message for d in validate_project(p))


def test_no_result_function_may_end_without_return():
    p = function_loop(); g, call = find(p, 'call'); fn, entry = find(p, 'entry', 'function')
    fn.nodes = {entry.id: entry}; fn.edges = []; fn.results = []
    # Remove loop (and body), leave call at end of behavior.
    loop = next(n for n in g.nodes.values() if n.kind == 'repeat'); g.remove(loop.id)
    r = Runtime(p); r.key_press('Space'); assert r.running


def test_recursive_call_rejected():
    p = function_loop(); fn, entry = find(p, 'entry', 'function'); fn.add('call', function=fn.id)
    errors = validate_project(p)
    assert any('рекурсия' in d.message for d in errors)


def test_nested_loop_allowed_with_explicit_region():
    p = function_loop(); g, loop = find(p, 'repeat')
    nested = g.add('repeat', region=loop.id); count = g.add('number', value=1)
    link(g, count, 'value', nested, 'n')
    assert not validate_project(p)


def test_loop_region_boundary_and_body_removal():
    p = function_loop(); g, loop = find(p, 'repeat'); move = next(n for n in g.nodes.values() if n.kind == 'move')
    other = g.add('move')
    with pytest.raises(ValueError, match='границу'):
        connect(p, g, Edge(move.id, 'next', other.id, 'in'))
    body_number = g.add('number', region=loop.id, value=2)
    target = g.add('vector')
    with pytest.raises(ValueError, match='пределами'):
        connect(p, g, Edge(body_number.id, 'value', target.id, 'x'))
    g.remove(loop.id)
    assert move.id not in g.nodes and body_number.id not in g.nodes
    assert all(e.source in g.nodes and e.target in g.nodes for e in g.edges)


def test_step_budget_includes_empty_loop():
    p = function_loop(100000); g, loop = find(p, 'repeat'); move = next(n for n in g.nodes.values() if n.kind == 'move'); g.remove(move.id)
    r = Runtime(p, step_limit=50)
    with pytest.raises(GraphError, match='лимит') as exc:
        r.key_press('Space')
    assert exc.value.diagnostic.node_id == loop.id


def test_function_budget_counts_computations():
    p = function_loop(); r = Runtime(p, step_limit=5)
    with pytest.raises(GraphError, match='лимит'):
        r.key_press('Space')


def test_history_create_delete_transform_connections_and_branching():
    p = basic(); h = History(limit=100); start = p.clone()
    oid = next(iter(p.nodes)); child = SceneNode(parent=oid, graph=p.nodes[oid].graph)
    p.nodes[child.id] = child; h.record(start, p, 'create')
    before = p.clone(); p.nodes[oid].transform.rotation = 40; h.record(before, p, 'transform')
    before = p.clone(); g = next(iter(p.graphs.values())); move = next(n for n in g.nodes.values() if n.kind == 'move'); g.remove(move.id)
    h.record(before, p, 'delete graph node')
    restored = h.undo(); assert restored.to_dict() == before.to_dict()
    assert h.redo().to_dict() == p.to_dict()
    p = h.undo(); before = p.clone(); p.remove_scene(oid); h.record(before, p, 'remove subtree')
    assert h.redo() is None
    p = h.undo(); assert child.id in p.nodes and p.nodes[child.id].graph == p.nodes[oid].graph
    assert p.to_dict() == before.to_dict()


def test_variable_history_stable_id():
    p = Project(); h = History(); before = p.clone(); var = Variable(); p.variables[var.id] = var
    h.record(before, p, 'variable'); assert var.id not in h.undo().variables
    assert var.id in h.redo().variables


def test_corrupt_file_atomic_save_and_no_mutation(tmp_path):
    p = basic(); save_project(p, tmp_path); original = (tmp_path/'project.horo.json').read_text(encoding='utf-8')
    bad = tmp_path/'bad.json'; bad.write_text('{not JSON}', encoding='utf-8')
    with pytest.raises(ValueError):
        load_project(bad)
    assert (tmp_path/'project.horo.json').read_text(encoding='utf-8') == original
    assert load_project(tmp_path).to_dict() == p.to_dict()


def test_failed_replace_keeps_previous_file(tmp_path, monkeypatch):
    import horo.storage as storage
    p = basic(); save_project(p, tmp_path); original = (tmp_path/'project.horo.json').read_bytes()
    p.name = 'changed'
    def fail(*args):
        raise OSError('simulated write failure')
    monkeypatch.setattr(storage.os, 'replace', fail)
    with pytest.raises(OSError):
        save_project(p, tmp_path)
    assert (tmp_path/'project.horo.json').read_bytes() == original
    assert not list(tmp_path.glob('*.tmp'))

@pytest.mark.parametrize('change', [lambda d: d.update(format_version=99),
    lambda d: d.update(width=True), lambda d: d.update(width=0),
    lambda d: next(iter(d['nodes'].values())).update(parent='missing'),
    lambda d: next(iter(d['nodes'].values()))['transform'].update(x='bad'),
    lambda d: next(iter(d['nodes'].values())).update(image='../secret')])
def test_invalid_project_structure(change):
    data = basic().to_dict(); change(data)
    with pytest.raises(ValueError):
        Project.from_dict(data)


def test_strict_types_reject_python_bool_as_number():
    assert not valid_value('number', True)
    assert not valid_value('number', float('nan'))
    assert not valid_value('vector', [1, True])
    assert valid_value('object', None)
    assert not valid_value('object', object())


def test_examples_all_load(tmp_path):
    write_examples(tmp_path)
    for file in tmp_path.glob('*/project.horo.json'):
        p = load_project(file); assert not validate_project(p), file


def test_calls_have_separate_results_and_parameter_ids_survive_rename():
    p = function_loop(); g, call = find(p, 'call'); fn = p.graphs[call.params['function']]
    fn.parameters[0].name = 'Переименован'; fn.results[0].name = 'Другое имя'
    r = Runtime(p); frame_a = r.frame(r.project.graphs[g.id], next(iter(p.nodes)))
    frame_b = r.frame(r.project.graphs[g.id], next(iter(p.nodes)))
    node = frame_a.graph.nodes[call.id]
    result_a = r.invoke(frame_a, node, {})
    assert set(result_a) == {v.id for v in fn.results}
    frame_a.calls[node.id] = result_a
    assert frame_b.calls == {}
    # A second explicit call with a changed argument produces a new independent result.
    amount_edge = next(e for e in frame_a.graph.edges if e.target == node.id and e.input == 'arg:'+fn.parameters[0].id)
    frame_a.graph.nodes[amount_edge.source].params['value'] = 1
    result_b = r.invoke(frame_b, node, {})
    assert result_a[fn.results[1].id] == 3 and result_b[fn.results[1].id] == 1


def test_function_object_argument_is_explicit():
    p = basic(); g, move = find(p, 'move'); fn = Graph(kind='function')
    param = Parameter(name='Кому', type='object'); fn.parameters = [param]
    entry = fn.add('entry'); fmove = fn.add('move'); vector = fn.add('vector', x=7, y=0)
    link(fn, entry, 'next', fmove, 'in'); link(fn, entry, param.id, fmove, 'object'); link(fn, vector, 'value', fmove, 'delta')
    p.graphs[fn.id] = fn
    g.remove(move.id); start = next(n for n in g.nodes.values() if n.kind == 'key'); call = g.add('call', function=fn.id)
    link(g, start, 'next', call, 'in'); link(g, start, 'object', call, 'arg:'+param.id)
    r = Runtime(p); r.key_press('Space'); assert next(iter(r.project.nodes.values())).transform.x == 87


def test_extra_argument_and_wrong_return_type_are_rejected():
    p = function_loop(); g, call = find(p, 'call'); value = next(n for n in g.nodes.values() if n.kind == 'number')
    g.edges.append(Edge(value.id, 'value', call.id, 'arg:nonexistent'))
    assert any('ID порта' in d.message for d in validate_project(p))
    p = function_loop(); fn, ret = find(p, 'return', 'function')
    fn.results[0].type = 'number'
    assert any('Несовместимые' in d.message for d in validate_project(p))


def test_history_bound():
    p = Project(); h = History(limit=2)
    for i in range(4):
        before = p.clone(); p.name = str(i); h.record(before, p, str(i))
    assert len(h.undo_stack) == 2
    assert h.undo().name == '2' and h.undo().name == '1' and h.undo() is None


def test_initial_variable_object_reference_diagnostics():
    p = basic(); v = Variable(type='object', value='missing', scope='game'); p.variables[v.id] = v
    assert any('Начальная ссылка' in d.message for d in validate_project(p))
