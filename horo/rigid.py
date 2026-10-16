"""Mass integrals and exterior contact features. All coordinates are world units.

No collision triangles are exposed as contact edges: triangulation seams never
become independent material surfaces. An impulse is applied to one body COM.
"""
import math
from dataclasses import dataclass
from .geometry import (EPS,add,sub,mul,dot,cross,length,unit,edges,area,
                       inside,point_segment,near,overlap,triangulate,Shape,distance)


def closest(p,a,b):
    d=sub(b,a);t=max(0.,min(1.,dot(sub(p,a),d)/dot(d,d)))
    return add(a,mul(d,t))


def mass_properties(forms,mass):
    """Uniform surface density; overlapping child shapes count twice.

    Integrate about a nearby reference to avoid cancellation near ±1e6.
    Polygon integrals use original boundary, not individual triangles.
    """
    origin=forms[0].points[0] if forms[0].points else forms[0].center
    pieces=[]
    for s in forms:
        if s.points:
            p=[sub(x,origin) for x in s.points];a=area(p)
            c=(sum((x[0]+y[0])*cross(x,y) for x,y in edges(p))/(6*a),
               sum((x[1]+y[1])*cross(x,y) for x,y in edges(p))/(6*a))
            j=sum(cross(x,y)*(dot(x,x)+dot(x,y)+dot(y,y)) for x,y in edges(p))/12
            j=j/a-dot(c,c)
        else:
            a=math.pi*s.radius*s.radius;c=sub(s.center,origin);j=s.radius*s.radius/2
        pieces.append((a,c,j))
    total=sum(a for a,c,j in pieces)
    center=mul(tuple(sum(a*c[i] for a,c,j in pieces) for i in (0,1)),1/total)
    inertia=mass/total*sum(a*(j+dot(sub(c,center),sub(c,center))) for a,c,j in pieces)
    if not math.isfinite(inertia) or inertia<=0:raise ValueError('Вырожденный момент инерции')
    return add(center,origin),inertia


@dataclass
class Contact:
    a: str
    b: str
    normal: tuple  # from B toward A
    point: tuple
    depth: float


def convex(poly):
    return all(cross(sub(b,a),sub(c,b))>=-EPS for a,b,c in zip(poly,poly[1:]+poly[:1],poly[2:]+poly[:2]))


def prepared(shape):
    # Shape instances are immutable working values: every translation/rotation
    # constructs a new Shape. Memoize derived boundary data, never body state.
    if not hasattr(shape,'_rigid_edges'):
        shape._rigid_edges=[(x,y,unit((y[1]-x[1],x[0]-y[0]))) for x,y in edges(shape.points)]
        shape._rigid_convex=convex(shape.points)
    return shape._rigid_edges


def convex_features(a,b,margin):
    best=None
    for shape in (a,b):
        for x,y,n in prepared(shape):
            pa=[dot(v,n) for v in a.points];pb=[dot(v,n) for v in b.points]
            if min(pa)>max(pb)+margin or min(pb)>max(pa)+margin:return []
            plus=max(pb)-min(pa);minus=max(pa)-min(pb)
            if plus<minus:depth,normal=plus,n
            else:depth,normal=minus,mul(n,-1)
            if best is None or depth<best[0]:best=(depth,normal)
    depth,n=best
    def face(shape,direction):
        choices=[]
        for x,y,normal in prepared(shape):
            choices.append((dot(normal,direction),dot(x,direction),x,y,normal))
        return max(choices,key=lambda c:c[:2])
    fa,fb=face(a,mul(n,-1)),face(b,n)
    if fb[0]>=fa[0]:
        ref,inc=fb,a;normal=fb[4];n=normal
    else:
        ref,inc=fa,b;normal=fa[4];n=mul(normal,-1)
    r0,r1=ref[2:4];t=unit(sub(r1,r0));span=length(sub(r1,r0))
    # Incident face most anti-parallel to reference face; clip against the two
    # reference side planes. Unlike support-vertex guessing this retains two
    # contacts for a nearly flat resting face, each with its own signed depth.
    candidates=[]
    for x,y,outward in prepared(inc):
        candidates.append((dot(outward,normal),x,y))
    _,p0,p1=min(candidates,key=lambda c:c[0]);v=sub(p1,p0)
    a0=dot(sub(p0,r0),t);dv=dot(v,t);lo,hi=0.,1.
    if abs(dv)<EPS:
        if a0 < -margin or a0>span+margin:return []
    else:
        u0,u1=(-a0/dv,(span-a0)/dv);lo=max(lo,min(u0,u1));hi=min(hi,max(u0,u1))
        if lo>hi:return []
    result=[]
    for u in ([lo,hi] if hi-lo>EPS else [lo]):
        p=add(p0,mul(v,u));dep=dot(sub(r0,p),normal)
        if dep>=-margin:result.append((n,add(p,mul(normal,dep/2)),dep))
    return result



def features(a,b,margin=2e-5,meshes=None):
    """Exterior vertex/edge manifolds. Returns (normal B->A,point,depth).

    Two face vertices give a stable two-point box contact. Concave polygons use
    their *original* external edges; no normal from an ear-clipping diagonal.
    Crossing thin polygons without an interior vertex use boundary intersections.
    """
    if not near(a,b,margin):return []
    if not a.points and not b.points:
        d=sub(a.center,b.center);r=a.radius+b.radius;dist=length(d)
        if dist>r+margin:return []
        n=unit(d) if dist>EPS else (1.,0.)
        return [(n,sub(a.center,mul(n,a.radius)),r-dist)]
    if not a.points or not b.points:
        c,p=(a,b) if not a.points else (b,a)
        q=min((closest(c.center,x,y) for x,y in edges(p.points)),key=lambda q:length(sub(c.center,q)))
        d=sub(c.center,q);dist=length(d);internal=inside(c.center,p.points)
        if not internal and dist>c.radius+margin:return []
        n=unit(mul(d,-1) if internal else d) if dist>EPS else (0.,-1.)
        if c is b:n=mul(n,-1)
        return [(n,q,c.radius+dist if internal else c.radius-dist)]
    prepared(a);prepared(b)
    if a._rigid_convex and b._rigid_convex:return convex_features(a,b,margin)
    # Decompose only for overlap queries. A candidate manifold must touch an
    # ORIGINAL boundary with the same outward normal; internal diagonals cannot
    # create constraints. All pieces still share one mass, COM and impulse state.
    def parts(shape):
        if hasattr(shape,'_rigid_parts'):return shape._rigid_parts
        if meshes is not None and shape.id in meshes:
            indices=meshes[shape.id]
            polygons=[[shape.points[i] for i in tri] for tri in indices] if indices else [shape.points]
        else:polygons=[shape.points] if shape._rigid_convex else triangulate(shape.points)
        shape._rigid_parts=[shape if poly is shape.points else Shape(shape.id,shape.body,poly) for poly in polygons]
        return shape._rigid_parts
    parts_a,parts_b=parts(a),parts(b)
    result=[]
    for x in parts_a:
        for y in parts_b:
            for n,p,depth in convex_features(x,y,margin):
                boundary=False
                for shape,normal in ((a,mul(n,-1)),(b,n)):
                    for u,v,outward in prepared(shape):
                        if dot(outward,normal)>.999999 and point_segment(p,u,v)<=max(0,depth)+margin:
                            boundary=True;break
                if boundary and not any(dot(n,q[0])>.999999 and length(sub(p,q[1]))<margin for q in result):result.append((n,p,depth))
    return result
