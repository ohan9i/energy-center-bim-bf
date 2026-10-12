"""Update published coordination JSON/IFC from the existing model, without DWG."""
import json
from pathlib import Path

from bf_bim.precise.ceiling_completion import complete_ceilings
from bf_bim.schema import Model
from bf_bim.ifc_export import export_ifc
from bf_bim.validate_ifc import validate_file
from bf_bim.spatial_navigation import build_spatial
from bf_bim.precise.coordination_quality import attach_evidence


def main():
    root = Path(__file__).resolve().parents[1]
    target = root/'web/public/models/precision-rebuild.json'
    data = json.loads(target.read_text(encoding='utf-8'))
    before = data['elements'].copy()
    report = complete_ceilings(data['elements'], data['floors'])
    attach_evidence([e for e in data['elements'] if e['source'].get('ceiling_completion')], data['floors'], {})
    # Normalize defaults before comparison so reruns don't bump the revision.
    model = Model.model_validate(data)
    if Model.model_validate({**data, 'elements': before}).elements != model.elements:
        model.revision += 1
    model.provenance['ceiling_completion'] = {'version': 1, 'design_verified': False, 'floors': report}
    model.provenance['bf_spatial'] = build_spatial(model.model_dump(mode='json'), model.provenance.get('bf_spatial'))
    output = root/'cad_output/ceiling-review'
    output.mkdir(parents=True, exist_ok=True)
    staging = output/'precision-rebuild-coordination-draft.ifc'
    print('Exporting coordination IFC', flush=True)
    staging.write_text(export_ifc(model, coordination_draft=True), encoding='utf-8')
    print('Validating IFC schema, every solid, volumes and coordinates', flush=True)
    validation = validate_file(model, staging)
    target.write_text(model.model_dump_json(indent=2), encoding='utf-8')
    (target.parent/staging.name).write_bytes(staging.read_bytes())
    (output/'validation.json').write_text(json.dumps({'floors': report, 'ifc': validation}, indent=2), encoding='utf-8')
    print(json.dumps({'floors': report, 'ifc': validation}, indent=2))


if __name__ == '__main__':
    main()
