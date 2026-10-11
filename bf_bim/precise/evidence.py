"""Current-archive schedule observations; no implicit member assignments."""
import math
import re
from collections import defaultdict

from bf_bim.drawing_evidence import collect_evidence


def collect_schedule_observations(archives):
    surveys=[];rows=[]
    for identifier,data,source_row in archives:
        surveys.append({'file':source_row['file'],'entities':data['scene_entities'],
                        'external_references':data['external_references']})
        groups=defaultdict(list)
        for e in data['scene_entities']:
            if e['type'] in ('TEXT','MTEXT','ATTRIB') and e['geometry'].get('insert'):
                groups[e.get('root_entity_id',e['id'])].append(e)
        for root,texts in groups.items():
            # Recognise a schedule block by its slab heading. Plan callouts
            # cannot accidentally inherit a nearby table dimension.
            slab_marks=[e for e in texts if re.fullmatch(r'[1-4brph~]+S\d+',e['geometry']['text'].strip())]
            if not (len(slab_marks)>=3 and any('COLUMN' in e['geometry']['text'].upper() for e in texts)):continue
            for mark in texts:
                text=mark['geometry']['text'].strip()
                if not re.fullmatch(r'[1-4brph~]+[BGS]\d+',text):continue
                position=mark['geometry']['insert'];kind='slab' if 'S' in text else 'beam'
                candidates=[]
                for e in texts:
                    value=e['geometry']['text'].strip().replace(' ','')
                    match=re.fullmatch(r'(\d+)[xX×](\d+)',value) if kind=='beam' else re.fullmatch(r'(\d+)',value)
                    p=e['geometry']['insert']
                    if match and 0<p[0]-position[0]<6000 and abs(p[1]-position[1])<2:
                        numbers=[int(v) for v in match.groups()]
                        if all(50<=v<=2000 for v in numbers):candidates.append((e,numbers))
                if len(candidates)!=1:continue
                e,numbers=candidates[0]
                rows.append({'id':identifier+'::'+mark['id'],'drawing_id':identifier,'source_sha256':source_row['sha256'],
                             'root_id':root,'mark':text,'kind':kind,'dimensions_m':[v*.001 for v in numbers],
                             'cad_ids':[mark['id'],e['id']],'status':'same_table_row_candidate',
                             'member_id':None,'assignment_verified':False})
            # Beam width and depth are often separate numeric TEXT entities,
            # with a literal x between them. Preserve that three-cell evidence.
            for mark in texts:
                text=mark['geometry']['text'].strip()
                if not re.fullmatch(r'[1-4brph~]+[BG]\d+',text):continue
                x,y=mark['geometry']['insert'][:2]
                cells=sorted([e for e in texts if 0<e['geometry']['insert'][0]-x<6000
                              and abs(e['geometry']['insert'][1]-y)<2],key=lambda e:e['geometry']['insert'][0])
                xs=[i for i,e in enumerate(cells) if e['geometry']['text'].strip().lower()=='x']
                if len(xs)!=1 or not 0<xs[0]<len(cells)-1:continue
                trio=cells[xs[0]-1:xs[0]+2]
                if not all(re.fullmatch(r'\d+',e['geometry']['text'].strip()) for e in (trio[0],trio[2])):continue
                numbers=[int(trio[0]['geometry']['text']),int(trio[2]['geometry']['text'])]
                if not all(50<=v<=2000 for v in numbers):continue
                rows.append({'id':identifier+'::'+mark['id'],'drawing_id':identifier,'source_sha256':source_row['sha256'],
                             'root_id':root,'mark':text,'kind':'beam','dimensions_m':[v*.001 for v in numbers],
                             'cad_ids':[mark['id']]+[e['id'] for e in trio],'status':'same_table_row_candidate',
                             'member_id':None,'assignment_verified':False})
    return {'survey':collect_evidence(surveys),'embedded_rows':rows,
            'policy':'A schedule row is an observation. Position, floor, revision and member identity must be independently matched.'}


def attach_column_candidates(members,evidence):
    for m in members:
        if m['kind']!='column':continue
        sizes=m['dimensions']['measured_plan']
        shape='circular' if sizes['shape']=='circular' else 'rectangular'
        values=[sizes['diameter_m']] if shape=='circular' else sizes['bounding_section_m']
        candidates=[r for r in evidence['survey']['column_sections'] if r['shape']==shape
                    and len(values)==len(r['dimensions_m']) and all(abs(a-b)<=.002 for a,b in zip(sorted(values),sorted(r['dimensions_m'])))]
        m['schedule_candidates']=candidates
        # A same-sized C3/C4 pair cannot resolve a member mark by proximity.
        m['schedule_assignment']={'status':'unassigned','candidate_marks':sorted({c['mark'] for c in candidates}),
                                  'reason':'Section-size compatibility does not identify member location or structural floor scope'}
