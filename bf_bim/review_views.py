"""Four geometry review views, using the same solids as IFC (no cosmetic filler)."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from shapely import constrained_delaunay_triangles
from shapely.geometry import box
from .schema import Model
from .geometry import solid_parts,polygon_parts


def main():
    out=Path('cad_output');m=Model.model_validate_json((out/'energy-center-model.json').read_text(encoding='utf-8'))
    plt.rcParams['font.family']='Malgun Gothic'
    levels={f.id:f.elevation for f in m.floors};indices={f.id:i for i,f in enumerate(m.floors)}
    core=next(e for e in m.elements if e.type=='stair' and e.floor_id=='f1')
    xs=[x for x,y in core.polygon];ys=[y for x,y in core.polygon]
    interior=(min(xs)-3,min(ys)-3,max(xs)+4,max(ys)+4)
    specs=[('exterior','외관 · 지붕 포함 · 미완성 경계 후보',(5,15,83,65),None,0,24),
           ('separated','층 분리 · 실제 좌표에 표시 간격 3 m 추가',(5,15,83,65),None,3,38),
           ('interior','1층 내부 / 계단 코어 · 임시 두께 포함',interior,'f1',0,4.4),
           ('section','구조 단면 · X=45 m에서 절단 / 보 미확정',(5,15,45,65),None,0,24)]
    for name,title,extent,floor,separation,top in specs:
        fig=plt.figure(figsize=(14,10));ax=fig.add_subplot(111,projection='3d')
        clip=box(*extent)
        for e in m.elements:
            if e.excluded or e.type in ('space','corridor','opening') or e.source.get('marker_width_m'):continue
            if floor and e.floor_id!=floor:continue
            if name=='separated' and e.type=='roof':continue
            elevation=levels[e.floor_id]+indices[e.floor_id]*separation
            for index,(poly,z,depth) in enumerate(solid_parts(e,m.elements)):
                material=e.components[index].source.get('material') if e.components else e.source.get('material')
                color={'metal':'#69777f','glazing':'#8ec4d3','concrete':'#bdc4c2','finish':'#e2dfd4','door':'#977553'}.get(material,{'column':'#667b86','wall':'#c4ccc6'}.get(e.type,'#aaaeb0'))
                alpha=.32 if material=='glazing' else 1
                for p in polygon_parts(poly.intersection(clip)):
                    faces=[];caps=[]
                    base=elevation+z
                    for tri in constrained_delaunay_triangles(p).geoms:
                        caps.append([(x,y,base+(depth or 0)) for x,y in tri.exterior.coords])
                        if depth is not None:caps.append([(x,y,base) for x,y in tri.exterior.coords])
                    if depth is not None:
                        for ring in [p.exterior,*p.interiors]:
                            coords=list(ring.coords)
                            faces.extend([[(a[0],a[1],base),(b[0],b[1],base),(b[0],b[1],base+depth),(a[0],a[1],base+depth)] for a,b in zip(coords,coords[1:])])
                    # Keep each solid independently depth-sorted. One collection
                    # per material incorrectly paints all slab caps over walls.
                    ax.add_collection3d(Poly3DCollection(faces+caps,facecolor=color,
                        edgecolors=['#65757d']*len(faces)+[(0,0,0,0)]*len(caps),
                        linewidth=.08,alpha=alpha,shade=True))
        xmin,ymin,xmax,ymax=extent
        ax.set(xlim=(xmin,xmax),ylim=(ymin,ymax),zlim=(-4.2 if floor is None else -.3,top),xlabel='X (m)',ylabel='Y (m)',zlabel='Z (m)')
        ax.set_box_aspect((xmax-xmin,ymax-ymin,top+4.2));ax.view_init(elev=42 if floor else 26,azim=-65)
        ax.set_title(title+'\n도면 XY/층 레벨 + 미확정 조립체 치수 · 시공용 확정 모델 아님',fontsize=14)
        fig.savefig(out/f'bim-review-{name}.png',dpi=150,bbox_inches='tight');plt.close(fig)
        print(name,flush=True)


if __name__=='__main__':main()
