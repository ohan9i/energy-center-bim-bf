"""Persist whole-building consistency results for a chosen model."""
import argparse
import json
from pathlib import Path
from bf_bim.precise.building_review import audit_building


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=Path('web/public/models/precision-rebuild.json'))
    parser.add_argument('--output', type=Path, default=Path('cad_output/precision-rebuild/coordination-v2/building-3d-review.json'))
    args = parser.parse_args()
    model = json.loads(args.model.read_text(encoding='utf8'))
    report = audit_building(model['elements'], model['provenance']['floors_evidence'])
    report['model_revision'] = model['revision']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
