"""0.4 editable acceptance scenes. No input/gameplay is hardcoded in Runtime."""
from pathlib import Path
from .model import Project,Graph,SceneNode,Transform,Variable
from .physics_examples import add_body
from .examples import link
from .storage import save_project


def jump_graph(g,basic=False,y=1200):
    key=g.add('key',0,y,key='Space');speed=g.add('number',400,y+300,value=310)
    if not basic:
        jump=g.add('jump',800,y)
        link(g,key,'next',jump,'in');link(g,key,'object',jump,'object');link(g,speed,'value',jump,'value')
        return
    ground=g.add('grounded',0,y+300);branch=g.add('if',400,y)
    up=g.add('get_up',0,y+600);vel=g.add('get_velocity',0,y+900)
    dp=g.add('dot',400,y+600);component=g.add('vector_scale',800,y+600)
    tangent=g.add('vector_sub',1200,y+600);along=g.add('vector_scale',800,y+300)
    result=g.add('vector_add',1600,y+300);setter=g.add('set_velocity',2000,y)
    for n in (ground,up,vel,setter):link(g,key,'object',n,'object')
    link(g,key,'next',branch,'in');link(g,ground,'value',branch,'condition');link(g,branch,'yes',setter,'in')
    for a,out,b,port in [(vel,'value',dp,'a'),(up,'value',dp,'b'),(up,'value',component,'vector'),(dp,'value',component,'factor'),
                          (vel,'value',tangent,'a'),(component,'value',tangent,'b'),(up,'value',along,'vector'),(speed,'value',along,'factor'),
                          (tangent,'value',result,'a'),(along,'value',result,'b'),(result,'value',setter,'value')]:link(g,a,out,b,port)


def character_graph(p,a,basic=False,side=False):
    g=Graph(name='Ходьба и '+('базовый прыжок' if basic else 'готовый прыжок'));p.graphs[g.id]=g;a.graph=g.id
    frame=g.add('frame');seq=g.add('sequence',400,0);link(g,frame,'next',seq,'in')
    walk=Variable(name='Скорость ходьбы',scope='run',owner=g.id);p.variables[walk.id]=walk
    # Pure ordinary graph: left key selects -140, otherwise right selects 140,
    # otherwise 0. On simultaneous press left has explicit priority.
    branch=g.add('if',800,0);left=g.add('held',400,300,key='A' if not side else 'W')
    link(g,seq,seq.outputs[0],branch,'in');link(g,left,'value',branch,'condition')
    write_left=g.add('write',1200,0,variable=walk.id);minus=g.add('number',800,300,value=-140)
    link(g,branch,'yes',write_left,'in');link(g,minus,'value',write_left,'value')
    right=g.add('held',800,600,key='D' if not side else 'S');branch_right=g.add('if',1200,600)
    link(g,branch,'no',branch_right,'in');link(g,right,'value',branch_right,'condition')
    for out,value,x in [('yes',140,1600),('no',0,2000)]:
        write=g.add('write',x,600,variable=walk.id);number=g.add('number',x,900,value=value)
        link(g,branch_right,out,write,'in');link(g,number,'value',write,'value')
    read=g.add('read',2400,300,variable=walk.id);vec=g.add('vector',2800,300);move=g.add('body_move',3200,0)
    link(g,read,'value',vec,'y' if side else 'x');link(g,seq,seq.outputs[1],move,'in')
    link(g,frame,'object',move,'object');link(g,vec,'value',move,'velocity')
    jump_graph(g,basic)
    return g


def platformer(basic=False):
    p=Project(name='Платформер: '+('базовый прыжок' if basic else 'готовый прыжок'),width=960,height=640)
    a,s=add_body(p,'Персонаж A/D, Space','controlled_body',100,470,'circle_shape',radius=14);a.gravity=[0,600]
    character_graph(p,a,basic)
    add_body(p,'Пол','static_body',480,600,width=940,height=40)
    b,t=add_body(p,'Проход снизу: площадка','static_body',300,475,width=180,height=12);t.one_way=True
    add_body(p,'Стена','static_body',850,530,width=30,height=100)
    platform,s=add_body(p,'Платформа I/J/K/L','platform_body',570,480,width=150,height=16)
    g=Graph(name='Движение платформы I/J/K/L');p.graphs[g.id]=g;platform.graph=g.id
    frame=g.add('frame');direction=g.add('direction',0,300,left='J',right='L',up='I',down='K')
    norm=g.add('normalize',400,300);scale=g.add('vector_scale',800,300);speed=g.add('number',400,600,value=60);move=g.add('platform_move',1200,0)
    link(g,frame,'next',move,'in');link(g,frame,'object',move,'object');link(g,direction,'value',norm,'vector')
    link(g,norm,'value',scale,'vector');link(g,speed,'value',scale,'factor');link(g,scale,'value',move,'value')
    return p


def material_lab():
    p=Project(name='Динамика: массы, отскок, вращение и трение',width=960,height=640)
    add_body(p,'Пол','static_body',480,600,width=940,height=40)
    for x,mass,e,mu,shape in [(150,1,.8,.2,'circle_shape'),(340,5,0,1,'rect_shape'),(520,1,.4,.5,'rect_shape')]:
        a,s=add_body(p,f'm={mass}, e={e}, μ={mu}','dynamic_body',x,160,shape,width=45,height=30,radius=22)
        a.gravity=[0,400];a.mass=mass;a.restitution=e;a.friction=mu
        if shape=='rect_shape':a.angular_velocity=40;a.velocity=[15,0]
    a,s=add_body(p,'Вогнутое тело — единая масса','dynamic_body',720,120,'polygon_shape',points=[[-25,-25],[25,-25],[25,0],[0,0],[0,25],[-25,25]])
    a.gravity=[0,400];a.angular_velocity=15
    return p


def side_gravity():
    p=Project(name='Боковая гравитация: W/S, Space',width=960,height=640)
    a,s=add_body(p,'Персонаж W/S','controlled_body',830,270,'circle_shape',radius=14);a.gravity=[500,0]
    character_graph(p,a,side=True)
    add_body(p,'Правый пол','static_body',920,320,width=30,height=600)
    return p


def impulse_lab():
    p=Project(name='Импульс в мировой точке: Space',width=960,height=640)
    a,s=add_body(p,'Составное тело','dynamic_body',460,280,width=80,height=30)
    t=SceneNode(name='Вторая форма',kind='circle_shape',parent=a.id,radius=20,transform=Transform(x=50));p.nodes[t.id]=t
    g=Graph(name='Однократный импульс со смещением');p.graphs[g.id]=g;a.graph=g.id
    key=g.add('key',key='Space');impulse=g.add('impulse',800,0);v=g.add('vector',0,300,x=0,y=-30);point=g.add('vector',400,300,x=410,y=280)
    link(g,key,'next',impulse,'in');link(g,key,'object',impulse,'object');link(g,v,'value',impulse,'value');link(g,point,'value',impulse,'point')
    return p


def generate(root):
    for name,p in [('22-dynamic-materials',material_lab()),('23-platformer-jump',platformer()),('24-platformer-basic-jump',platformer(True)),('25-side-gravity',side_gravity()),('26-off-center-impulse',impulse_lab())]:save_project(p,Path(root)/name)


if __name__=='__main__':generate('examples')
