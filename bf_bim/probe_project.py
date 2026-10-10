import json
from pathlib import Path
from collections import Counter
from shapely.geometry import Polygon

def main():
    es=json.loads(Path('cad_output/scene-compact.json').read_text(encoding='utf-8'))
    use=[e for e in es if e.get('bounds') and 32920000<e['bounds']['min'][0] and e['bounds']['max'][0]<33020000 and -5730000<e['bounds']['min'][1] and e['bounds']['max'][1]<-5640000]
    for layer in ['A-CON','A-COL','A-BRICK','A-WAL','A-FIN','A-HAT','A-AREA1','A-DOOR','A-COR-EVTR','A-STAIR']:
        items=[e for e in use if e['layer']==layer];polys=[]
        for e in items:
            g=e['geometry']
            if e['type']=='LWPOLYLINE' and g.get('closed'):
                try:
                    p=Polygon([(v[0]*.001,v[1]*.001) for v in g['vertices']]);polys.append((e['id'],round(p.area,3),len(g['vertices']),g['vertices'][0][:2]))
                except:pass
        print(layer,Counter(e['type'] for e in items),'polygons',sorted(polys,key=lambda x:-x[1])[:15])
    print('ROOM TEXT',[(e['geometry']['text'],e['geometry']['insert'][:2]) for e in use if e['type']=='TEXT' and e['layer']=='A-TEX2'])
    print('DOOR INSERTS',[(e['id'],e['geometry']['block_name'],e['geometry']['insert'][:2],e['geometry']['rotation_deg']) for e in es if e['type']=='INSERT' and 32920000<e['geometry']['insert'][0]<33020000 and -5730000<e['geometry']['insert'][1]<-5640000 and ('DOOR' in e['geometry']['block_name'].upper() or 'FSD' in e['geometry']['block_name'].upper())])

if __name__=='__main__':main()
