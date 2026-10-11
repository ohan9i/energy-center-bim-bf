"""Measure unclassified candidate floor area; never treat it as walkable space."""
import json
from pathlib import Path
from shapely.geometry import Polygon
from shapely.ops import unary_union
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as Patch

OUT=Path('cad_output/precision-rebuild/coordination-v2')
m=json.loads((OUT/'preview.json').read_text(encoding='utf8'));s=m['provenance']['bf_spatial'];report=[]
def region(records):return unary_union([Polygon(r[0],r[1:]) for rec in records for r in rec['region']])
def draw(ax,g,color):
    for p in g.geoms if hasattr(g,'geoms') else [g]:
        if p.geom_type!='Polygon' or p.is_empty:continue
        ax.add_patch(Patch(list(p.exterior.coords),facecolor=color,edgecolor='none'))
        for hole in p.interiors:ax.add_patch(Patch(list(hole.coords),facecolor='white',edgecolor='none'))
fig,axes=plt.subplots(1,2,figsize=(14,8))
for fid in ('b1','f1','f2','f3','f4'):
    support=unary_union([Polygon(e['polygon'],e['holes']) for e in m['elements'] if e['type']=='floor' and e['floor_id']==fid])
    blocked=region([b for b in s['blockers'] if b['floor_id']==fid])
    known=region([sp for sp in s['spaces'] if sp['floor_id']==fid])
    free=support.difference(blocked);unknown=free.difference(known)
    report.append({'floor_id':fid,'candidate_non_blocked_floor_area_m2':free.area,
        'identified_candidate_space_area_m2':known.area,'unclassified_candidate_floor_area_m2':unknown.area,
        'unclassified_fraction':unknown.area/free.area,'walkability_verified':False,
        'basis':'Provisional floor support minus current blockers/voids and unreviewed room candidates; not actual usable floor area.'})
    if fid in ('f1','f3'):
        ax=axes[0 if fid=='f1' else 1];draw(ax,support,'#596b78');draw(ax,known,'#6eb8d0');draw(ax,unknown,'#e4ae54')
        ax.autoscale();ax.set_aspect('equal');ax.set_title(f'{fid.upper()} / blue: candidate spaces / amber: unclassified ({unknown.area:.1f} m2)');ax.grid(alpha=.15)
fig.tight_layout();fig.savefig(OUT/'space-coverage-f1-f3.png',dpi=150);plt.close(fig)
(OUT/'space-coverage.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report))
