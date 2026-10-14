"""Apply current exterior/roof coordination to a preserved revision 9.

The normal full rebuild also calls the same author and numerical cleanup.
This fast path refuses a changed strict model or generator input dependency.
"""
import json
import shutil
import argparse
from copy import deepcopy
from pathlib import Path
from collections import Counter
from bf_bim.schema import Model
from bf_bim.ifc_export import export_ifc
from bf_bim.validate_ifc import validate_file
from bf_bim.precise.coordination import ROOT,BASE,OUT,save,sha256,normalize_components
from bf_bim.precise.coordination_quality import attach_evidence,audit_relationships,audit_navigation_junctions,verified_model_dict
from bf_bim.precise.photo_exterior import apply_photo_exterior
from bf_bim.precise.completion import complete_parapets,trim_solid_junctions
from bf_bim.precise.building_review import audit_building
from bf_bim.precision_model import COURTYARD
from bf_bim.spatial_navigation import build_spatial,OUTPUT as SPATIAL_OUTPUT
from shapely.geometry import Polygon,LineString
from shapely.ops import unary_union


def retained_remnant_review(baseline):
    """Recover the 44 observations without reclassifying or re-extracting CAD."""
    observations=json.loads((BASE/'wall-remnant-observations.json').read_text(encoding='utf8'))['elements']
    by_id={e['id']:e for e in baseline['elements']}
    traces={(t['floor_id'],t['id']):t for t in baseline['provenance']['cad_traces']}
    records=[]
    for old in observations:
        current=by_id[old['id']];p=Polygon(old['polygon'],old['holes'])
        curves=[{'cad_id':i,'points':traces[(old['floor_id'],i)]['points'],
                 'native_type':traces[(old['floor_id'],i)]['native_type'],
                 'tolerance_m':traces[(old['floor_id'],i)]['tolerance_m']}
                for i in old['source']['cad_ids'] if (old['floor_id'],i) in traces]
        if not curves:raise ValueError('Preserved native remnant evidence missing: '+old['id'])
        records.append({'id':old['id'],'floor_id':old['floor_id'],'cad_ids':old['source']['cad_ids'],
            'source_sha256':old['source']['source_sha256'],
            'classification':current['source']['candidate_classification'],
            'classification_reason':current['source']['classification_reason'],
            'residual_area_m2':p.area,'effective_width_m':2*p.area/p.length,
            'source_curve_distance_m':p.distance(unary_union([LineString(c['points']) for c in curves])),
            'native_curves':curves,'solid_restored':bool(current['components']),
            'action':'retain original revision 9 classification and preserved native trace observations',
            'design_classification_verified':False,'reclassification_performed':False})
    return records


def build(baseline, sync_web=False, preview_only=False):
    data=json.loads(baseline.read_text(encoding='utf8'))
    prior_checks=json.loads((OUT/'validation.json').read_text(encoding='utf8'))
    remnant_review=prior_checks.get('boolean_remnant_review') or retained_remnant_review(data)
    if data['revision']!=9:raise ValueError('Exterior-only build requires the preserved revision 9; use full coordination rebuild otherwise.')
    for key,path in [('candidate_cache_sha256',ROOT/'cad_output/energy-center-model.json'),('strict_stage_sha256',BASE/'bim.json')]:
        if data['provenance'][key]!=sha256(path):raise ValueError('Source dependency changed: '+key)
    specs={s['id']:s for s in data['provenance']['floors_evidence']}
    removed_parapets={e['id'] for e in data['elements'] if any(c['role']=='assumed_parapet' for c in e['components'])}
    elements=[deepcopy(e) for e in data['elements'] if e['id'] not in removed_parapets]
    parapets=complete_parapets(elements,specs)
    report=apply_photo_exterior(elements,specs)
    report['slab_junctions']=trim_solid_junctions(elements,specs,
        selected_ids={e['id'] for e in elements if e['source'].get('photo_reference')})
    # The baseline solids already passed numerical cleanup and IFC validation.
    # Preserve their vertex ordering too; normalise only newly authored solids.
    authored={r['id'] for r in parapets}
    normalize_components([e for e in elements if e['source'].get('photo_reference') or e['id'] in authored],specs)
    building_review=audit_building(elements,list(specs.values()))
    assert building_review['summary']['maximum_slab_pair_volume_m3']<1e-5
    assert building_review['summary']['maximum_opaque_opening_residual_m3']<1e-5
    assert building_review['summary']['facade_missing_volume_m3']<.001
    assert building_review['summary']['parapet_outside_boundary_volume_m3']<1e-5
    # Original CAD geometry must be byte-identical for an exterior-only change.
    current={e['id']:e for e in elements}
    fields=('polygon','holes','height','z_offset','mesh','role')
    changed=[]
    for old in data['elements']:
        if old['id'] in removed_parapets:continue
        new=current[old['id']]
        if any(old[k]!=new[k] for k in ('polygon','holes','height','z_offset')) or [{k:c.get(k) for k in fields} for c in old['components']]!=[{k:c.get(k) for k in fields} for c in new['components']]:changed.append(old['id'])
    if changed:raise AssertionError('Exterior-only build changed preserved geometry: '+str(changed[:10]))
    missing={e['source']['file']:e['source'].get('missing_references',[]) for e in elements}
    decisions=attach_evidence(elements,list(specs.values()),missing)
    relationships=audit_relationships(elements,list(specs.values()),COURTYARD)
    junctions=audit_navigation_junctions(elements,list(specs.values()))
    data.update(revision=11,elements=elements)
    data['warnings'].append('외장과 외벽 BIPV는 현장 사진 기반 표현입니다. 외장 깊이와 패널 치수·배치는 추정이며 준공 실측 모델이 아닙니다.')
    data['provenance'].update(modelling_version=14,photo_exterior=report,building_3d_review=building_review['summary'],junction_audit=junctions['summary'],verified_solids=sum(d['eligible'] for d in decisions))
    data['provenance']['assumed_completion']['elements']=sum(bool(e['source'].get('user_assumed_completion')) for e in elements)
    model=Model.model_validate(data)
    overrides=SPATIAL_OUTPUT/'overrides.json'
    model.provenance['bf_spatial']=build_spatial(model.model_dump(mode='json'),json.loads(overrides.read_text('utf8')) if overrides.exists() else None)
    save('photo-review-preview.json',model.model_dump(mode='json'))
    if preview_only:
        print('Local review preview written; public model and IFC unchanged.',flush=True)
        return
    verified=Model.model_validate(verified_model_dict(model))
    for m,name,draft in [(model,'energy-center-Coordination-Draft.ifc',True),(verified,'energy-center-Verified.ifc',False)]:
        print('Exporting',name,flush=True);(OUT/name).write_text(export_ifc(m,coordination_draft=draft),encoding='utf8')
    print('Validating IFC every solid, volume and world coordinates',flush=True)
    checks={**prior_checks,**{key:validate_file(m,OUT/name) for key,m,name in [('draft_ifc',model,'energy-center-Coordination-Draft.ifc'),('verified_ifc',verified,'energy-center-Verified.ifc')]}}
    checks.update(architectural_relationships=relationships,navigation_junctions=junctions,certified_design=False,
        boolean_remnant_review=remnant_review,
        exterior_only_preservation={'baseline_sha256':sha256(baseline),'original_elements':len(data['elements'])-len(report['added'])-len(parapets),
            'changed_geometry':changed,'replaced_assumed_parapets':len(removed_parapets)})
    save('preview.json',model.model_dump(mode='json'));save('verified-model.json',verified.model_dump(mode='json'))
    save('validation.json',checks);save('photo-exterior-validation.json',report)
    save('building-3d-review.json',building_review)
    save('member-validation.json',{'policy':'member-evidence/1','verified_solids':model.provenance['verified_solids'],'members':decisions})
    prior_summary=json.loads((OUT/'summary.json').read_text(encoding='utf8'))
    summary={**prior_summary,'status':'coordination_draft','elements':len(elements),'components':sum(len(e['components']) for e in elements),
        'types':dict(Counter(e['type'] for e in elements)),'floors':dict(Counter(e['floor_id'] for e in elements)),
        'verified_solids':model.provenance['verified_solids'],'photo_exterior_added':len(report['added']),'ifc':checks}
    save('summary.json',summary)
    if sync_web:
        for src,dst in [('preview.json','precision-rebuild.json'),('energy-center-Verified.ifc','precision-rebuild-verified.ifc'),('energy-center-Coordination-Draft.ifc','precision-rebuild-coordination-draft.ifc')]:shutil.copyfile(OUT/src,ROOT/'web/public/models'/dst)
    print(json.dumps({k:summary[k] for k in ('elements','components','verified_solids','photo_exterior_added')}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline',type=Path);parser.add_argument('--sync-web',action='store_true')
    parser.add_argument('--preview-only',action='store_true')
    args=parser.parse_args();build(args.baseline,args.sync_web,args.preview_only)
