"""0.4 deterministic physics checks. No wall clock or GUI dependencies."""
import math
import pytest
from horo.model import Project,SceneNode,Transform,Graph,Edge
from horo.physics import PhysicsWorld,PhysicsError,world_shapes
from horo.rigid import mass_properties,features
from horo.geometry import dot,length,sub,overlap
from horo.examples import link
from horo.runtime import Runtime
from horo.errors import GraphError
from horo.storage import save_project,load_project
from horo.validation import validate_project
from horo.history import History
from test_physics import body,Clock


def run(w,seconds,dt=.02):
    for i in range(round(seconds/dt)):w.update(dt)


def falling(shape='rect_shape',gravity=(0,100),**kw):
    p=Project();a,s=body(p,'dynamic_body',shape=shape,**kw);a.gravity=list(gravity)
    b,t=body(p,'static_body',y=30,w=500,h=10)
    return p,a,s,b,t,PhysicsWorld(p)


def floor_character(gravity=(0,100)):
    p=Project();a,s=body(p);a.gravity=list(gravity)
    b,t=body(p,'static_body',y=10,w=100,h=10)
    return p,a,b,PhysicsWorld(p)


@pytest.mark.parametrize('shape,inertia', [('rect_shape',100/6),('circle_shape',12.5)])
def test_exact_mass_integrals(shape,inertia):
    p=Project();a,s=body(p,'dynamic_body',shape=shape);a.mass=3
    c,i=mass_properties(world_shapes(p)[a.id],a.mass)
    assert c==pytest.approx((0,0));assert i==pytest.approx(inertia*3)


def test_compound_offset_and_overlapping_layers():
    p=Project();a,s=body(p,'dynamic_body');s.transform.x=-10
    t=SceneNode(kind='rect_shape',parent=a.id,width=10,height=10,transform=Transform(x=10));p.nodes[t.id]=t
    c,i=mass_properties(world_shapes(p)[a.id],2)
    assert c==pytest.approx((0,0));assert i==pytest.approx(2*(100/6+100))
    t.transform.x=-10;c,i=mass_properties(world_shapes(p)[a.id],2)
    assert c==pytest.approx((-10,0));assert i==pytest.approx(100/3)


def test_concave_integral_equals_area_partition():
    p=Project();a,s=body(p,'dynamic_body',shape='polygon_shape',points=[[0,0],[20,0],[20,10],[10,10],[10,20],[0,20]])
    c,i=mass_properties(world_shapes(p)[a.id],3)
    assert c==pytest.approx((25/3,25/3));assert i==pytest.approx(550/3)


@pytest.mark.parametrize('dt',[.1,.02,.008])
def test_independent_gravity_and_mass(dt):
    p=Project();a,s=body(p,'dynamic_body',x=-100);b,t=body(p,'dynamic_body',x=100);a.mass=1;b.mass=9
    a.gravity=b.gravity=[0,30];w=PhysicsWorld(p);run(w,.4,dt)
    assert w.dynamics.read('get_velocity',a.id)==pytest.approx([0,12])
    assert w.dynamics.read('get_velocity',b.id)==pytest.approx([0,12])
    w.dynamics.action('set_gravity',b.id,[10,0]);run(w,.4,dt)
    assert w.dynamics.read('get_velocity',a.id)==pytest.approx([0,24])
    assert w.dynamics.read('get_velocity',b.id)==pytest.approx([4,12])


def test_impulse_center_and_offset():
    p=Project();a,s=body(p,'dynamic_body');a.mass=2;w=PhysicsWorld(p);d=w.dynamics
    d.action('impulse',a.id,[10,0]);assert d.read('get_velocity',a.id)==[5,0];assert d.read('get_angular',a.id)==0
    d.action('impulse',a.id,[10,0],[0,5]);assert d.read('get_velocity',a.id)==[10,0]
    assert d.states[a.id].omega==pytest.approx(-50/(100/3))


def test_offset_com_remains_fixed_when_spinning_with_parent():
    p=Project();parent=SceneNode(transform=Transform(x=100,y=200,rotation=30,sx=2,sy=2));p.nodes[parent.id]=parent
    a,s=body(p,'dynamic_body',parent=parent.id);s.transform.x=10;a.angular_velocity=90
    w=PhysicsWorld(p);before=w.dynamics.states[a.id].center
    run(w,1,.02);after=mass_properties(world_shapes(p)[a.id],1)[0]
    assert after==pytest.approx(before,abs=1e-7)
    assert a.transform.rotation==pytest.approx(90)


@pytest.mark.parametrize('shape',['rect_shape','circle_shape','polygon_shape'])
@pytest.mark.parametrize('dt',[.1,.02])
def test_fall_and_rest(shape,dt):
    p,a,s,b,t,w=falling(shape,points=[[-5,-5],[5,-5],[5,5],[-5,5]] if shape=='polygon_shape' else None)
    run(w,1,dt);v=w.dynamics.read('get_velocity',a.id)
    assert a.transform.y==pytest.approx(20,abs=.02)
    assert length(v)<.02
    initial=a.transform.y;run(w,.4,dt);assert abs(a.transform.y-initial)<.002


def test_off_center_collision_rotates_not_arbitrary_animation():
    p=Project();a,s=body(p,'dynamic_body',x=-7,y=-20);a.velocity=[0,80];a.friction=0
    b,t=body(p,'static_body',x=0,y=10,w=10,h=10);b.friction=0
    w=PhysicsWorld(p);peak=0.;rotation=0.
    for _ in range(40):
        w.update(.01);peak=max(peak,abs(w.dynamics.states[a.id].omega));rotation=max(rotation,min(a.transform.rotation,360-a.transform.rotation))
    assert peak>.1
    assert rotation>.1


@pytest.mark.parametrize('dt',[.1,.02])
def test_bounce_material_max_and_energy(dt):
    p,a,s,b,t,w=falling();a.gravity=[0,0];w.dynamics.states[a.id].gravity=(0,0)
    a.restitution=.3;b.restitution=.8;w.dynamics.action('set_velocity',a.id,[0,100])
    run(w,.3,dt);v=w.dynamics.read('get_velocity',a.id)
    assert v[1]==pytest.approx(-80,abs=.1);assert length(v)<=100.01


def test_friction_sqrt_pair_slows_slide():
    def simulate(mu):
        p,a,s,b,t,w=falling();a.friction=mu;b.friction=1
        run(w,1);w.dynamics.action('set_velocity',a.id,[50,0]);run(w,.4)
        return abs(w.dynamics.states[a.id].velocity[0])
    assert simulate(0)>49.9
    assert simulate(.25)<40


@pytest.mark.parametrize('dt',[.1,.016,.008])
def test_high_speed_thin_wall(dt):
    p=Project();a,s=body(p,'dynamic_body',x=-50,shape='circle_shape',r=.25);a.velocity=[10000,0]
    b,t=body(p,'static_body',x=1,w=.5,h=100);w=PhysicsWorld(p);w.update(dt)
    assert a.transform.x<.501;assert abs(w.dynamics.states[a.id].velocity[0])<.01


def test_rotational_extreme_does_not_cross_wall():
    p=Project();a,s=body(p,'dynamic_body',x=-12,w=20,h=2);a.angular_velocity=720
    b,t=body(p,'static_body',x=0,w=.5,h=100);w=PhysicsWorld(p);run(w,.2)
    assert max(x for x,y in world_shapes(p)[a.id][0].points)<-.2499


def test_no_push_in_either_direction_or_support_on_dynamic():
    p=Project();a,s=body(p);b,t=body(p,'dynamic_body',x=10);w=PhysicsWorld(p)
    w.command(a.id,[100,0]);w.update(.1)
    assert a.transform.x<1e-4;assert b.transform.x==pytest.approx(10);assert w.dynamics.read('get_velocity',b.id)==[0,0]
    w.dynamics.action('set_velocity',b.id,[-50,0]);run(w,.2)
    assert a.transform.x<1e-4;assert b.transform.x>9.999
    assert not w.dynamics.read('grounded',a.id)


def test_controlled_drive_and_accumulated_velocity_separate():
    p=Project();a,s=body(p);a.gravity=[0,100];w=PhysicsWorld(p)
    for i in range(10):w.command(a.id,[30,0]);w.update(.02)
    assert a.transform.x==pytest.approx(6);assert w.dynamics.read('get_velocity',a.id)==pytest.approx([0,20])
    before=a.transform.x;w.update(.02);assert a.transform.x==before


@pytest.mark.parametrize('orientation',[0,90,180,270])
def test_support_orientation_and_jump(orientation):
    r=math.radians(orientation);g=(-math.sin(r)*100,math.cos(r)*100)
    p=Project();a,s=body(p);a.gravity=list(g)
    b,t=body(p,'static_body',x=-math.sin(r)*10,y=math.cos(r)*10,w=100,h=10,rotation=orientation)
    # Rotate character as well so surfaces are initially touching.
    a.transform.rotation=orientation;w=PhysicsWorld(p)
    assert w.dynamics.read('grounded',a.id)
    assert w.dynamics.action('jump',a.id,50)
    assert not w.dynamics.read('grounded',a.id)
    assert not w.dynamics.action('jump',a.id,50)
    assert dot(w.dynamics.read('get_velocity',a.id),w.dynamics.up(a.id))==pytest.approx(50)
    w.update(.02);assert not w.dynamics.read('grounded',a.id)


def test_zero_gravity_explicit_up_and_no_wall_support():
    p,a,b,w=floor_character((0,0));assert w.dynamics.read('grounded',a.id)
    a.up=[1,0];w.dynamics.refresh_support(world_shapes(p));assert not w.dynamics.read('grounded',a.id)


@pytest.mark.parametrize('angle,grounded',[(30,True),(45,True),(50,False)])
def test_slope_angle(angle,grounded):
    # Circle touches center of an inclined rectangular floor.
    r=math.radians(angle);p=Project();a,s=body(p,shape='circle_shape');a.gravity=[0,100]
    b,t=body(p,'static_body',x=-math.sin(r)*10,y=math.cos(r)*10,w=100,h=10,rotation=angle)
    w=PhysicsWorld(p);assert w.dynamics.read('grounded',a.id)==grounded


def test_jump_preserves_tangent_and_consumes_primitive_support():
    p,a,b,w=floor_character();d=w.dynamics
    d.action('set_velocity',a.id,[12,0]);assert d.read('grounded',a.id)
    d.action('jump',a.id,30);assert d.read('get_velocity',a.id)==[12,-30]
    p,a,b,w=floor_character();d=w.dynamics;d.action('set_velocity',a.id,[12,-30])
    assert not d.read('grounded',a.id);assert not d.action('jump',a.id,30)


@pytest.mark.parametrize('dt',[.1,.02])
def test_one_way_pass_below_land_and_leave(dt):
    p=Project();a,s=body(p,y=20,shape='circle_shape');a.gravity=[0,100]
    b,t=body(p,'static_body',w=100,h=4);t.one_way=True
    w=PhysicsWorld(p);w.dynamics.action('set_velocity',a.id,[0,-100]);run(w,.4,dt)
    assert a.transform.y<-7
    run(w,1.6,dt);assert a.transform.y==pytest.approx(-7,abs=.001)
    assert w.dynamics.read('grounded',a.id)
    for i in range(round(.8/dt)):w.command(a.id,[100,0]);w.update(dt)
    assert not w.dynamics.read('grounded',a.id);assert not w.dynamics.action('jump',a.id,50)


def test_one_way_normal_transformed_by_shape_parent():
    p=Project();parent=SceneNode(transform=Transform(rotation=90));p.nodes[parent.id]=parent
    b,t=body(p,'static_body',parent=parent.id,w=100,h=4);t.one_way=True
    a,s=body(p,x=7,shape='circle_shape');a.gravity=[-100,0];w=PhysicsWorld(p)
    assert w.dynamics.read('grounded',a.id)
    run(w,.2);assert a.transform.x==pytest.approx(7,abs=.001)


@pytest.mark.parametrize('velocity',[(20,0),(0,20),(0,-20)])
def test_platform_actual_carry_and_no_double_motion(velocity):
    p=Project();a,s=body(p);a.gravity=[0,100]
    b,t=body(p,'platform_body',y=10,w=100,h=10);w=PhysicsWorld(p)
    for _ in range(10):w.dynamics.action('platform_move',b.id,velocity);w.update(.02)
    assert (a.transform.x,a.transform.y)==pytest.approx((velocity[0]*.2,velocity[1]*.2),abs=.001)
    assert (b.transform.x,b.transform.y)==pytest.approx((velocity[0]*.2,10+velocity[1]*.2),abs=.001)
    assert w.dynamics.read('grounded',a.id)


def test_platform_walk_jump_no_velocity_inheritance():
    p=Project();a,s=body(p);a.gravity=[0,100];b,t=body(p,'platform_body',y=10,w=100,h=10);w=PhysicsWorld(p)
    w.dynamics.action('platform_move',b.id,[20,0]);w.command(a.id,[10,0]);w.update(.1)
    assert a.transform.x==pytest.approx(3,abs=.001)
    w.dynamics.action('jump',a.id,50);w.dynamics.action('platform_move',b.id,[20,0]);w.update(.1)
    assert a.transform.x==pytest.approx(3,abs=.001);assert w.dynamics.read('get_velocity',a.id)[0]==0


def test_platform_ceiling_constrains_actual_movement():
    p=Project();a,s=body(p);a.gravity=[0,100];b,t=body(p,'platform_body',y=10,w=100,h=10)
    ceiling,c=body(p,'static_body',y=-20,w=100,h=10);w=PhysicsWorld(p)
    w.dynamics.action('platform_move',b.id,[0,-100]);w.update(.1)
    assert a.transform.y==pytest.approx(-10,abs=.001);assert b.transform.y==pytest.approx(0,abs=.001)
    w.dynamics.action('platform_move',b.id,[0,-100]);w.update(.1)
    assert a.transform.y>=-10.00001;assert b.transform.y>=-.00001


@pytest.mark.parametrize('attr,value',[('mass',0),('mass',-1),('mass',float('nan')),('gravity',[0,float('inf')]),('velocity',[10001,0]),('up',[0,0]),('friction',-1),('restitution',2),('angular_velocity',float('nan'))])
def test_invalid_authoring_diagnostics(attr,value):
    p=Project();a,s=body(p,'dynamic_body');setattr(a,attr,value)
    with pytest.raises((ValueError,PhysicsError)):PhysicsWorld(p)


@pytest.mark.parametrize('kind,body_kind',[('get_angular','controlled_body'),('jump','dynamic_body'),('platform_move','static_body'),('impulse','controlled_body')])
def test_wrong_body_type_is_not_noop(kind,body_kind):
    p=Project();a,s=body(p,body_kind);w=PhysicsWorld(p)
    with pytest.raises(PhysicsError):
        if kind.startswith('get'):w.dynamics.read(kind,a.id)
        else:w.dynamics.action(kind,a.id,30 if kind=='jump' else [1,0])


def test_new_settings_roundtrip_and_history(tmp_path):
    p=Project();a,s=body(p,'dynamic_body');a.gravity=[2,3];a.mass=7;a.angular_velocity=12
    before=p.clone();h=History();a.friction=.8
    h.record(before,p,'Материал')
    assert h.undo().nodes[a.id].friction==.5
    assert h.redo().nodes[a.id].friction==.8
    save_project(p,tmp_path);loaded=load_project(tmp_path)
    if isinstance(loaded,tuple):loaded=loaded[0]
    assert loaded.nodes[a.id].mass==7;assert loaded.nodes[a.id].gravity==[2,3]


def action_graph(p,a,kind,value_kind='vector',**params):
    g=Graph();p.graphs[g.id]=g;a.graph=g.id
    start=g.add('start');act=g.add(kind);v=g.add(value_kind,**params)
    link(g,start,'next',act,'in');link(g,start,'object',act,'object');link(g,v,'value',act,'value')
    return g,start,act


def test_runtime_set_gravity_snapshot_and_restart_cleanup():
    p=Project();a,s=body(p,'dynamic_body');g,start,act=action_graph(p,a,'set_gravity',x=0,y=100)
    assert not validate_project(p)
    c=Clock();r=Runtime(p,clock=c);r.start();c.advance(.1);r.update()
    assert r.project.nodes[a.id].transform.y>0;assert a.transform.y==0;assert a.gravity==[0,0]
    r.stop();assert not r.physics.dynamics.states;assert not r.contact_queue
    r2=Runtime(p,clock=Clock());assert r2.project.nodes[a.id].transform.y==0


def test_runtime_error_points_to_action_and_does_not_crash_editor():
    p=Project();a,s=body(p);g,start,act=action_graph(p,a,'impulse',x=1,y=0)
    r=Runtime(p,clock=Clock())
    with pytest.raises(GraphError) as exc:r.start()
    assert exc.value.diagnostic.node_id==act.id;assert not r.running


def test_basic_graph_equals_ready_jump():
    def make(basic):
        p=Project();a,s=body(p);a.gravity=[0,100];b,t=body(p,'static_body',y=10,w=100,h=10)
        g=Graph();p.graphs[g.id]=g;a.graph=g.id;key=g.add('key',key='Space');speed=g.add('number',value=50)
        if not basic:
            jump=g.add('jump');link(g,key,'next',jump,'in');link(g,key,'object',jump,'object');link(g,speed,'value',jump,'value')
        else:
            ground=g.add('grounded');branch=g.add('if');up=g.add('get_up');vel=g.add('get_velocity');dp=g.add('dot');component=g.add('vector_scale');tangent=g.add('vector_sub');along=g.add('vector_scale');result=g.add('vector_add');setter=g.add('set_velocity')
            for n in (ground,up,vel,setter):link(g,key,'object',n,'object')
            link(g,key,'next',branch,'in');link(g,ground,'value',branch,'condition');link(g,branch,'yes',setter,'in')
            link(g,vel,'value',dp,'a');link(g,up,'value',dp,'b');link(g,up,'value',component,'vector');link(g,dp,'value',component,'factor')
            link(g,vel,'value',tangent,'a');link(g,component,'value',tangent,'b');link(g,up,'value',along,'vector');link(g,speed,'value',along,'factor')
            link(g,tangent,'value',result,'a');link(g,along,'value',result,'b');link(g,result,'value',setter,'value')
        assert not validate_project(p)
        r=Runtime(p,clock=Clock());r.key_press('Space');return r,a.id
    a,ai=make(False);b,bi=make(True)
    assert a.physics.dynamics.read('get_velocity',ai)==b.physics.dynamics.read('get_velocity',bi)==[0,-50]
    assert not a.physics.dynamics.read('grounded',ai);assert not b.physics.dynamics.read('grounded',bi)


def test_dynamic_dynamic_elastic_equal_masses():
    p=Project();a,s=body(p,'dynamic_body',x=-20,shape='circle_shape');b,t=body(p,'dynamic_body',x=20,shape='circle_shape')
    a.velocity=[50,0];b.velocity=[-50,0];a.restitution=b.restitution=1;a.friction=b.friction=0
    w=PhysicsWorld(p);run(w,.5)
    assert w.dynamics.read('get_velocity',a.id)==pytest.approx([-50,0],abs=.01)
    assert w.dynamics.read('get_velocity',b.id)==pytest.approx([50,0],abs=.01)


@pytest.mark.parametrize('shape',['concave','compound'])
def test_concave_and_compound_rest_one_body(shape):
    p=Project();a,s=body(p,'dynamic_body',shape='polygon_shape',points=[[-10,-10],[10,-10],[10,0],[0,0],[0,10],[-10,10]])
    if shape=='compound':
        s.kind='rect_shape';s.width=10;s.height=20;s.transform.x=-5
        t=SceneNode(kind='rect_shape',parent=a.id,width=10,height=10,transform=Transform(x=5,y=-5));p.nodes[t.id]=t
    a.gravity=[0,100];b,t=body(p,'static_body',y=40,w=500,h=10)
    w=PhysicsWorld(p);run(w,2)
    assert a.transform.y<36
    assert length(w.dynamics.states[a.id].velocity)<1
    assert len([n for n in p.nodes.values() if n.kind=='dynamic_body'])==1


def test_box_stack_rest_and_contact_pairs():
    p=Project();floor,t=body(p,'static_body',y=30,w=500,h=10);boxes=[]
    for y in (20,10,0):
        a,s=body(p,'dynamic_body',y=y);a.gravity=[0,100];boxes.append(a)
    w=PhysicsWorld(p);events=[]
    for _ in range(100):events.extend(w.update(.02))
    assert len(w.contacts)==3
    for a in boxes:
        assert length(w.dynamics.states[a.id].velocity)<.1
    assert all(pair[0]<pair[1] for kind,pair in events)


def test_dynamic_one_way_lands_and_passes_back():
    p=Project();a,s=body(p,'dynamic_body',y=20,shape='circle_shape');a.gravity=[0,100];a.velocity=[0,-100]
    b,t=body(p,'static_body',w=100,h=4);t.one_way=True
    w=PhysicsWorld(p);run(w,2);assert a.transform.y==pytest.approx(-7,abs=.002)


def test_platform_does_not_glue_dynamic_objects():
    p=Project();a,s=body(p,'dynamic_body');a.gravity=[0,100];a.friction=0
    b,t=body(p,'platform_body',y=10,w=100,h=10);b.friction=0;w=PhysicsWorld(p)
    for _ in range(10):w.dynamics.action('platform_move',b.id,[20,0]);w.update(.02)
    assert abs(a.transform.x)<.001;assert b.transform.x==pytest.approx(4,abs=.001)


def test_stable_multiple_support_tiebreaker():
    p=Project();a,s=body(p,w=20,h=10)
    b,t=body(p,'platform_body',x=-10,y=10,w=20,h=10);c,u=body(p,'platform_body',x=10,y=10,w=20,h=10)
    w=PhysicsWorld(p);assert w.dynamics.support[a.id][1]==min(b.id,c.id)


def test_stop_clears_pending_platform_and_support():
    p,a,b,w=floor_character();w.dynamics.action('jump',a.id,20);w.stop()
    assert not w.dynamics.support and not w.dynamics.states and not w.commands


@pytest.mark.parametrize('shape',['rect_shape','circle_shape'])
def test_large_coordinates_with_minimum_shapes(shape):
    p=Project();a,s=body(p,'dynamic_body',x=900000,y=900000,w=.5,h=.5,shape=shape,r=.25);a.velocity=[100,0]
    w=PhysicsWorld(p);w.update(.1)
    assert a.transform.x==pytest.approx(900010,abs=1e-5)


def test_platform_lifts_dynamic_by_contact_not_glue():
    p=Project();a,s=body(p,'dynamic_body');a.gravity=[0,100]
    b,t=body(p,'platform_body',y=10,w=100,h=10);w=PhysicsWorld(p)
    for _ in range(10):w.dynamics.action('platform_move',b.id,[0,-10]);w.update(.02)
    assert b.transform.y==pytest.approx(8,abs=.001)
    assert a.transform.y==pytest.approx(-2,abs=.001)
    assert w.dynamics.states[a.id].velocity[1]==pytest.approx(-10,abs=.01)
    assert a.id not in w.dynamics.support


def test_concave_seam_sliding_has_no_internal_wall_or_spin():
    p=Project();a,s=body(p,'dynamic_body',x=0,y=-5,shape='circle_shape');a.gravity=[0,100];a.velocity=[20,0];a.friction=0
    b,t=body(p,'static_body',shape='polygon_shape',points=[[-50,0],[100,0],[100,20],[80,20],[80,10],[-50,10]])
    b.friction=0;w=PhysicsWorld(p);run(w,2)
    assert a.transform.x==pytest.approx(40,abs=.01)
    assert abs(w.dynamics.states[a.id].omega)<1e-6


def test_no_floor_from_ceiling_and_air_refusal_does_not_modify_velocity():
    p=Project();a,s=body(p);a.gravity=[0,100];b,t=body(p,'static_body',y=-10,w=100,h=10);w=PhysicsWorld(p)
    assert not w.dynamics.read('grounded',a.id)
    assert not w.dynamics.action('jump',a.id,50)
    assert w.dynamics.read('get_velocity',a.id)==[0,0]


def test_angular_read_write_and_zero_gravity_no_drift():
    p=Project();a,s=body(p,'dynamic_body');w=PhysicsWorld(p);d=w.dynamics
    d.action('set_angular',a.id,60);assert d.read('get_angular',a.id)==pytest.approx(60)
    run(w,.5);assert a.transform.rotation==pytest.approx(30)
    assert d.read('get_velocity',a.id)==[0,0]
    assert (a.transform.x,a.transform.y)==pytest.approx((0,0))


def test_two_commands_last_wins_for_platform():
    p=Project();a,s=body(p,'platform_body');w=PhysicsWorld(p);d=w.dynamics
    d.action('platform_move',a.id,[10,0]);d.action('platform_move',a.id,[20,0]);w.update(.1)
    assert a.transform.x==pytest.approx(2);w.update(.1);assert a.transform.x==pytest.approx(2)


def test_unsupported_one_way_shape_and_owner_rejected():
    p=Project();a,s=body(p,'dynamic_body');s.one_way=True
    with pytest.raises(PhysicsError):PhysicsWorld(p)
    p=Project();a,s=body(p,'static_body',shape='polygon_shape');s.one_way=True
    with pytest.raises((PhysicsError,ValueError)):PhysicsWorld(p)


def test_character_does_not_drag_dynamic_through_friction():
    p=Project();a,s=body(p,w=100,h=10);b,t=body(p,'dynamic_body',y=-10);b.gravity=[0,100]
    a.friction=b.friction=1;w=PhysicsWorld(p)
    for _ in range(10):w.command(a.id,[10,0]);w.update(.02)
    assert a.transform.x==pytest.approx(2,abs=.001)
    assert abs(b.transform.x)<.001
    assert abs(w.dynamics.states[b.id].velocity[0])<.001


def test_impulse_uses_world_com_after_immediate_teleport():
    p=Project();a,s=body(p,'dynamic_body');w=PhysicsWorld(p)
    a.transform.x=100
    w.dynamics.action('impulse',a.id,[0,10],[100,0])
    assert w.dynamics.states[a.id].omega==pytest.approx(0,abs=1e-10)
    assert w.dynamics.read('get_velocity',a.id)==[0,10]


def test_teleport_invalidates_support_including_parent_and_passenger():
    p,a,b,w=floor_character();assert w.dynamics.read('grounded',a.id)
    a.transform.x=100;w.dynamics.teleported(a.id)
    assert not w.dynamics.action('jump',a.id,50)
    parent=SceneNode();p.nodes[parent.id]=parent;a.parent=parent.id
    a.transform.x=0;w.dynamics.refresh_support(world_shapes(p));assert w.dynamics.read('grounded',a.id)
    w.dynamics.teleported(parent.id);assert not w.dynamics.read('grounded',a.id)
    w.dynamics.refresh_support(world_shapes(p));w.dynamics.teleported(b.id)
    assert not w.dynamics.read('grounded',a.id)
