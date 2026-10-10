"""Explicit provisional solids on CAD footprints; never promote them to verified data.

One assembly definition feeds web geometry and IFC. Unknown measured opening
heights remain null; the provisional opening range is separately recorded.
"""
import json
import math
from collections import Counter
from pathlib import Path
from shapely.geometry import Polygon, LineString
from .geometry import polygon_parts


def load_parameters(path=None):
    p=json.loads(Path(path or Path(__file__).with_name('assembly_parameters.json')).read_text(encoding='utf-8'))
    for key,value in p.items():
        if isinstance(value,(int,float)) and (not math.isfinite(value) or not 0<value<5):
            raise ValueError(f'Invalid assembly parameter: {key}')
    if p['frame_width']*2>=min(p['door_height'],p['window_height']):
        raise ValueError('Frame exceeds opening height')
    return p


def refine_assemblies(elements,p):
    counts=Counter()
    def parts(poly,role,height,z,material,parameters):
        return [dict(role=role,polygon=list(g.exterior.coords)[:-1],
            holes=[list(r.coords)[:-1] for r in g.interiors],height=height,z_offset=z,
            source=dict(geometry_status='provisional',dimension_verified=False,
                material=material,parameter_keys=parameters,parameter_file='bf_bim/assembly_parameters.json'))
            for g in polygon_parts(poly) if g.area>1e-8]
    for e in elements:
        poly=Polygon(e['polygon'],e.get('holes',[]));kind=e['type'];components=[]
        if kind in ('floor','roof'):
            # Floor elevation is finished-floor level: all structural depth below it.
            finish=p['finish_thickness'];depth=p['slab_thickness']
            components+=parts(poly,'structural_slab',depth,-finish-depth,'concrete',['slab_thickness','finish_thickness'])
            components+=parts(poly,'floor_finish' if kind=='floor' else 'roof_finish',finish,-finish,'finish',['finish_thickness'])
        elif kind=='stair':
            for c in e['components']:
                c={**c,'source':dict(c['source'])}
                if c['role']=='landing' and e['height'] is not None:
                    c['height']=p['landing_thickness'];c['z_offset']-=c['height']
                    c['source'].update(dimension_verified=False,geometry_status='provisional',parameter_keys=['landing_thickness'],material='concrete')
                elif c['role']=='tread' and c['height'] is not None:
                    # Stepped underside carries each riser to its neighbour; isolated thin steps are avoided.
                    c['height']+=p['stair_support_thickness'];c['z_offset']-=p['stair_support_thickness']
                    c['source'].update(dimension_verified=False,geometry_status='provisional',parameter_keys=['stair_support_thickness'],material='concrete')
                components.append(c)
        elif kind in ('door','window') and not e['source'].get('marker_width_m'):
            if kind=='door':
                a=e['source']['hinge'];b=e['source']['leaf_end'];line=LineString([a,b]);width=line.length
                if width<=2*p['frame_width']:continue
                ux=(b[0]-a[0])/width;uy=(b[1]-a[1])/width;cx=(a[0]+b[0])/2;cy=(a[1]+b[1])/2
                depth=min(.15,poly.area/width);z=0.;height=p['door_height']
            else:
                corners=list(poly.minimum_rotated_rectangle.exterior.coords)
                lengths=[math.dist(corners[i],corners[i+1]) for i in range(4)]
                i=max(range(4),key=lengths.__getitem__);width=lengths[i];depth=min(.2,min(lengths))
                if width<=2*p['frame_width'] or depth<.012:continue
                a,b=corners[i],corners[i+1];ux=(b[0]-a[0])/width;uy=(b[1]-a[1])/width
                cx,cy=poly.centroid.coords[0];z=p['window_sill'];height=p['window_height']
            nx,ny=-uy,ux
            def rectangle(lo,hi,d):
                return Polygon([(cx+ux*s+nx*t,cy+uy*s+ny*t) for s,t in [(lo,-d/2),(hi,-d/2),(hi,d/2),(lo,d/2)]])
            f=p['frame_width'];left=-width/2;right=width/2
            for lo,hi in ((left,left+f),(right-f,right)):
                components+=parts(rectangle(lo,hi,depth),'jamb',height,z,'metal',['frame_width',kind+'_height'])
            components+=parts(rectangle(left+f,right-f,depth),'head_frame',f,z+height-f,'metal',['frame_width',kind+'_height'])
            if kind=='window':
                components+=parts(rectangle(left+f,right-f,depth),'sill_frame',f,z,'metal',['frame_width','window_sill'])
                components+=parts(rectangle(left+f,right-f,min(depth,p['glass_thickness'])),'glass',height-2*f,z+f,'glazing',['glass_thickness','window_height','window_sill'])
            else:
                components+=parts(rectangle(left+f,right-f,p['door_leaf_thickness']),'door_leaf',height-f,z,'door',['door_leaf_thickness','door_height'])
            e['source']['provisional_opening']=dict(z_offset=z,height=height,dimension_verified=False,
                parameter_keys=[kind+'_height']+(['window_sill'] if kind=='window' else []))
            # Cut through the measured host depth, retaining the measured span.
            # Route footprints are untouched. Only parallel host candidates qualify.
            cuts=[]
            for wall in elements:
                if wall['type']!='wall' or wall['floor_id']!=e['floor_id'] or wall['source'].get('marker_width_m'):continue
                wp=Polygon(wall['polygon'],wall.get('holes',[]))
                if wp.distance(poly)>.2:continue
                cs=list(wp.minimum_rotated_rectangle.exterior.coords)
                k=max(range(4),key=lambda i:math.dist(cs[i],cs[i+1]));span=math.dist(cs[k],cs[k+1])
                wx,wy=(cs[k+1][0]-cs[k][0])/span,(cs[k+1][1]-cs[k][1])/span
                if abs(wx*ux+wy*uy)<.95:continue
                ts=[(x-cx)*nx+(y-cy)*ny for x,y in wp.exterior.coords]
                t0,t1=min(ts)-.001,max(ts)+.001
                cut=Polygon([(cx+ux*s+nx*t,cy+uy*s+ny*t) for s,t in [(left,t0),(right,t0),(right,t1),(left,t1)]])
                if cut.intersection(wp).area>1e-6:cuts.append(list(cut.exterior.coords)[:-1])
            if cuts:e['source']['architectural_opening_polygons']=cuts
        elif kind=='elevator':
            # Hollow storey shell, not a filled shaft/car box. Existing architectural walls take precedence.
            inner=poly.buffer(-p['shaft_lining_thickness'],join_style=2)
            if inner.is_empty:continue
            shell=poly.difference(inner)
            from shapely.ops import unary_union
            nearby=[Polygon(w['polygon'],w.get('holes',[])) for w in elements if w['type']=='wall' and w['floor_id']==e['floor_id'] and not w['source'].get('marker_width_m')]
            if nearby:shell=shell.difference(unary_union(nearby))
            doors=[Polygon(d['polygon'],d.get('holes',[])) for d in elements if d['type']=='door' and d['floor_id']==e['floor_id'] and Polygon(d['polygon'],d.get('holes',[])).distance(poly)<.2]
            # A candidate entrance is open up to the provisional door head, retaining the lintel.
            opening=unary_union(doors) if doors else Polygon()
            head=min(p['door_height'],e['height'])
            components+=parts(shell.difference(opening),'shaft_lining',head,0,'concrete',['shaft_lining_thickness','door_height'])
            if e['height']>head:components+=parts(shell,'shaft_lintel',e['height']-head,head,'concrete',['shaft_lining_thickness','door_height'])
            e['source']['entrance_status']='candidate door overlap' if doors else 'unresolved; no entrance fabricated'
        if components:
            e['components']=components
            e['source']['assembly_status']='provisional_not_drawing_verified'
            e['source']['parameter_file']='bf_bim/assembly_parameters.json'
            e['source']['dimension_verified']=False
            counts[kind]+=1
    return dict(assemblies=dict(counts),status='provisional_not_drawing_verified',
        missing_beams='No coordinate-resolved beam evidence: missing structural XREF; no guessed beams created.')
