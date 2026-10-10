"""Schedule/detail evidence kept separate from an unverified member assignment."""
import math
import re
from shapely.geometry import Polygon


def collect_evidence(drawings):
    columns=[];walls=[];notes={};missing=set()
    for d in drawings:
        texts=[e for e in d['entities'] if e['type'] in ('TEXT','MTEXT') and e['geometry'].get('insert')]
        for ref in d['external_references']:
            if not ref.get('exists'):missing.add(ref.get('id','unknown'))
        if '/S04-001' in d['file']:
            dimensions=[]
            for e in texts:
                text=e['geometry'].get('text','')
                rect=re.fullmatch(r'\(\s*(\d+)\s*[xX×]\s*(\d+)\s*\)',text)
                circle=re.fullmatch(r'\(\s*[ΦØ]\s*(\d+)\s*\)',text)
                if rect or circle:
                    dimensions.append((e,'rectangular' if rect else 'circular',
                        [float(v)*.001 for v in (rect.groups() if rect else (circle.group(1),))]))
            for mark in texts:
                if not re.fullmatch(r'C\d+',mark['geometry'].get('text','')):continue
                p=mark['geometry']['insert'];candidates=[r for r in dimensions if abs(p[1]-r[0]['geometry']['insert'][1])<1000]
                if not candidates:continue
                dim,shape,values=min(candidates,key=lambda r:math.dist(p[:2],r[0]['geometry']['insert'][:2]))
                if math.dist(p[:2],dim['geometry']['insert'][:2])>3000:continue
                columns.append(dict(mark=mark['geometry']['text'],shape=shape,dimensions_m=values,
                    file=d['file'],cad_ids=[mark['id'],dim['id']],match_method='schedule text row proximity',member_assignment_verified=False))
        if '/S04-018' in d['file']:
            marks=[e for e in texts if re.fullmatch(r'W\d+',e['geometry'].get('text',''))]
            thicknesses=[e for e in texts if re.fullmatch(r'\d+',e['geometry'].get('text','')) and 100<=int(e['geometry']['text'])<=1000]
            for mark in marks:
                p=mark['geometry']['insert'];row=[e for e in thicknesses if abs(e['geometry']['insert'][1]-p[1])<100 and 0<e['geometry']['insert'][0]-p[0]<3000]
                if len(row)==1:walls.append(dict(mark=mark['geometry']['text'],thickness_m=int(row[0]['geometry']['text'])*.001,
                    file=d['file'],cad_ids=[mark['id'],row[0]['id']],member_assignment_verified=False))
        for e in texts:
            text=e['geometry'].get('text','').strip()
            if not re.search(r'THK\s*\d+|fck\s*=|fy\s*=|복층유리|단열재|벽돌쌓기',text,re.I):continue
            # Text is evidence of a detail specification, not a global assignment.
            key=(d['file'],text)
            if key not in notes:notes[key]=dict(file=d['file'],text=text,cad_ids=[],occurrences=0,member_assignment_verified=False)
            note=notes[key];note['occurrences']+=1
            if len(note['cad_ids'])<3:note['cad_ids'].append(e['id'])
    return dict(column_sections=columns,wall_sections=walls,note_candidates=list(notes.values()),
                unavailable_references=sorted(missing),member_assignment_verified=False,
                limitation='Schedule dimensions and detail notes do not establish member position, extent, height or layer assignment.')


def annotate_columns(elements,evidence,by_id):
    for e in elements:
        if e['type']!='column':continue
        p=Polygon(e['polygon'],e['holes']);src=by_id[e['source']['cad_id']]
        if src['type']=='CIRCLE':shape='circular';values=[src['geometry']['radius']*.002]
        else:
            shape='rectangular';corners=list(p.minimum_rotated_rectangle.exterior.coords)
            values=sorted([math.dist(corners[0],corners[1]),math.dist(corners[1],corners[2])])
        matches=[r for r in evidence['column_sections'] if r['shape']==shape and len(values)==len(r['dimensions_m']) and
                 all(abs(a-b)<.002 for a,b in zip(values,sorted(r['dimensions_m'])))]
        if matches:e['source']['structural_section_candidates']=matches
