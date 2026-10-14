"""Offscreen integration checks, not a substitute for the Windows manual checklist."""
import copy
from pathlib import Path
from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDockWidget, QLineEdit
from horo.ui.main import MainWindow
from horo.ui.graph import CardItem, PortItem
from horo.examples import basic, counter, function_loop, write_examples, test_xpm as xpm_text
from horo.model import Graph, Project, SceneNode
from horo.storage import save_project, load_project


def window(qapp, tmp_path, factory=basic):
    p = factory(); save_project(p, tmp_path)
    (tmp_path/'assets').mkdir(exist_ok=True); (tmp_path/'assets/test.xpm').write_text(xpm_text(), encoding='ascii')
    w = MainWindow(); w.replace_project(p, tmp_path); w.show(); qapp.processEvents()
    return w


def finish(w, qapp):
    w.saved = w.project.to_dict(); w.close(); qapp.processEvents()


def test_editor_opens_panels_are_docked_and_game_isolated(qapp, tmp_path):
    w = window(qapp, tmp_path)
    for dock in w.docks:
        assert not dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        dock.hide()
    w.reset_layout(); assert all(d.isVisible() for d in w.docks)
    original = w.project.to_dict(); oid = next(iter(w.project.nodes))
    w.run_game(); qapp.processEvents(); game = w.game
    w.run_game(); assert w.game is game
    QTest.keyClick(game, Qt.Key.Key_Space); qapp.processEvents()
    assert game.runtime.project.nodes[oid].transform.x == 110
    assert w.project.to_dict() == original
    w.stop_game(); qapp.processEvents(); assert w.game is None
    w.run_game(); qapp.processEvents(); assert w.game.runtime.project.nodes[oid].transform.x == 80
    finish(w, qapp)


def test_gui_build_basic_graph_using_editor_actions(qapp, tmp_path):
    w = window(qapp, tmp_path, lambda: Project())
    w.add_scene('sprite'); oid = w.selected
    g = Graph(name='Из редактора'); w.project.graphs[g.id] = g; w.project.nodes[oid].graph = g.id
    w.open_graph(g.id); w.add_graph_node('key', 0, 0); w.add_graph_node('vector', 0, 250)
    w.add_graph_node('move', 420, 0); qapp.processEvents()
    nodes = {n.kind: n for n in w.current_graph().nodes.values()}
    w.set_node_param(nodes['vector'].id, 'x', 42); qapp.processEvents()
    canvas = w.graph_editor.canvas
    for a, out, b, inp in [('key', 'next', 'move', 'in'), ('key', 'object', 'move', 'object'), ('vector', 'value', 'move', 'delta')]:
        source = canvas.card_items[nodes[a].id].port_items[('out', out)]
        target = canvas.card_items[nodes[b].id].port_items[('in', inp)]
        canvas.port_clicked(source); canvas.port_clicked(target); qapp.processEvents()
    assert len(w.current_graph().edges) == 3
    assert w.save(); reloaded = load_project(tmp_path)
    w.replace_project(reloaded, tmp_path); w.run_game(); qapp.processEvents()
    QTest.keyClick(w.game, Qt.Key.Key_Space); qapp.processEvents()
    assert w.game.runtime.project.nodes[oid].transform.x == 42
    finish(w, qapp)


def test_card_constant_field_changes_runtime(qapp, tmp_path):
    w = window(qapp, tmp_path); g = next(iter(w.project.graphs.values())); w.open_graph(g.id)
    vec = next(n for n in g.nodes.values() if n.kind == 'vector')
    card = w.graph_editor.canvas.card_items[vec.id]
    proxy = next(child for child in card.childItems() if hasattr(child, 'widget'))
    field = proxy.widget().findChildren(QLineEdit)[0]
    field.setText('77'); field.editingFinished.emit(); qapp.processEvents()
    assert w.current_graph().nodes[vec.id].params['x'] == 77
    finish(w, qapp)


def test_graph_delete_undo_navigation_and_loop_region(qapp, tmp_path):
    w = window(qapp, tmp_path, function_loop)
    g = next(g for g in w.project.graphs.values() if g.kind == 'behavior'); w.open_graph(g.id)
    loop = next(n for n in g.nodes.values() if n.kind == 'repeat')
    w.open_region(loop.id); qapp.processEvents()
    move = next(n for n in g.nodes.values() if n.kind == 'move')
    assert move.id in w.graph_editor.canvas.card_items
    assert loop.id in w.graph_editor.canvas.card_items
    w.remove_graph_elements([move.id], []); w.graph_editor.canvas.setFocus(); w.undo(); qapp.processEvents()
    assert move.id in w.current_graph().nodes
    from horo.errors import Diagnostic
    w.message(Diagnostic('test', g.id, move.id)); w.navigate(w.console.item(w.console.count()-1))
    assert w.region == loop.id
    assert w.graph_editor.canvas.card_items[move.id].isSelected()
    finish(w, qapp)


def test_bad_open_preserves_current_document(qapp, tmp_path):
    w = window(qapp, tmp_path); original = w.project.to_dict()
    bad = tmp_path/'bad.json'; bad.write_text('broken')
    assert not w.open_path(bad)
    assert w.project.to_dict() == original
    finish(w, qapp)


def test_gui_counter_and_function_examples(qapp, tmp_path):
    for factory, presses, x in [(counter, 3, 100), (function_loop, 1, 125)]:
        folder = tmp_path/factory.__name__; folder.mkdir()
        w = window(qapp, folder, factory); w.run_game(); qapp.processEvents()
        for _ in range(presses):
            QTest.keyClick(w.game, Qt.Key.Key_Space); qapp.processEvents()
        assert next(iter(w.game.runtime.project.nodes.values())).transform.x == x
        finish(w, qapp)


def test_scene_click_and_drag_does_not_destroy_active_item(qapp, tmp_path):
    w = window(qapp, tmp_path); canvas = w.scene_editor.canvas; w.scene_editor.fit(); qapp.processEvents()
    oid = next(iter(w.project.nodes)); item = canvas.items_by_id[oid]
    start = canvas.mapFromScene(item.mapToScene(QPointF(20, 20)))
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start); qapp.processEvents()
    assert w.selected == oid
    assert canvas.items_by_id[oid] is item
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas.viewport(), start+QPoint(40, 0), delay=10)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start+QPoint(40, 0))
    qapp.processEvents()
    assert w.project.nodes[oid].transform.x > 80
    assert len(w.history.undo_stack) == 1
    canvas.setFocus(); w.undo(); qapp.processEvents(); assert w.project.nodes[oid].transform.x == 80
    finish(w, qapp)


def test_typed_red_blue_mouse_connections(qapp, tmp_path):
    w = window(qapp, tmp_path); g = next(iter(w.project.graphs.values())); move = next(n for n in g.nodes.values() if n.kind=='move')
    key = next(n for n in g.nodes.values() if n.kind=='key')
    w.project.graphs[g.id].edges = [e for e in g.edges if e.input != 'in']; w.open_graph(g.id)
    canvas = w.graph_editor.canvas; canvas.resetTransform(); canvas.centerOn(360, 150); qapp.processEvents()
    source = canvas.card_items[key.id].port_items[('out', 'next')]
    target = canvas.card_items[move.id].port_items[('in', 'in')]
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(source.scenePos()))
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(target.scenePos()))
    qapp.processEvents(); assert len(w.current_graph().edges) == 3
    finish(w, qapp)


def test_runtime_error_keeps_editor_open_and_navigates(qapp, tmp_path):
    w = window(qapp, tmp_path, lambda: function_loop(-1)); w.run_game(); qapp.processEvents()
    QTest.keyClick(w.game, Qt.Key.Key_Space); qapp.processEvents()
    assert not w.game.runtime.running and w.isVisible()
    error = w.console.item(w.console.count()-1); d = error.data(Qt.ItemDataRole.UserRole)
    assert 'целым' in d.message
    w.navigate(error); assert w.graph_editor.canvas.card_items[d.node_id].isSelected()
    finish(w, qapp)


def test_variable_dialog_from_card_is_one_undoable_entity(qapp, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    w = window(qapp, tmp_path); g = next(iter(w.project.graphs.values())); w.open_graph(g.id)
    w.add_graph_node('read', 0, 600); node = next(n for n in w.current_graph().nodes.values() if n.kind=='read')
    count = len(w.history.undo_stack)
    def fill():
        dialog = QApplication.activeModalWidget()
        dialog.name.setText('Создана в блоке'); dialog.value.setText('0'); dialog.finish()
    QTimer.singleShot(0, fill); w.create_variable(node.id); qapp.processEvents()
    assert len(w.project.variables) == 1 and len(w.history.undo_stack) == count+1
    vid = next(iter(w.project.variables)); assert w.current_graph().nodes[node.id].params['variable'] == vid
    w.graph_editor.canvas.setFocus(); w.undo(); qapp.processEvents(); assert vid not in w.project.variables
    w.redo(); qapp.processEvents(); assert vid in w.project.variables
    assert w.current_graph().nodes[node.id].params['variable'] == vid
    finish(w, qapp)


def test_build_function_signature_and_body_through_ui(qapp, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from horo.model import TYPES, Edge
    w = window(qapp, tmp_path, lambda: Project())
    w.add_scene('sprite'); oid = w.selected
    def new_graph(kind, name):
        def fill():
            dialog = QApplication.activeModalWidget(); dialog.setTextValue(name); dialog.accept()
        QTimer.singleShot(0, fill); w.new_graph(kind); qapp.processEvents()
        return w.graph_id
    fnid = new_graph('function', 'UI функция')
    def parameter(name, kind, result):
        def fill():
            dialog = QApplication.activeModalWidget(); dialog.name.setText(name)
            dialog.type.setCurrentIndex(TYPES.index(kind)); dialog.finish()
        QTimer.singleShot(0, fill); w.add_parameter(result); qapp.processEvents()
    parameter('N', 'number', False); parameter('Вектор', 'vector', False)
    parameter('Смещение', 'vector', True); parameter('Повторы', 'number', True)
    w.add_graph_node('return', 420, 0)
    fn = w.current_graph(); entry = next(n for n in fn.nodes.values() if n.kind=='entry'); ret = next(n for n in fn.nodes.values() if n.kind=='return')
    pnum, pvec = fn.parameters; rvec, rnum = fn.results
    for a, out, b, inp in [(entry, 'next', ret, 'in'), (entry, pvec.id, ret, rvec.id), (entry, pnum.id, ret, rnum.id)]:
        w.add_edge(Edge(a.id, out, b.id, inp))
    gid = new_graph('behavior', 'UI поведение'); w.project.nodes[oid].graph = gid
    for kind, x, y in [('number', 0, 250), ('vector', 0, 450), ('call', 420, 0), ('repeat', 840, 0)]:
        w.add_graph_node(kind, x, y)
    g = w.current_graph(); nodes = {n.kind:n for n in g.nodes.values()}
    w.set_node_param(nodes['number'].id, 'value', 3); qapp.processEvents()
    w.set_node_param(nodes['vector'].id, 'x', 15); qapp.processEvents()
    w.set_node_param(nodes['vector'].id, 'y', 5); qapp.processEvents()
    w.set_node_param(nodes['call'].id, 'function', fnid); qapp.processEvents()
    for a, out, b, inp in [('key', 'next', 'call', 'in'), ('number', 'value', 'call', 'arg:'+pnum.id),
                          ('vector', 'value', 'call', 'arg:'+pvec.id), ('call', 'next', 'repeat', 'in'),
                          ('call', 'result:'+rnum.id, 'repeat', 'n')]:
        w.add_edge(Edge(nodes[a].id, out, nodes[b].id, inp))
    w.open_region(nodes['repeat'].id); w.add_graph_node('move', 20, 20)
    move = next(n for n in w.current_graph().nodes.values() if n.kind=='move')
    for a, out, inp in [('repeat', 'body', 'in'), ('key', 'object', 'object'), ('call', 'result:'+rvec.id, 'delta')]:
        w.add_edge(Edge(nodes[a].id, out, move.id, inp))
    assert w.save(); w.replace_project(load_project(tmp_path), tmp_path)
    w.run_game(); qapp.processEvents(); assert w.game is not None
    QTest.keyClick(w.game, Qt.Key.Key_Space); qapp.processEvents()
    assert w.game.runtime.project.nodes[oid].transform.x == 45
    assert w.game.runtime.project.nodes[oid].transform.y == 15
    finish(w, qapp)


def test_save_and_run_flush_last_field_edit(qapp, tmp_path):
    w = window(qapp, tmp_path); g = next(iter(w.project.graphs.values())); w.open_graph(g.id)
    vec = next(n for n in w.current_graph().nodes.values() if n.kind=='vector')
    w.set_node_param(vec.id, 'x', 91)
    # No processEvents: save/run must not capture the previous field value.
    assert w.save(); assert next(n for g in load_project(tmp_path).graphs.values() for n in g.nodes.values() if n.kind=='vector').params['x'] == 91
    w.run_game(); qapp.processEvents(); QTest.keyClick(w.game, Qt.Key.Key_Space); qapp.processEvents()
    assert next(iter(w.game.runtime.project.nodes.values())).transform.x == 171
    finish(w, qapp)


def test_editor_shortcuts_do_not_steal_text_input(qapp, tmp_path):
    w = window(qapp, tmp_path); w.select_object(next(iter(w.project.nodes))); qapp.processEvents()
    field = next(f for f in w.props.findChildren(QLineEdit) if not f.isReadOnly())
    field.setFocus(); qapp.processEvents()
    QTest.keyClick(field, Qt.Key.Key_F5); qapp.processEvents()
    assert w.game is None
    field.selectAll(); QTest.keyClicks(field, 'Edited'); QTest.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert field.text() != 'Edited'
    field.editingFinished.emit(); qapp.processEvents()
    finish(w, qapp)


def test_stage_two_outputs_buttons_ids_and_undo(qapp,tmp_path):
    from PySide6.QtWidgets import QPushButton
    from horo.model import Edge
    w=window(qapp,tmp_path);g=next(iter(w.project.graphs.values()));w.open_graph(g.id)
    w.add_graph_node('sequence',800,0);seq=next(n for n in w.current_graph().nodes.values() if n.kind=='sequence')
    original=seq.outputs[:];card=w.graph_editor.canvas.card_items[seq.id]
    proxy=next(c for c in card.childItems() if hasattr(c,'widget'))
    plus=next(b for b in proxy.widget().findChildren(QPushButton) if b.text()=='+ Выход')
    plus.click();qapp.processEvents();assert len(w.current_graph().nodes[seq.id].outputs)==3
    w.add_graph_node('move',1200,0);target=list(w.current_graph().nodes.values())[-1]
    w.add_edge(Edge(seq.id,original[0],target.id,'in'))
    before=w.project.to_dict();w.edit_output(seq.id,'remove',original[0]);qapp.processEvents()
    assert original[0] not in w.current_graph().nodes[seq.id].outputs
    assert not any(e.source==seq.id and e.output==original[0] for e in w.current_graph().edges)
    w.graph_editor.canvas.setFocus();w.undo();qapp.processEvents();assert w.project.to_dict()==before
    w.edit_output(seq.id,'down',original[0]);qapp.processEvents()
    assert w.current_graph().nodes[seq.id].outputs[1]==original[0]
    assert any(e.source==seq.id and e.output==original[0] for e in w.current_graph().edges)
    finish(w,qapp)


def test_stage_two_nested_regions_back_and_delete_restore(qapp,tmp_path):
    w=window(qapp,tmp_path);g=next(iter(w.project.graphs.values()));w.open_graph(g.id)
    w.add_graph_node('repeat',700,0);outer=next(n for n in w.current_graph().nodes.values() if n.kind=='repeat')
    w.open_region(outer.id);assert 'while' in w.graph_editor.canvas.allowed()
    w.add_graph_node('while',10,20);inner=next(n for n in w.current_graph().nodes.values() if n.kind=='while')
    w.open_region(inner.id);assert w.region==inner.id and 'Пока' in w.graph_editor.breadcrumb.text()
    w.graph_editor.back.click();assert w.region==outer.id
    w.graph_editor.back.click();assert w.region is None
    w.remove_graph_elements([outer.id],[]);assert inner.id not in w.current_graph().nodes
    w.graph_editor.canvas.setFocus();w.undo();qapp.processEvents()
    assert w.current_graph().nodes[inner.id].region==outer.id
    finish(w,qapp)


def test_stage_two_game_update_not_paint_and_close_cancels_wait(qapp,tmp_path):
    from horo.ui.game import GameWindow
    from horo.runtime import Runtime
    from horo.examples import link
    w=window(qapp,tmp_path);g=next(iter(w.project.graphs.values()));oid=next(iter(w.project.nodes))
    frame=g.add('frame');action=g.add('move');vec=g.add('vector',x=1,y=0)
    link(g,frame,'next',action,'in');link(g,frame,'object',action,'object');link(g,vec,'value',action,'delta')
    wait=g.add('wait',n=100);link(g,action,'next',wait,'in')
    clock=[0];r=Runtime(w.project,clock=lambda:clock[0]);game=GameWindow(r,tmp_path)
    w.game=game;game.failed.connect(w.message);game.finished.connect(w.game_finished)
    game.show();qapp.processEvents();game.timer.stop()
    x=r.project.nodes[oid].transform.x;game.canvas.viewport().update();qapp.processEvents()
    assert r.project.nodes[oid].transform.x==x
    clock[0]=.1;game.handle(r.update);assert r.project.nodes[oid].transform.x==x+1 and r.sleepers
    w.stop_game();qapp.processEvents();assert not r.tasks and not r.sleepers and not r.ready and not r.scopes
    finish(w,qapp)


def test_stage_two_release_event_and_multiple_start_cards(qapp,tmp_path):
    from horo.examples import link
    w=window(qapp,tmp_path);g=next(iter(w.project.graphs.values()));w.open_graph(g.id)
    w.add_graph_node('key',0,700);w.add_graph_node('key_release',0,950)
    keys=[n for n in w.current_graph().nodes.values() if n.kind=='key'];assert len(keys)==2
    release=next(n for n in w.current_graph().nodes.values() if n.kind=='key_release')
    action=w.current_graph().add('move');vec=w.current_graph().add('vector',x=5,y=0)
    link(w.current_graph(),release,'next',action,'in');link(w.current_graph(),release,'object',action,'object');link(w.current_graph(),vec,'value',action,'delta')
    w.run_game();qapp.processEvents();oid=next(iter(w.project.nodes))
    QTest.keyPress(w.game,Qt.Key.Key_Space);qapp.processEvents();assert w.game.runtime.project.nodes[oid].transform.x==110
    QTest.keyRelease(w.game,Qt.Key.Key_Space);qapp.processEvents();assert w.game.runtime.project.nodes[oid].transform.x==115
    finish(w,qapp)


def test_stage_two_received_release_is_event_even_without_previous_window_press(qapp,tmp_path):
    from horo.examples import link
    w=window(qapp,tmp_path);g=next(iter(w.project.graphs.values()))
    release=g.add('key_release');action=g.add('move');vector=g.add('vector',x=5,y=0)
    link(g,release,'next',action,'in');link(g,release,'object',action,'object');link(g,vector,'value',action,'delta')
    w.run_game();qapp.processEvents();oid=next(iter(w.project.nodes))
    QTest.keyRelease(w.game,Qt.Key.Key_Space);qapp.processEvents()
    assert w.game.runtime.project.nodes[oid].transform.x==85
    finish(w,qapp)
