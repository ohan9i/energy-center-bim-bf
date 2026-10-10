import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from .schema import Model
from .geometry import footprint,polygon_parts
from .ifc_export import export_ifc

def main():
    m=Model.model_validate_json(Path('cad_output/energy-center-model.json').read_text(encoding='utf-8'))
    plt.rcParams['font.family']='Malgun Gothic'
    fig=plt.figure(figsize=(16,9))
    for num,floor in enumerate(m.floors,1):
        ax=fig.add_subplot(1,2,num,projection='3d')
        ax.set_title(f'{floor.name} · 실제 DWG 기반 검토용 모델',pad=15)
        es=[e for e in m.elements if e.floor_id==floor.id]
        for e in es:
            if e.type=='floor':
                for p in polygon_parts(footprint(e,m.elements)):
                    ax.add_collection3d(Poly3DCollection([[(x,y,0) for x,y in p.exterior.coords]],facecolor='#e0e7e7',edgecolor='#aabbbb',alpha=.4))
                continue
            color={'wall':'#cad7d8','column':'#677f86','door':'#c79532','stair':'#b0a08a','elevator':'#759da8'}.get(e.type,'#a0b5b9')
            height=e.height if e.height is not None else .05
            for p in polygon_parts(footprint(e,m.elements)):
                pts=list(p.exterior.coords);faces=[[(x,y,height) for x,y in pts]]
                faces.extend([[(a[0],a[1],0),(b[0],b[1],0),(b[0],b[1],height),(a[0],a[1],height)] for a,b in zip(pts,pts[1:])])
                ax.add_collection3d(Poly3DCollection(faces,facecolor=color,edgecolor='#6f878e',linewidth=.15,alpha=.9))
        for p in [p for p in m.places if p.floor_id==floor.id and 'E.V' not in p.name]:ax.text(*p.point,4.6,p.name[3:],fontsize=7,color='#204c5a')
        xs=[x for e in es for x,y in e.polygon];ys=[y for e in es for x,y in e.polygon]
        ax.set_xlim(min(xs)-2,max(xs)+2);ax.set_ylim(min(ys)-2,max(ys)+2);ax.set_zlim(0,7)
        ax.set_box_aspect((max(xs)-min(xs),max(ys)-min(ys),8));ax.view_init(elev=48,azim=-65)
        ax.set_xlabel('X (m)');ax.set_ylabel('Y (m)');ax.set_zlabel('높이 (m)')
    fig.suptitle('에너지융복합종합지원센터 · 지상 1·2층\n단면도 층간 높이 4.20 m / 자동 추정 요소 검토 필요',fontsize=16)
    fig.savefig('cad_output/energy-center-preview.png',dpi=160,bbox_inches='tight');plt.close(fig)
    Path('cad_output/energy-center.ifc').write_text(export_ifc(m),encoding='utf-8')
    print(f'Preview and IFC generated: {len(m.elements)} elements')

if __name__=='__main__':main()
