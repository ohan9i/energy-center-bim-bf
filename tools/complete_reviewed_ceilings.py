"""Update published coordination JSON/IFC from the existing model, without DWG."""
import json
from collections import Counter
from pathlib import Path

from bf_bim.precise.ceiling_completion import complete_ceilings
from bf_bim.schema import Model
from bf_bim.ifc_export import export_ifc
from bf_bim.validate_ifc import validate_file
from bf_bim.spatial_navigation import build_spatial
from bf_bim.precise.coordination_quality import attach_evidence
from bf_bim.precise.coordination_quality import verified_model_dict
from bf_bim.precise.coordination import normalize_components,OUT,save
from bf_bim.precise.building_review import audit_building


def main():
    root = Path(__file__).resolve().parents[1]
    target = root/'web/public/models/precision-rebuild.json'
    data = json.loads(target.read_text(encoding='utf-8'))
    before = data['elements'].copy()
    report = complete_ceilings(data['elements'], data['floors'])
    specs={s['id']:s for s in data['provenance']['floors_evidence']}
    normalize_components([e for e in data['elements'] if e['source'].get('ceiling_completion')],specs)
    decisions=attach_evidence([e for e in data['elements'] if e['source'].get('ceiling_completion')], data['floors'], {})
    # Normalize defaults before comparison so reruns don't bump the revision.
    model = Model.model_validate(data)
    if Model.model_validate({**data, 'elements': before}).elements != model.elements:
        model.revision += 1
    model.provenance['ceiling_completion'] = {'version': 1, 'design_verified': False, 'floors': report}
    model.provenance['modelling_version']=15
    review=audit_building(model.model_dump(mode='json')['elements'],list(specs.values()))
    assert review['summary']['maximum_slab_pair_volume_m3']<1e-5
    assert review['summary']['maximum_opaque_opening_residual_m3']<1e-5
    assert review['summary']['facade_missing_volume_m3']<.001
    assert review['summary']['parapet_outside_boundary_volume_m3']<1e-5
    model.provenance['building_3d_review']=review['summary']
    model.provenance['assumed_completion']['elements']=sum(bool(e.source.get('user_assumed_completion')) for e in model.elements)
    model.provenance['bf_spatial'] = build_spatial(model.model_dump(mode='json'), model.provenance.get('bf_spatial'))
    output = root/'cad_output/ceiling-review'
    output.mkdir(parents=True, exist_ok=True)
    staging = output/'precision-rebuild-coordination-draft.ifc'
    print('Exporting coordination IFC', flush=True)
    staging.write_text(export_ifc(model, coordination_draft=True), encoding='utf-8')
    print('Validating IFC schema, every solid, volumes and coordinates', flush=True)
    validation = validate_file(model, staging)
    verified=Model.model_validate(verified_model_dict(model))
    verified_path=output/'precision-rebuild-verified.ifc'
    verified_path.write_text(export_ifc(verified),encoding='utf8')
    verified_validation=validate_file(verified,verified_path)
    target.write_text(model.model_dump_json(indent=2), encoding='utf-8')
    (target.parent/staging.name).write_bytes(staging.read_bytes())
    (target.parent/verified_path.name).write_bytes(verified_path.read_bytes())
    save('preview.json',model.model_dump(mode='json'))
    save('verified-model.json',verified.model_dump(mode='json'))
    save('building-3d-review.json',review)
    (OUT/'energy-center-Coordination-Draft.ifc').write_bytes(staging.read_bytes())
    (OUT/'energy-center-Verified.ifc').write_bytes(verified_path.read_bytes())
    checks=json.loads((OUT/'validation.json').read_text(encoding='utf8'))
    checks.update(draft_ifc=validation,verified_ifc=verified_validation,building_3d_review=review,
                  ceiling_completion=report)
    save('validation.json',checks)
    member_file=OUT/'member-validation.json'
    ledger=json.loads(member_file.read_text(encoding='utf8'))
    members={d['id']:d for d in ledger['members']};members.update({d['id']:d for d in decisions})
    ledger['members']=[d for e in model.elements if (d:=members.get(e.id)) is not None]
    save('member-validation.json',ledger)
    completion=json.loads((OUT/'completion-validation.json').read_text(encoding='utf8'))
    completion['ceilings']=report;save('completion-validation.json',completion)
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf8'))
    summary.update(elements=len(model.elements),components=sum(len(e.components) for e in model.elements),
        types=dict(Counter(e.type for e in model.elements)),floors=dict(Counter(e.floor_id for e in model.elements)),
        ifc={'draft_ifc':validation,'verified_ifc':verified_validation})
    save('summary.json',summary)
    (output/'validation.json').write_text(json.dumps({'floors': report, 'ifc': validation}, indent=2), encoding='utf-8')
    print(json.dumps({'revision':model.revision,'floors': report, 'ifc': validation}, indent=2))


if __name__ == '__main__':
    main()
