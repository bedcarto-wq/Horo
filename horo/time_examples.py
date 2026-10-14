"""Small stage-two projects built from ordinary editable nodes, not runtime special cases."""
from pathlib import Path
from .model import Project, Graph, SceneNode, Variable, Parameter
from .examples import link, test_xpm
from .storage import save_project


def base(name, kind='key'):
    p=Project(name=name)
    obj=SceneNode(name='Изображение',kind='sprite',image='assets/test.xpm')
    obj.transform.x=80;obj.transform.y=100;p.nodes[obj.id]=obj
    g=Graph(name=name);p.graphs[g.id]=g;obj.graph=g.id
    return p,g,g.add(kind),obj


def move(g,start,x=20,y=0,region=None):
    node=g.add('move',20,20,region=region);vec=g.add('vector',20,230,region=region,x=x,y=y)
    link(g,start,'object',node,'object');link(g,vec,'value',node,'delta')
    return node


def connect(g,a,b,output='next'):link(g,a,output,b,'in')


def parallel_sequence():
    p,g,start,obj=base('Ожидание, разветвитель и последовательность')
    seq=g.add('sequence',430,0);fork=g.add('fork',850,0);connect(g,start,seq);connect(g,seq,fork,seq.outputs[0])
    wait=g.add('wait',1270,0,n=1);connect(g,fork,wait,fork.outputs[0])
    late=move(g,start,60);late.x=1700;late.y=0;connect(g,wait,late)
    immediate=move(g,start,0,30);immediate.x=1270;immediate.y=450;connect(g,fork,immediate,fork.outputs[1])
    final=move(g,start,0,50);final.x=850;final.y=850;connect(g,seq,final,seq.outputs[1])
    # Values are separate cards and remain editable; place them near each action.
    vectors=[n for n in g.nodes.values() if n.kind=='vector']
    for vec,target in zip(vectors,[late,immediate,final]):vec.x=target.x;vec.y=target.y+230
    return p


def events():
    p,g,start,obj=base('Старт, кадр и отпускание', 'start')
    first=move(g,start,20);first.x=430;first.y=0;connect(g,start,first)
    frame=g.add('frame',0,500);action=g.add('move',430,500);vector=g.add('vector',850,500,x=0,y=0)
    # Delta seconds makes speed proportional to update time (1 unit per second).
    link(g,frame,'delta',vector,'x');link(g,vector,'value',action,'delta');link(g,frame,'object',action,'object');connect(g,frame,action)
    release=g.add('key_release',0,950,key='Space');done=move(g,release,0,20);done.x=430;done.y=950;connect(g,release,done)
    vectors=[n for n in g.nodes.values() if n.kind=='vector' and n.id!=vector.id]
    for vec,target in zip(vectors,[first,done]):vec.x=850;vec.y=target.y
    return p


def while_wait(control=None):
    p,g,start,obj=base('Пока с ожиданием' if control is None else 'Отмена итерации: '+control)
    count=Variable(name='Осталось',value=3,scope='object');p.variables[count.id]=count
    read=g.add('read',0,300,variable=count.id);zero=g.add('number',0,650,value=0);greater=g.add('greater',430,300)
    link(g,read,'value',greater,'a');link(g,zero,'value',greater,'b')
    loop=g.add('while',850,0);connect(g,start,loop);link(g,greater,'value',loop,'condition')
    minus=g.add('number',400,400,region=loop.id,value=-1);add=g.add('add',800,400,region=loop.id)
    put=g.add('write',20,20,region=loop.id,variable=count.id)
    link(g,read,'value',add,'a');link(g,minus,'value',add,'b');link(g,add,'value',put,'value')
    wait=g.add('wait',400,20,region=loop.id,n=.5)
    action=move(g,start,20,region=loop.id);action.x=800;action.y=20
    if control:
        fork=g.add('fork',20,20,region=loop.id);put.x=430;put.y=20;wait.x=430;wait.y=600
        connect(g,loop,fork,'body');connect(g,fork,put,fork.outputs[0]);connect(g,fork,wait,fork.outputs[1]);connect(g,wait,action)
        ctrl=g.add(control,850,20,region=loop.id);connect(g,put,ctrl)
        wait.params['n']=2
        action.x=850;action.y=600
    else:
        connect(g,loop,put,'body');connect(g,put,wait);connect(g,wait,action)
    return p


def nested_functions():
    p,g,start,obj=base('Вложенные функции и ожидание')
    functions=[]
    for name in ['А','Б']:
        fn=Graph(name='Функция '+name,kind='function')
        param=Parameter(name='Вектор',type='vector');result=Parameter(name='Смещение',type='vector')
        number=Parameter(name='Число',type='number');number_result=Parameter(name='Число обратно',type='number')
        fn.parameters=[param,number];fn.results=[result,number_result]
        fn.add('entry',0,0);p.graphs[fn.id]=fn;functions.append(fn)
    a,b=functions;be=next(iter(b.nodes.values()));wait=b.add('wait',430,0,n=1);ret=b.add('return',850,0)
    connect(b,be,wait);connect(b,wait,ret)
    for param,result in zip(b.parameters,b.results):link(b,be,param.id,ret,result.id)
    ae=next(iter(a.nodes.values()));call=a.add('call',430,0,function=b.id);aret=a.add('return',850,0)
    connect(a,ae,call);connect(a,call,aret)
    for ap,bp,ar,br in zip(a.parameters,b.parameters,a.results,b.results):
        link(a,ae,ap.id,call,'arg:'+bp.id);link(a,call,'result:'+br.id,aret,ar.id)
    outer=g.add('call',430,0,function=a.id);vec=g.add('vector',0,350,x=60,y=0);num=g.add('number',0,600,value=2)
    connect(g,start,outer);link(g,vec,'value',outer,'arg:'+a.parameters[0].id);link(g,num,'value',outer,'arg:'+a.parameters[1].id)
    loop=g.add('repeat',850,0);connect(g,outer,loop);link(g,outer,'result:'+a.results[1].id,loop,'n')
    action=g.add('move',20,20,region=loop.id);connect(g,loop,action,'body');link(g,start,'object',action,'object');link(g,outer,'result:'+a.results[0].id,action,'delta')
    second=g.add('key',0,900,key='A');now=move(g,second,0,20);now.x=430;now.y=900;connect(g,second,now)
    return p


def nested_loops():
    p,g,start,obj=base('Вложенные циклы')
    outer=g.add('repeat',430,0);two=g.add('number',0,350,value=2);connect(g,start,outer);link(g,two,'value',outer,'n')
    inner=g.add('repeat',20,20,region=outer.id);three=g.add('number',20,350,region=outer.id,value=3)
    connect(g,outer,inner,'body');link(g,three,'value',inner,'n')
    wait=g.add('wait',20,20,region=inner.id,n=.2);action=move(g,start,10,region=inner.id);action.x=430;action.y=20
    connect(g,inner,wait,'body');connect(g,wait,action)
    return p


def function_return():
    p,g,start,obj=base('Возврат отменяет ожидающую ветку')
    fn=Graph(name='Первый возврат',kind='function');result=Parameter(name='Смещение',type='vector');fn.results=[result];p.graphs[fn.id]=fn
    entry=fn.add('entry',0,0);fork=fn.add('fork',430,0);connect(fn,entry,fork)
    for index,duration in enumerate([.5,3]):
        wait=fn.add('wait',850,index*450,n=duration);ret=fn.add('return',1270,index*450);vec=fn.add('vector',850,index*450+230,x=20 if index==0 else 200,y=0)
        connect(fn,fork,wait,fork.outputs[index]);connect(fn,wait,ret);link(fn,vec,'value',ret,result.id)
    call=g.add('call',430,0,function=fn.id);action=g.add('move',850,0);connect(g,start,call);connect(g,call,action)
    link(g,start,'object',action,'object');link(g,call,'result:'+result.id,action,'delta')
    return p


def frame_limit():
    p,g,start,obj=base('Проверка лимита живых задач', 'frame')
    wait=g.add('wait',430,0,n=1000);connect(g,start,wait)
    return p


def write_time_examples(root):
    cases={'time_parallel_sequence':parallel_sequence(),'time_events':events(),
           'time_while':while_wait(),'time_break':while_wait('break'),
           'time_continue':while_wait('continue'),'time_nested_functions':nested_functions(),
           'time_nested_loops':nested_loops(),'time_function_return':function_return(),
           'time_task_limit':frame_limit()}
    for name,p in cases.items():
        folder=Path(root)/name;(folder/'assets').mkdir(parents=True,exist_ok=True)
        (folder/'assets/test.xpm').write_text(test_xpm(),encoding='ascii');save_project(p,folder)
