"""Offscreen editor integration. Does not claim a clean-Windows manual playthrough."""
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit,QComboBox
from horo.ui.main import MainWindow
from horo.ui.game import GameWindow
from horo.model import Project,SceneNode,Graph,Transform
from horo.runtime import Runtime
from horo.storage import save_project,load_project
from horo.physics_examples import playground


def editor(qapp,tmp_path,project=None):
    p=project or Project();save_project(p,tmp_path)
    w=MainWindow();w.replace_project(p,tmp_path);w.resize(1420,900);w.show();qapp.processEvents();return w

def close(w,qapp):w.saved=w.project.to_dict();w.close();qapp.processEvents()

def test_create_body_forms_and_undo_redo_ids(qapp,tmp_path):
    w=editor(qapp,tmp_path);w.add_scene('controlled_body');oid=w.selected
    for kind in ['rect_shape','circle_shape','polygon_shape']:
        w.select_object(oid);w.add_scene(kind);sid=w.selected
        assert w.project.nodes[sid].parent==oid
        w.undo();assert sid not in w.project.nodes
        w.redo();assert w.project.nodes[sid].id==sid
    w.select_object(oid);snapshot=w.project.to_dict();w.remove_scene();assert oid not in w.project.nodes
    w.undo();assert w.project.to_dict()==snapshot
    close(w,qapp)


def test_polygon_new_draft_invalid_cancel_and_commit(qapp,tmp_path):
    w=editor(qapp,tmp_path);w.add_scene('static_body');w.add_scene('polygon_shape');sid=w.selected
    tool=w.scene_editor.canvas.contour;original=w.project.nodes[sid].points.copy()
    tool.begin(sid,True);tool.points=[[0,0],[20,20],[0,20],[20,0]];tool.finish();qapp.processEvents()
    assert w.project.nodes[sid].points==original;assert tool.node_id==sid
    tool.cancel();assert w.project.nodes[sid].points==original
    tool.begin(sid,True);points=[[0,0],[100,0],[100,20],[20,20],[20,100],[0,100]];tool.points=points.copy();tool.finish();qapp.processEvents()
    assert w.project.nodes[sid].points==points
    w.undo();assert w.project.nodes[sid].points==original
    w.redo();assert w.project.nodes[sid].points==points
    w.save();assert load_project(tmp_path).nodes[sid].points==points
    close(w,qapp)


def test_vertex_drag_is_one_history_operation(qapp,tmp_path):
    w=editor(qapp,tmp_path);w.add_scene('static_body');oid=w.selected;w.project.nodes[oid].transform=Transform(x=300,y=200)
    w.add_scene('polygon_shape');sid=w.selected
    canvas=w.scene_editor.canvas;canvas.fitInView(0,0,800,600,Qt.AspectRatioMode.KeepAspectRatio)
    tool=canvas.contour;tool.begin(sid);before=w.project.nodes[sid].points.copy()
    item=canvas.items_by_id[sid];pos=canvas.mapFromScene(item.mapToScene(QPointF(*before[0])))
    QTest.mousePress(canvas.viewport(),Qt.MouseButton.LeftButton,pos=pos)
    for d in [QPoint(-5,0),QPoint(-10,0),QPoint(-15,0)]:QTest.mouseMove(canvas.viewport(),pos+d)
    QTest.mouseRelease(canvas.viewport(),Qt.MouseButton.LeftButton,pos=pos+QPoint(-15,0));qapp.processEvents()
    after=w.project.nodes[sid].points.copy();assert after!=before
    w.undo();assert w.project.nodes[sid].points==before
    w.redo();assert w.project.nodes[sid].points==after
    close(w,qapp)


def test_form_size_properties_history(qapp,tmp_path):
    from PySide6.QtWidgets import QDoubleSpinBox
    w=editor(qapp,tmp_path);w.add_scene('static_body');w.add_scene('circle_shape');sid=w.selected
    spin=w.props_form.itemAt(1).widget() # First row's field is radius.
    assert isinstance(spin,QDoubleSpinBox)
    spin.setValue(45);spin.editingFinished.emit();qapp.processEvents();assert w.project.nodes[sid].radius==45
    w.undo();assert w.project.nodes[sid].radius==32
    close(w,qapp)


def test_input_loss_focus_clears_runtime(qapp,tmp_path):
    from PySide6.QtGui import QFocusEvent
    r=Runtime(Project(),clock=lambda:0);game=GameWindow(r,tmp_path);game.show();qapp.processEvents();game.timer.stop()
    QTest.keyPress(game,Qt.Key.Key_W);QTest.keyPress(game,Qt.Key.Key_D)
    assert r.held=={'W','D'}
    game.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut));assert not game.held and not r.held
    game.close();qapp.processEvents()


def test_playground_editor_shapes_ports_and_reload(qapp,tmp_path):
    w=editor(qapp,tmp_path,playground());g=next(iter(w.project.graphs.values()));w.open_graph(g.id);qapp.processEvents()
    canvas=w.graph_editor.canvas
    direction=next(n for n in g.nodes.values() if n.kind=='direction')
    card=canvas.card_items[direction.id];proxy=next(i for i in card.childItems() if hasattr(i,'widget'))
    combos=proxy.widget().findChildren(QComboBox);assert len(combos)==4
    combos[0].setCurrentText('Left');qapp.processEvents()
    assert w.current_graph().nodes[direction.id].params['left']=='Left'
    assert w.save();assert load_project(tmp_path).graphs[g.id].nodes[direction.id].params['left']=='Left'
    w.select_object(next(n.id for n in w.project.nodes.values() if n.kind=='polygon_shape'))
    assert w.selected in w.scene_editor.canvas.items_by_id
    close(w,qapp)


def test_insert_delete_vertex_through_scene(qapp,tmp_path):
    w=editor(qapp,tmp_path);w.add_scene('static_body');oid=w.selected
    w.project.nodes[oid].transform=Transform(x=300,y=200);w.add_scene('polygon_shape');sid=w.selected
    canvas=w.scene_editor.canvas;canvas.fitInView(0,0,800,600,Qt.AspectRatioMode.KeepAspectRatio)
    tool=canvas.contour;tool.begin(sid);original=w.project.nodes[sid].points.copy()
    item=canvas.items_by_id[sid];pos=canvas.mapFromScene(item.mapToScene(QPointF(0,-32)))
    QTest.mouseClick(canvas.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos);qapp.processEvents()
    assert len(w.project.nodes[sid].points)==5
    QTest.keyClick(canvas,Qt.Key.Key_Delete);qapp.processEvents();assert w.project.nodes[sid].points==original
    w.undo();assert len(w.project.nodes[sid].points)==5
    w.undo();assert w.project.nodes[sid].points==original
    close(w,qapp)
