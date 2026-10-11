"""Identify drawing wall traces missing from BIM envelopes, without inventing bands."""
import json
import sys
import subprocess
from pathlib import Path
from shapely.geometry import Polygon,LineString
from shapely.ops import unary_union
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

OUT=Path('cad_output/precision-rebuild/coordination-v2')
baseline='--baseline' in sys.argv
m=json.loads(subprocess.check_output(['git','show','a921c2c:web/public/models/precision-rebuild.json'])) if baseline else json.loads((OUT/'preview.json').read_text(encoding='utf8'))
results=[]
for fid in ('b1','f1','f2','f3','f4','roof','phroof'):
    traces=[t for t in m['provenance']['cad_traces'] if t['floor_id']==fid and t['kind']=='wall']
    es=[e for e in m['elements'] if e['floor_id']==fid and e['type'] in ('wall','column','door','window')]
    envelope=unary_union([Polygon(e['polygon'],e['holes']) for e in es]).buffer(.001)
    missing=[]
    for t in traces:
        line=LineString(t['points']);gap=line.difference(envelope)
        if gap.length>.01:
            parts=list(gap.geoms) if hasattr(gap,'geoms') else [gap]
            missing.append({'cad_id':t['id'],'missing_length_m':gap.length,
                'segments':[list(q.coords) for q in parts if q.geom_type=='LineString' and q.length>.01]})
    results.append({'floor_id':fid,'wall_traces':len(traces),'wall_trace_length_m':sum(LineString(t['points']).length for t in traces),
        'unsupported_trace_length_m':sum(q['missing_length_m'] for q in missing),'missing_traces':missing,
        'status':'source-coverage observation; no closure or route approval'})
    if fid=='f1' and not baseline:
        fig,ax=plt.subplots(figsize=(12,10))
        for e in es:
            p=Polygon(e['polygon'],e['holes']);ax.fill(*p.exterior.xy,color='#94a4af',alpha=.45)
        ax.add_collection(LineCollection([t['points'] for t in traces],colors='#21688a',linewidths=.5))
        ax.add_collection(LineCollection([line for q in missing for line in q['segments']],colors='#d44330',linewidths=1.5))
        ax.autoscale();ax.set_aspect('equal');ax.grid(alpha=.2);ax.set_title('1F: native wall traces vs BIM / red: outside envelopes (>1mm)')
        fig.tight_layout();fig.savefig(OUT/'wall-source-coverage-f1.png',dpi=140);plt.close(fig)
(OUT/('wall-source-coverage-baseline.json' if baseline else 'wall-source-coverage.json')).write_text(json.dumps(results,indent=2),encoding='utf8')
print(json.dumps([{k:v for k,v in q.items() if k!='missing_traces'} for q in results]))
