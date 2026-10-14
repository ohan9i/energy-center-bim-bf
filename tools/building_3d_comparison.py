"""Compare the staged pre-edit model to the current model without saving it.

Run before staging the new model. Only metrics/source hashes are retained;
the previous model is never restored to the public model catalogue.
"""
import hashlib
import json
import subprocess
from pathlib import Path
from bf_bim.precise.building_review import audit_building


def main():
    original=subprocess.check_output(['git','show',':web/public/models/precision-rebuild.json'])
    before=json.loads(original)
    after=json.loads(Path('web/public/models/precision-rebuild.json').read_text(encoding='utf8'))
    if before['revision']>=after['revision']:
        raise ValueError('Run before staging the new model; baseline must precede the current revision.')
    a=audit_building(before['elements'],before['provenance']['floors_evidence'])
    b=audit_building(after['elements'],after['provenance']['floors_evidence'])
    current={e['id']:e for e in after['elements']}
    def geometry(e):
        return {**{k:e.get(k) for k in ('polygon','holes','height','z_offset')},
                'components':[{k:c.get(k) for k in ('polygon','holes','height','z_offset','role','mesh')}
                              for c in e['components']]}
    retained=[e for e in before['elements'] if not e['source'].get('photo_reference')
              and not any(c['role']=='assumed_parapet' for c in e['components'])]
    changed=[e['id'] for e in retained if e['id'] not in current or geometry(e)!=geometry(current[e['id']])]
    report={'baseline_revision':before['revision'],'revision':after['revision'],
            'baseline_sha256':hashlib.sha256(original).hexdigest(),
            'baseline_source':'Git index before staging this change; no old model saved or republished',
            'before':a['summary'],'after':b['summary'],'retained_original_elements':len(retained),
            'changed_retained_geometry':changed,'design_verified':False,'route_approved':False}
    out=Path('cad_output/precision-rebuild/coordination-v2/building-3d-comparison.json')
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert not changed, changed[:10]
    print(json.dumps({k:v for k,v in report.items() if k not in ('baseline_source','baseline_sha256')},ensure_ascii=False))


if __name__=='__main__':main()
