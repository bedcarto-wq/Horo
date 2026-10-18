"""0.4.1 local editor changes; no physics/language policy added."""
import copy
import pytest
from PySide6.QtCore import Qt,QPointF,QMimeData
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QLabel,QPushButton,QDoubleSpinBox
from horo.model import Project,Graph,SceneNode,Variable,Edge,Transform
from horo.ports import LABELS,DESCRIPTIONS,ports,port_help,PHYSICS_ACTION,PHYSICS_READ
from horo.validation import node_availability,validate_graph,validate_project,connection_error
from horo.runtime import Runtime
from horo.errors import Diagnostic,GraphError
from horo.ui.graph import NodeSearch
from horo.ui.console import ConsolePanel,LIMIT
from test_gui import window,finish
from test_dynamics_gui import field


def catalog_rows(w):
    return {w.catalog.topLevelItem(i).child(j).data(0,Qt.ItemDataRole.UserRole):w.catalog.topLevelItem(i).child(j)
            for i in range(w.catalog.topLevelItemCount()) for j in range(w.catalog.topLevelItem(i).childCount())}


@pytest.mark.parametrize('kind,region', [('behavior',None),('function',None),('behavior','loop'),('function','loop')])
def test_single_availability_policy_all_add_paths(qapp,tmp_path,kind,region):
    p=Project();g=Graph(kind=kind);p.graphs[g.id]=g
    if kind=='function':g.add('entry',0,0)
    loop=g.add('repeat',0,200)
    actual_region=loop.id if region else None
    w=window(qapp,tmp_path,lambda:p);w.open_graph(g.id);w.open_region(actual_region)
    allowed={k for k in LABELS if not node_availability(w.current_graph(),k,actual_region)}
    assert set(w.graph_editor.canvas.allowed())==allowed
    assert set(catalog_rows(w))==allowed
    w.catalog.show_unavailable.setChecked(True)
    rows=catalog_rows(w);assert set(rows)==set(LABELS)
    canvas=w.graph_editor.canvas
    dialog=NodeSearch(w.current_graph(),actual_region,canvas)
    reasons=[]
    for i in range(dialog.list.count()):
        item=dialog.list.item(i);k=item.data(Qt.ItemDataRole.UserRole)
        reason=node_availability(w.current_graph(),k,actual_region)
        assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled)==(reason is None)
        assert bool(rows[k].flags() & Qt.ItemFlag.ItemIsEnabled)==(reason is None)
        if reason:
            assert reason in rows[k].text(0) and reason in item.text()
            w.catalog.explain_item(rows[k]);assert reason in w.catalog.reason.text()
            reasons.append((k,reason))
    dialog.close()
    for k,reason in reasons:
        before=w.project.to_dict();w.add_graph_node(k,40,50)
        assert w.project.to_dict()==before
        assert reason in w.graph_editor.feedback.text()
    # Drop uses same policy, even a hand-made forbidden mime payload.
    if reasons:
        k,reason=reasons[0];mime=QMimeData();mime.setData('application/x-horo-node',k.encode())
        event=QDropEvent(QPointF(0,0),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        canvas.dropEvent(event);assert reason in w.graph_editor.feedback.text()
    finish(w,qapp)


@pytest.mark.parametrize('kind,gkind,region,word', [
    ('return','behavior',None,'графе-функции'),('key','function',None,'поведении'),
    ('continue','behavior',None,'контекст цикла'),('break','function',None,'контекст цикла'),
    ('start','behavior','loop','внешней области')])
def test_validator_reuses_context_reasons(kind,gkind,region,word):
    p=Project();g=Graph(kind=gkind);p.graphs[g.id]=g
    loop=g.add('repeat',0,0);n=g.add(kind,0,0,loop.id if region else None)
    reason=node_availability(g,kind,n.region,adding=False)
    assert word in reason
    assert reason in [d.message for d in validate_graph(p,g) if d.node_id==n.id]


def test_incomplete_allowed_saved_and_marked_not_forbidden(qapp,tmp_path):
    w=window(qapp,tmp_path);g=w.current_graph()
    if not g:g=next(iter(w.project.graphs.values()));w.open_graph(g.id)
    assert node_availability(g,'move') is None
    w.add_graph_node('move',600,600);node=list(w.current_graph().nodes.values())[-1]
    card=w.graph_editor.canvas.card_items[node.id]
    assert card.issues and any('Обязательный вход' in text for text in card.issues)
    proxy=next(c for c in card.childItems() if hasattr(c,'widget'))
    assert any('⚠' in label.text() for label in proxy.widget().findChildren(QLabel))
    assert w.save() # incomplete graphs have always been savable
    finish(w,qapp)


def test_connection_refusal_is_local_and_does_not_change_model(qapp,tmp_path):
    w=window(qapp,tmp_path);g=next(iter(w.project.graphs.values()));w.open_graph(g.id)
    n=g.add('number',0,0);m=g.add('move',400,0);w.refresh()
    edge=Edge(source=n.id,output='value',target=m.id,input='delta')
    reason=connection_error(w.project,g,edge);assert 'Ожидается Вектор2, получено Число' in reason
    before=w.project.to_dict();w.add_edge(edge)
    assert w.project.to_dict()==before
    assert reason in w.graph_editor.feedback.text()
    finish(w,qapp)


def test_graph_origin_shared_and_signature_context(qapp,tmp_path):
    p=Project(name='Проверка контекста');g=Graph(name='Общий');g.add('start',0,0);p.graphs[g.id]=g
    a=SceneNode(name='Первый',graph=g.id);b=SceneNode(name='Второй',graph=g.id);p.nodes={a.id:a,b.id:b}
    f=Graph(name='Расчёт',kind='function');f.add('entry',0,0);f.parameters=[Variable(name='Число X',type='number')];f.results=[Variable(name='Смещение',type='vector')];p.graphs[f.id]=f
    w=window(qapp,tmp_path,lambda:p);w.open_graph(g.id,a.id)
    assert 'Первый' in w.graph_editor.context.text() and 'раздельны' in w.graph_editor.context.text()
    w.select_object(b.id);assert 'Первый' in w.graph_editor.context.text() # selecting is not re-opening
    w.open_graph(g.id);assert 'Ресурс графа' in w.graph_editor.context.text() and 'Объект:' not in w.graph_editor.context.text()
    w.open_graph(f.id);assert 'Функция' in w.graph_editor.context.text()
    assert 'Число X: Число' in w.graph_editor.signature.text() and 'Смещение: Вектор2' in w.graph_editor.signature.text()
    # Shared validation must not fabricate the first owner.
    broken=g.add('move',0,300)
    assert all(d.object_id is None for d in validate_project(p) if d.graph_id==g.id)
    finish(w,qapp)


@pytest.mark.parametrize('kind,expected',[('move','локальные координаты'),('body_move','мировые координаты'),
    ('set_gravity','с²'),('set_velocity','с; мировые'),('impulse','Масса ×'),('get_angular','Градусы/с'),('wait','Секунды')])
def test_port_help_uses_actual_types_units_and_connection(kind,expected):
    p=Project();g=Graph();n=g.add(kind,0,0)
    assert set(LABELS)==set(DESCRIPTIONS)
    texts=[port_help(p,g,n,port) for port in ports(p,g,n)]
    assert any(expected in text for text in texts)
    for port,text in zip(ports(p,g,n),texts):
        assert port.label in text
        if port.direction=='in' and port.type!='exec':
            assert ('Обязательный' if port.required else 'Необязательный') in text
    port=next((x for x in ports(p,g,n) if x.direction=='in' and x.type!='exec'),None)
    if port:
        g.edges.append(Edge(source='source',output='value',target=n.id,input=port.key));assert 'приходит по линии' in port_help(p,g,n,port)


def test_card_description_disclosure_preserves_authoring(qapp,tmp_path):
    w=window(qapp,tmp_path);g=next(iter(w.project.graphs.values()));w.open_graph(g.id)
    n=next(iter(g.nodes.values()));before=w.project.to_dict()
    w.graph_editor.canvas.toggle_description(n.id);qapp.processEvents()
    card=w.graph_editor.canvas.card_items[n.id]
    proxy=next(c for c in card.childItems() if hasattr(c,'widget'))
    assert DESCRIPTIONS[n.kind] in [label.text() for label in proxy.widget().findChildren(QLabel)]
    assert w.project.to_dict()==before
    finish(w,qapp)


@pytest.mark.parametrize('attr,index,default',[('mass',None,1),('gravity',0,0),('restitution',None,0),('velocity',1,0)])
def test_reset_exact_property_default_and_history(qapp,tmp_path,attr,index,default):
    w=window(qapp,tmp_path,Project);w.add_scene('dynamic_body');oid=w.selected
    n=w.project.nodes[oid];n.mass=6;n.gravity=[15,700];n.velocity=[8,9];n.restitution=.8
    before=copy.deepcopy(n);w.reset_property(oid,attr,index=index)
    after=w.project.nodes[oid];value=getattr(after,attr)
    assert (value[index] if index is not None else value)==default
    if index is not None:assert value[1-index]==getattr(before,attr)[1-index]
    w.undo();assert w.project.nodes[oid]==before
    w.redo();assert getattr(w.project.nodes[oid],attr)!=getattr(before,attr)
    finish(w,qapp)


def test_transform_reset_is_not_saved_value(qapp,tmp_path):
    w=window(qapp,tmp_path);oid=next(iter(w.project.nodes));w.project.nodes[oid].transform=Transform(x=123,y=77,sx=2,sy=2)
    w.save();w.reset_property(oid,'x',transform=True)
    assert w.project.nodes[oid].transform.x==0 and w.project.nodes[oid].transform.y==77
    w.undo();assert w.project.nodes[oid].transform.x==123
    finish(w,qapp)


def test_console_filters_bounded_aggregation_and_private_values(qapp):
    panel=ConsolePanel();p=Project()
    d=Diagnostic('Ошибка типа',graph_id='g',node_id='n',object_id='o',expected='Число',received='PRIVATE-SECRET',invocation='run/1')
    panel.add(d,p);panel.add(d,p);assert panel.list.count()==1 and '×2' in panel.list.item(0).text()
    panel.add(Diagnostic(**{**d.__dict__,'object_id':'other'}),p)
    panel.add(Diagnostic(**{**d.__dict__,'invocation':'run/2'}),p)
    assert panel.list.count()==3
    panel.add(Diagnostic('Тест',severity='info'),p);panel.add(Diagnostic('Тест',severity='warning'),p)
    panel.filters['error'].setChecked(False)
    assert all(panel.list.item(i).isHidden() for i in range(3)) and not panel.list.item(3).isHidden()
    panel.list.setCurrentRow(0);panel.copy_details()
    assert 'PRIVATE-SECRET' not in qapp.clipboard().text() and 'Контекст вызова' in qapp.clipboard().text()
    assert panel.list.item(0).data(Qt.ItemDataRole.UserRole).received is None
    for i in range(LIMIT+1):panel.add(Diagnostic('Сообщение '+str(i),severity='info'),p)
    assert panel.list.count()==LIMIT==len(panel.records)
    panel.clear();assert not panel.records and panel.list.count()==0
    panel.close()


def test_session_preferences_and_deleted_source_navigation(qapp,tmp_path):
    w=window(qapp,tmp_path);w.catalog.show_unavailable.setChecked(True);w.console_panel.filters['warning'].setChecked(False)
    oid=next(iter(w.project.nodes));d=Diagnostic('Тест',object_id=oid,shape_id='removed')
    w.message(d);w.console.setCurrentRow(0);w.navigate_target(d,'object');assert w.selected==oid
    w.navigate_target(d,'shape');assert 'удалён' in w.console_panel.notice.text()
    w.navigate(w.console.item(0)) # no crash even if one source gone
    finish(w,qapp)
    other=window(qapp,tmp_path);assert not other.catalog.show_unavailable.isChecked() and other.console_panel.filters['warning'].isChecked();finish(other,qapp)


def test_editor_state_tracks_running_and_error(qapp,tmp_path):
    w=window(qapp,tmp_path);assert w.state_label.text()=='Редактирование' and not w.stop_action.isEnabled()
    w.run_game();qapp.processEvents();assert w.state_label.text()=='Игра запущена'
    # Authoring remains permitted and isolated, as before.
    w.add_scene('transform');assert len(w.project.nodes)!=len(w.game.runtime.project.nodes)
    w.stop_game();qapp.processEvents();assert w.state_label.text()=='Редактирование'
    g=next(iter(w.project.graphs.values()));g.add('move',0,300);w.run_game()
    assert w.state_label.text()=='Остановлено из-за ошибки' and w.game is None
    finish(w,qapp)


def test_diagnostic_invocations_distinct_no_semantic_change():
    r=Runtime(Project());g=Graph();a=r.frame(g,None);b=r.frame(g,None)
    assert a.diagnostic_id!=b.diagnostic_id
    with pytest.raises(GraphError) as exc:r.fail(a,None,'Тест')
    assert exc.value.diagnostic.invocation==a.diagnostic_id and not r.running


def test_new_checking_project_is_ordinary_and_runs_twice():
    from pathlib import Path
    from horo.storage import load_project
    p=load_project(Path(__file__).resolve().parents[1]/'examples/27-editor-clarity')
    assert not validate_project(p)
    before={o.id:(o.transform.x,o.transform.y) for o in p.nodes.values()}
    r=Runtime(p);r.key_press('Space')
    for o in r.project.nodes.values():assert (o.transform.x,o.transform.y)==(before[o.id][0]+45,before[o.id][1]+15)
    r.stop();again=Runtime(p)
    for o in again.project.nodes.values():assert (o.transform.x,o.transform.y)==before[o.id]
    again.stop()


def test_runtime_error_state_and_deleted_graph_shape_sources(qapp,tmp_path):
    w=window(qapp,tmp_path);w.run_game();qapp.processEvents();game=w.game
    diagnostic=Diagnostic('Контролируемая ошибка',graph_id='deleted',node_id='gone',object_id='gone',shape_id='gone')
    def fail():raise GraphError(diagnostic)
    game.handle(fail);assert not game.runtime.running and w.state_label.text()=='Остановлено из-за ошибки'
    w.console.setCurrentRow(w.console.count()-1);w.navigate(w.console.currentItem());assert 'удалён' in w.console_panel.notice.text()
    w.navigate_target(diagnostic,'graph');assert 'удалён' in w.console_panel.notice.text()
    w.stop_game();qapp.processEvents();assert w.game is None
    finish(w,qapp)


def test_reset_flushes_pending_field_edit_before_default(qapp,tmp_path):
    w=window(qapp,tmp_path);oid=next(iter(w.project.nodes))
    w.defer_transform(oid,'x',987)
    w.reset_property(oid,'x',transform=True);qapp.processEvents()
    assert w.project.nodes[oid].transform.x==0
    w.undo();assert w.project.nodes[oid].transform.x==987
    finish(w,qapp)


def test_disabled_catalog_hover_explains_and_real_context_reset(qapp,tmp_path):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QTimer,QPoint
    from PySide6.QtWidgets import QApplication,QMenu
    w=window(qapp,tmp_path);g=next(iter(w.project.graphs.values()));w.open_graph(g.id)
    w.catalog.show_unavailable.setChecked(True);w.catalog.search.setText('Вернуть');qapp.processEvents()
    item=next(iter(catalog_rows(w).values()));pos=w.catalog.visualItemRect(item).center()
    QTest.mouseMove(w.catalog.viewport(),pos);qapp.processEvents()
    assert 'графе-функции' in w.catalog.reason.text()
    oid=next(iter(w.project.nodes));w.select_object(oid);spin=field(w,'X')
    def choose():
        menu=QApplication.activePopupWidget()
        assert isinstance(menu,QMenu)
        action=menu.actions()[-1];assert 'по умолчанию' in action.text()
        menu.setActiveAction(action);QTest.keyClick(menu,Qt.Key.Key_Return)
    QTimer.singleShot(30,choose)
    spin.customContextMenuRequested.emit(QPoint(5,5));qapp.processEvents()
    assert w.project.nodes[oid].transform.x==0
    w.undo();assert w.project.nodes[oid].transform.x==80
    finish(w,qapp)
