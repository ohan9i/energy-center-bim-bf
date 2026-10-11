"""Targeted original drawing inspection; does not mutate extraction inputs."""
from collections import Counter
import re
from bf_bim.precise.rebuild import load_archive, AUDIT, read, layer

def structural_preview():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from bf_bim.precise.rebuild import native_profile, OUTPUT, safe
    from bf_bim.precise.schema import Registration
    a,row=load_archive('S02-001~',read(AUDIT/'drawing-index.json'))
    frame=Registration(id='inspect',drawing_id='S02-001~',origin_cad=(190000,-680000),scale_m_per_unit=.001)
    fig,ax=plt.subplots(figsize=(15,14))
    for e in a['scene_entities']:
        b=e.get('bounds')
        if not b or b['min'][0]<190000 or b['max'][0]>265000 or b['min'][1]<-680000 or b['max'][1]>-620000:continue
        if not safe(e,set()):continue
        if e['type'] in ('LINE','LWPOLYLINE','CIRCLE','ARC','SPLINE'):
            try:l,p=native_profile(e,frame)
            except (ValueError,KeyError,NotImplementedError):continue
            x,y=l.xy;ax.plot(x,y,linewidth=.4,color='#777' if layer(e)=='DEFPOINTS' else '#217c91')
        elif e['type'] in ('TEXT','MTEXT') and re.fullmatch(r'(?:[1-4rR]|phr)[BGSCW][0-9]+[A-Z]?',e['geometry'].get('text','').strip()):
            x,y=e['geometry']['insert'][:2];ax.text((x-190000)*.001,(y+680000)*.001,e['geometry']['text'],fontsize=6,color='#a22222',rotation=e['geometry'].get('rotation_deg',0))
    ax.set_aspect('equal');ax.grid(alpha=.2);fig.tight_layout()
    out=OUTPUT/'coordination-v2/structural-native-f1.png';fig.savefig(out,dpi=150);print(out)

def main():
    rows=read(AUDIT/'drawing-index.json')
    for name in ['S02-001~','S02-021~','A07-001~','A07-011~','A07-021~','A06-001~013']:
        a,row=load_archive(name,rows)
        texts=[e for e in a['scene_entities'] if e['type'] in ('TEXT','MTEXT') and not e.get('precision_geometry_blocked')]
        print('\nDRAWING',name,'entities',len(a['scene_entities']),'layers',Counter(layer(e) for e in a['scene_entities']).most_common(10))
        important=[e for e in texts if re.search(r'구조평면|층.*평면|지붕|[1-4]B[1-9]|THK|SL[+-]|SSL|FFL|EL[+-]|슬라브|슬래브',e['geometry'].get('text',''))]
        print([(e['geometry']['text'],[round(v,1) for v in e['geometry'].get('insert',[])[:2]]) for e in important[:65]])

def inspect_doors():
    from bf_bim.precise.window_authoring import _dimension
    a,row=load_archive('A10-001~',read(AUDIT/'drawing-index.json'))
    texts=[q for q in a['scene_entities'] if q['type']=='TEXT' and '/child:' not in q['id']]
    dims=[(q,_dimension(q)) for q in a['scene_entities'] if q['type']=='DIMENSION'];dims=[(q,d) for q,d in dims if d]
    for tag in texts:
        label=tag['geometry'].get('text','')
        if label not in ('SSD','FSD','SD'):continue
        x,y=tag['geometry']['insert'][:2]
        nums=[q for q in texts if re.fullmatch(r'3a?|1',q['geometry'].get('text','')) and abs(q['geometry']['insert'][0]-x)<400 and 150<q['geometry']['insert'][1]-y<800]
        scopes=[q for q in texts if 500<q['geometry']['insert'][0]-x<2000 and -1300<q['geometry']['insert'][1]-y<-500 and 'F :' in q['geometry']['text']]
        if not nums or not scopes:continue
        print(label,nums[0]['geometry']['text'],[round(x,1),round(y,1)],scopes[0]['geometry']['text'])
        near=[(q,d) for q,d in dims if all(x-100<p[0]<x+8000 and y+1000<p[1]<y+7000 for p in d[1:3])]
        print('dimensions',[(d[0],round(d[3],3),[[round(p[0]-x),round(p[1]-y)] for p in d[1:3]],q['id']) for q,d in near])

if __name__=='__main__':
    import sys
    structural_preview() if '--structural' in sys.argv else inspect_doors() if '--doors' in sys.argv else main()
