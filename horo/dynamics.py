"""Local extension of the 0.3 swept kinematic world, not a new scheduler.

Authoring values remain on SceneNode. All accumulated velocities, support and
mass state live here, in the Runtime snapshot. Rotation is about the common COM.
"""
import math
from dataclasses import dataclass
from .model import number,valid_value
from .geometry import (EPS,ENTER,LEAVE,MIN_SIZE,add,sub,mul,dot,cross,length,unit,
                       near,distance,sweep,edges,point_segment,Shape)
from .rigid import mass_properties,features,Contact,convex
from .geometry import triangulate

BOUNCE_THRESHOLD=1.0  # normal world units / s; suppress micro-bounces
CONTACT_SLOP=2e-5
POSITION_TOL=2e-6
SUPPORT_COS=math.sqrt(.5)


def validate_settings(node):
    if node.kind.endswith('_body'):
        if not number(node.mass) or node.mass<=0:raise ValueError('Масса должна быть конечной и больше нуля')
        for name in ('friction','restitution'):
            if not number(getattr(node,name)) or not 0<=getattr(node,name)<=1:raise ValueError('Трение/отскок должны быть от 0 до 1')
        for name in ('gravity','velocity','up'):
            if not valid_value('vector',getattr(node,name)):raise ValueError(f'{name}: нужен конечный Вектор2')
        if length(node.up)<=EPS:raise ValueError('Направление вверх не может быть нулевым')
        if length(node.velocity)>10000+EPS:raise ValueError('Скорость больше 10000 ед./с')
        if not number(node.angular_velocity):raise ValueError('Угловая скорость должна быть конечной')
        if node.kind!='dynamic_body' and node.angular_velocity!=0:raise ValueError('Угловая скорость доступна только динамическому телу')
        if node.kind in ('static_body','platform_body') and (length(node.gravity)>0 or length(node.velocity)>0):raise ValueError('Гравитация/накопленная скорость доступны управляемому и динамическому телу')
    if not isinstance(node.one_way,bool):raise ValueError('Односторонность должна быть логической')
    if node.one_way and node.kind!='rect_shape':raise ValueError('Односторонняя поверхность поддерживается только прямоугольником')
    if node.kind=='rect_shape':
        if not valid_value('vector',node.one_way_normal) or tuple(node.one_way_normal) not in ((0,-1),(0,1),(-1,0),(1,0)):
            raise ValueError('Нормаль прямоугольной поверхности: (0,-1), (0,1), (-1,0) или (1,0)')


def plane(project,s):
    node=project.nodes[s.id]
    if not node.one_way:return None
    owner=project.nodes[s.body]
    if owner.kind not in ('static_body','platform_body'):
        from .physics import PhysicsError
        raise PhysicsError('Односторонняя форма нужна неподвижному телу или платформе',owner.id,node.id)
    m=project.world_matrix(s.id);v=node.one_way_normal
    n=unit((m[0]*v[0]+m[2]*v[1],m[1]*v[0]+m[3]*v[1]))
    return n,max(dot(p,n) for p in s.points)


def extent(s,n):
    return min(dot(p,n) for p in s.points) if s.points else dot(s.center,n)-s.radius


def initial_pair_blocks(project,a,b):
    for surface,other in ((a,b),(b,a)):
        pl=plane(project,surface)
        if pl and extent(other,pl[0])<pl[1]-LEAVE:return False
    return True


@dataclass
class State:
    center: tuple
    inertia: float
    velocity: tuple
    omega: float
    gravity: tuple
    inverse_mass: float=0
    inverse_inertia: float=0


class Dynamics:
    def __init__(self,world):
        from .physics import world_shapes,PhysicsError
        self.world=world;self.project=world.project;self.states={};self.support={};self.platform_commands={}
        self.contexts={};self.kinematic_velocity={};self.previous={};self.consumed=set()
        forms=world_shapes(self.project)
        self.meshes={}
        for fs in forms.values():
            for sh in fs:
                if sh.points:
                    self.meshes[sh.id]=None if convex(sh.points) else [[sh.points.index(v) for v in tri] for tri in triangulate(sh.points)]
        self.active=False
        for oid,shapes in forms.items():
            node=self.project.nodes[oid]
            try:
                validate_settings(node)
                for s in shapes:validate_settings(self.project.nodes[s.id]);plane(self.project,s)
                c,i=mass_properties(shapes,node.mass)
            except ValueError as e:raise PhysicsError(str(e),oid) from e
            dyn=node.kind=='dynamic_body'
            if dyn and not all(number(v) for v in (1/node.mass,1/i)):
                raise PhysicsError('Обратная масса/инерция не представима конечным числом',oid)
            self.states[oid]=State(c,i,tuple(node.velocity),math.radians(node.angular_velocity),tuple(node.gravity),
                                   1/node.mass if dyn else 0,1/i if dyn else 0)
            self.active |= dyn or node.kind=='platform_body' or any(self.project.nodes[s.id].one_way for s in shapes) or length(node.gravity)>0 or length(node.velocity)>0
        self.refresh_support(forms)

    def stop(self):
        self.states.clear();self.meshes.clear();self.support.clear();self.platform_commands.clear();self.contexts.clear();self.previous.clear();self.consumed.clear();self.kinematic_velocity.clear()

    def body(self,oid,kinds):
        from .physics import PhysicsError
        n=self.project.nodes.get(oid) if isinstance(oid,str) else None
        if not n or n.kind not in kinds or oid not in self.states:raise PhysicsError('Нужен объект типа: '+', '.join(kinds),oid)
        return n,self.states[oid]

    def read(self,kind,oid):
        if kind in ('get_angular','get_mass','get_inertia'):
            n,s=self.body(oid,('dynamic_body',))
        elif kind in ('grounded','get_up'):
            n,s=self.body(oid,('controlled_body',))
        else:n,s=self.body(oid,('controlled_body','dynamic_body'))
        return {'get_velocity':lambda:list(s.velocity),'get_gravity':lambda:list(s.gravity),
                'get_angular':lambda:math.degrees(s.omega),'grounded':lambda:oid in self.support,
                'get_up':lambda:list(self.up(oid)),'get_mass':lambda:n.mass,'get_inertia':lambda:s.inertia}[kind]()

    def action(self,kind,oid,value,point=None,context=None):
        from .physics import PhysicsError,MAX_SPEED
        allowed=('platform_body',) if kind=='platform_move' else ('dynamic_body',) if kind in ('set_angular','impulse') else ('controlled_body',) if kind=='jump' else ('controlled_body','dynamic_body')
        n,s=self.body(oid,allowed)
        scalar=kind in ('set_angular','jump')
        if not (number(value) if scalar else valid_value('vector',value)):raise PhysicsError('Нужно конечное число' if scalar else 'Нужен конечный Вектор2',oid)
        if kind in ('set_velocity','platform_move') and length(value)>MAX_SPEED+EPS:raise PhysicsError('Скорость больше 10000 ед./с',oid)
        self.contexts[oid]=context
        self.active=True
        if kind=='platform_move':self.platform_commands[oid]=tuple(value)
        elif kind=='set_gravity':s.gravity=tuple(value)
        elif kind=='set_angular':s.omega=math.radians(value)
        elif kind=='set_velocity':
            s.velocity=tuple(value)
            # The primitive setter consumes support exactly as the ready jump.
            if n.kind=='controlled_body' and dot(value,self.up(oid))>EPS:self.consume(oid)
        elif kind=='jump':
            if value<0:raise PhysicsError('Скорость прыжка не может быть отрицательной',oid)
            if oid not in self.support:return False
            up=self.up(oid);s.velocity=add(s.velocity,mul(up,value-dot(s.velocity,up)));self.consume(oid)
        elif kind=='impulse':
            from .physics import world_shapes
            s.center=mass_properties(world_shapes(self.project)[oid],n.mass)[0]
            p=s.center if point is None else point
            if not valid_value('vector',p):raise PhysicsError('Точка импульса: нужен мировой Вектор2',oid)
            s.velocity=add(s.velocity,mul(value,s.inverse_mass));s.omega+=cross(sub(p,s.center),value)*s.inverse_inertia
        if not valid_value('vector',s.velocity) or length(s.velocity)>MAX_SPEED+EPS or not number(s.omega):raise PhysicsError('Результат воздействия вне числового диапазона/скорости 10000',oid)
        return True

    def consume(self,oid):self.support.pop(oid,None);self.consumed.add(oid)
    def teleported(self,oid):
        affected=set()
        for body in self.states:
            key=body
            while key:
                if key==oid:affected.add(body);break
                key=self.project.nodes[key].parent
        for body in affected:self.consume(body)
        for passenger,support in list(self.support.items()):
            if support[1] in affected:self.consume(passenger)
    def up(self,oid):
        s=self.states[oid]
        return unit(mul(s.gravity,-1)) if length(s.gravity)>0 else unit(self.project.nodes[oid].up)

    def filter(self,a,b,d=(0.,0.)):
        for surface,other,relative in ((b,a,d),(a,b,mul(d,-1))):
            pl=plane(self.project,surface)
            if pl:
                oldsurface=self.previous.get(surface.id,surface);oldother=self.previous.get(other.id,other)
                # plane() uses current orientation (platforms never rotate), old
                # position offset must come from old shape vertices.
                level=max(dot(p,pl[0]) for p in oldsurface.points)
                if extent(oldother,pl[0])<level-LEAVE:return False
                if dot(relative,pl[0])>EPS:return False
        return True

    def refresh_support(self,shapes):
        result={}
        for oid,forms in shapes.items():
            if self.project.nodes[oid].kind!='controlled_body':continue
            up=self.up(oid);candidates=[]
            for other,others in shapes.items():
                if other==oid or self.project.nodes[other].kind not in ('static_body','platform_body'):continue
                for a in forms:
                    for b in others:
                        if not self.filter(a,b):continue
                        for normal,p,depth in features(a,b,LEAVE,self.meshes):
                            pl=plane(self.project,b)
                            if pl and dot(normal,pl[0])<.999:continue
                            score=dot(normal,up)
                            if score>=SUPPORT_COS-1e-9 and depth>=-LEAVE:
                                candidates.append((-score,other,b.id,normal))
            if candidates:result[oid]=min(candidates,key=lambda x:x[:3])
        self.support=result

    def translate(self,oid,d,shapes):
        self.world._translate(oid,d);self.states[oid].center=add(self.states[oid].center,d)
        shapes[oid]=[s.translated(d) for s in shapes[oid]]

    def rotate(self,oid,angle,shapes):
        # Rotation of the authored origin about COM; parent transform is already
        # uniform and checked by world_shapes. World delta angle == local delta.
        n=self.project.nodes[oid];m=self.project.world_matrix(oid);c=self.states[oid].center
        v=sub((m[4],m[5]),c);co,si=math.cos(angle),math.sin(angle)
        new=add(c,(co*v[0]-si*v[1],si*v[0]+co*v[1]))
        self.world._translate(oid,sub(new,(m[4],m[5])))
        n.transform.rotation=(n.transform.rotation+math.degrees(angle))%360
        def turn(p):
            v=sub(p,c);return add(c,(co*v[0]-si*v[1],si*v[0]+co*v[1]))
        shapes[oid]=[Shape(s.id,s.body,[turn(p) for p in s.points] if s.points else None,turn(s.center),s.radius) for s in shapes[oid]]

    def move_kinematic(self,oid,d,shapes,ignore=()):
        before=self.states[oid].center
        subset={k:v for k,v in shapes.items() if k not in ignore or k==oid}
        total,normals=self.world.move(oid,d,subset)
        shapes[oid]=subset[oid];self.states[oid].center=add(before,total)
        return total,normals

    def platforms(self,h,shapes):
        for oid,v in sorted(self.platform_commands.items()):
            d=mul(v,h)
            passengers=sorted(k for k,sup in self.support.items() if sup[1]==oid and k not in self.consumed)
            # Preflight common translation; no temporary model mutation. A
            # blocked passenger constrains the platform, never crushes it.
            fraction=1.
            for moving in [oid]+passengers:
                for other,forms in shapes.items():
                    if other==oid or other in passengers:continue
                    # The platform itself can accelerate dynamic objects by
                    # contact; a character passenger still must not push them.
                    if moving==oid and self.project.nodes[other].kind=='dynamic_body':continue
                    for a in shapes[moving]:
                        for b in forms:
                            if not self.filter(a,b,d):continue
                            hit=sweep(a,b,d)
                            if hit:fraction=min(fraction,max(0.,hit[0]-EPS/max(length(d),EPS)))
            actual=mul(d,fraction)
            self.translate(oid,actual,shapes)
            self.kinematic_velocity[oid]=mul(actual,1/h) if h else (0.,0.)
            for passenger in passengers:self.translate(passenger,actual,shapes)

    def manifolds(self,shapes):
        cs=[];ids=sorted(shapes)
        for index,a in enumerate(ids):
            for b in ids[index+1:]:
                if not (self.states[a].inverse_mass or self.states[b].inverse_mass):continue
                for x in shapes[a]:
                    for y in shapes[b]:
                        rel=mul(sub(self.velocity(a),self.velocity(b)),self._h)
                        if not self.filter(x,y,rel):continue
                        for normal,p,depth in features(x,y,CONTACT_SLOP,self.meshes):
                            px,py=plane(self.project,x),plane(self.project,y)
                            if py and dot(normal,py[0])<.999:continue
                            if px and dot(normal,mul(px[0],-1))<.999:continue
                            cs.append(Contact(a,b,normal,p,depth))
        return cs

    def velocity(self,oid):
        s=self.states[oid]
        if self.project.nodes[oid].kind=='controlled_body':return (0.,0.)
        return s.velocity if s.inverse_mass else self.kinematic_velocity.get(oid,(0.,0.))

    def impulse_pair(self,c,j):
        for oid,sign in ((c.a,1),(c.b,-1)):
            s=self.states[oid]
            if s.inverse_mass:
                impulse=mul(j,sign);s.velocity=add(s.velocity,mul(impulse,s.inverse_mass))
                s.omega+=cross(sub(c.point,s.center),impulse)*s.inverse_inertia

    def solve(self,contacts):
        # Accumulated sequential impulses: no repeated restitution energy, and
        # Coulomb friction is limited by the accumulated normal impulse.
        accum=[[0.,0.] for c in contacts];targets=[]
        def relative(c):
            a,b=self.states[c.a],self.states[c.b];ra,rb=sub(c.point,a.center),sub(c.point,b.center)
            va=add(self.velocity(c.a),(-a.omega*ra[1],a.omega*ra[0]))
            vb=add(self.velocity(c.b),(-b.omega*rb[1],b.omega*rb[0]))
            return sub(va,vb),ra,rb
        for c in contacts:
            vn=dot(relative(c)[0],c.normal)
            e=max(self.project.nodes[c.a].restitution,self.project.nodes[c.b].restitution)
            targets.append(-e*vn if vn<-BOUNCE_THRESHOLD else 0.)
        iterations=64 if any(self.states[c.a].inverse_mass and self.states[c.b].inverse_mass for c in contacts) else 16
        for _ in range(iterations):
            for i,c in enumerate(contacts):
                a,b=self.states[c.a],self.states[c.b];v,ra,rb=relative(c);n=c.normal;t=(-n[1],n[0])
                denom=a.inverse_mass+b.inverse_mass+cross(ra,n)**2*a.inverse_inertia+cross(rb,n)**2*b.inverse_inertia
                if denom<=0:continue
                old=accum[i][0];new=max(0.,old+(targets[i]-dot(v,n))/denom);accum[i][0]=new
                self.impulse_pair(c,mul(n,new-old))
                v,ra,rb=relative(c)
                denom=a.inverse_mass+b.inverse_mass+cross(ra,t)**2*a.inverse_inertia+cross(rb,t)**2*b.inverse_inertia
                mu=math.sqrt(self.project.nodes[c.a].friction*self.project.nodes[c.b].friction)
                limit=mu*new;old=accum[i][1];new=max(-limit,min(limit,old-dot(v,t)/denom));accum[i][1]=new
                self.impulse_pair(c,mul(t,new-old))

    def update(self,dt):
        from .physics import PhysicsError,world_shapes,MAX_DT,MAX_SPEED
        if not number(dt) or not 0<=dt<=MAX_DT+EPS:raise PhysicsError('Физика: dt должен быть от 0 до 0.1 с')
        shapes=world_shapes(self.project)
        # Old teleport semantics are retained, including overlap diagnostics.
        for oid,forms in shapes.items():
            self.states[oid].center=mass_properties(forms,self.project.nodes[oid].mass)[0]
        # Teleports must still be checked. Solver tolerance applies only to
        # dynamic pairs, not to overlapping kinematic bodies.
        ids=list(shapes)
        for i,a in enumerate(ids):
            for b in ids[i+1:]:
                for x in shapes[a]:
                    for y in shapes[b]:
                        if not initial_pair_blocks(self.project,x,y):continue
                        from .geometry import overlap
                        if overlap(x,y):
                            if (self.states[a].inverse_mass or self.states[b].inverse_mass) and max((z[2] for z in features(x,y)),default=0)<=CONTACT_SLOP:continue
                            raise PhysicsError('Проникновение тел; исправьте начальную сцену/телепортацию',a,x.id)
        self.previous={s.id:s for forms in shapes.values() for s in forms};self.world.hit_pairs.clear()
        self.world.collision_filter=self.filter
        commands=self.world.commands;self.world.commands={}
        self.contexts.update({k:v[1] for k,v in commands.items()})
        feature=math.inf
        for forms in shapes.values():
            for sh in forms:
                if not sh.points:feature=min(feature,2*sh.radius);continue
                es=list(edges(sh.points))
                for i,(a,b) in enumerate(es):
                    n=unit((b[1]-a[1],a[0]-b[0]))
                    projections=[dot(p,n) for p in sh.points]
                    feature=min(feature,length(sub(b,a)),max(projections)-min(projections))
                    for j,(c,d) in enumerate(es):
                        if j<=i+1 or (i==0 and j==len(es)-1):continue
                        feature=min(feature,point_segment(a,c,d),point_segment(b,c,d),point_segment(c,a,b),point_segment(d,a,b))
        travel=max(MIN_SIZE,feature)*.2
        remaining=dt
        try:
            while remaining>1e-12:
                # Adaptive point-displacement bound includes COM offset and spin.
                # No silent velocity clamp or new reduced geometric domain.
                vmax=0.
                for oid,s in self.states.items():
                    node=self.project.nodes[oid]
                    if node.kind not in ('controlled_body','dynamic_body','platform_body'):continue
                    r=max(max(length(sub(p,s.center)) for p in sh.points) if sh.points else length(sub(sh.center,s.center))+sh.radius for sh in shapes[oid])
                    drive=commands.get(oid,((0.,0.),None))[0] if node.kind=='controlled_body' else self.platform_commands.get(oid,(0.,0.))
                    speed=length(add(s.velocity,drive))+length(s.gravity)*remaining+abs(s.omega)*r
                    if not number(speed):raise PhysicsError('Скорость крайней точки не конечна',oid)
                    vmax=max(vmax,speed)
                h=min(remaining,1/60,travel/max(vmax,1.))
                if remaining-h==remaining:raise PhysicsError('Шаг вращения не представим с текущими числовыми параметрами')
                self.previous={sh.id:sh for fs in shapes.values() for sh in fs}
                self._h=h;self.kinematic_velocity={}
                self.platforms(h,shapes)
                for oid,s in self.states.items():
                    node=self.project.nodes[oid]
                    if node.kind not in ('controlled_body','dynamic_body'):continue
                    s.velocity=add(s.velocity,mul(s.gravity,h))
                    if length(s.velocity)>MAX_SPEED+EPS:raise PhysicsError('Скорость больше 10000 ед./с',oid)
                    if node.kind=='controlled_body':
                        v=add(s.velocity,commands.get(oid,((0.,0.),None))[0])
                        if length(v)>MAX_SPEED+EPS:raise PhysicsError('Суммарная скорость больше 10000 ед./с',oid)
                        total,normals=self.move_kinematic(oid,mul(v,h),shapes)
                        self.kinematic_velocity[oid]=mul(total,1/h)
                        for n in normals:
                            inward=dot(s.velocity,n)
                            if inward<0:s.velocity=sub(s.velocity,mul(n,inward))
                    else:
                        self.translate(oid,mul(s.velocity,h),shapes)
                        if s.omega:self.rotate(oid,s.omega*h,shapes)
                contacts=self.manifolds(shapes);self.solve(contacts)
                for c in contacts:self.world.hit_pairs.add(tuple(sorted((c.a,c.b))))
                # Remove numerical impulse residue only, not real damping.
                touched={oid for c in contacts for oid in (c.a,c.b)}
                for oid in touched:
                    state=self.states[oid]
                    if state.inverse_mass and length(state.velocity)+abs(state.omega)<1e-5:
                        state.velocity=(0.,0.);state.omega=0.
                # Split positional correction does not change kinetic energy.
                for _ in range(160):
                    contacts=self.manifolds(shapes);worst=max((c.depth for c in contacts),default=0.)
                    if worst<=POSITION_TOL+EPS:break
                    counts={}
                    for c in contacts:
                        key=(c.a,c.b);counts[key]=counts.get(key,0)+1
                    for c in contacts:
                        a,b=self.states[c.a],self.states[c.b]
                        ra,rb=sub(c.point,a.center),sub(c.point,b.center)
                        ca,cb=cross(ra,c.normal),cross(rb,c.normal)
                        den=a.inverse_mass+b.inverse_mass+ca*ca*a.inverse_inertia+cb*cb*b.inverse_inertia
                        amount=max(0.,c.depth-POSITION_TOL)*.8/den/counts[(c.a,c.b)]
                        if a.inverse_mass:
                            self.translate(c.a,mul(c.normal,amount*a.inverse_mass),shapes)
                            self.rotate(c.a,amount*ca*a.inverse_inertia,shapes)
                        if b.inverse_mass:
                            self.translate(c.b,mul(c.normal,-amount*b.inverse_mass),shapes)
                            self.rotate(c.b,-amount*cb*b.inverse_inertia,shapes)
                # Numerical contacts may retain <=2e-6 overlap; a large
                # unresolved overlap is an actionable error, never hidden.
                if any(c.depth>CONTACT_SLOP for c in self.manifolds(shapes)):
                    c=max(self.manifolds(shapes),key=lambda c:c.depth)
                    raise PhysicsError('Не удалось разрешить контакт: пересечение/сдавливание',c.a)
                remaining-=h
                self.refresh_support(shapes)
                # Support consumed by jump is not reacquired in the same update.
                for oid in self.consumed:self.support.pop(oid,None)
            world_shapes(self.project) # final authoritative transform/bounds validation
            pairs=set();ids=sorted(shapes)
            for i,a in enumerate(ids):
                for b in ids[i+1:]:
                    if any(self.filter(x,y) and near(x,y,LEAVE) and distance(x,y)<=LEAVE for x in shapes[a] for y in shapes[b]):pairs.add((a,b))
            self.refresh_support(shapes)
            for oid in self.consumed:self.support.pop(oid,None)
            events=[('contact_end',p) for p in sorted(self.world.contacts-pairs)]+[('contact_begin',p) for p in sorted(pairs-self.world.contacts)]
            for pair in sorted(self.world.hit_pairs-pairs-self.world.contacts):events.extend([('contact_begin',pair),('contact_end',pair)])
            self.world.contacts=pairs
            return events
        finally:
            self.platform_commands.clear();self.consumed.clear();self.world.collision_filter=None
