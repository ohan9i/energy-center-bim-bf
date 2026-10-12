"""Read original structural sheets and isolated backup copies; preserve originals."""
from pathlib import Path
from collections import Counter
import gzip, json, tempfile, shutil, hashlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family']='Malgun Gothic'
from bf_bim.precise.rebuild import load_archive, AUDIT, read, layer, ROOT
from cad_reader.reader import analyze_drawing

OUT=ROOT/'cad_output/precision-rebuild/structural-inspection'

def backup_archives():
    source=ROOT/'에너지-건축도면/[S00-000]구조'
    result=[]
    for p in source.glob('*.bak'):
        name=p.stem.split(' ')[0];dst=OUT/(name+'-backup.json.gz')
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if dst.exists():
            with gzip.open(dst,'rt',encoding='utf-8') as f: a=json.load(f)
            if a.get('backup_original',{}).get('sha256')!=digest:
                raise ValueError('Backup revision differs from inspection cache: '+str(p))
        else:
            with tempfile.TemporaryDirectory(prefix='structure-backup-') as tmp:
                copy=Path(tmp)/'backup.dwg';shutil.copyfile(p,copy)
                a=analyze_drawing(copy,precise_identity=True)
                a['backup_original']={'file':str(p.relative_to(ROOT)),'sha256':digest}
            with gzip.open(dst,'wt',encoding='utf-8') as f: json.dump(a,f,ensure_ascii=False)
        assert digest==hashlib.sha256(p.read_bytes()).hexdigest()
        print(name,'backup',a['coverage']['scene_entity_count'],[(r['id'],r.get('embedded_entity_count')) for r in a['external_references'] if r['kind']=='xref'],flush=True)
        result.append((name+'-backup',a))
    return result

def render(name,a):
    fig,ax=plt.subplots(figsize=(20,14))
    for e in a['scene_entities']:
        if e['type']!='LINE' or e.get('precision_geometry_blocked'):continue
        g=e['geometry'];pts=[g['start'],g['end']]
        if max(abs(c) for p in pts for c in p[:2])>2e6:continue
        ax.plot([p[0] for p in pts],[p[1] for p in pts],color='#3b6f85',lw=.25)
    for e in a['scene_entities']:
        if e['type']!='TEXT':continue
        g=e['geometry'];t=g['text'];x,y=g['insert'][:2]
        if len(t)<12 and abs(x)<2e6 and abs(y)<2e6:
            ax.text(x,y,t,fontsize=3,color='#983b20',rotation=g.get('rotation_deg',0))
    ax.set_aspect('equal');fig.tight_layout();fig.savefig(OUT/(name+'-overview.png'),dpi=150);plt.close(fig)

def main():
    OUT.mkdir(parents=True,exist_ok=True);rows=read(AUDIT/'drawing-index.json')
    all_data=[]
    for name in ['S02-001~','S02-021~','S03-001~','S04-001','S04-017','S04-018']:
        a,row=load_archive(name,rows);all_data.append((name,a))
    all_data+=backup_archives()
    for name,a in all_data:
        print(name,'layers',Counter((layer(e),e['type']) for e in a['scene_entities']).most_common(12),flush=True)
        titles=[(e['geometry']['text'],[round(c) for c in e['geometry']['insert'][:2]]) for e in a['scene_entities'] if e['type'] in ('TEXT','MTEXT') and any(t in e['geometry'].get('text','') for t in ('층','평면','단면','SL','FLOOR'))]
        print('titles',titles[:40],flush=True)
        if name.startswith(('S02','S03')):render(name,a)

if __name__=='__main__':main()
