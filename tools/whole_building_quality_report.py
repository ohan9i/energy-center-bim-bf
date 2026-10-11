"""Revision 7 measurements against published revision 6 and preserved native CAD."""
from collections import Counter
import hashlib
import json
import math
import subprocess
import ifcopenshell
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shapely.geometry import Polygon
from shapely.ops import unary_union
from bf_bim.precise.rebuild import ROOT,OUTPUT,AUDIT,read,load_archive,native_profile
from bf_bim.precise.schema import Registration
from bf_bim.precise.coordination_quality import opening_axis

OUT=OUTPUT/'coordination-v2'
BASELINE='a921c2c'

def signature(e):
    data=[Polygon(e['polygon'],e.get('holes',[])).normalize().wkt,
          [(c['role'],c['z_offset'],c['height'],Polygon(c['polygon'],c.get('holes',[])).normalize().wkt,c.get('mesh')) for c in e['components']]]
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def main():
    ref=subprocess.check_output(['git','rev-parse',BASELINE],cwd=ROOT,text=True).strip()
    before=json.loads(subprocess.check_output(['git','show',ref+':web/public/models/precision-rebuild.json'],cwd=ROOT))
    after=read(OUT/'preview.json');old={e['id']:e for e in before['elements']};now={e['id']:e for e in after['elements']}
    assert after['provenance']['modelling_version']==10
    changed=[e for e in after['elements'] if e['id'] in old and signature(e)!=signature(old[e['id']])]
    groups=[e for e in after['elements'] if e['source'].get('native_door_evidence')]
    rows=read(AUDIT/'drawing-index.json');archive,row=load_archive('A04-001~008',rows)
    lookup={q['id']:q for q in archive['scene_entities']};specs={s['id']:s for s in after['provenance']['floors_evidence']}
    measurements=[];native_plans={}
    walls={}
    for label,model in [('before',before),('after',after)]:
        walls[label]={f:unary_union([Polygon(c['polygon'],c.get('holes',[])) for e in model['elements']
            if e['type']=='wall' and e['floor_id']==f for c in e['components']
            if c['z_offset']<=1<c['z_offset']+c['height']]) for f in specs}
    for e in groups:
        s=e['source'];a=s['door_plan_axis'];ev=s['native_door_evidence'];fid=e['floor_id']
        frame=Registration(id='independent',drawing_id='A04-001~008',origin_cad=tuple(specs[fid]['origin']),scale_m_per_unit=.001)
        jambs=[]
        for identity in ev['cad_ids'][:2]:
            line,p=native_profile(lookup[identity],frame)
            if p is None and line.is_ring:p=Polygon(line.coords)
            assert p is not None
            jambs.append(p)
        native=unary_union(jambs).convex_hull
        residual=native.hausdorff_distance(Polygon(e['polygon'],e['holes']))
        assert residual<1e-6
        native_plans[e['id']]=jambs
        cx,cy=a['origin'];ux,uy=a['direction'];w=a['width_m'];d=a['depth_m'];f=ev['jamb_width_m']
        clear=Polygon([(cx+ux*x-uy*y,cy+uy*x+ux*y) for x,y in [(-w/2+f,-d/2),(w/2-f,-d/2),(w/2-f,d/2),(-w/2+f,d/2)]])
        prev=old[e['id']];v=opening_axis(prev)
        angle=math.degrees(math.acos(min(1,abs(v[1][0]*ux+v[1][1]*uy))))
        measurements.append({'element_id':e['id'],'floor_id':fid,'native_width_m':w,'before_leaf_candidate_width_m':v[2],
            'before_width_difference_m':abs(w-v[2]),'before_axis_difference_deg':angle,
            'native_outer_boundary_hausdorff_m':residual,'bridge_residual_m':ev['width_bridge_residual_m'],
            'former_leaf_candidates':len(ev['original_leaf_candidates']),
            'wall_occupied_clear_envelope_at_z1_m2':{k:clear.intersection(walls[k][fid]).area for k in walls},
            'height_status':s['property_status'].get('height'),'design_verified':e['verified']})
    xrefs=[];levels=[]
    for name in ('S02-001~','S02-021~','A07-011~','A06-001~013'):
        arc,r=load_archive(name,rows)
        for x in r['external_references']:
            xrefs.append({'drawing':r['file'],'source_sha256':r['sha256'],'name':x['id'],'exists':x['exists'],
                          'embedded_entity_count':x.get('embedded_entity_count'),
                          'contents_extracted':x['contents_extracted']})
        for q in arc['scene_entities']:
            if q['type'] in ('TEXT','MTEXT') and ('59.30' in q['geometry'].get('text','') or '59.90' in q['geometry'].get('text','')):
                levels.append({'drawing':r['file'],'cad_id':q['id'],'text':q['geometry']['text'],'source_sha256':r['sha256']})
        del arc
    section,r=load_archive('A04-021~026',rows)
    for q in section['scene_entities']:
        if q['type'] in ('TEXT','MTEXT') and '59.90' in q['geometry'].get('text',''):
            levels.append({'drawing':r['file'],'cad_id':q['id'],'text':q['geometry']['text'],'source_sha256':r['sha256']})
    del section,archive
    f=ifcopenshell.open(str(OUT/'energy-center-Coordination-Draft.ifc'))
    semantics={k:len(f.by_type(k)) for k in ('IfcDoorType','IfcWindowType','IfcOpeningElement','IfcRelVoidsElement','IfcRelFillsElement','IfcRelDefinesByType')}
    assert semantics['IfcDoorType']==1 and semantics['IfcWindowType']==6
    typed=sum(len(r.RelatedObjects) for r in f.by_type('IfcRelDefinesByType'))
    assert typed==17
    spatial=after['provenance']['bf_spatial'];portals={p['element_id']:p for p in spatial['portals']}
    for e in groups:
        assert e['id'] in portals
        assert not any(i in portals for i in e['source']['native_door_evidence']['superseded_leaf_ids'])
        p=portals[e['id']]
        assert p['status']=='unresolved' and p['properties']['clear_width'] is None
    floor_review=[]
    for fid in ('b1','f1','f2','f3','f4','roof','phroof','pit','ph'):
        es=[e for e in after['elements'] if e['floor_id']==fid]
        floor_review.append({'floor_id':fid,'elements':len(es),'components':sum(len(e['components']) for e in es),
            'types':dict(Counter(e['type'] for e in es)),
            'native_door_assemblies':sum(e in groups for e in es),
            'removed_leaf_duplicates':sum(len(e['source']['native_door_evidence']['superseded_leaf_ids']) for e in es if e in groups),
            'changed_geometry':dict(Counter(e['type'] for e in changed if e['floor_id']==fid)),
            'recovered_native_wall_parts':sum(bool(e['source'].get('native_wall_closure')) for e in es),
            'verified_solids':sum(e['verified'] for e in es)})
    report={'baseline_git_ref':ref,'before_revision':before['revision'],'after_revision':after['revision'],
        'before_elements':len(before['elements']),'after_elements':len(after['elements']),
        'before_components':sum(len(e['components']) for e in before['elements']),
        'after_components':sum(len(e['components']) for e in after['elements']),
        'changed_geometry_by_type':dict(Counter(e['type'] for e in changed)),
        'removed_elements':[{'id':i,'type':e['type'],'floor_id':e['floor_id']} for i,e in old.items() if i not in now],
        'added_elements':[{'id':i,'type':e['type'],'floor_id':e['floor_id']} for i,e in now.items() if i not in old],
        'floor_review':floor_review,'native_door_measurements':measurements,
        'wall_recovery':read(OUT/'wall-recovery-validation.json'),
        'wall_source_coverage_before':read(OUT/'wall-source-coverage-baseline.json'),
        'wall_source_coverage_after':read(OUT/'wall-source-coverage.json'),
        'candidate_space_coverage':read(OUT/'space-coverage.json'),
        'ifc_semantics':semantics,'typed_instances':typed,'source_xref_audit':xrefs,
        'unresolved_roof_level_observations':levels,'roof_level_conflict_m':.6,
        'bf':{'before_portals':len(before['provenance']['bf_spatial']['portals']),'after_portals':len(portals),
              'approved_spaces':sum(p['status']=='confirmed' for p in spatial['spaces']),
              'approved_portals':sum(p['status']=='confirmed' for p in spatial['portals']),
              'actual_route_verified':False,'reason':'Actual interior boundaries, door/vertical operational conditions unresolved.'},
        'ifc_validation':read(OUT/'validation.json')['draft_ifc'],'source_preservation':{k:v for k,v in read(OUT/'preservation.json').items() if k!='hashes_before'}}
    if (OUT/'source-preservation-after-task.json').exists():
        report['post_task_preservation']=read(OUT/'source-preservation-after-task.json')
    (OUT/'whole-building-quality.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    # Side by side comparison uses native profiles, not a screenshot of a second generated model.
    identity='coord-48640c9874f6dd4d4424';e=now[identity];ev=e['source']['native_door_evidence'];axis=e['source']['door_plan_axis']
    cx,cy=axis['origin'];ux,uy=axis['direction']
    def local(poly):return [((x-cx)*ux+(y-cy)*uy,-(x-cx)*uy+(y-cy)*ux) for x,y in poly.exterior.coords]
    fig,axs=plt.subplots(1,3,figsize=(15,4))
    for ax,title in zip(axs,['Native CAD jambs + whole opening','Revision 6: separate arc candidates','Revision 7: restored whole opening']):
        for p in native_plans[identity]:
            x,y=zip(*local(p));ax.fill(x,y,color='#263b52',alpha=.5)
        ax.set_title(title);ax.set_aspect('equal');ax.grid(alpha=.2);ax.set_xlim(-1.6,1.6);ax.set_ylim(-1.5,1.5);ax.set_xlabel('m')
    for original in ev['original_leaf_candidates']:
        p=Polygon(old[original['element_id']]['polygon']);x,y=zip(*local(p));axs[1].fill(x,y,color='#cc6240',alpha=.35)
    p=Polygon(e['polygon']);x,y=zip(*local(p));axs[0].plot(x,y,color='#26846b');axs[2].plot(x,y,color='#26846b')
    for c in e['components']:
        if c['z_offset']<=1<c['z_offset']+c['height']:
            x,y=zip(*local(Polygon(c['polygon'])));axs[2].plot(x,y,color='#478fbb' if c['source']['material']=='glazing' else '#444')
    fig.tight_layout();fig.savefig(OUT/'whole-building-door-before-after.png',dpi=160);plt.close(fig)
    print(json.dumps({k:v for k,v in report.items() if k in ('before_elements','after_elements','before_components','after_components','changed_geometry_by_type','ifc_semantics','source_preservation','bf','floor_review')},ensure_ascii=True))

if __name__=='__main__':main()
