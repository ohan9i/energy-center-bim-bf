"""Measure current structural additions against published revision 7."""
import hashlib,json,subprocess,gzip,math
from collections import Counter
from pathlib import Path
from shapely.geometry import Polygon,LineString
from shapely.ops import unary_union
from bf_bim.precise.rebuild import ROOT,read
OUT=ROOT/'cad_output/precision-rebuild/coordination-v2'

def main():
    baseline=json.loads(subprocess.check_output(['git','show','b39c661:web/public/models/precision-rebuild.json']))
    model=read(OUT/'preview.json');evidence=read(OUT/'structural-authoring-validation.json')
    floors={f['id']:f['elevation'] for f in model['floors']};lookup={e['id']:e for e in model['elements']}
    beams=[e for e in model['elements'] if e['type']=='beam'];overlaps={};headroom=[]
    for fid in ['f1','f2','f3','f4','roof']:
        ps=[unary_union([Polygon(c['polygon'],c['holes']) for c in e['components']]) for e in beams if e['floor_id']==fid]
        overlaps[fid]=max(0,sum(p.area for p in ps)-unary_union(ps).area)
    for beam in beams:
        lower=lookup[beam['source']['structural_girder']['support_ids'][0]]['floor_id']
        for c in beam['components']:
            headroom.append(floors[beam['floor_id']]+c['z_offset']-floors[lower])
    backup=[]
    for p in (ROOT/'cad_output/precision-rebuild/structural-inspection').glob('*-backup.json.gz'):
        with gzip.open(p,'rt',encoding='utf8') as f:a=json.load(f)
        r=a['backup_original'];assert hashlib.sha256((ROOT/r['file']).read_bytes()).hexdigest()==r['sha256']
        backup.append({**r,'original_unchanged':True,'scene_entities':len(a['scene_entities']),
                       'xref_embedded_entity_counts':[r['embedded_entity_count'] for r in a['external_references'] if r['kind']=='xref']})
    report={'baseline':'b39c661 / revision 7','revision':model['revision'],'modelling_version':model['provenance']['modelling_version'],
      'before_elements':len(baseline['elements']),'after_elements':len(model['elements']),
      'before_components':sum(len(e['components']) for e in baseline['elements']),
      'after_components':sum(len(e['components']) for e in model['elements']),
      'before_beams':sum(e['type']=='beam' for e in baseline['elements']),'girders_by_floor':dict(Counter(e['floor_id'] for e in beams)),
      'slab_assignments':evidence['slab_assignments'],'wall_head_cuts':len(evidence['wall_head_cuts']),
      'removed_duplicate_wall_volume_m3':sum(q['removed_duplicate_volume_m3'] for q in evidence['wall_head_cuts']),
      'beam_duplicate_area_m2_by_floor':overlaps,'provisional_min_clearance_over_supporting_floor_m':min(headroom),
      'max_native_axis_normal_residual_m':max(r['max_normal_residual_m'] for r in evidence['registrations']),
      'unresolved_by_reason':dict(Counter(q['reason'] for q in evidence['unresolved'])),
      'backup_audit':backup,'ifc':read(OUT/'validation.json')['draft_ifc'],
      'source_preservation':{k:v for k,v in read(OUT/'preservation.json').items() if k!='hashes_before'},
      'bf':{'spaces':len(model['provenance']['bf_spatial']['spaces']),'portals':len(model['provenance']['bf_spatial']['portals']),
            'verified_actual_route':False,'native_beam_outline_recovered':False}}
    (OUT/'structural-quality.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family']='Malgun Gothic'
    fig,axes=plt.subplots(1,2,figsize=(15,7))
    for ax,src,title in zip(axes,[baseline,model],['Revision 7: 구조 보 미구현','Revision 8: 주열·보 부호·기둥 경간·단면표 해석']):
        for e in src['elements']:
            if e['floor_id']!='f2':continue
            if e['type']=='floor':
                p=Polygon(e['polygon'],e['holes']);x,y=p.exterior.xy;ax.fill(x,y,color='#dfe5eb',alpha=.45)
            if e['type']=='column':
                p=Polygon(e['polygon'],e['holes']);x,y=p.exterior.xy;ax.fill(x,y,color='#334c5a')
            if e['type']=='beam':
                for c in e['components']:
                    p=Polygon(c['polygon'],c['holes']);x,y=p.exterior.xy;ax.fill(x,y,color='#b87836')
                s=e['source']['structural_girder'];a,b=s['axis'];ax.text((a[0]+b[0])/2,(a[1]+b[1])/2,s['mark'],fontsize=6,color='#744d26')
        ax.set_aspect('equal');ax.set_xlim(-5,80);ax.set_ylim(-5,75);ax.grid(alpha=.15);ax.set_title(title);ax.set_xlabel('m')
    fig.tight_layout(pad=2);fig.savefig(OUT/'structural-before-after-f2.png',dpi=150,bbox_inches='tight');plt.close(fig)
    print(json.dumps({k:v for k,v in report.items() if k not in ('slab_assignments','backup_audit','ifc')},ensure_ascii=True))

if __name__=='__main__':main()
