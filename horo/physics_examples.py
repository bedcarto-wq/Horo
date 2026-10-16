"""Editable stage-three demonstrations. Movement is entirely ordinary Horo Graph."""
from pathlib import Path
from .model import Project,SceneNode,Transform,Graph,Variable
from .examples import link
from .storage import save_project


def add_body(p,name,kind,x,y,shape='rect_shape',**values):
    n=SceneNode(name=name,kind=kind,transform=Transform(x=x,y=y));p.nodes[n.id]=n
    s=SceneNode(name=name+' — форма',kind=shape,parent=n.id,**values);p.nodes[s.id]=s
    return n,s


def movement_graph(p,player,custom=False):
    g=Graph(name='Управление персонажем');p.graphs[g.id]=g;player.graph=g.id
    frame=g.add('frame',0,0);move=g.add('body_move',1260,0)
    link(g,frame,'next',move,'in');link(g,frame,'object',move,'object')
    normalize=g.add('normalize',420,300);scale=g.add('vector_scale',840,300);speed=g.add('number',420,600,value=180)
    link(g,normalize,'value',scale,'vector');link(g,speed,'value',scale,'factor');link(g,scale,'value',move,'velocity')
    if not custom:
        direction=g.add('direction',0,300,left='A',right='D',up='W',down='S')
        link(g,direction,'value',normalize,'vector')
    else:
        # Custom control: held Right/Left -> If -> assign run variable. No Direction node.
        frame_link=g.add('sequence',420,0);link(g,frame,'next',frame_link,'in')
        # Remove the original exec edge only (the data object edge remains).
        g.edges=[e for e in g.edges if not(e.source==frame.id and e.target==move.id and e.input=='in')]
        var=Variable(name='Скорость X',scope='run',owner=g.id);p.variables[var.id]=var
        held=g.add('held',0,950,key='Right');condition=g.add('if',420,950)
        link(g,frame_link,frame_link.outputs[0],condition,'in');link(g,held,'value',condition,'condition')
        for output,value,y in [('yes',1,950),('no',0,1300)]:
            write=g.add('write',840,y,variable=var.id);number=g.add('number',420,y+200,value=value)
            link(g,condition,output,write,'in');link(g,number,'value',write,'value')
        read=g.add('read',0,300,variable=var.id);vec=g.add('vector',0,600,x=0,y=0)
        link(g,read,'value',vec,'x');link(g,vec,'value',normalize,'vector');link(g,frame_link,frame_link.outputs[1],move,'in')
    for event,y,name in [('contact_begin',1600,'Начал контактов'),('contact_end',2050,'Закончил контактов')]:
        var=Variable(name=name,scope='object');p.variables[var.id]=var
        start=g.add(event,0,y);read=g.add('read',420,y+250,variable=var.id)
        one=g.add('number',420,y+500,value=1);plus=g.add('add',840,y+250);put=g.add('write',1260,y,variable=var.id)
        link(g,read,'value',plus,'a');link(g,one,'value',plus,'b');link(g,plus,'value',put,'value');link(g,start,'next',put,'in')
    return g


def playground():
    p=Project(name='Физика: WASD, скольжение и парные контакты',width=960,height=640)
    player,s=add_body(p,'Персонаж','controlled_body',100,100,'circle_shape',radius=14)
    movement_graph(p,player)
    walls=SceneNode(name='Составные границы',kind='static_body');p.nodes[walls.id]=walls
    for x,y,w,h in [(480,10,940,20),(480,630,940,20),(10,320,20,640),(950,320,20,640),(320,200,20,220),(390,300,120,20)]:
        shape=SceneNode(name='Стена',kind='rect_shape',parent=walls.id,width=w,height=h,transform=Transform(x=x,y=y));p.nodes[shape.id]=shape
    add_body(p,'Круглое препятствие','static_body',560,180,'circle_shape',radius=55)
    n,s=add_body(p,'Вогнутая стена','static_body',570,350,'polygon_shape',points=[[0,0],[200,0],[200,30],[35,30],[35,190],[0,190]])
    n,s=add_body(p,'Поворот учитывается','static_body',760,180,width=20,height=150);s.transform.rotation=30
    # In a separate space, a second controlled body behaves as an obstacle, not a dynamic crate.
    add_body(p,'Второе управляемое тело','controlled_body',190,420,width=40,height=40)
    return p


def thin_wall():
    p=Project(name='Непрерывная проверка тонкой стены',width=960,height=640)
    player,_=add_body(p,'Тело','controlled_body',80,320,'circle_shape',radius=10)
    movement_graph(p,player);g=p.graphs[player.graph]
    next(n for n in g.nodes.values() if n.kind=='number' and n.params.get('value')==180).params['value']=10000
    add_body(p,'Стена 0.5','static_body',480,320,width=.5,height=600)
    return p


def custom_input():
    p=Project(name='Своё управление без узла направления')
    player,_=add_body(p,'Персонаж','controlled_body',100,100);movement_graph(p,player,True)
    add_body(p,'Стена','static_body',400,100,width=20,height=180)
    return p


def write_examples(folder):
    for name,factory in [('physics_playground',playground),('physics_thin_wall',thin_wall),('physics_custom_input',custom_input)]:
        save_project(factory(),Path(folder)/name)
