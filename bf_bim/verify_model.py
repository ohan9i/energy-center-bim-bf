"""Cross-check BIM against source IDs / measured geometry and render review plates."""
import json
from collections import Counter
from pathlib import Path
import hashlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import PathPatch
from matplotlib.path import Path as PlotPath
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from .schema import Model
from .geometry import solid_parts,polygon_parts
from .precision_model import select_sheet,COURTYARD
from .project_model import entity_lines,SHEET_SPACING,xy
from .ifc_export import export_ifc

def main():
    out=Path('cad_output');m=Model.model_validate_json((out/'energy-center-model.json').read_text(encoding='utf-8'))
    es=json.loads((out/'scene-compact.json').read_text(encoding='utf-8'));by_id={e['id']:e for e in es}
    assert m.links==[], 'This work must not create BF navigation links.'
    issues=[];checks=[];residuals=[]
    for floor in m.floors:
        n=0 if floor.id=='b1' else 5 if floor.id=='roof' else int(floor.id[1:]);offset=(n-1)*SHEET_SPACING
        elements=[e for e in m.elements if e.floor_id==floor.id]
        slabs=unary_union([Polygon(e.polygon,e.holes) for e in elements if e.type in ('floor','roof')])
        if floor.id!='b1':assert slabs.intersection(COURTYARD).area<.003
        for e in elements:
            p=Polygon(e.polygon,e.holes)
            if e.type in ('stair','elevator'):
                assert slabs.intersection(p).area<.005
            if e.type=='column' and e.source.get('geometry_status')=='measured_plan':
                src=by_id[e.source['cad_id']];g=src['geometry']
                if src['type']=='LWPOLYLINE':
                    original=Polygon([xy(v,offset) for v in g['vertices']])
                    residual=p.hausdorff_distance(original);residuals.append(residual)
                    assert residual<=.001, (e.id,residual)
            for id in e.source.get('cad_ids',[]):
                assert id in by_id, f'{e.id}: unknown CAD ID {id}'
            for c in e.components:
                assert Polygon(c.polygon,c.holes).is_valid
                assert e.z_offset+c.z_offset+(c.height or 0)<=5.4+.001
            if e.type in ('door','window'):assert e.height is None, 'Unmatched schedule heights must remain unknown.'
        checks.append(dict(floor=floor.id,element_count=len(elements),types=dict(Counter(e.type for e in elements)),
            slab_candidate_area_m2=round(slabs.area,3),courtyard_overlap_m2=round(slabs.intersection(COURTYARD).area,8)))
    for row in m.provenance['source_audit']:
        path=Path('에너지-건축도면')/row['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
    supplement_ids={d['file']:{e['id'] for e in d['entities']} for d in
        [json.loads(path.read_text(encoding='utf-8')) for path in out.glob('*-evidence.json')]}
    for e in m.elements:
        for candidate in e.source.get('structural_section_candidates',[]):
            assert not candidate['member_assignment_verified']
            assert all(id in supplement_ids[candidate['file']] for id in candidate['cad_ids'])
    drawing_evidence=m.provenance.get('drawing_evidence',{})
    for candidate in drawing_evidence.get('column_sections',[])+drawing_evidence.get('wall_sections',[])+drawing_evidence.get('note_candidates',[]):
        assert not candidate['member_assignment_verified']
        assert all(id in supplement_ids[candidate['file']] for id in candidate['cad_ids'])
    for glob,key in [('A04-001*.dwg','floorplan_sha256'),('A04-021*.dwg','section_sha256')]:
        assert hashlib.sha256(next(Path('에너지-건축도면').glob(glob)).read_bytes()).hexdigest()==m.provenance[key]
    plt.rcParams['font.family']='Malgun Gothic'
    palette={'wall':'#adb8b2','column':'#536a75','window':'#47aacb','door':'#b37a3a','space':'#bcd7cb','corridor':'#c1d7e7','floor':'#f0ece1','roof':'#d4dce0','stair':'#928875','elevator':'#7e91a8','opening':'#d6b881'}
    def patch(ax,p,color,alpha=1):
        from shapely.geometry.polygon import orient
        p=orient(p,sign=1);vertices=[];codes=[]
        for r in [p.exterior,*p.interiors]:
            coords=list(r.coords);vertices.extend(coords);codes.extend([PlotPath.MOVETO]+[PlotPath.LINETO]*(len(coords)-2)+[PlotPath.CLOSEPOLY])
        ax.add_patch(PathPatch(PlotPath(vertices,codes),facecolor=color,edgecolor=color,linewidth=.2,alpha=alpha))
    fig,axes=plt.subplots(2,3,figsize=(19,12))
    for ax,floor in zip(axes.flat,m.floors):
        n=0 if floor.id=='b1' else 5 if floor.id=='roof' else int(floor.id[1:]);off=(n-1)*SHEET_SPACING
        cad=[l for e in select_sheet(es,n) if e['layer'] in {'A-CON','A-BRICK','A-COL','A-AL03','A-WIN','A-DOOR','A-DOR','A-STAIR','A-FIN'} for l in entity_lines(e,off)]
        elements=[e for e in m.elements if e.floor_id==floor.id]
        for kind in ('floor','roof','space','corridor','stair','elevator','wall','column','window','door'):
            for e in elements:
                if e.type!=kind or e.source.get('marker_width_m'):continue
                patch(ax,Polygon(e.polygon,e.holes),palette[kind],.38 if kind in ('space','corridor') else .8)
        ax.add_collection(LineCollection([list(l.coords) for l in cad],colors='#bd3434',linewidths=.25,alpha=.45))
        for place in m.places:
            if place.floor_id==floor.id and 'E.V' not in place.name:ax.text(*place.point,place.name,fontsize=5,color='#163d4a')
        ax.set_xlim(5,83);ax.set_ylim(15,65);ax.set_aspect('equal');ax.set_title(f'{floor.name} · Z {floor.elevation:.2f} m');ax.set_xlabel('X (m)');ax.set_ylabel('Y (m)');ax.grid(alpha=.15)
    fig.suptitle('실제 도면과 BIM 대조 · 지하 1층 / 지상 1~4층 / 지붕 후보\n빨강: CAD 선 · 재질색: BIM 재구성 후보 (확정 수량 아님)',fontsize=18);fig.tight_layout();fig.savefig(out/'bim-cad-comparison.png',dpi=170);plt.close(fig)
    # Render assemblies using precisely the geometry exported to IFC.
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig=plt.figure(figsize=(16,10));ax=fig.add_subplot(111,projection='3d')
    for e in m.elements:
        if e.type in ('space','corridor','opening','roof') or e.source.get('marker_width_m'):continue
        elevation=next(f.elevation for f in m.floors if f.id==e.floor_id)+m.floors.index(next(f for f in m.floors if f.id==e.floor_id))*3
        for p,z,depth in solid_parts(e,m.elements):
            # Polygon triangulation preserves courtyard/core holes in preview slabs.
            if depth is None:
                from shapely import constrained_delaunay_triangles
                for tri in constrained_delaunay_triangles(p).geoms:ax.add_collection3d(Poly3DCollection([[(x,y,elevation+z) for x,y in tri.exterior.coords]],facecolor=palette.get(e.type,'#ccc'),edgecolor='none',alpha=.55))
                continue
            faces=[]
            for r in [p.exterior,*p.interiors]:
                points=list(r.coords)
                faces.extend([[(a[0],a[1],elevation+z),(b[0],b[1],elevation+z),(b[0],b[1],elevation+z+depth),(a[0],a[1],elevation+z+depth)] for a,b in zip(points,points[1:])])
            ax.add_collection3d(Poly3DCollection(faces,facecolor=palette.get(e.type,'#ccc'),edgecolor='#61717b',linewidth=.1,alpha=.16 if e.type=='elevator' else .85))
            from shapely import constrained_delaunay_triangles
            caps=[]
            for tri in constrained_delaunay_triangles(p).geoms:
                for level in (elevation+z,elevation+z+depth):
                    caps.append([(x,y,level) for x,y in tri.exterior.coords])
            ax.add_collection3d(Poly3DCollection(caps,facecolor=palette.get(e.type,'#ccc'),edgecolor='none',alpha=.85))
    ax.set_xlim(5,83);ax.set_ylim(15,65);ax.set_zlim(0,35);ax.set_box_aspect((78,50,35));ax.view_init(elev=38,azim=-65)
    ax.set_title('BIM 조립체 검토 · 층별 표시 간격 3 m\n슬래브·창호·샤프트 임시 치수 포함 / 지붕 후보 숨김',fontsize=14)
    fig.savefig(out/'energy-center-preview.png',dpi=150,bbox_inches='tight');plt.close(fig)
    (out/'energy-center.ifc').write_text(export_ifc(m),encoding='utf-8')
    report=dict(status='automated_geometric_checks_passed',not_certified=True,floors=checks,
        audited_drawing_count=len({r['file'] for r in m.provenance['source_audit']})+1,
        maximum_column_plan_deviation_m=max(residuals,default=0),source_hashes_unchanged=True,
        unknown_door_window_heights_preserved=True,assemblies=sum(len(e.components) for e in m.elements),
        limitations=m.provenance['missing_information'],browser_visual_check='unavailable: browser inventory empty; Chrome creation rejected')
    (out/'bim-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
