"""Editor integration, offscreen; not a manual Windows acceptance claim."""
import pytest
from PySide6.QtWidgets import QDoubleSpinBox,QComboBox
from horo.model import Project
from horo.storage import load_project
from horo.dynamics_examples import platformer,material_lab,side_gravity,impulse_lab
from horo.ports import PHYSICS_READ,PHYSICS_ACTION
from test_physics_gui import editor,close
from test_physics import Clock
from horo.runtime import Runtime
from horo.validation import validate_project


def field(w,label):
    for row in range(w.props_form.rowCount()):
        l=w.props_form.itemAt(row,w.props_form.ItemRole.LabelRole)
        if l and l.widget().text()==label:return w.props_form.itemAt(row,w.props_form.ItemRole.FieldRole).widget()
    raise AssertionError(label)


def test_dynamic_properties_history_and_disk(qapp,tmp_path):
    w=editor(qapp,tmp_path);w.add_scene('dynamic_body');oid=w.selected
    mass=field(w,'Масса');mass.setValue(3);mass.editingFinished.emit();qapp.processEvents()
    assert w.project.nodes[oid].mass==3;w.undo();assert w.project.nodes[oid].mass==1
    w.redo();assert w.project.nodes[oid].mass==3
    grav=field(w,'Гравитация Y');grav.setValue(600);grav.editingFinished.emit();qapp.processEvents()
    w.add_scene('rect_shape');w.save();loaded=load_project(tmp_path)
    assert loaded.nodes[oid].gravity==[0,600];assert loaded.nodes[oid].mass==3
    close(w,qapp)


def test_platform_and_one_way_property_history(qapp,tmp_path):
    w=editor(qapp,tmp_path);w.add_scene('platform_body');bid=w.selected;w.add_scene('rect_shape');sid=w.selected
    choice=field(w,'Поверхность');choice.setCurrentIndex(1);qapp.processEvents()
    assert w.project.nodes[sid].one_way;w.undo();assert not w.project.nodes[sid].one_way
    w.redo();normal=field(w,'Блокирующая сторона');normal.setCurrentIndex(2);qapp.processEvents()
    assert w.project.nodes[sid].one_way_normal==[-1,0]
    w.save();assert load_project(tmp_path).nodes[bid].kind=='platform_body';close(w,qapp)


def test_new_nodes_have_visible_typed_cards(qapp,tmp_path):
    p=platformer(True);w=editor(qapp,tmp_path,p);g=next(iter(p.graphs.values()))
    w.open_graph(g.id)
    for kind in list(PHYSICS_READ)+list(PHYSICS_ACTION)+['dot','vector_add','vector_sub']:
        w.add_graph_node(kind,0,0);qapp.processEvents()
    assert all(any(n.kind==k for n in w.current_graph().nodes.values()) for k in PHYSICS_ACTION)
    close(w,qapp)


@pytest.mark.parametrize('factory',[material_lab,platformer,lambda:platformer(True),side_gravity,impulse_lab])
def test_examples_validate_and_run(factory):
    p=factory();assert not validate_project(p)
    c=Clock();r=Runtime(p,clock=c);r.start()
    for i in range(200):
        if i==60:r.key_press('Space')
        if i==61:r.key_release('Space')
        c.advance(.016);r.update()
    r.stop()
