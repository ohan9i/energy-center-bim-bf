"""Compare current actual solids against the preserved revision 8 Git artifact.

No route search or synthetic building-success example is performed.
"""
from collections import Counter
import json
from pathlib import Path
import subprocess

from shapely.ops import unary_union
from shapely.strtree import STRtree
from bf_bim.precise.completion import profile
from bf_bim.assembly_solids import mesh_volume

OUT=Path('cad_output/precision-rebuild/coordination-v2')
BASELINE='975b947'


def slab_penetrations(m):
    elevations={f['id']:f['elevation'] for f in m['floors']}
    slabs=[(profile(c),elevations[e['floor_id']]+c['z_offset'],
            elevations[e['floor_id']]+c['z_offset']+c['height'],e['id'])
        for e in m['elements'] if e['type'] in ('floor','roof') for c in e['components']]
    tree=STRtree([p for p,_,_,_ in slabs]);volume=0.;largest=0.;pairs=0
    for e in m['elements']:
        if e['type'] not in ('wall','column','beam','elevator') or e['floor_id']=='pit':continue
        for c in e['components']:
            p=profile(c);a=elevations[e['floor_id']]+c['z_offset'];b=a+c['height']
            for i in tree.query(p):
                q,x,y,_=slabs[i];h=min(b,y)-max(a,x)
                if h<=1e-7:continue
                v=p.intersection(q).area*h
                if v>1e-8:volume+=v;largest=max(largest,v);pairs+=1
    return {'duplicate_volume_m3':volume,'maximum_pair_volume_m3':largest,'intersecting_pairs':pairs}


def beam_duplicates(m):
    result={}
    for fid in ['f1','f2','f3','f4','roof']:
        beams=[unary_union([profile(c) for c in e['components']]) for e in m['elements']
               if e['floor_id']==fid and e['type']=='beam']
        result[fid]=max(0.,sum(p.area for p in beams)-unary_union(beams).area)
    return result


def main():
    before=json.loads(subprocess.check_output(['git','show',BASELINE+':web/public/models/precision-rebuild.json']))
    after=json.loads((OUT/'preview.json').read_text(encoding='utf8'))
    current={e['id']:e for e in after['elements']}
    checks={}
    for kind in ('window','door','column'):
        es=[e for e in before['elements'] if e['type']==kind]
        changes=[e['id'] for e in es if e['id'] not in current or profile(e).symmetric_difference(profile(current[e['id']])).area>1e-9]
        checks[kind]={'observed_profiles':len(es),'changed_plan_profiles':changes}
    portal_changes=[]
    for e in before['elements']:
        if e['type'] not in ('window','door'):continue
        q=current[e['id']]
        if e['source']['provisional_opening']!=q['source']['provisional_opening']:portal_changes.append(e['id'])
        def geometry(x):return [{k:c.get(k) for k in ('polygon','holes','height','z_offset','mesh','role')} for c in x['components']]
        if geometry(e)!=geometry(q):portal_changes.append(e['id'])
    before_area={fid:sum(profile(e).area for e in before['elements'] if e['floor_id']==fid and e['type'] in ('floor','roof') and e['components']) for fid in ('b1','f1','f2','f3','f4','roof','phroof')}
    after_area={fid:sum(profile(e).area for e in after['elements'] if e['floor_id']==fid and e['type'] in ('floor','roof') and e['components']) for fid in before_area}
    completion=json.loads((OUT/'completion-validation.json').read_text(encoding='utf8'))
    report={'baseline_commit':BASELINE,'before_revision':before['revision'],'after_revision':after['revision'],
        'before_counts':dict(Counter(e['type'] for e in before['elements'])),
        'after_counts':dict(Counter(e['type'] for e in after['elements'])),
        'before_slab_penetrations':slab_penetrations(before),'after_slab_penetrations':slab_penetrations(after),
        'after_beam_duplicate_area_m2':beam_duplicates(after),
        'preserved_plan_profiles':checks,'changed_portal_geometries':sorted(set(portal_changes)),
        'slab_parent_area_m2':{fid:{'before':before_area[fid],'after':after_area[fid],
            'difference':after_area[fid]-before_area[fid]} for fid in before_area},
        'inferred_beams_by_floor':dict(Counter(e['floor_id'] for e in completion['beams']['added'])),
        'inferred_wall_infills_by_floor':dict(Counter(e['floor_id'] for e in completion['walls'])),
        'inferred_portal_hosts_by_floor':dict(Counter(e['floor_id'] for e in completion['portal_hosts'])),
        'shaft_compartments':completion['shafts'],
        'maximum_prism_profile_mesh_volume_difference_m3':max((abs(mesh_volume(c['mesh'])-profile(c).area*c['height'])
            for e in after['elements'] if e['type']!='stair' for c in e['components'] if c.get('mesh')),default=0.),
        'route_calculated':False,'design_verified':False}
    (OUT/'completion-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert all(not r['changed_plan_profiles'] for r in checks.values())
    assert not portal_changes
    assert report['after_slab_penetrations']['maximum_pair_volume_m3']<1e-5
    assert max(report['after_beam_duplicate_area_m2'].values())<1e-5
    assert report['maximum_prism_profile_mesh_volume_difference_m3']<1e-7
    print(json.dumps({k:report[k] for k in ('before_slab_penetrations','after_slab_penetrations','inferred_beams_by_floor','inferred_portal_hosts_by_floor')},ensure_ascii=False))


if __name__=='__main__':main()
