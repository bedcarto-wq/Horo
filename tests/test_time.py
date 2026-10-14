"""Real graph integration tests with a deterministic clock, never sleep()."""
import copy
import pytest
from horo.model import Project, SceneNode, Graph, Variable, Parameter, Edge, uid
from horo.examples import link, basic, counter, function_loop
from horo.runtime import Runtime
from horo.validation import validate_project, connect
from horo.errors import GraphError
from horo.history import History
from horo.storage import save_project, load_project

class Clock:
    def __init__(self): self.value = 0
    def __call__(self): return self.value
    def advance(self, amount): self.value += amount


def base(start='key'):
    p = Project(); obj = SceneNode(); p.nodes[obj.id] = obj
    g = Graph(); p.graphs[g.id] = g; obj.graph = g.id
    key = g.add(start)
    return p, g, key, obj


def move(g, source, amount=1, region=None):
    vec = g.add('vector', region=region, x=amount, y=0)
    node = g.add('move', region=region)
    link(g, vec, 'value', node, 'delta'); link(g, source, 'object', node, 'object')
    return node


def write(p, g, var, value, region=None):
    value_node = g.add('bool' if var.type == 'bool' else 'number', region=region, value=value)
    node = g.add('write', region=region, variable=var.id)
    link(g, value_node, 'value', node, 'value')
    return node


def attach(g, a, b, output='next'):
    link(g, a, output, b, 'in')


def valid_runtime(p, **kwargs):
    assert not validate_project(p), [d.message for d in validate_project(p)]
    return Runtime(p, **kwargs)


def clean(r):
    assert not r.tasks and not r.scopes and not r.ready and not r.sleepers


def test_start_once_per_instance_and_new_session():
    p,g,key,obj = base('start'); action = move(g, key, 3); attach(g,key,action)
    other=copy.deepcopy(obj);other.id=uid();p.nodes[other.id]=other
    for _ in range(2):
        r=valid_runtime(p, clock=Clock());r.start();r.start();r.update()
        assert all(o.transform.x==3 for o in r.project.nodes.values())
        clean(r)
    assert obj.transform.x==0


def test_start_variables_available_and_frame_event_data():
    p,g,key,obj=base('start'); v=Variable(scope='game',value=4);p.variables[v.id]=v
    read=g.add('read',variable=v.id); one=g.add('number',value=1);add=g.add('add');put=g.add('write',variable=v.id)
    link(g,read,'value',add,'a');link(g,one,'value',add,'b');link(g,add,'value',put,'value');attach(g,key,put)
    frame=g.add('frame');delta=Variable(scope='run',owner=g.id,value=0);p.variables[delta.id]=delta
    put_delta=g.add('write',variable=delta.id);link(g,frame,'delta',put_delta,'value');attach(g,frame,put_delta)
    out=Variable(scope='game',value=0);p.variables[out.id]=out
    put_time=g.add('write',variable=out.id);link(g,frame,'time',put_time,'value');attach(g,put_delta,put_time)
    c=Clock();r=valid_runtime(p,clock=c);r.start();assert r.game[v.id]==5
    c.advance(.25);r.update();assert r.game[out.id]==.25
    assert delta.value==0


def test_multiple_starts_release_and_repeated_events_are_independent():
    p,g,key,obj=base();release=g.add('key_release');second=g.add('key')
    for start,dx in [(key,1),(second,2),(release,4)]:attach(g,start,move(g,start,dx))
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.project.nodes[obj.id].transform.x==3
    r.key_release('Space',auto_repeat=True);assert r.project.nodes[obj.id].transform.x==3
    r.key_release('Space');assert r.project.nodes[obj.id].transform.x==7
    r.key_press('Space');assert r.project.nodes[obj.id].transform.x==10


def test_different_start_event_data_never_mix():
    p,g,key,obj=base();second=g.add('key',key='A');action=move(g,key,1);attach(g,second,action)
    r=valid_runtime(p,clock=Clock())
    with pytest.raises(GraphError,match='другого старта'):r.key_press('A')
    clean(r)


def test_wait_does_not_block_other_branch_or_spend_sleeping_budget():
    p,g,key,obj=base();fork=g.add('fork');attach(g,key,fork)
    wait=g.add('wait',n=1);late=move(g,key,10);now=move(g,key,1)
    attach(g,fork,wait,fork.outputs[0]);attach(g,wait,late);attach(g,fork,now,fork.outputs[1])
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');assert r.project.nodes[obj.id].transform.x==1
    c.advance(.999);r.update();assert r.project.nodes[obj.id].transform.x==1 and r.steps==0
    c.advance(.001);r.update();assert r.project.nodes[obj.id].transform.x==11;clean(r)
    r.update();assert r.project.nodes[obj.id].transform.x==11


def test_zero_wait_yields_update_and_repeated_event_gets_new_launch():
    p,g,key,obj=base();wait=g.add('wait',n=0);attach(g,key,wait);attach(g,wait,move(g,key,1))
    r=valid_runtime(p,clock=Clock());r.key_press('Space');r.key_press('Space')
    assert r.project.nodes[obj.id].transform.x==0 and len(r.sleepers)==2
    r.update();assert r.project.nodes[obj.id].transform.x==2;clean(r)

@pytest.mark.parametrize('n', [-1, float('inf'), float('nan'), 'bad'])
def test_invalid_wait_value_is_error(n):
    p,g,key,obj=base();wait=g.add('wait',n=n);attach(g,key,wait)
    if isinstance(n,(int,float)) and n==-1:
        r=valid_runtime(p,clock=Clock())
        with pytest.raises(GraphError,match='отрицательным'):r.key_press('Space')
        clean(r)
    else:
        assert validate_project(p)


def test_cancellation_stop_and_restart_remove_waiting_work():
    p,g,key,obj=base();wait=g.add('wait',n=1);attach(g,key,wait);attach(g,wait,move(g,key,1))
    c=Clock();r=valid_runtime(p,clock=c);frame=r.frame(r.project.graphs[g.id],obj.id)
    handle=r.execute(frame,r.project.graphs[g.id].nodes[wait.id]);assert r.sleepers
    r.cancel(handle);r.cancel(handle);clean(r)
    c.advance(2);r.update();assert r.project.nodes[obj.id].transform.x==0
    r.key_press('Space');assert r.sleepers;r.stop();r.stop();clean(r)
    c.advance(2);r.update();assert r.project.nodes[obj.id].transform.x==0
    fresh=valid_runtime(p,clock=c);fresh.update();assert fresh.project.nodes[obj.id].transform.x==0


def test_sequence_waits_all_descendants_before_second_output():
    p,g,key,obj=base();seq=g.add('sequence');fork=g.add('fork');attach(g,key,seq);attach(g,seq,fork,seq.outputs[0])
    wait=g.add('wait',n=1);attach(g,fork,wait,fork.outputs[0]);attach(g,wait,move(g,key,10))
    attach(g,fork,move(g,key,1),fork.outputs[1]);attach(g,seq,move(g,key,100),seq.outputs[1])
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');assert r.project.nodes[obj.id].transform.x==1
    c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==111;clean(r)


def test_empty_outputs_are_completed_and_sequence_has_explicit_order():
    p,g,key,obj=base();seq=g.add('sequence');seq.outputs.append(uid());attach(g,key,seq)
    attach(g,seq,move(g,key,3),seq.outputs[2]);r=valid_runtime(p,clock=Clock());r.key_press('Space')
    assert r.project.nodes[obj.id].transform.x==3;clean(r)


def test_repeat_waits_all_fork_branches_before_next_iteration():
    p,g,key,obj=base();loop=g.add('repeat');count=g.add('number',value=2);link(g,count,'value',loop,'n');attach(g,key,loop)
    fork=g.add('fork',region=loop.id);attach(g,loop,fork,'body')
    wait=g.add('wait',region=loop.id,n=1);attach(g,fork,wait,fork.outputs[0]);attach(g,wait,move(g,key,10,loop.id))
    attach(g,fork,move(g,key,1,loop.id),fork.outputs[1])
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');assert r.project.nodes[obj.id].transform.x==1
    c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==12
    c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==22;clean(r)


def test_port_ids_order_roundtrip_and_undo_delete(tmp_path):
    p,g,key,obj=base();fork=g.add('fork');fork.outputs.append(uid());attach(g,key,fork)
    v=Variable(scope='game');p.variables[v.id]=v
    attach(g,fork,write(p,g,v,1),fork.outputs[0]);attach(g,fork,write(p,g,v,2),fork.outputs[1])
    ids=fork.outputs[:];links=copy.deepcopy(g.edges)
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.game[v.id]==2
    g.edit_output(fork.id,'up',ids[1]);assert fork.outputs==[ids[1],ids[0],ids[2]] and g.edges==links
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.game[v.id]==1
    save_project(p,tmp_path);q=load_project(tmp_path);assert q.graphs[g.id].nodes[fork.id].outputs==fork.outputs
    h=History();before=p.clone();g.edit_output(fork.id,'remove',ids[0]);h.record(before,p,'remove output')
    restored=h.undo();assert restored.to_dict()==before.to_dict()
    assert h.redo().graphs[g.id].nodes[fork.id].outputs==fork.outputs
    with pytest.raises(ValueError,match='минимум'):g.edit_output(fork.id,'remove',ids[1])


def condition_loop(initial=3, delay=0):
    p,g,key,obj=base();v=Variable(scope='game',value=initial);p.variables[v.id]=v
    loop=g.add('while');read=g.add('read',variable=v.id);zero=g.add('number',value=0);greater=g.add('greater')
    link(g,read,'value',greater,'a');link(g,zero,'value',greater,'b');link(g,greater,'value',loop,'condition');attach(g,key,loop)
    minus=g.add('number',value=-1);add=g.add('add',region=loop.id);put=g.add('write',region=loop.id,variable=v.id)
    link(g,read,'value',add,'a');link(g,minus,'value',add,'b');link(g,add,'value',put,'value');attach(g,loop,put,'body')
    wait=g.add('wait',region=loop.id,n=delay);attach(g,put,wait)
    return p,g,key,obj,v,loop,put,wait


def test_while_false_zero_iterations_and_current_condition_each_iteration():
    p,g,key,obj,v,loop,put,wait=condition_loop(0);r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.game[v.id]==0;clean(r)
    p,g,key,obj,v,loop,put,wait=condition_loop(3)
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.game[v.id]==2
    r.update();assert r.game[v.id]==1;r.update();assert r.game[v.id]==0;r.update();clean(r)


def test_nested_repeat_uses_existing_regions_and_break_nearest_loop():
    p,g,key,obj=base();outer=g.add('repeat');inner=g.add('repeat',region=outer.id)
    two=g.add('number',value=2);three=g.add('number',value=3);link(g,two,'value',outer,'n');link(g,three,'value',inner,'n')
    attach(g,key,outer);attach(g,outer,inner,'body');action=move(g,key,1,inner.id);attach(g,inner,action,'body')
    done=move(g,key,10,outer.id);attach(g,inner,done)
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.project.nodes[obj.id].transform.x==26;clean(r)
    br=g.add('break',region=inner.id);attach(g,action,br)
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.project.nodes[obj.id].transform.x==22;clean(r)

@pytest.mark.parametrize('control,remaining', [('continue',0),('break',1)])
def test_loop_control_cancels_other_iteration_waits(control,remaining):
    p,g,key,obj,v,loop,put,wait=condition_loop(2,5)
    # Replace body with fork; one branch updates then controls, the other waits then moves.
    g.edges[:]=[e for e in g.edges if not (e.source==loop.id and e.output=='body') and not (e.source==put.id and e.output=='next')]
    fork=g.add('fork',region=loop.id);attach(g,loop,fork,'body');attach(g,fork,put,fork.outputs[0])
    ctrl=g.add(control,region=loop.id);attach(g,put,ctrl)
    attach(g,fork,wait,fork.outputs[1]);attach(g,wait,move(g,key,100,loop.id))
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');assert r.game[v.id]==remaining;clean(r)
    c.advance(100);r.update();assert r.project.nodes[obj.id].transform.x==0


def function_chain(p, wait=1):
    b=Graph(name='Б',kind='function');p.graphs[b.id]=b
    bp=Parameter(name='Данные',type='vector');br=Parameter(name='Результат',type='vector');b.parameters=[bp];b.results=[br]
    entry=b.add('entry');pause=b.add('wait',n=wait);ret=b.add('return')
    attach(b,entry,pause);attach(b,pause,ret);link(b,entry,bp.id,ret,br.id)
    a=Graph(name='А',kind='function');p.graphs[a.id]=a
    ap=Parameter(name='Данные',type='vector');ar=Parameter(name='Результат',type='vector');a.parameters=[ap];a.results=[ar]
    ae=a.add('entry');call=a.add('call',function=b.id);aret=a.add('return')
    attach(a,ae,call);attach(a,call,aret);link(a,ae,ap.id,call,'arg:'+bp.id);link(a,call,'result:'+br.id,aret,ar.id)
    return a,ap,ar,b


def call_move(p,g,key,fn,param,result,vector=None):
    call=g.add('call',function=fn.id);attach(g,key,call)
    if vector is None:vector=g.add('vector',x=10,y=0)
    link(g,vector,'value',call,'arg:'+param.id)
    action=g.add('move');attach(g,call,action);link(g,key,'object',action,'object');link(g,call,'result:'+result.id,action,'delta')
    return call


def test_nested_function_waits_caller_not_other_chain():
    p,g,key,obj=base();a,ap,ar,b=function_chain(p)
    call_move(p,g,key,a,ap,ar)
    second=g.add('key');attach(g,second,move(g,second,1))
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');assert r.project.nodes[obj.id].transform.x==1
    c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==11;clean(r)


def test_two_calls_same_function_isolate_parameters_temporaries_results():
    p,g,key,obj=base();a,ap,ar,b=function_chain(p)
    v=Variable(type='vector',value=[1,0],scope='object');p.variables[v.id]=v
    read=g.add('read',variable=v.id);call_move(p,g,key,a,ap,ar,read)
    temp=Variable(scope='run',owner=b.id,value=0);p.variables[temp.id]=temp
    other=copy.deepcopy(obj);other.id=uid();p.nodes[other.id]=other
    c=Clock();r=valid_runtime(p,clock=c);r.objects[other.id][v.id]=[2,0];r.key_press('Space')
    active=[s for s in r.scopes.values() if s.kind=='call' and s.frame.graph.id==b.id]
    assert len(active)==2 and active[0].frame.temporary is not active[1].frame.temporary
    active[0].frame.temporary[temp.id]=7;assert active[1].frame.temporary[temp.id]==0
    c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==1 and r.project.nodes[other.id].transform.x==2;clean(r)


def returning_fork(p, missing=False):
    fn=Graph(kind='function');p.graphs[fn.id]=fn
    result=Parameter(type='number');fn.results=[result]
    entry=fn.add('entry');fork=fn.add('fork');attach(fn,entry,fork)
    # first branch empty, second waits then returns (or ends without a return)
    wait=fn.add('wait',n=1);attach(fn,fork,wait,fork.outputs[1])
    if not missing:
        ret=fn.add('return');num=fn.add('number',value=5);attach(fn,wait,ret);link(fn,num,'value',ret,result.id)
    return fn,result


def test_missing_return_checked_only_after_all_call_branches_finish():
    p,g,key,obj=base();fn,result=returning_fork(p,True);call=g.add('call',function=fn.id);attach(g,key,call)
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');assert r.running and r.sleepers
    c.advance(1)
    with pytest.raises(GraphError,match='без возврата') as exc:r.update()
    assert exc.value.diagnostic.graph_id==fn.id;clean(r)
    p,g,key,obj=base();fn,result=returning_fork(p);call=g.add('call',function=fn.id);attach(g,key,call)
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');c.advance(1);r.update();clean(r)


def test_first_return_wins_without_rolling_back_world_changes():
    p,g,key,obj=base();fn=Graph(kind='function');p.graphs[fn.id]=fn;result=Parameter(type='number');fn.results=[result]
    v=Variable(scope='game',value=0);p.variables[v.id]=v
    entry=fn.add('entry');fork=fn.add('fork');attach(fn,entry,fork)
    w=write(p,fn,v,7);attach(fn,fork,w,fork.outputs[0])
    for value, predecessor, output in [(1,w,'next'),(2,fork,fork.outputs[1])]:
        ret=fn.add('return');num=fn.add('number',value=value);attach(fn,predecessor,ret,output);link(fn,num,'value',ret,result.id)
    call=g.add('call',function=fn.id);attach(g,key,call);put=g.add('write',variable=v.id);attach(g,call,put);link(g,call,'result:'+result.id,put,'value')
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.game[v.id]==2;clean(r)
    # Without the caller's subsequent write, the already-completed world write remains 7.
    g.remove(put.id);r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.game[v.id]==7;clean(r)


def test_return_cancels_only_its_call_and_delayed_branches():
    p,g,key,obj=base();fn=Graph(kind='function');p.graphs[fn.id]=fn
    result=Parameter(type='vector');fn.results=[result]
    entry=fn.add('entry');fork=fn.add('fork');attach(fn,entry,fork)
    short=fn.add('wait',n=1);long=fn.add('wait',n=10)
    attach(fn,fork,short,fork.outputs[0]);attach(fn,fork,long,fork.outputs[1])
    for wait in (short,long):
        ret=fn.add('return');vec=fn.add('vector',x=1,y=0);attach(fn,wait,ret);link(fn,vec,'value',ret,result.id)
    call=g.add('call',function=fn.id);attach(g,key,call);action=g.add('move');attach(g,call,action)
    link(g,key,'object',action,'object');link(g,call,'result:'+result.id,action,'delta')
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');c.advance(.5);r.key_press('Space')
    c.advance(.5);r.update();assert r.project.nodes[obj.id].transform.x==1 and len(r.sleepers)==2
    c.advance(.5);r.update();assert r.project.nodes[obj.id].transform.x==2;clean(r)
    c.advance(100);r.update();assert r.project.nodes[obj.id].transform.x==2


def test_return_inside_loop_cancels_whole_function():
    p=function_loop(return_in_function=True);g=next(g for g in p.graphs.values() if g.kind=='function')
    loop=next(n for n in g.nodes.values() if n.kind=='repeat');ret=next(n for n in g.nodes.values() if n.kind=='return')
    g.edges[:]=[e for e in g.edges if not (e.source==loop.id and e.output=='body')]
    fork=g.add('fork',region=loop.id);attach(g,loop,fork,'body');attach(g,fork,ret,fork.outputs[0])
    wait=g.add('wait',region=loop.id,n=100);attach(g,fork,wait,fork.outputs[1])
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert next(iter(r.project.nodes.values())).transform.x==125;clean(r)


def test_direct_and_indirect_recursion_rejected_with_node():
    p,g,key,obj=base();a=Graph(kind='function');b=Graph(kind='function');p.graphs[a.id]=a;p.graphs[b.id]=b
    for fn,target in [(a,b),(b,a)]:
        entry=fn.add('entry');call=fn.add('call',function=target.id);attach(fn,entry,call)
    errors=validate_project(p);assert any('рекурсия' in d.message and d.node_id for d in errors)


def test_depth_limit_is_iterative_and_reports_deep_origin():
    p,g,key,obj=base();functions=[]
    for i in range(6):
        fn=Graph(name=str(i),kind='function');p.graphs[fn.id]=fn;fn.add('entry');functions.append(fn)
    for a,b in zip(functions,functions[1:]):
        attach(a,next(iter(a.nodes.values())),a.add('call',function=b.id))
    attach(g,key,g.add('call',function=functions[0].id))
    r=valid_runtime(p,clock=Clock(),call_limit=3)
    with pytest.raises(GraphError,match='уровней') as exc:r.key_press('Space')
    assert exc.value.diagnostic.graph_id==functions[2].id;clean(r)
    r=valid_runtime(p,clock=Clock(),call_limit=6);r.key_press('Space');clean(r)


def test_frame_wait_live_task_limit_is_not_silent_event_dropping():
    p,g,key,obj=base('frame');attach(g,key,g.add('wait',n=100));r=valid_runtime(p,clock=Clock(),task_limit=3)
    for _ in range(3):r.update()
    assert len(r.tasks)==3
    with pytest.raises(GraphError,match='живых задач') as exc:r.update()
    assert exc.value.diagnostic.node_id==key.id;clean(r)


def test_empty_true_while_and_total_branch_work_stop_on_shared_budget():
    p,g,key,obj=base();loop=g.add('while');truth=g.add('bool',value=True)
    link(g,truth,'value',loop,'condition');attach(g,key,loop)
    r=valid_runtime(p,clock=Clock(),step_limit=30)
    with pytest.raises(GraphError,match='лимит'):r.key_press('Space')
    clean(r)
    p,g,key,obj=base();fork=g.add('fork',outputs=[uid() for _ in range(30)]);attach(g,key,fork)
    r=valid_runtime(p,clock=Clock(),step_limit=15)
    with pytest.raises(GraphError,match='лимит'):r.key_press('Space')
    clean(r)


def test_invalid_region_cycles_and_function_cannot_break_callers_loop():
    p,g,key,obj=base();outer=g.add('repeat');inner=g.add('repeat',region=outer.id);outer.region=inner.id
    assert any('владельцев' in d.message for d in validate_project(p))
    p,g,key,obj=base();fn=Graph(kind='function');p.graphs[fn.id]=fn;entry=fn.add('entry');br=fn.add('break');attach(fn,entry,br)
    assert any('только в теле' in d.message for d in validate_project(p))


def test_stage_one_files_remain_compatible_and_new_graph_roundtrip(tmp_path):
    for factory in (basic,counter,function_loop):
        p=factory();raw=p.to_dict()
        for graph in raw['graphs'].values():
            for node in graph['nodes'].values():node.pop('outputs')
        q=Project.from_dict(raw);r=valid_runtime(q,clock=Clock());r.key_press('Space');clean(r)
    p,g,key,obj=base();wait=g.add('wait',n=0);attach(g,key,wait);attach(g,wait,move(g,key,5))
    save_project(p,tmp_path);q=load_project(tmp_path)
    assert q.to_dict()==p.to_dict();r=valid_runtime(q,clock=Clock());r.key_press('Space');r.update();assert r.project.nodes[obj.id].transform.x==5


def test_clock_must_be_finite_and_monotonic():
    p,g,key,obj=base();c=Clock();r=valid_runtime(p,clock=c);c.advance(1);r.update();c.value=0
    with pytest.raises(GraphError,match='монотонным'):r.update()
    clean(r)


def test_branch_temporary_variables_shared_only_inside_one_launch():
    p,g,key,obj=base();v=Variable(scope='run',owner=g.id,value=0);out=Variable(scope='game',value=0)
    p.variables[v.id]=v;p.variables[out.id]=out
    fork=g.add('fork');attach(g,key,fork)
    put=g.add('write',variable=v.id);link(g,key,'time',put,'value');attach(g,fork,put,fork.outputs[0])
    wait=g.add('wait',n=1);attach(g,fork,wait,fork.outputs[1])
    read=g.add('read',variable=v.id);copy_out=g.add('write',variable=out.id);link(g,read,'value',copy_out,'value');attach(g,wait,copy_out)
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');c.advance(.5);r.key_press('Space')
    launches=[s for s in r.scopes.values() if s.kind=='run']
    assert len(launches)==2 and launches[0].frame.temporary[v.id]==0 and launches[1].frame.temporary[v.id]==.5
    c.advance(.5);r.update();assert r.game[out.id]==0
    c.advance(.5);r.update();assert r.game[out.id]==.5;clean(r)


def test_repeat_reads_count_once_despite_body_write():
    p,g,key,obj=base();v=Variable(scope='game',value=2);p.variables[v.id]=v
    read=g.add('read',variable=v.id);loop=g.add('repeat');link(g,read,'value',loop,'n');attach(g,key,loop)
    put=write(p,g,v,0,loop.id);attach(g,loop,put,'body');attach(g,put,move(g,key,1,loop.id))
    r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.project.nodes[obj.id].transform.x==2;clean(r)


def test_inner_break_does_not_cancel_outer_iteration_sibling_wait():
    p,g,key,obj=base();outer=g.add('repeat');two=g.add('number',value=2);link(g,two,'value',outer,'n');attach(g,key,outer)
    fork=g.add('fork',region=outer.id);attach(g,outer,fork,'body')
    inner=g.add('repeat',region=outer.id);link(g,two,'value',inner,'n');attach(g,fork,inner,fork.outputs[0])
    br=g.add('break',region=inner.id);attach(g,inner,br,'body')
    wait=g.add('wait',region=outer.id,n=1);attach(g,fork,wait,fork.outputs[1]);attach(g,wait,move(g,key,10,outer.id))
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');assert len(r.sleepers)==1
    c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==10 and len(r.sleepers)==1
    c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==20;clean(r)


def test_function_return_after_wait_does_not_leak_caller_loop_context():
    p,g,key,obj=base();fn=Graph(kind='function');p.graphs[fn.id]=fn;entry=fn.add('entry');pause=fn.add('wait',n=1);ret=fn.add('return')
    attach(fn,entry,pause);attach(fn,pause,ret)
    loop=g.add('repeat');count=g.add('number',value=2);link(g,count,'value',loop,'n');attach(g,key,loop)
    call=g.add('call',region=loop.id,function=fn.id);attach(g,loop,call,'body');attach(g,call,move(g,key,3,loop.id))
    c=Clock();r=valid_runtime(p,clock=c);r.key_press('Space');c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==3
    c.advance(1);r.update();assert r.project.nodes[obj.id].transform.x==6;clean(r)


def test_sixty_four_deep_calls_complete_without_python_recursive_stack():
    p,g,key,obj=base();fns=[]
    for i in range(64):
        fn=Graph(name=str(i),kind='function');p.graphs[fn.id]=fn;fn.add('entry');fns.append(fn)
    for a,b in zip(fns,fns[1:]):attach(a,next(iter(a.nodes.values())),a.add('call',function=b.id))
    attach(g,key,g.add('call',function=fns[0].id));r=valid_runtime(p,clock=Clock());r.key_press('Space');clean(r)


def test_errors_in_deep_waiting_function_keep_original_graph_node():
    p,g,key,obj=base();a,ap,ar,b=function_chain(p)
    wait=next(n for n in b.nodes.values() if n.kind=='wait');wait.params['n']=-1
    call_move(p,g,key,a,ap,ar);r=valid_runtime(p,clock=Clock())
    with pytest.raises(GraphError) as exc:r.key_press('Space')
    assert exc.value.diagnostic.graph_id==b.id and exc.value.diagnostic.node_id==wait.id and exc.value.diagnostic.object_id==obj.id
    clean(r)


def test_branch_queue_order_is_deterministic_not_uuid_order():
    for _ in range(5):
        p,g,key,obj=base();v=Variable(scope='game',value=0);p.variables[v.id]=v
        fork=g.add('fork',outputs=['z_last_in_alphabet','a_first_in_alphabet']);attach(g,key,fork)
        attach(g,fork,write(p,g,v,1),fork.outputs[0]);attach(g,fork,write(p,g,v,2),fork.outputs[1])
        r=valid_runtime(p,clock=Clock());r.key_press('Space');assert r.game[v.id]==2;clean(r)


def test_stage_two_checking_projects_load_validate_execute_and_roundtrip(tmp_path):
    from horo.time_examples import write_time_examples
    write_time_examples(tmp_path)
    files=list(tmp_path.glob('*/project.horo.json'));assert len(files)==9
    for path in files:
        original=path.read_bytes();p=load_project(path);c=Clock();r=valid_runtime(p,clock=c)
        r.start();r.key_press('Space');r.key_release('Space')
        for _ in range(5):c.advance(.5);r.update()
        r.stop();clean(r)
        assert path.read_bytes()==original
        folder=tmp_path/'roundtrip';save_project(p,folder);assert load_project(folder).to_dict()==p.to_dict()
