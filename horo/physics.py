"""Kinematic bodies, compound shapes and pair contacts. No GUI or third-party solver."""
import math
from .geometry import (Shape,EPS,ENTER,LEAVE,MIN_SIZE,MAX_COORD,validate_polygon,
                       triangulate,add,sub,mul,dot,length,overlap,distance,sweep,near)
from .model import number

BODIES=('static_body','controlled_body')
SHAPES=('rect_shape','circle_shape','polygon_shape')
MAX_SPEED=10_000
MAX_DT=.1

class PhysicsError(ValueError):
    def __init__(self,message,body=None,shape=None):
        super().__init__(message);self.body=body;self.shape=shape

def shape_points(node):
    if node.kind=='polygon_shape':return validate_polygon(node.points)
    if node.kind=='rect_shape':
        if not all(number(v) and MIN_SIZE<=v<=MAX_COORD for v in (node.width,node.height)):
            raise ValueError('Размеры прямоугольника должны быть от 0.5 до 1000000')
        w,h=node.width/2,node.height/2;return [(-w,-h),(w,-h),(w,h),(-w,h)]
    if not number(node.radius) or not MIN_SIZE/2<=node.radius<=MAX_COORD:
        raise ValueError('Радиус круга должен быть от 0.25 до 1000000')
    return None

def world_shapes(project):
    result={n.id:[] for n in project.nodes.values() if n.kind in BODIES}
    for n in project.nodes.values():
        if n.kind not in SHAPES:continue
        owner=project.nodes.get(n.parent)
        if not owner or owner.kind not in BODIES:raise PhysicsError('Форма должна быть непосредственным ребёнком тела',shape=n.id)
        try:
            local=shape_points(n);triangulate(local) if local else None
            key=n.id
            while key:
                current=project.nodes[key];t=current.transform
                if not all(number(v) for v in vars(t).values()):raise ValueError('Неконечное преобразование')
                if t.sx<=0 or t.sy<=0 or abs(t.sx-t.sy)>1e-9*max(t.sx,t.sy):raise ValueError('Физика: нужен положительный равномерный масштаб формы и всех родителей')
                if key!=n.id and key!=owner.id and current.kind in BODIES:raise ValueError('Физические тела нельзя вкладывать друг в друга')
                key=current.parent
            m=project.world_matrix(n.id);scale=math.hypot(m[0],m[1])
            def point(p):return (m[0]*p[0]+m[2]*p[1]+m[4],m[1]*p[0]+m[3]*p[1]+m[5])
            transformed=[point(p) for p in local] if local else None
            if transformed:validate_polygon([list(p) for p in transformed])
            elif n.radius*scale<MIN_SIZE/2:raise ValueError('Мировой диаметр круга меньше 0.5')
            s=Shape(n.id,owner.id,transformed,point((0,0)),n.radius*scale if local is None else 0.)
            if not all(number(v) and abs(v)<=MAX_COORD for v in s.bounds()):raise ValueError('Мировая граница вне диапазона ±1000000')
            result[owner.id].append(s)
        except ValueError as e:raise PhysicsError(str(e),owner.id,n.id) from e
    for oid,forms in result.items():
        if not forms:raise PhysicsError('У физического тела нет формы',oid)
    return result

class PhysicsWorld:
    def __init__(self,project):
        self.project=project;self.contacts=set();self.commands={};self.hit_pairs=set()
        self.validate_positions(world_shapes(project))

    def stop(self):self.contacts.clear();self.commands.clear();self.hit_pairs.clear()

    def command(self,oid,velocity,context=None):
        node=self.project.nodes.get(oid) if isinstance(oid,str) else None
        if not node or node.kind!='controlled_body':raise PhysicsError('Нужен существующий объект «Управляемое тело»',oid)
        if not isinstance(velocity,(list,tuple)) or len(velocity)!=2 or not all(number(v) for v in velocity):raise PhysicsError('Скорость должна быть конечным Вектор2',oid)
        if length(velocity)>MAX_SPEED+EPS:raise PhysicsError('Скорость больше 10000 ед./с',oid)
        self.commands[oid]=(tuple(velocity),context)

    def validate_positions(self,shapes):
        ids=list(shapes)
        for i,a in enumerate(ids):
            for b in ids[i+1:]:
                for x in shapes[a]:
                    for y in shapes[b]:
                        if overlap(x,y):raise PhysicsError(f'Проникновение тел {a} и {b}; исправьте начальную сцену/телепортацию',a,x.id)

    def _translate(self,oid,d):
        n=self.project.nodes[oid];t=n.transform
        if n.parent:
            a,b,c,e,_,_=self.project.world_matrix(n.parent);det=a*e-b*c
            dx,dy=(e*d[0]-c*d[1])/det,(-b*d[0]+a*d[1])/det
        else:dx,dy=d
        t.x+=dx;t.y+=dy

    def move(self,oid,d,shapes):
        remaining=d;total=(0.,0.);normals=[]
        # Bound iterations; unresolved remainder is an error, never silent truncation.
        for _ in range(16):
            if length(remaining)<=EPS:break
            candidates=[]
            for other,forms in shapes.items():
                if other==oid:continue
                for a in shapes[oid]:
                    for b in forms:
                        hit=sweep(a,b,remaining)
                        if hit:candidates.append((hit[0],hit[1],other))
            if not candidates:
                part=remaining;remaining=(0.,0.)
            else:
                at=min(h[0] for h in candidates)
                simultaneous=[h for h in candidates if abs(h[0]-at)*length(remaining)<=ENTER]
                part=mul(remaining,max(0.,at- EPS/max(length(remaining),EPS)))
                remaining=mul(remaining,1-at)
                for _,normal,other in simultaneous:
                    self.hit_pairs.add(tuple(sorted((oid,other))))
                    if all(length(sub(normal,n))>EPS for n in normals):normals.append(normal)
                # Projection onto all active halfspaces. At conflicting corners stop.
                for _pass in range(8):
                    for n in normals:
                        inward=dot(remaining,n)
                        if inward<0:remaining=sub(remaining,mul(n,inward))
                if any(dot(remaining,n)<-EPS for n in normals):remaining=(0.,0.)
            shapes[oid]=[s.translated(part) for s in shapes[oid]];total=add(total,part)
        else:
            if length(remaining)>EPS:raise PhysicsError('Движение не сошлось за 16 столкновений; уменьшите скорость/сложность угла',oid)
        self._translate(oid,total)

    def update(self,dt):
        shapes=world_shapes(self.project)
        self.validate_positions(shapes)
        if not number(dt) or dt<0 or (shapes and dt>MAX_DT+EPS):raise PhysicsError('Физика: dt должен быть от 0 до 0.1 с')
        self.hit_pairs.clear()
        commands=self.commands;self.commands={}
        for oid in shapes: # stable project order, not order of branch arrivals
            if oid in commands:self.move(oid,mul(commands[oid][0],dt),shapes)
        # Detect invalid world coordinates after moving as well.
        world_shapes(self.project)
        pairs=set();ids=list(shapes)
        for i,a in enumerate(ids):
            for b in ids[i+1:]:
                pair=tuple(sorted((a,b)));tol=LEAVE if pair in self.contacts else ENTER
                if any(near(x,y,tol) and distance(x,y)<=tol for x in shapes[a] for y in shapes[b]):pairs.add(pair)
        # Swept transient hits are contacts even if sliding leaves the obstacle this update.
        events=[('contact_end',p) for p in sorted(self.contacts-pairs)]
        events += [('contact_begin',p) for p in sorted(pairs-self.contacts)]
        for p in sorted(self.hit_pairs-pairs-self.contacts):events.extend([('contact_begin',p),('contact_end',p)])
        self.contacts=pairs
        return events
