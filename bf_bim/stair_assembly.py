"""Candidate stair solids following CAD nosings, with explicit unverified details."""
import math
from shapely.geometry import Polygon, LineString
from .assembly_solids import tapered_prism,rail_segment


def refine_stair(e,p):
    if e['height'] is None:return e['components']  # No fabricated non-typical storey.
    components=[];flights={}
    for c in e['components']:
        c={**c,'source':dict(c['source'])}
        if c['role']=='landing':
            c['height']=p['landing_thickness'];c['z_offset']-=c['height']
            c['source'].update(geometry_status='provisional',dimension_verified=False,material='concrete',parameter_keys=['landing_thickness'])
        elif c['role']=='tread':
            flight=c['source']['flight_index'];flights.setdefault(flight,[]).append(c)
            rise=c['height'];top=c['z_offset']+rise;depth=p['stair_support_thickness']
            lows=[top-rise-depth,top-rise-depth,top-depth,top-depth] if flight==0 else [top-depth,top-depth,top-rise-depth,top-rise-depth]
            c=tapered_prism(Polygon(c['polygon']),lows,[top]*4,'tread',dict(c['source'],
                geometry_status='provisional',dimension_verified=False,material='concrete',
                surface_roles=['tread','riser','sloping_soffit'],parameter_keys=['stair_support_thickness']))
        components.append(c)
    source=dict(geometry_status='provisional',dimension_verified=False,material='metal',
        placement_verified=False,detail_assignment_verified=False,
        detail_candidates=e['source'].get('railing_detail_candidates',[]),
        parameter_keys=['handrail_height','handrail_diameter','railing_post_diameter','railing_post_spacing'],
        note='CAD flight envelope; rail placement and detail assignment are unverified. Not a BF clearance measurement.')
    for flight,steps in flights.items():
        first,last=steps[0],steps[-1];a,b=first['polygon'][0:2];d,c=last['polygon'][3],last['polygon'][2]
        # polygon ring preserves the measured flight boundaries.
        tops=[s['z_offset']+s['height'] for s in steps];rise=first['height']
        low=tops[0];high=tops[-1]+(rise if flight==0 else -rise)
        inset=p['handrail_diameter']/2+.012
        for side,(start,end) in enumerate(((a,d),(b,c))):
            other=b if side==0 else a
            width=math.dist(a,b);dx=(other[0]-start[0])/width;dy=(other[1]-start[1])/width
            start=(start[0]+dx*inset,start[1]+dy*inset);end=(end[0]+dx*inset,end[1]+dy*inset)
            h=p['handrail_height'];run=math.dist(start,end)
            components.append(rail_segment((*start,low+h),(*end,high+h),p['handrail_diameter'],'handrail',dict(source,flight_index=flight)))
            count=max(1,math.ceil(run/p['railing_post_spacing']))
            for i in range(count+1):
                t=i/count;x=start[0]+(end[0]-start[0])*t;y=start[1]+(end[1]-start[1])*t
                step=min(len(steps)-1,int(t*len(steps)));base=tops[step]
                rail_z=low+(high-low)*t+h
                components.append(rail_segment((x,y,base),(x,y,rail_z),p['railing_post_diameter'],'railing_post',dict(source,flight_index=flight)))
        # Complete the final structural riser at the landing face. A 150 mm
        # landing alone does not reach a 175 mm last riser / inclined soffit.
        end_a,end_b=(d,c) if flight==0 else (a,b)
        line=LineString([end_a,end_b]);top=e['height']/2 if flight==0 else e['height']
        landings=[l for l in components if l['role']=='landing' and abs(l['z_offset']+l['height']-top)<1e-6]
        for landing in landings:
            poly=line.buffer(.04,cap_style=2).intersection(Polygon(landing['polygon']))
            if poly.area<1e-8:continue
            depth=p['landing_thickness']+rise
            components.append(dict(role='landing_bearing',polygon=list(poly.exterior.coords)[:-1],holes=[],
                height=rise,z_offset=top-depth,source=dict(geometry_status='provisional',dimension_verified=False,
                material='concrete',parameter_keys=['landing_thickness'],note='Terminal riser bearing below landing; no duplicate solid inside landing')))
    e['source']['stair_soffit_status']='continuous inclined underside; flight direction unverified'
    e['source']['railing_status']='provisional placement; detail candidates not assigned to member'
    return components
