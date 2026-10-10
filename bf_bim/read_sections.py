import json
from pathlib import Path
from cad_reader import analyze_drawing

def main():
    folder=next(p for p in Path('.').iterdir() if p.is_dir() and p.name=='에너지-건축도면')
    path=next(folder.glob('A04-021*.dwg'))
    d=analyze_drawing(path,max_scene_entities=100000)
    texts=[dict(id=e['id'],text=e['geometry']['text'],point=e['geometry'].get('insert'),layer=e['effective_layer']) for e in d['scene_entities'] if e.get('layout')=='Model' and e['type'] in ('TEXT','MTEXT')]
    out={'source':d['source'],'texts':texts,'warnings':d['warnings']}
    Path('cad_output/section-texts.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([t for t in texts if any(w in t['text'].upper() for w in ('F.L','FL','S.L','SL','GL','층','4,','3,','4.','3.','±'))],ensure_ascii=False))

if __name__=='__main__':main()
