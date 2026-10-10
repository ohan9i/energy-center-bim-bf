import json, math
from pathlib import Path
from collections import Counter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

def segments(e):
    g=e['geometry']
    if e['type']=='LINE':return [[g['start'][:2],g['end'][:2]]]
    if e['type']=='LWPOLYLINE':
        if g.get('segments'):return sum((segments({'type':s['type'],'geometry':s}) for s in g['segments']),[])
        p=g['vertices'];return [[a[:2],b[:2]] for a,b in zip(p,p[1:]+p[:1] if g.get('closed') else p[1:])]
    if e['type'] in ('ARC','CIRCLE'):
        c=g['center'];r=g['radius'];a=math.radians(g.get('start_angle_deg',0));s=math.radians(g.get('sweep_angle_deg',360));n=max(6,int(s*12));points=[[c[0]+r*math.cos(a+s*i/n),c[1]+r*math.sin(a+s*i/n)] for i in range(n+1)]
        return list(zip(points,points[1:]))
    return []

def main():
    es=json.loads(Path('cad_output/scene-compact.json').read_text(encoding='utf-8'))
    plt.rcParams['font.family']='Malgun Gothic'
    from .project_model import SHEET_SPACING
    for name,box in [(name,(32920000+(i-1)*SHEET_SPACING,33020000+(i-1)*SHEET_SPACING,-5730000,-5640000)) for i,name in enumerate(('detailed-basement','detailed-first','detailed-second','detailed-third','detailed-fourth','detailed-roof'))]+[('alternate-first',(32920000,33020000,-5910000,-5800000))]:
        x1,x2,y1,y2=box
        use=[e for e in es if e.get('bounds') and e['bounds']['min'][0]>=x1 and e['bounds']['max'][0]<=x2 and e['bounds']['min'][1]>=y1 and e['bounds']['max'][1]<=y2]
        fig,ax=plt.subplots(figsize=(18,12 if name!='overview' else 4));lines=[];doors=[]
        for e in use:
            for a,b in segments(e):
                line=[[(a[0]-x1)*.001,(a[1]-y1)*.001],[(b[0]-x1)*.001,(b[1]-y1)*.001]]
                (doors if e['layer'] in ('A-DOOR','A-DOR') else lines).append(line)
            if e['type'] in ('TEXT','MTEXT') and e['layer'] in ('A-TEX2','text1'):
                p=e['geometry']['insert'];t=e['geometry']['text']
                if len(t)>1 and not t.isnumeric():ax.text((p[0]-x1)*.001,(p[1]-y1)*.001,t,fontsize=5 if name=='overview' else 8,color='#13536b')
        ax.add_collection(LineCollection(lines,colors='#45545b',linewidths=.2 if name=='overview' else .5))
        ax.add_collection(LineCollection(doors,colors='#bb4747',linewidths=.7))
        ax.set_xlim(0,(x2-x1)*.001);ax.set_ylim(0,(y2-y1)*.001);ax.set_aspect('equal');ax.set_title(name+' · CAD geometry (m)');ax.grid(alpha=.15)
        fig.savefig('cad_output/'+name+'.png',dpi=160,bbox_inches='tight');plt.close(fig)
        print(name,'count',len(use),'layers',Counter(e['layer'] for e in use).most_common(15))
    texts=[(e['geometry']['text'],e['geometry']['insert']) for e in es if e['type']=='TEXT' and e['layer']=='A-TEX2' and 33310000<e['geometry']['insert'][0]<33560000 and -4940000<e['geometry']['insert'][1]<-4860000]
    print('ROOM LABELS',texts)

if __name__=='__main__':main()
