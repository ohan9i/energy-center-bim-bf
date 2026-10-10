"""Inspect actual CAD JSON without changing original DWGs."""
import json
from collections import Counter
from pathlib import Path

def main():
    d=json.loads(Path('cad_output/actual-floorplans.json').read_text(encoding='utf-8'))
    es=[e for e in d['scene_entities'] if e.get('layout')=='Model']
    texts=[dict(id=e['id'],layer=e['effective_layer'],text=e['geometry'].get('text'),point=e['geometry'].get('insert')) for e in es if e['type'] in ('TEXT','MTEXT','ATTRIB')]
    inserts=[e for e in d['layouts'][0]['entities'] if e['type']=='INSERT']
    if d['layouts'][0]['name']!='Model':
        inserts=[e for lay in d['layouts'] if lay['name']=='Model' for e in lay['entities'] if e['type']=='INSERT']
    report={'units':d['units'],'sha256':d['source']['sha256_before'],'layers':Counter(e['effective_layer'] for e in es),
        'titles':[t for t in texts if any(w in t['text'] for w in ('평면도','층 평면','지하','지상','로비','사무','복도','홀','승강','계단','층고'))],
        'text_sample':texts[:45], 'root_inserts':[{'id':e['id'],'layer':e['layer'],**e['geometry']} for e in inserts],
        'refs':d['external_references'],'warning_counts':Counter(w['code'] for w in d['warnings'])}
    Path('cad_output/project-inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('layers','root_inserts')},ensure_ascii=False,indent=2))
    print('ROOT BLOCKS',Counter(e['geometry']['block_name'] for e in inserts).most_common(50))
    # Compact scene is used only in local processing, not included in static hosting.
    compact=[{'id':e['id'],'type':e['type'],'layer':e['effective_layer'],'root':e['root_entity_id'],'geometry':e['geometry'],'bounds':e.get('bounds'),'parents':e.get('insert_ancestry',[])} for e in es if e['type'] in ('LINE','LWPOLYLINE','ARC','CIRCLE','TEXT','MTEXT','INSERT')]
    Path('cad_output/scene-compact.json').write_text(json.dumps(compact,ensure_ascii=False),encoding='utf-8')

if __name__=='__main__':main()
