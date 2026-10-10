"""Read supplementary DWGs through the existing isolated reader, with hash caches."""
import json
import logging
from collections import Counter
from pathlib import Path
from cad_reader import analyze_drawing
from .prepare_project import sha

PREFIXES=('A04-011','A07-011','A10-001','A04-021','S02-001','S02-021','S03-001',
          'S04-001','S04-017','S04-018','A06-001','A05-001','A07-001','A10-041','A03-001')

def main(prefixes=PREFIXES):
    # The structured report retains proxy warnings; avoid thousands of repeated
    # ezdxf copy warnings obscuring the per-file audit progress.
    logging.getLogger('ezdxf').setLevel(logging.ERROR)
    out = Path('cad_output')
    folder=Path('에너지-건축도면')
    for prefix in prefixes:
        path = next(folder.rglob(prefix+'*.dwg'))
        target = out / (prefix+'-evidence.json')
        digest = sha(path)
        if target.exists() and json.loads(target.read_text(encoding='utf-8'))['source']['sha256_before'] == digest:
            print(prefix, 'cache', flush=True)
            continue
        print(prefix, 'reading', flush=True)
        data = analyze_drawing(path)
        es = [e for e in data['scene_entities'] if e.get('layout') == 'Model']
        payload = dict(file=path.relative_to(folder).as_posix(), source=data['source'], units=data['units'],
            warnings=data['warnings'], external_references=data['external_references'],
            layers=dict(Counter(e['effective_layer'] for e in es)),
            entities=[dict(id=e['id'], type=e['type'], layer=e['effective_layer'],
                root=e['root_entity_id'], geometry=e['geometry'], bounds=e.get('bounds')) for e in es])
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        assert sha(path) == digest
        print(prefix, len(es), 'entities; original hash unchanged', flush=True)

if __name__ == '__main__':
    main()
