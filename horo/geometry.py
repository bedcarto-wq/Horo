"""Finite 2D geometry, independent of Qt. Boundaries are authoritative, never mesh seams."""
import math
from dataclasses import dataclass

EPS = 1e-6
ENTER = 1e-5
LEAVE = 2e-5
MAX_COORD = 1_000_000
MIN_SIZE = .5


def add(a, b): return (a[0]+b[0], a[1]+b[1])
def sub(a, b): return (a[0]-b[0], a[1]-b[1])
def mul(a, s): return (a[0]*s, a[1]*s)
def dot(a, b): return a[0]*b[0]+a[1]*b[1]
def cross(a, b): return a[0]*b[1]-a[1]*b[0]
def length(a): return math.hypot(*a)
def unit(a):
    scale = max(abs(a[0]),abs(a[1]))
    if not scale:return (0.,0.)
    scaled=(a[0]/scale,a[1]/scale); n=length(scaled)
    return (scaled[0]/n,scaled[1]/n)
def edges(points): return zip(points, points[1:]+points[:1])
def area(p): return sum(cross(a,b) for a,b in edges(p))/2

def point_segment(p, a, b):
    d = sub(b,a); t = max(0., min(1., dot(sub(p,a),d)/dot(d,d)))
    return length(sub(p,add(a,mul(d,t))))

def intersects(a,b,c,d):
    ab,cd=sub(b,a),sub(d,c)
    x,y=cross(ab,sub(c,a)),cross(ab,sub(d,a))
    u,v=cross(cd,sub(a,c)),cross(cd,sub(b,c))
    if x*y < 0 and u*v < 0: return True
    return any(abs(k)<=EPS and point_segment(p,s,t)<=EPS for k,p,s,t in
               [(x,c,a,b),(y,d,a,b),(u,a,c,d),(v,b,c,d)])

def validate_polygon(raw):
    if not isinstance(raw,list) or len(raw)<3:
        raise ValueError('Контур: минимум три вершины')
    p=[]
    for v in raw:
        if not isinstance(v,(list,tuple)) or len(v)!=2 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or abs(x)>MAX_COORD for x in v):
            raise ValueError('Контур: нужны конечные координаты в диапазоне ±1000000')
        p.append(tuple(v))
    for i,a in enumerate(p):
        for b in p[i+1:]:
            if length(sub(a,b))<=EPS: raise ValueError('Контур: повторяющиеся вершины')
    if abs(area(p))<=EPS: raise ValueError('Контур: нулевая площадь')
    es=list(edges(p))
    for a,b in es:
        e=sub(b,a);n=unit((e[1],-e[0]));projection=[dot(v,n) for v in p]
        if max(projection)-min(projection)<MIN_SIZE-EPS:
            raise ValueError('Контур: толщина меньше 0.5')
    for i,(a,b) in enumerate(es):
        if length(sub(b,a))<MIN_SIZE: raise ValueError('Контур: ребро короче 0.5')
        prev=p[i-1]
        if abs(cross(sub(a,prev),sub(b,a)))<=EPS and dot(sub(a,prev),sub(b,a))<0:
            raise ValueError('Контур: обратное перекрывающееся ребро')
        for j in range(i+1,len(es)):
            if j==i+1 or (i==0 and j==len(es)-1):continue
            c,d=es[j]
            if intersects(a,b,c,d): raise ValueError('Контур: самопересечение')
            if min(point_segment(a,c,d),point_segment(b,c,d),point_segment(c,a,b),point_segment(d,a,b))<MIN_SIZE-EPS:
                raise ValueError('Контур: зазор/толщина между несмежными рёбрами меньше 0.5')
    return p if area(p)>0 else list(reversed(p))

def inside(p, poly):
    if any(point_segment(p,a,b)<=EPS for a,b in edges(poly)):return True
    result=False
    for a,b in edges(poly):
        if (a[1]>p[1]) != (b[1]>p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]: result=not result
    return result

def triangulate(poly):
    """Ear clipping. Original vertices/edges remain the editable collision boundary."""
    remaining=list(poly); result=[]
    while len(remaining)>3:
        for i,b in enumerate(remaining):
            a,c=remaining[i-1],remaining[(i+1)%len(remaining)]
            if cross(sub(b,a),sub(c,b))<=EPS: continue
            tri=[a,b,c]
            if any(inside(v,tri) for j,v in enumerate(remaining) if j not in (i,(i-1)%len(remaining),(i+1)%len(remaining))):continue
            result.append(tri);remaining.pop(i);break
        else:
            # Collinear redundant points are legal; remove only in the internal mesh.
            for i,b in enumerate(remaining):
                if abs(cross(sub(b,remaining[i-1]),sub(remaining[(i+1)%len(remaining)],b)))<=EPS:
                    remaining.pop(i);break
            else: raise ValueError('Не удалось разбить контур')
    result.append(remaining);return result

@dataclass
class Shape:
    id: str
    body: str
    points: list | None = None
    center: tuple = (0.,0.)
    radius: float = 0.

    def translated(self,d):
        return Shape(self.id,self.body,[add(p,d) for p in self.points] if self.points else None,add(self.center,d),self.radius)

    def bounds(self):
        if self.points:
            return (min(p[0] for p in self.points),min(p[1] for p in self.points),max(p[0] for p in self.points),max(p[1] for p in self.points))
        x,y=self.center;r=self.radius;return x-r,y-r,x+r,y+r

def near(a,b,margin=0):
    x,y=a.bounds(),b.bounds()
    return not (x[2]+margin<y[0] or y[2]+margin<x[0] or x[3]+margin<y[1] or y[3]+margin<x[1])

def triangles_overlap(a,b):
    for poly in (a,b):
        for x,y in edges(poly):
            n=unit((y[1]-x[1],x[0]-y[0]));pa=[dot(p,n) for p in a];pb=[dot(p,n) for p in b]
            if min(max(pa),max(pb))-max(min(pa),min(pb))<=EPS:return False
    return True

def overlap(a,b):
    if not near(a,b):return False
    if not a.points and not b.points:return length(sub(a.center,b.center))<a.radius+b.radius-EPS
    if not a.points or not b.points:
        circle,poly=(a,b) if not a.points else (b,a)
        return inside(circle.center,poly.points) or min(point_segment(circle.center,x,y) for x,y in edges(poly.points))<circle.radius-EPS
    return any(triangles_overlap(x,y) for x in triangulate(a.points) for y in triangulate(b.points))

def distance(a,b):
    if not a.points and not b.points:return max(0.,length(sub(a.center,b.center))-a.radius-b.radius)
    if not a.points or not b.points:
        c,p=(a,b) if not a.points else (b,a)
        return 0. if inside(c.center,p.points) else max(0.,min(point_segment(c.center,x,y) for x,y in edges(p.points))-c.radius)
    if any(intersects(x,y,u,v) for x,y in edges(a.points) for u,v in edges(b.points)):return 0.
    if inside(a.points[0],b.points) or inside(b.points[0],a.points):return 0.
    return min([point_segment(p,x,y) for p in a.points for x,y in edges(b.points)]+[point_segment(p,x,y) for p in b.points for x,y in edges(a.points)])

def ray_circle(p,d,c,r):
    q=sub(p,c); aa=dot(d,d);bb=dot(q,d);cc=dot(q,q)-r*r
    if aa<=1e-24:return None
    disc=bb*bb-aa*cc
    if disc<0:return None
    t=(-bb-math.sqrt(max(0.,disc)))/aa
    if -EPS<=t<=1+EPS:
        n=unit(sub(add(p,mul(d,max(0.,t))),c))
        if dot(d,n)<-EPS:return max(0.,min(1.,t)),n
    return None

def point_edge(p,d,a,b,offset=0.):
    e=sub(b,a);n=unit((e[1],-e[0]));den=dot(d,n)
    if den>=-EPS:return None
    t=(dot(sub(a,p),n)+offset)/den
    if not -EPS<=t<=1+EPS:return None
    hit=sub(add(p,mul(d,max(0.,t))),mul(n,offset));u=dot(sub(hit,a),e)/dot(e,e)
    if -EPS<=u<=1+EPS:return max(0.,min(1.,t)),n
    return None

def sweep(a,b,d):
    """Exact translational feature sweeps; no time sampling and no triangulation edges."""
    ab=a.bounds();bb=b.bounds()
    swept=(min(ab[0],ab[0]+d[0]),min(ab[1],ab[1]+d[1]),max(ab[2],ab[2]+d[0]),max(ab[3],ab[3]+d[1]))
    if swept[2]+ENTER<bb[0] or bb[2]+ENTER<swept[0] or swept[3]+ENTER<bb[1] or bb[3]+ENTER<swept[1]:return None
    hits=[]
    if not a.points and not b.points:return ray_circle(a.center,d,b.center,a.radius+b.radius)
    if not a.points:
        for x,y in edges(b.points):
            h=point_edge(a.center,d,x,y,a.radius)
            if h:hits.append(h)
        for p in b.points:
            h=ray_circle(a.center,d,p,a.radius)
            if h:hits.append(h)
    elif not b.points:
        h=sweep(b,a,mul(d,-1))
        return (h[0],mul(h[1],-1)) if h else None
    else:
        for p in a.points:
            for x,y in edges(b.points):
                h=point_edge(p,d,x,y)
                if h:hits.append(h)
        for p in b.points:
            for x,y in edges(a.points):
                h=point_edge(p,mul(d,-1),x,y)
                if h:hits.append((h[0],mul(h[1],-1)))
    return min(hits,key=lambda h:h[0]) if hits else None
