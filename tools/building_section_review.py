"""Render actual component/triangle sections, including sloping stair meshes.

This is a model inspection drawing, not an independent CAD section approval.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Rectangle
from shapely.geometry import Polygon, LineString

COLORS = {'wall':'#858b8f', 'column':'#526474', 'beam':'#788b98',
          'floor':'#ad9f82', 'roof':'#ad9f82', 'window':'#57a7c5',
          'door':'#c59455', 'stair':'#a25c8b', 'elevator':'#6c9c83'}


def mesh_slice(mesh, center, direction, base):
    n = np.array([-direction[1], direction[0]])
    vs = np.array(mesh['vertices'], dtype=float)
    ds = (vs[:, :2]-center)@n
    segments = []
    for triangle in mesh['triangles']:
        points = []
        for a, b in zip(triangle, [triangle[1], triangle[2], triangle[0]]):
            if abs(ds[a]) < 1e-8:
                points.append(vs[a])
            if ds[a]*ds[b] < -1e-16:
                points.append(vs[a]+(vs[b]-vs[a])*ds[a]/(ds[a]-ds[b]))
        unique = {tuple(np.round(p, 8)): p for p in points}
        if len(unique) == 2:
            segments.append([[(p[:2]-center)@direction, p[2]+base] for p in unique.values()])
    return segments


def section(ax, model, center, direction, detailed=False):
    levels = {f['id']: f['elevation'] for f in model['floors']}
    line = LineString([center-direction*150, center+direction*150])
    count = 0
    for e in model['elements']:
        if e['type'] not in COLORS or e.get('excluded'):
            continue
        for c in e['components']:
            if not c.get('height'):
                continue
            z = levels[e['floor_id']]+e.get('z_offset', 0)+c['z_offset']
            color = COLORS[e['type']]
            if c.get('mesh'):
                segments = mesh_slice(c['mesh'], center, direction, z)
                if segments:
                    ax.add_collection(LineCollection(segments, colors=color, linewidths=.55))
                    count += 1
                continue
            p = Polygon(c['polygon'], c.get('holes', []))
            cut = line.intersection(p)
            lines = list(cut.geoms) if hasattr(cut, 'geoms') else [cut]
            for segment in lines:
                if segment.geom_type != 'LineString' or segment.length < 1e-6:
                    continue
                ts = [(np.array(xy)-center)@direction for xy in segment.coords]
                ax.add_patch(Rectangle((min(ts), z), max(ts)-min(ts), c['height'],
                                      facecolor=color, edgecolor=color, linewidth=.25, alpha=.7))
                count += 1
    for fid in ('b1','f1','f2','f3','f4','roof','phroof'):
        z = levels[fid]
        ax.axhline(z, color='#426ca0', lw=.45, ls='--', alpha=.6)
        ax.text(-11 if detailed else -40, z+.08, f'{fid} FL {z:.2f}', fontsize=7, color='#426ca0')
    ax.set_xlim(-12, 12) if detailed else ax.set_xlim(-42, 42)
    ax.set_ylim(-5.8, 24)
    ax.set_aspect('equal')
    ax.set_xlabel('Distance along section (m)')
    ax.set_ylabel('Model Z (m)')
    ax.grid(alpha=.12)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=Path('web/public/models/precision-rebuild.json'))
    parser.add_argument('--output', type=Path, default=Path('cad_output/precision-rebuild/coordination-v2/building-3d'))
    args = parser.parse_args()
    model = json.loads(args.model.read_text(encoding='utf8'))
    cores = [e for e in model['elements'] if e['floor_id']=='f1' and e['type']=='elevator']
    p = Polygon(cores[0]['polygon'], cores[0]['holes'])
    center = np.array([p.centroid.x, p.centroid.y])
    corners = list(p.minimum_rotated_rectangle.exterior.coords)
    a, b = max(zip(corners, corners[1:]), key=lambda pair: LineString(pair).length)
    u = np.array(b)-a
    u /= np.linalg.norm(u)
    v = np.array([-u[1], u[0]])
    args.output.mkdir(parents=True, exist_ok=True)
    sections = []
    for detailed, name in [(False, 'whole-building-sections'), (True, 'core-sections')]:
        fig, axes = plt.subplots(1, 2, figsize=(16, 9))
        for label, ax, d in zip(['A-A', 'B-B'], axes, [u, v]):
            count = section(ax, model, center, d, detailed)
            ax.set_title(f'{label}: actual model geometry, R{model["revision"]}')
            sections.append({'view':name, 'section':label, 'center_xy_m':center.tolist(),
                             'direction':d.tolist(), 'intersected_components':count})
        fig.suptitle('Coordination sections: assigned FL datums; FFL/SSL details and drawing approval unresolved', fontsize=11)
        fig.tight_layout()
        fig.savefig(args.output/(name+'.png'), dpi=140)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 8))
    traces = [t['points'] for t in model['provenance']['cad_traces'] if t['floor_id']=='f1']
    ax.add_collection(LineCollection(traces, colors='#8296a5', linewidths=.4))
    for label, d, color in [('A-A', u, '#bd5360'), ('B-B', v, '#587bad')]:
        points = [center-d*45, center+d*45]
        ax.plot([q[0] for q in points], [q[1] for q in points], color=color, lw=1.2, label=label)
    ax.set_xlim(0, 90); ax.set_ylim(10, 65); ax.set_aspect('equal'); ax.legend()
    ax.set_title('Section locations on preserved 1F CAD traces (same extraction)')
    ax.set_xlabel('Model X (m)'); ax.set_ylabel('Model Y (m)')
    fig.tight_layout(); fig.savefig(args.output/'section-locations.png', dpi=140); plt.close(fig)
    # A shaft-centred section may pass only through stair landings. Also cut
    # through a measured tread centre, perpendicular to its width, so the actual
    # stepped/sloped triangle geometry is visible instead of its prism envelope.
    stair=next(e for e in model['elements'] if e['floor_id']=='f1' and e['type']=='stair' and e['components'])
    tread=next(c for c in stair['components'] if c['role']=='tread')
    p=Polygon(tread['polygon'],tread['holes']);corners=list(p.minimum_rotated_rectangle.exterior.coords)
    a,b=max(zip(corners,corners[1:]),key=lambda pair:LineString(pair).length)
    width=np.array(b)-a;width/=np.linalg.norm(width)
    flight=np.array([-width[1],width[0]]);flight_center=np.array([p.centroid.x,p.centroid.y])
    fig,ax=plt.subplots(figsize=(8,10));count=section(ax,model,flight_center,flight,True)
    ax.set_xlim(-6,6);ax.set_title('Actual stair flight section: direction assignment unresolved')
    fig.tight_layout();fig.savefig(args.output/'stair-flight-section.png',dpi=140);plt.close(fig)
    sections.append({'view':'stair-flight-section','section':'C-C','center_xy_m':flight_center.tolist(),
                     'direction':flight.tolist(),'intersected_components':count,'stair_id':stair['id']})
    (args.output/'sections.json').write_text(json.dumps({'sections':sections, 'independent_drawing_verified':False}, indent=2), encoding='utf8')
    print(json.dumps({'section_views':len(sections), 'output':str(args.output)}))


if __name__=='__main__':
    main()
