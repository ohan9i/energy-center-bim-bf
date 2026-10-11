"""Correlate native plan frames with dimensioned A10 window elevations.

Only a unique mark, stated floor scope and matching outer width can replace
generic dimensions. The association remains reviewable, not design approved.
"""
from collections import defaultdict
from copy import deepcopy
import math
import re

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from .rebuild import native_profile, profile_dict, safe, layer
from .schema import Registration


def recover_plan_frames(elements, archive, specs):
    by_block=defaultdict(list)
    for entity in archive['scene_entities']:
        for ancestor in entity.get('insert_ancestry',[]):
            by_block[ancestor].append(entity)
    lookup={e['id']:e for e in archive['scene_entities']}
    clipped={w.get('entity_id') for w in archive['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
    report=[]
    for e in elements:
        src=e['source'];axis=src.get('window_plan_axis')
        if e['type']!='window' or not axis:continue
        roots=[lookup[i] for i in src['cad_ids'] if i in lookup and lookup[i]['type']=='INSERT']
        if len(roots)!=1:continue
        root=roots[0];spec=specs[e['floor_id']]
        frame=Registration(id=e['floor_id']+'-frame',drawing_id='A04-001~008',
                           origin_cad=tuple(spec['origin']),scale_m_per_unit=.001)
        cx,cy=axis['origin'];ux,uy=axis['direction'];depth=axis['depth_m'];width=axis['width_m']
        curves=[];jambs=[]
        for q in by_block[root['id']]:
            if not safe(q,clipped) or layer(q) not in ('A-DOOR','A-WIN'):continue
            try:line,p=native_profile(q,frame)
            except (ValueError,KeyError,TypeError,NotImplementedError):continue
            if p is None and line.is_ring:p=Polygon(line.coords)
            uv=[((x-cx)*ux+(y-cy)*uy,-(x-cx)*uy+(y-cy)*ux) for x,y in line.coords]
            lo,hi=min(p[0] for p in uv),max(p[0] for p in uv)
            t0,t1=min(p[1] for p in uv),max(p[1] for p in uv)
            if max(abs(lo),abs(hi))>width/2+.16 or max(abs(t0),abs(t1))>depth/2+.002:continue
            curves.append((line,q['id']))
            if p and .025<hi-lo<.12 and abs(t1-t0-depth)<.002:
                jambs.append((lo,hi,t0,t1,q['id'],p))
        if len(jambs)<2:continue
        ordered=sorted(jambs,key=lambda q:q[0]);left,right=ordered[0],ordered[-1]
        if left[1]>=0 or right[0]<=0 or abs(left[1]-left[0]-(right[1]-right[0]))>.002:continue
        if abs((left[0]+right[1])/2)>.002:continue
        a,b=left[5].centroid,right[5].centroid
        span=a.distance(b);ux,uy=(b.x-a.x)/span,(b.y-a.y)/span;cx,cy=(a.x+b.x)/2,(a.y+b.y)/2
        uv=[((x-cx)*ux+(y-cy)*uy,-(x-cx)*uy+(y-cy)*ux)
            for jamb in (left,right) for x,y in jamb[5].exterior.coords]
        lo,hi=min(p[0] for p in uv),max(p[0] for p in uv);t0,t1=min(p[1] for p in uv),max(p[1] for p in uv)
        envelope=Polygon([(cx+ux*s-uy*t,cy+uy*s+ux*t) for s,t in [(lo,t0),(hi,t0),(hi,t1),(lo,t1)]])
        source_curves=unary_union([q for q,_ in curves])
        uncovered=envelope.boundary.difference(source_curves.buffer(.000001)).length
        residual=max(source_curves.distance(envelope.boundary.interpolate(n/128,normalized=True)) for n in range(129))
        if uncovered>.00001 or residual>.000001:continue
        previous=Polygon(e['polygon'],e.get('holes',[]))
        faces=defaultdict(set)
        for line,identifier in curves:
            if len(line.coords)!=2:continue
            uv=[((x-cx)*ux+(y-cy)*uy,-(x-cx)*uy+(y-cy)*ux) for x,y in line.coords]
            if abs(uv[0][1]-uv[1][1])>1e-6:continue
            if min(v[0] for v in uv)>lo+left[1]-left[0]+.001 or max(v[0] for v in uv)<hi-(right[1]-right[0])-.001:continue
            faces[round((uv[0][1]+uv[1][1])/2,8)].add(identifier)
        evidence={'drawing_id':'A04-001~008','file':src['file'],'source_sha256':src['source_sha256'],
                  'cad_ids':sorted(i for _,i in curves),'block_id':root['id'],
                  'method':'two closed native jamb profiles and covered outer boundary',
                  'boundary_residual_m':residual,'uncovered_boundary_length_m':uncovered,'width_m':hi-lo,'depth_m':t1-t0,
                  'jamb_width_m':left[1]-left[0],'previous_width_m':width,
                  'parallel_faces':[{'offset_m':v,'cad_ids':sorted(refs)} for v,refs in sorted(faces.items())],
                  'footprint_added_m2':envelope.difference(previous).area}
        e.update(profile_dict(envelope))
        src['window_plan_axis']={**axis,'origin':list(envelope.centroid.coords)[0],
                                 'direction':[ux,uy],'width_m':hi-lo,'depth_m':t1-t0}
        src['native_frame_evidence']=evidence
        src['cad_ids']=sorted(set(src['cad_ids'])|set(evidence['cad_ids']))
        report.append({'element_id':e['id'],'floor_id':e['floor_id'],**evidence})
    return report


def _dimension(e):
    g=e['geometry'];pts=g.get('definition_points_raw',{})
    a,b=pts.get('defpoint2'),pts.get('defpoint3')
    if not a or not b:return None
    dx,dy=abs(b[0]-a[0]),abs(b[1]-a[1])
    direction='x' if dy<.1 else 'y' if dx<.1 else None
    if not direction:return None
    value=g.get('measurement',0)
    text=g.get('text_override','').strip()
    if text not in ('','<>'):
        # A non-scale/overridden diagram cannot establish measured geometry.
        try:override=float(text.replace(',',''))
        except ValueError:return None
        if abs(override-value)>.5:return None
    if abs(max(dx,dy)-value)>.5:return None
    return direction,a[:2],b[:2],value*.001


def window_catalog(archive,row):
    """Read the dimensioned elevation, including sill vs overall datum height."""
    clipped={w.get('entity_id') for w in archive['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
    entities=[e for e in archive['scene_entities'] if safe(e,clipped)]
    texts=[e for e in entities if e['type'] in ('TEXT','MTEXT') and '/child:' not in e['id']]
    dims=[(e,_dimension(e)) for e in entities if e['type']=='DIMENSION']
    dims=[(e,d) for e,d in dims if d]
    catalog=[]
    for tag in texts:
        if tag['geometry'].get('text','').strip()!='AW':continue
        x,y=tag['geometry']['insert'][:2]
        numbers=[q for q in texts if re.fullmatch(r'\d+[a-z]?',q['geometry'].get('text','').strip())
                 and abs(q['geometry']['insert'][0]-x)<400 and 150<q['geometry']['insert'][1]-y<800]
        scopes=[q for q in texts if 500<q['geometry']['insert'][0]-x<2000
                and -1300<q['geometry']['insert'][1]-y<-500
                and re.search(r'(?:B1|[1-4R])F\s*:',q['geometry'].get('text',''))]
        if len(numbers)!=1 or len(scopes)!=1:continue
        mark='AW-'+numbers[0]['geometry']['text'].strip()
        # Revised variants need a dedicated dimensional association.
        if mark.endswith('a'):continue
        nearby=[(e,d) for e,d in dims if all(x<p[0]<x+6700 and y+1500<p[1]<y+6500 for p in d[1:3])]
        horizontal=[(e,d) for e,d in nearby if d[0]=='x']
        vertical=[(e,d) for e,d in nearby if d[0]=='y']
        if not horizontal or not vertical:continue
        wd=max(horizontal,key=lambda q:q[1][3]);hd=max(vertical,key=lambda q:q[1][3])
        xmin,xmax=sorted(p[0] for p in wd[1][1:3]);ymin,ymax=sorted(p[1] for p in hd[1][1:3])
        frame=Registration(id=mark+'-elevation',drawing_id='A10-001~',origin_cad=(xmin,ymin),scale_m_per_unit=.001)
        lines=[];outlines=[]
        for q in entities:
            if layer(q)!='A-DOOR' or q['type'] not in ('LINE','LWPOLYLINE'):continue
            b=q.get('bounds')
            if b and (b['max'][0]<xmin-.5 or b['min'][0]>xmax+.5 or b['max'][1]<ymin-.5 or b['min'][1]>ymax+.5):continue
            try:line,p=native_profile(q,frame)
            except (ValueError,KeyError,TypeError,NotImplementedError):continue
            if p is None and line.is_ring:p=Polygon(line.coords)
            if any(not -.0005<=a<=wd[1][3]+.0005 or not -.0005<=b<=hd[1][3]+.0005 for a,b in line.coords):continue
            lines.append((line,q['id']))
            if p and abs(p.bounds[0])<.0005 and abs(p.bounds[2]-wd[1][3])<.0005 and abs(p.bounds[3]-hd[1][3])<.0005:
                if abs(p.area-(p.bounds[2]-p.bounds[0])*(p.bounds[3]-p.bounds[1]))<1e-6:outlines.append((p,q['id']))
        unique={p.normalize().wkb_hex:(p,i) for p,i in outlines}
        if len(unique)!=1:continue
        outline,outline_id=next(iter(unique.values()));lo=outline.bounds[1];hi=outline.bounds[3];w=wd[1][3]
        segments=[]
        for line,identifier in lines:
            for a,b in zip(list(line.coords),list(line.coords)[1:]):
                segments.append((a,b,identifier))
        vertical_positions=sorted({round(a[0],6) for a,b,_ in segments if abs(a[0]-b[0])<1e-5
                                   and abs(min(a[1],b[1])-lo)<.0005 and abs(max(a[1],b[1])-hi)<.0005})
        vbars=[(a,b) for a,b in zip(vertical_positions,vertical_positions[1:]) if .025<b-a<.081]
        if not vbars or abs(vbars[0][0])>.0005 or abs(vbars[-1][1]-w)>.0005:continue
        regions=[];complete=True
        for n,(a,b) in enumerate(vbars):
            regions.append({'s0':a,'s1':b,'z0':lo,'z1':hi,'role':'jamb' if n in (0,len(vbars)-1) else 'mullion'})
        for left,right in zip(vbars,vbars[1:]):
            a,b=left[1],right[0]
            heights=sorted({round(p[1],6) for p,q,_ in segments if abs(p[1]-q[1])<1e-5
                            and min(p[0],q[0])<=a+.0005 and max(p[0],q[0])>=b-.0005 and lo-.0005<=p[1]<=hi+.0005})
            rails=[(z0,z1) for z0,z1 in zip(heights,heights[1:]) if .025<z1-z0<.081]
            if not rails or abs(rails[0][0]-lo)>.0005 or abs(rails[-1][1]-hi)>.0005:
                complete=False;break
            for z0,z1 in rails:
                regions.append({'s0':a,'s1':b,'z0':z0,'z1':z1,
                                'role':'sill_frame' if abs(z0-lo)<.0005 else 'head_frame' if abs(z1-hi)<.0005 else 'transom'})
            for below,above in zip(rails,rails[1:]):
                regions.append({'s0':a,'s1':b,'z0':below[1],'z1':above[0],'role':'glass'})
        if not complete:continue
        descriptions=[q for q in texts if 500<q['geometry']['insert'][0]-x<2000 and -500<q['geometry']['insert'][1]-y<1100]
        glass=[q for q in descriptions if re.search(r'THK\s*\d+',q['geometry'].get('text',''))]
        glass_values={int(m)*.001 for q in glass for m in re.findall(r'THK\s*(\d+)',q['geometry']['text'])}
        if len(glass_values)!=1:continue
        build_ups=set()
        for q in glass:
            m=re.search(r'(\d+(?:\.\d+)?)LE.*?\+\s*(\d+(?:\.\d+)?)(?:AR|A)\s*\+\s*(\d+(?:\.\d+)?)(?:CL|LE)',q['geometry']['text'])
            if m:
                layers=tuple(float(v)*.001 for v in m.groups())
                if abs(sum(layers)-next(iter(glass_values)))<1e-7:build_ups.add(layers)
        scope=scopes[0]['geometry']['text']
        floors=sorted(set('b1' if f=='B1' else 'roof' if f=='R' else 'f'+f for f in re.findall(r'(B1|[1-4R])F\s*:',scope)))
        catalog.append({'mark':mark,'width_m':w,'height_m':hi-lo,'sill_m':lo,
                        'datum_to_head_m':hd[1][3],'glass_thickness_m':next(iter(glass_values)),
                        'elevation_origin_cad':[xmin,ymin],
                        'glazing_build_up_m':list(next(iter(build_ups))) if len(build_ups)==1 else None,
                        'floors':floors,'scope_text':scope,'regions':regions,
                        'description':[q['geometry']['text'] for q in descriptions],
                        'references':[{'drawing_id':'A10-001~','file':row['file'],'source_sha256':row['sha256'],
                                       'cad_ids':sorted({tag['id'],numbers[0]['id'],scopes[0]['id'],wd[0]['id'],hd[0]['id'],outline_id,
                                                          *[i for _,i in lines],*[q['id'] for q in descriptions]})}],
                        'status':'dimensioned_elevation_not_design_approved'})
    return catalog


def apply_window_schedules(elements,catalog):
    by_mark=defaultdict(list)
    for item in catalog:by_mark[item['mark']].append(item)
    report=[]
    for e in elements:
        if e['type']!='window':continue
        src=e['source'];links=src.get('plan_schedule_links',[]);axis=src.get('window_plan_axis')
        if len(links)!=1 or not axis or not src.get('native_frame_evidence'):continue
        options=by_mark[links[0]['mark']]
        if len(options)!=1:continue
        spec=options[0]
        if e['floor_id'] not in spec['floors'] or abs(axis['width_m']-spec['width_m'])>.002:continue
        ux,uy=axis['direction'];cx,cy=axis['origin'];width=axis['width_m'];depth=axis['depth_m']
        faces=src['native_frame_evidence'].get('parallel_faces',[])
        pairs=[(a,b) for i,a in enumerate(faces) for b in faces[i+1:]
               if abs(b['offset_m']-a['offset_m']-spec['glass_thickness_m'])<.0005]
        placement={'status':'provisional','reason':'No unique native face pair matching glazing thickness; centred preview'}
        if len(pairs)==1:
            a,b=pairs[0]
            placement={'status':'drawing_correlated','normal_bounds_m':[a['offset_m'],b['offset_m']],
                       'method':'native parallel face pair matched to A10 unit thickness',
                       'cad_ids':sorted(set(a['cad_ids']+b['cad_ids']))}
        components=[]
        for r in spec['regions']:
            s0,s1=(r['s0']/spec['width_m']-.5)*width,(r['s1']/spec['width_m']-.5)*width
            d=spec['glass_thickness_m'] if r['role']=='glass' else depth
            build_up=spec.get('glazing_build_up_m') if r['role']=='glass' else None
            bounds=placement.get('normal_bounds_m',[-d/2,d/2]) if r['role']=='glass' else [-d/2,d/2]
            tmin,tmax=bounds
            thicknesses=[(tmin,tmin+build_up[0]),(tmax-build_up[2],tmax)] if build_up else [(tmin,tmax)]
            for layer_index,(t0,t1) in enumerate(thicknesses):
                p=Polygon([(cx+ux*s-uy*t,cy+uy*s+ux*t) for s,t in [(s0,t0),(s1,t0),(s1,t1),(s0,t1)]])
                components.append({**profile_dict(p),'role':r['role'],'height':r['z1']-r['z0'],'z_offset':r['z0'],
                               'source':{'geometry_status':'drawing_correlated','dimension_verified':False,
                                         'material':'glazing' if r['role']=='glass' else 'metal',
                                         'references':deepcopy(spec['references']),'schedule_mark':spec['mark'],
                                         'glazing_layer_index':layer_index if build_up else None,
                                         'glazing_build_up_m':build_up,
                                         'parameter_keys':[],'association_status':'mark_floor_scope_outer_width_correlated_not_reviewed'}})
        e['components']=components
        src['schedule_assignment']={k:deepcopy(v) for k,v in spec.items() if k!='regions'}
        src['schedule_assignment'].update(status='mark_floor_scope_outer_width_correlated_not_reviewed',
            plan_references=deepcopy(links),width_residual_m=abs(axis['width_m']-spec['width_m']),
            glazing_plan_placement=placement,
            sill_reference='A10 lower dimension datum; floor FFL/SSL assignment remains provisional')
        src['provisional_opening']={'height':spec['height_m'],'z_offset':spec['sill_m'],'dimension_verified':False,
                                    'parameter_keys':[],'status':'drawing_correlated_not_design_approved'}
        for k in ('window_height','window_sill','glass_thickness','frame_width'):src.get('assumptions',{}).pop(k,None)
        src['property_status'].update(height='drawing_correlated',section='drawing_correlated',member_mark='drawing_correlated')
        src['assembly_status']='drawing_correlated_not_design_approved'
        src['unknowns']=['individual_material_product','plan_callout_review','floor_datum_assignment','revision_assignment']
        if placement['status']=='provisional':src.setdefault('assumptions',{})['glass_placement']=placement
        src['type_definition']={'kind':'window','mark':spec['mark'],'width_m':spec['width_m'],
                                'height_m':spec['height_m'],'sill_m':spec['sill_m'],
                                'glass_thickness_m':spec['glass_thickness_m'],'references':deepcopy(spec['references']),
                                'status':'drawing_correlated_not_design_approved'}
        report.append({'element_id':e['id'],'floor_id':e['floor_id'],'mark':spec['mark'],
                       'width_m':width,'height_m':spec['height_m'],'sill_m':spec['sill_m'],
                       'glass_thickness_m':spec['glass_thickness_m'],'components':len(components),
                       'width_residual_m':abs(width-spec['width_m']),'design_verified':False})
    return report
