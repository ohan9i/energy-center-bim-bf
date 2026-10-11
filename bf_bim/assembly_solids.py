"""Closed prisms / inclined rails shared by the viewer and IFC tessellation."""
import math
from shapely.geometry import MultiPoint, Polygon
from .schema import SolidMesh


def mesh_volume(mesh):
    vertices=mesh.vertices if hasattr(mesh,'vertices') else mesh['vertices']
    triangles=mesh.triangles if hasattr(mesh,'triangles') else mesh['triangles']
    return sum(sum(vertices[a][i]*(vertices[b][(i+1)%3]*vertices[c][(i+2)%3]-vertices[b][(i+2)%3]*vertices[c][(i+1)%3]) for i in range(3))/6 for a,b,c in triangles)


def mesh_component(vertices,triangles,role,source):
    # Weld collapsed wedge tips; remove degenerate triangles before validation.
    unique=[];indices={};mapping=[]
    for v in vertices:
        key=tuple(round(x,10) for x in v)
        if key not in indices:indices[key]=len(unique);unique.append(list(v))
        mapping.append(indices[key])
    faces=[tuple(mapping[i] for i in t) for t in triangles]
    faces=[t for t in faces if len(set(t))==3]
    if mesh_volume(dict(vertices=unique,triangles=faces))<0:faces=[(a,c,b) for a,b,c in faces]
    base=min(v[2] for v in unique);height=max(v[2] for v in unique)-base
    for v in unique:v[2]-=base
    mesh=SolidMesh(vertices=unique,triangles=faces)
    poly=MultiPoint([(v[0],v[1]) for v in unique]).convex_hull
    return dict(role=role,polygon=list(poly.exterior.coords)[:-1],holes=[],height=height,z_offset=base,
        mesh=mesh.model_dump(),source=source)


def tapered_prism(poly,lower,upper,role,source):
    pts=list(poly.exterior.coords)[:-1]
    if len(pts)!=4:raise ValueError('Tapered prism requires four plan corners')
    vertices=[(x,y,z) for levels in (lower,upper) for (x,y),z in zip(pts,levels)]
    triangles=[(0,2,1),(0,3,2),(4,5,6),(4,6,7)]
    for i in range(4):
        j=(i+1)%4;triangles.extend(((i,j,j+4),(i,j+4,i+4)))
    return mesh_component(vertices,triangles,role,source)


def rail_segment(a,b,diameter,role,source):
    delta=[b[i]-a[i] for i in range(3)];length=math.sqrt(sum(x*x for x in delta))
    if length<1e-6:raise ValueError('Zero-length rail')
    axis=[x/length for x in delta]
    # Horizontal normal remains stable for vertical posts.
    normal=[-axis[1],axis[0],0] if abs(axis[2])<.99 else [1,0,0]
    n=math.sqrt(sum(x*x for x in normal));normal=[x/n for x in normal]
    other=[axis[(i+1)%3]*normal[(i+2)%3]-axis[(i+2)%3]*normal[(i+1)%3] for i in range(3)]
    segments=12;vertices=[]
    for end in (a,b):
        for k in range(segments):
            angle=2*math.pi*k/segments
            vertices.append([end[i]+diameter/2*(normal[i]*math.cos(angle)+other[i]*math.sin(angle)) for i in range(3)])
    triangles=[]
    for i in range(segments):
        j=(i+1)%segments;triangles.extend(((i,j,j+segments),(i,j+segments,i+segments)))
    for i in range(1,segments-1):triangles.extend(((0,i+1,i),(segments,segments+i,segments+i+1)))
    return mesh_component(vertices,triangles,role,source)
