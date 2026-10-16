"""Stage 3: geometry and game-time checks without Qt or real sleeps."""
import math
import pytest
from horo.geometry import (Shape,validate_polygon,triangulate,area,overlap,distance,sweep,ENTER,LEAVE)
from horo.physics import PhysicsWorld,PhysicsError,world_shapes
from horo.model import Project,SceneNode,Transform,Graph,Variable
from horo.runtime import Runtime
from horo.errors import GraphError
from horo.examples import link
from horo.storage import save_project,load_project
from horo.validation import validate_project

class Clock:
    def __init__(self):self.value=0
    def __call__(self):return self.value
    def advance(self,dt):self.value+=dt

def body(p,kind='controlled_body',x=0,y=0,shape='rect_shape',w=10,h=10,r=5,points=None,parent=None,rotation=0):
    n=SceneNode(kind=kind,name=kind,parent=parent,transform=Transform(x=x,y=y,rotation=rotation));p.nodes[n.id]=n
    s=SceneNode(kind=shape,name=shape,parent=n.id,width=w,height=h,radius=r)
    if points is not None:s.points=points
    p.nodes[s.id]=s
    return n,s

def basic():
    p=Project();a,sa=body(p);b,sb=body(p,'static_body',x=30,w=10,h=100)
    return p,a,b,sa,sb

def graph_move(p,a,kind='frame',vx=100,vy=0):
    g=Graph();p.graphs[g.id]=g;a.graph=g.id
    start=g.add(kind);move=g.add('body_move');vector=g.add('vector',x=vx,y=vy)
    link(g,start,'next',move,'in');link(g,start,'object',move,'object');link(g,vector,'value',move,'velocity')
    return g,start,move,vector

def runtime(p):
    c=Clock();return Runtime(p,clock=c),c

def step(r,c,dt=.05):c.advance(dt);r.update()

def test_polygon_winding_and_ears_preserve_area():
    raw=[[0,0],[100,0],[100,20],[20,20],[20,100],[0,100]]
    p=validate_polygon(raw);ts=triangulate(p)
    assert len(ts)==4
    assert sum(area(t) for t in ts)==pytest.approx(area(p))
    assert validate_polygon(list(reversed(raw)))==p
    assert raw[0]==[0,0]

@pytest.mark.parametrize('points',[
 [],[[0,0],[1,0]],[[0,0],[10,0],[0,0]],[[0,0],[10,0],[20,0]],
 [[0,0],[10,10],[0,10],[10,0]],[[0,0],[10,0],[5,0],[5,10]],
 [[0,0],[float('nan'),2],[2,2]],[[0,0],[float('inf'),0],[2,2]],
 [[0,0],[True,0],[2,2]],[[0,0],[.1,0],[0,10]],
 [[0,0],[10,0],[10,.1],[0,.1]],
])
def test_bad_polygons(points):
    with pytest.raises(ValueError):validate_polygon(points)

@pytest.mark.parametrize('shape',['rect_shape','circle_shape','polygon_shape'])
def test_supported_shapes(shape):
    p=Project();a,s=body(p,shape=shape);shapes=world_shapes(p)
    assert len(shapes[a.id])==1
    assert shapes[a.id][0].id==s.id

@pytest.mark.parametrize('sx,sy',[(0,1),(-1,-1),(1,2),(float('nan'),1)])
def test_reject_unsupported_scale(sx,sy):
    p=Project();a,s=body(p);a.transform.sx=sx;a.transform.sy=sy
    with pytest.raises(PhysicsError,match='масштаб|Неконечное'):world_shapes(p)

def test_parent_transform_once_and_world_motion():
    p=Project();parent=SceneNode(transform=Transform(x=100,y=100,sx=2,sy=2,rotation=90));p.nodes[parent.id]=parent
    a,s=body(p,x=10,parent=parent.id);s.transform.x=3
    forms=world_shapes(p)[a.id];pts=forms[0].points
    assert sum(x for x,y in pts)/4==pytest.approx(100)
    assert sum(y for x,y in pts)/4==pytest.approx(126)
    w=PhysicsWorld(p);w.command(a.id,[100,0]);w.update(.1)
    assert a.transform.x==pytest.approx(10);assert a.transform.y==pytest.approx(-5)

def test_parent_nonuniform_rejected():
    p=Project();parent=SceneNode(transform=Transform(sx=1,sy=2));p.nodes[parent.id]=parent;body(p,parent=parent.id)
    with pytest.raises(PhysicsError):world_shapes(p)

def test_circle_scale_drawing_geometry():
    p=Project();a,s=body(p,shape='circle_shape');a.transform.sx=a.transform.sy=2
    assert world_shapes(p)[a.id][0].radius==10

def test_compound_internal_overlap_allowed():
    p=Project();a,s=body(p);extra=SceneNode(kind='circle_shape',parent=a.id,radius=5);p.nodes[extra.id]=extra
    assert len(PhysicsWorld(p).project.nodes)==3

def test_nested_bodies_rejected():
    p=Project();a,_=body(p);body(p,parent=a.id)
    with pytest.raises(PhysicsError,match='вкладывать'):world_shapes(p)

@pytest.mark.parametrize('value',[0,-1,float('nan'),float('inf'),True])
def test_bad_rectangle_sizes(value):
    p=Project();a,s=body(p);s.width=value
    with pytest.raises(PhysicsError):world_shapes(p)

@pytest.mark.parametrize('shape_a,shape_b',[('rect_shape','rect_shape'),('circle_shape','rect_shape'),('rect_shape','circle_shape'),('circle_shape','circle_shape')])
def test_sweep_blocks_thin_wall_high_speed(shape_a,shape_b):
    p=Project();a,_=body(p,shape=shape_a);b,_=body(p,'static_body',x=100,shape=shape_b,w=.5,h=100,r=.25 if shape_b=='circle_shape' else 5)
    w=PhysicsWorld(p);w.command(a.id,[10000,0]);events=w.update(.1)
    assert a.transform.x<100
    assert not any(overlap(x,y) for x in world_shapes(p)[a.id] for y in world_shapes(p)[b.id])
    assert ('contact_begin',tuple(sorted((a.id,b.id)))) in events

@pytest.mark.parametrize('dt',[1/30,1/60,1/120,.1])
def test_free_motion_frame_rate(dt):
    p=Project();a,_=body(p);w=PhysicsWorld(p)
    for _ in range(round(1/dt)):w.command(a.id,[120,0]);w.update(dt)
    assert a.transform.x==pytest.approx(120,abs=1e-5)

def test_slide_and_stable_wall_contact():
    p,a,b,sa,sb=basic();w=PhysicsWorld(p);begins=0
    for _ in range(20):
        w.command(a.id,[100,10]);events=w.update(.05)
        begins+=sum(kind=='contact_begin' for kind,pair in events)
        assert a.transform.x<=20+1e-5
    assert begins==1;assert a.transform.x==pytest.approx(20,abs=1e-5);assert a.transform.y==pytest.approx(10,abs=1e-4)
    for _ in range(10):w.command(a.id,[0,0]);assert w.update(.05)==[]
    w.command(a.id,[-100,0]);events=w.update(.05);assert events[0][0]=='contact_end'

def test_two_walls_corner():
    p,a,b,_,_=basic();extra=SceneNode(kind='rect_shape',parent=b.id,width=100,height=10,transform=Transform(x=-30,y=30));p.nodes[extra.id]=extra
    w=PhysicsWorld(p)
    for _ in range(20):w.command(a.id,[100,100]);w.update(.05)
    assert a.transform.x==pytest.approx(20,abs=1e-4);assert a.transform.y==pytest.approx(20,abs=1e-4)

def test_rotated_rectangle_really_collides():
    p=Project();a,_=body(p,shape='circle_shape');wall,_=body(p,'static_body',x=50,rotation=45,w=10,h=150)
    w=PhysicsWorld(p)
    for _ in range(5):w.command(a.id,[100,0]);w.update(.1)
    assert a.transform.y<0;assert a.transform.x<50

def test_concave_interior_is_open_and_no_triangle_seams():
    p=Project();a,_=body(p,x=60,y=60,shape='circle_shape');wall,_=body(p,'static_body',points=[[0,0],[100,0],[100,20],[20,20],[20,100],[0,100]],shape='polygon_shape')
    w=PhysicsWorld(p)
    for _ in range(10):w.command(a.id,[-100,0]);w.update(.05)
    assert a.transform.x==pytest.approx(25,abs=1e-4)
    for _ in range(20):w.command(a.id,[0,100]);w.update(.05)
    assert a.transform.y==pytest.approx(160,abs=1e-4)

def test_compound_contact_transfers_without_false_end():
    p=Project();a,_=body(p,x=0,y=-30,shape='circle_shape');wall,s=body(p,'static_body',x=10,y=-25,w=10,h=50)
    s2=SceneNode(kind='rect_shape',parent=wall.id,width=10,height=50,transform=Transform(y=50));p.nodes[s2.id]=s2
    w=PhysicsWorld(p);events=w.update(.01);assert len(events)==1
    for _ in range(60):
        w.command(a.id,[0,20]);assert w.update(.05)==[]
    w.command(a.id,[-100,0]);assert w.update(.05)[0][0]=='contact_end'

def test_controlled_bodies_block_without_push():
    p=Project();a,_=body(p);b,_=body(p,x=30)
    w=PhysicsWorld(p);w.command(a.id,[1000,0]);w.update(.1)
    assert a.transform.x==pytest.approx(20,abs=1e-4);assert b.transform.x==30

def test_initial_overlap_and_teleport_error():
    p,a,b,_,_=basic();a.transform.x=30
    with pytest.raises(PhysicsError,match='Проникновение'):PhysicsWorld(p)
    a.transform.x=0;w=PhysicsWorld(p);a.transform.x=30
    with pytest.raises(PhysicsError,match='Проникновение'):w.update(.01)

@pytest.mark.parametrize('velocity',[[10001,0],[float('nan'),0],[0,float('inf')],[True,0],'1,2'])
def test_invalid_velocity(velocity):
    p,a,_,_,_=basic();w=PhysicsWorld(p)
    with pytest.raises(PhysicsError):w.command(a.id,velocity)

@pytest.mark.parametrize('dt',[.1001,-1,float('nan'),float('inf')])
def test_bad_dt(dt):
    p,a,_,_,_=basic();w=PhysicsWorld(p)
    with pytest.raises(PhysicsError):w.update(dt)

def test_last_command_wins_then_stops():
    p=Project();a,_=body(p);w=PhysicsWorld(p)
    w.command(a.id,[100,0]);w.command(a.id,[20,0]);w.update(.1);assert a.transform.x==2
    w.update(.1);assert a.transform.x==2

def test_held_direction_opposites_normalization():
    p=Project();g=Graph();p.graphs[g.id]=g;g.add('key');d=g.add('direction');n=g.add('normalize');link(g,d,'value',n,'vector');h=g.add('held',key='W')
    r,c=runtime(p);f=r.frame(g,None)
    assert r.evaluate(f,d,'value',{})==[0,0]
    r.key_press('W');r.key_press('D')
    assert r.evaluate(f,d,'value',{})==[1,-1]
    assert r.evaluate(f,h,'value',{}) is True
    assert r.evaluate(f,n,'value',{})==pytest.approx([2**-.5,-2**-.5])
    r.key_press('S');r.key_press('A');assert r.evaluate(f,n,'value',{})==[0,0]
    r.key_release('W');assert r.evaluate(f,h,'value',{}) is False

@pytest.mark.parametrize('kind',['normalize','vector_scale'])
def test_vector_nodes_strict_types(kind):
    p=Project();g=Graph();g.add('key');p.graphs[g.id]=g;source=g.add('vector');node=g.add(kind);link(g,source,'value',node,'vector')
    if kind=='vector_scale':
        factor=g.add('number',value=2);link(g,factor,'value',node,'factor')
    r,c=runtime(p);source.params['x']='text'
    # Runtime owns its snapshot; mutate the actual runtime card for a defensive runtime check.
    r.project.graphs[g.id].nodes[source.id].params['x']='text'
    with pytest.raises(GraphError):r.evaluate(r.frame(r.project.graphs[g.id],None),r.project.graphs[g.id].nodes[node.id],'value',{})

def test_runtime_frame_movement_and_snapshot():
    p,a,b,_,_=basic();g,start,move,v=graph_move(p,a)
    r,c=runtime(p);step(r,c)
    assert r.project.nodes[a.id].transform.x==5;assert a.transform.x==0
    r.stop();assert not r.held and not r.contact_queue and not r.physics.contacts
    r2,c2=runtime(p);assert r2.project.nodes[a.id].transform.x==0

def test_runtime_contact_deferred_isolated_and_paired():
    p,a,b,_,_=basic();g,start,move,v=graph_move(p,a,vx=1000)
    count=Variable(scope='game');p.variables[count.id]=count
    begin=g.add('contact_begin');write=g.add('write',variable=count.id);one=g.add('number',value=1)
    link(g,begin,'next',write,'in');link(g,one,'value',write,'value')
    r,c=runtime(p);step(r,c);assert r.game[count.id]==0;assert r.contact_queue
    step(r,c);assert r.game[count.id]==1
    assert not r.contact_queue

def test_deleted_contact_body_and_stop_safe():
    p,a,b,_,_=basic();a.transform.x=20;g,_,_,_=graph_move(p,a,vx=0)
    r,c=runtime(p);step(r,c);r.project.remove_scene(b.id);step(r,c)
    assert ('contact_end',tuple(sorted((a.id,b.id)))) in r.contact_queue
    r.stop();assert not r.contact_queue

def test_move_errors_point_to_graph_node():
    p,a,b,_,_=basic();g,start,move,v=graph_move(p,b)
    r,c=runtime(p)
    with pytest.raises(GraphError) as exc:step(r,c)
    assert exc.value.diagnostic.node_id==move.id and exc.value.diagnostic.graph_id==g.id
    assert not r.running

def test_old_move_remains_local_not_physical():
    p,a,b,_,_=basic();g=Graph();p.graphs[g.id]=g;a.graph=g.id;start=g.add('key');move=g.add('move');v=g.add('vector',x=30,y=0)
    link(g,start,'next',move,'in');link(g,start,'object',move,'object');link(g,v,'value',move,'delta')
    r,c=runtime(p);r.key_press('Space');assert r.project.nodes[a.id].transform.x==30
    with pytest.raises(GraphError,match='Проникновение'):step(r,c)

def test_storage_roundtrip_all_shapes(tmp_path):
    p=Project();a,_=body(p);b,_=body(p,'static_body',x=100,shape='circle_shape');c,_=body(p,'static_body',x=300,shape='polygon_shape')
    graph_move(p,a);save_project(p,tmp_path);q=load_project(tmp_path)
    assert q.to_dict()==p.to_dict();assert not validate_project(q);PhysicsWorld(q)

def test_thin_geometry_and_out_of_bounds_rejected():
    p=Project();a,s=body(p,w=.1)
    with pytest.raises(PhysicsError):PhysicsWorld(p)
    s.width=10;a.transform.x=1_000_000
    with pytest.raises(PhysicsError):PhysicsWorld(p)

def test_missing_body_and_missing_shape():
    p,a,b,_,_=basic();w=PhysicsWorld(p)
    with pytest.raises(PhysicsError):w.command('missing',[0,0])
    p.remove_scene(a.id);w.update(.01)
    p=Project();a=SceneNode(kind='controlled_body');p.nodes[a.id]=a
    with pytest.raises(PhysicsError,match='нет формы'):PhysicsWorld(p)

def test_contact_hysteresis():
    p=Project();a,_=body(p,shape='circle_shape');b,_=body(p,'static_body',x=10+ENTER*.5,shape='circle_shape')
    w=PhysicsWorld(p);assert w.update(.01)[0][0]=='contact_begin'
    b.transform.x=10+(ENTER+LEAVE)/2;assert w.update(.01)==[]
    b.transform.x=10+LEAVE*2;assert w.update(.01)[0][0]=='contact_end'

def test_examples_validate_run_roundtrip(tmp_path):
    from horo.physics_examples import playground,thin_wall,custom_input
    for factory in [playground,thin_wall,custom_input]:
        p=factory();assert not validate_project(p);folder=tmp_path/factory.__name__;save_project(p,folder);q=load_project(folder)
        assert p.to_dict()==q.to_dict();r,c=runtime(q);r.key_press('D' if factory!=custom_input else 'Right')
        for _ in range(20):step(r,c,.01)
        assert r.running

def test_normalize_extreme_finite_vector():
    from horo.geometry import unit
    assert unit([1.7e308,1.7e308])==pytest.approx([2**-.5,2**-.5])

def test_random_continuous_motion_does_not_penetrate():
    import random
    random.seed(817)
    for _ in range(100):
        p=Project();a,_=body(p,x=-100,y=random.uniform(-70,70),shape=random.choice(['rect_shape','circle_shape']),rotation=random.uniform(-180,180))
        b,_=body(p,'static_body',x=30,shape=random.choice(['rect_shape','circle_shape']),w=20,h=100,r=40,rotation=random.uniform(-180,180))
        w=PhysicsWorld(p);w.command(a.id,[random.uniform(100,3000),random.uniform(-400,400)]);w.update(.1)
        shapes=world_shapes(p);assert not any(overlap(x,y) for x in shapes[a.id] for y in shapes[b.id])

def test_contact_handler_can_wait_using_existing_tasks():
    p,a,b,_,_=basic();a.transform.x=20;g=Graph();p.graphs[g.id]=g;a.graph=g.id
    begin=g.add('contact_begin');wait=g.add('wait',n=.05);put=g.add('write');v=Variable(scope='game');p.variables[v.id]=v;put.params['variable']=v.id
    one=g.add('number',value=1);link(g,begin,'next',wait,'in');link(g,wait,'next',put,'in');link(g,one,'value',put,'value')
    r,c=runtime(p);step(r,c,.01);step(r,c,.01);assert r.sleepers and r.game[v.id]==0
    step(r,c,.06);assert r.game[v.id]==1

def test_custom_control_without_direction_node():
    from horo.physics_examples import custom_input
    p=custom_input();assert not any(n.kind=='direction' for g in p.graphs.values() for n in g.nodes.values())
    a=next(n for n in p.nodes.values() if n.kind=='controlled_body');r,c=runtime(p);r.key_press('Right')
    step(r,c,.1);assert r.project.nodes[a.id].transform.x==118
    r.key_release('Right');step(r,c,.1);assert r.project.nodes[a.id].transform.x==118

def test_normalized_diagonal_speed():
    from horo.physics_examples import playground
    p=playground();a=next(n for n in p.nodes.values() if n.kind=='controlled_body');r,c=runtime(p)
    r.key_press('D');r.key_press('S');step(r,c,.1)
    t=r.project.nodes[a.id].transform
    assert math.hypot(t.x-a.transform.x,t.y-a.transform.y)==pytest.approx(18)

def test_skinny_triangle_rejected():
    with pytest.raises(ValueError,match='толщина'):validate_polygon([[0,0],[100,0],[50,.1]])

def test_contact_handler_deleting_body_safe(monkeypatch):
    p,a,b,_,_=basic();a.transform.x=20;g=Graph();p.graphs[g.id]=g;a.graph=g.id;g.add('contact_begin');g.add('contact_end')
    r,c=runtime(p);original=r._step;deleted=[]
    def handler(task):
        if task.node and task.node.kind=='contact_begin' and not deleted:
            r.project.remove_scene(b.id);deleted.append(b.id)
        original(task)
    monkeypatch.setattr(r,'_step',handler)
    step(r,c,.01);step(r,c,.01);step(r,c,.01)
    assert deleted==[b.id] and r.running and not r.physics.contacts

def test_stop_inside_contact_handler_clears_all_work(monkeypatch):
    p,a,b,_,_=basic();a.transform.x=20;g=Graph();p.graphs[g.id]=g;a.graph=g.id;g.add('contact_begin')
    r,c=runtime(p);original=r._step
    def handler(task):
        if task.node and task.node.kind=='contact_begin':r.stop();return
        original(task)
    monkeypatch.setattr(r,'_step',handler)
    step(r,c,.01);step(r,c,.01)
    assert not r.running and not r.tasks and not r.contact_queue and not r.physics.contacts

def test_physics_error_shape_diagnostic():
    p,a,b,sa,sb=basic();a.transform.sx=2
    with pytest.raises(GraphError) as e:Runtime(p)
    assert e.value.diagnostic.shape_id==sa.id
    assert sa.id in e.value.diagnostic.describe(p)

def test_vector_multiply_strict_factor_and_overflow():
    p=Project();g=Graph();p.graphs[g.id]=g;g.add('key');v=g.add('vector',x=3,y=-4);factor=g.add('number',value=2);node=g.add('vector_scale')
    link(g,v,'value',node,'vector');link(g,factor,'value',node,'factor');r,c=runtime(p);graph=r.project.graphs[g.id]
    assert r.evaluate(r.frame(graph,None),graph.nodes[node.id],'value',{})==[6,-8]
    graph.nodes[factor.id].params['value']='2'
    with pytest.raises(GraphError):r.evaluate(r.frame(graph,None),graph.nodes[node.id],'value',{})

def test_contact_events_obey_existing_task_limit():
    p,a,b,_,_=basic();a.transform.x=20;g=Graph();p.graphs[g.id]=g;a.graph=g.id
    for _ in range(4):g.add('contact_begin')
    c=Clock();r=Runtime(p,clock=c,task_limit=2);step(r,c,.01)
    with pytest.raises(GraphError,match='живых задач'):step(r,c,.01)
    assert not r.running and not r.tasks
