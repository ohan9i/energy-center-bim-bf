"""Restore door opening axes from native jamb pairs rather than swing arcs.

A swing radius includes symbol offsets and is not the outer door width.
Paired native closed jambs require an exact inner-span line or a unique pair
with compatible referenced swing radii. Ambiguous pairs remain unresolved.
"""
from collections import defaultdict
from copy import deepcopy
import math
import re
from shapely.geometry import Polygon, LineString, Point
from shapely import set_precision
from shapely.ops import unary_union,polygonize
from .rebuild import native_profile, profile_dict, safe, layer
from .schema import Registration
from .window_authoring import _dimension


def native_door_groups(elements,archive,specs):
    lookup={q['id']:q for q in archive['scene_entities']}
    families=defaultdict(list)
    for q in archive['scene_entities']:
        for root in q.get('insert_ancestry',[]):families[root].append(q)
    clipped={w.get('entity_id') for w in archive['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
    roots=defaultdict(list)
    for e in elements:
        if e['type']!='door':continue
        refs=e['source'].get('cad_ids',[])
        arcs=[lookup[r] for r in refs if r in lookup and lookup[r]['type']=='ARC']
        if len(arcs)!=1 or not arcs[0].get('insert_ancestry'):continue
        roots[(e['floor_id'],arcs[0]['insert_ancestry'][-1])].append(e)
    result=[]
    for (fid,root),doors in roots.items():
        frame=Registration(id=fid+'-door-native',drawing_id='A04-001~008',origin_cad=tuple(specs[fid]['origin']),scale_m_per_unit=.001)
        polys=[];lines=[];panels=[]
        for q in families[root]:
            if not safe(q,clipped) or layer(q) not in ('A-DOOR','A-DOR','A-WIN'):continue
            try:l,p=native_profile(q,frame)
            except (ValueError,KeyError,TypeError,NotImplementedError):continue
            if p is None and l.is_ring:p=Polygon(l.coords)
            if p and p.is_valid:
                r=list(p.minimum_rotated_rectangle.exterior.coords)
                sizes=sorted([math.dist(r[0],r[1]),math.dist(r[1],r[2])])
                if layer(q) in ('A-DOOR','A-DOR') and .025<sizes[0]<.09 and .08<sizes[1]<.251 and abs(p.area-sizes[0]*sizes[1])<1e-7:
                    polys.append((p,q['id'],sizes))
                if .02<sizes[0]<.081 and .5<sizes[1]<2.5 and abs(p.area-sizes[0]*sizes[1])<1e-7:
                    panels.append((p,q['id'],sizes))
            if q['type']=='LINE' and layer(q) in ('A-DOOR','A-DOR'):lines.append((l,q['id']))
        for i,(a,aid,asz) in enumerate(polys):
            for b,bid,bsz in polys[i+1:]:
                span=a.centroid.distance(b.centroid)
                if not .5<span<5 or max(abs(asz[k]-bsz[k]) for k in (0,1))>1e-6:continue
                ux=(b.centroid.x-a.centroid.x)/span;uy=(b.centroid.y-a.centroid.y)/span
                cx=(a.centroid.x+b.centroid.x)/2;cy=(a.centroid.y+b.centroid.y)/2
                uv=[((x-cx)*ux+(y-cy)*uy,-(x-cx)*uy+(y-cy)*ux) for p in (a,b) for x,y in p.exterior.coords]
                lo,hi=min(s for s,t in uv),max(s for s,t in uv);t0,t1=min(t for s,t in uv),max(t for s,t in uv)
                if abs(hi-lo-(span+asz[0]))>1e-6 or abs(t1-t0-asz[1])>1e-6:continue
                bridges=[(l,k) for l,k in lines if abs(l.length-(span-asz[0]))<1e-6
                         and ((a.boundary.distance(Point(l.coords[0]))<1e-6 and b.boundary.distance(Point(l.coords[-1]))<1e-6)
                         or (b.boundary.distance(Point(l.coords[0]))<1e-6 and a.boundary.distance(Point(l.coords[-1]))<1e-6))]
                matched=[]
                for e in doors:
                    arc=lookup[e['source']['cad_ids'][0]]
                    center=arc['geometry']['center'];p=Point((center[0]-frame.origin_cad[0])*.001,(center[1]-frame.origin_cad[1])*.001)
                    if min(p.distance(a),p.distance(b))<.12:matched.append(e)
                if not 1<=len(matched)<=2:continue
                radii=[lookup[e['source']['cad_ids'][0]]['geometry']['radius']*.001 for e in matched]
                if abs(sum(radii)-(span-asz[0]))>.2:continue
                poly=Polygon([(cx+ux*s-uy*t,cy+uy*s+ux*t) for s,t in [(lo,t0),(hi,t0),(hi,t1),(lo,t1)]])
                leaf_plans={}
                for e in matched:
                    arc=lookup[e['source']['cad_ids'][0]]
                    pts=[Point((arc['geometry'][k][0]-frame.origin_cad[0])*.001,(arc['geometry'][k][1]-frame.origin_cad[1])*.001) for k in ('start','end')]
                    center=arc['geometry']['center'];pivot=Point((center[0]-frame.origin_cad[0])*.001,(center[1]-frame.origin_cad[1])*.001)
                    # Both closed leaves can touch a shared meeting point.
                    # Require this leaf's own native hinge as well as its arc tip.
                    hits=[(p,k,sz) for p,k,sz in panels if p.boundary.distance(pivot)<.12 and min(p.boundary.distance(pt) for pt in pts)<1e-6]
                    if len(hits)==1:
                        p,k,sz=hits[0];leaf_plans[e['id']]={'cad_id':k,'thickness_m':sz[0],'leaf_length_m':sz[1],
                            'status':'native plan symbol envelope; physical construction requires schedule',**profile_dict(p)}
                records={'floor_id':fid,'root_id':root,'elements':matched,'polygon':poly,'native_leaf_plans':leaf_plans,
                         'axis':{'origin':[cx,cy],'direction':[ux,uy],'width_m':hi-lo,'depth_m':t1-t0},
                         'jamb_width_m':asz[0],'cad_ids':[aid,bid,*[k for l,k in bridges],*[r for e in matched for r in e['source']['cad_ids']],*[p['cad_id'] for p in leaf_plans.values()]],
                         'method':'native closed jamb pair joined by exact native inner-span line' if bridges else 'unique native closed jamb pair and compatible referenced swing radii',
                         'swing_radius_sum_residual_m':abs(sum(radii)-(span-asz[0])),
                         'width_bridge_residual_m':min((abs(l.length-(span-asz[0])) for l,k in bridges),default=None)}
                result.append(records)
    memberships=defaultdict(int)
    for g in result:
        for e in g['elements']:memberships[e['id']]+=1
    return [g for g in result if all(memberships[e['id']]==1 for e in g['elements'])]


def door_catalog(archive,row):
    """Dimensioned A10 outer elevation and explicit floor scope, no defaults."""
    clipped={w.get('entity_id') for w in archive['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
    entities=[q for q in archive['scene_entities'] if safe(q,clipped)]
    texts=[q for q in entities if q['type'] in ('TEXT','MTEXT') and '/child:' not in q['id']]
    dims=[]
    for q in entities:
        if q['type']!='DIMENSION':continue
        d=_dimension(q)
        # '<>(2300)' preserves the native primary value and explicitly lists
        # an alternative. Do not assign the alternative to a revised mark.
        if d is None and re.fullmatch(r'<>\s*\(\d+(?:\.\d+)?\)',q['geometry'].get('text_override','').strip()):
            primary=deepcopy(q);primary['geometry']['text_override']='<> '
            d=_dimension(primary)
        if d:dims.append((q,d))
    catalog=[]
    for tag in texts:
        label=tag['geometry'].get('text','').strip()
        if label not in ('AD','SSD','SD','FSD','FSSD'):continue
        x,y=tag['geometry']['insert'][:2]
        numbers=[q for q in texts if re.fullmatch(r'\d+[a-z]?',q['geometry'].get('text','').strip())
                 and abs(q['geometry']['insert'][0]-x)<400 and 150<q['geometry']['insert'][1]-y<800]
        scopes=[q for q in texts if 500<q['geometry']['insert'][0]-x<2000 and -1300<q['geometry']['insert'][1]-y<-500
                and re.search(r'(?:B1|[1-4R])F\s*:',q['geometry'].get('text',''))]
        if len(numbers)!=1 or len(scopes)!=1:continue
        nearby=[(q,d) for q,d in dims if all(x-100<p[0]<x+8000 and y+1000<p[1]<y+7000 for p in d[1:3])]
        hs=[(q,d) for q,d in nearby if d[0]=='x'];vs=[(q,d) for q,d in nearby if d[0]=='y']
        if not hs or not vs:continue
        wd=max(hs,key=lambda q:q[1][3]);hd=max(vs,key=lambda q:q[1][3])
        xmin,xmax=sorted(p[0] for p in wd[1][1:3]);ymin,ymax=sorted(p[1] for p in hd[1][1:3])
        frame=Registration(id='door-elevation',drawing_id='A10-001~',origin_cad=(xmin,ymin),scale_m_per_unit=.001)
        outlines=[];bars=[]
        for q in entities:
            if q['type'] not in ('LINE','LWPOLYLINE') or layer(q)!='A-DOOR':continue
            bb=q.get('bounds')
            if not bb or bb['min'][0]<xmin-.5 or bb['max'][0]>xmax+.5 or bb['min'][1]<ymin-.5 or bb['max'][1]>ymax+.5:continue
            try:l,p=native_profile(q,frame)
            except (ValueError,KeyError,TypeError,NotImplementedError):continue
            if p is None and l.is_ring:p=Polygon(l.coords)
            if p:
                bx=p.bounds
                if max(abs(bx[k]-v) for k,v in enumerate((0,0,wd[1][3],hd[1][3])))<.0005 and abs(p.area-wd[1][3]*hd[1][3])<1e-6:outlines.append((p,q['id']))
            bars.append((l,q['id']))
        if not outlines:continue
        descriptions=[q for q in texts if 500<q['geometry']['insert'][0]-x<2000 and -1100<q['geometry']['insert'][1]-y<1100]
        scope=scopes[0]['geometry']['text']
        floors=sorted(set('b1' if f=='B1' else 'roof' if f=='R' else 'f'+f for f in re.findall(r'(B1|[1-4R])F\s*:',scope)))
        description=' / '.join(q['geometry']['text'] for q in descriptions)
        fixed=re.search(r'FIX\s*:\s*THK\s*(\d+(?:\.\d+)?)',description)
        moving=re.search(r'DOOR\s*:\s*THK\s*(\d+(?:\.\d+)?)',description)
        tube=re.search(r'\((\d+)\s*[×Xx]\s*(\d+)\s*[×Xx]\s*(\d+(?:\.\d+)?)T\)',description)
        catalog.append({'mark':label+'-'+numbers[0]['geometry']['text'].strip(),'width_m':wd[1][3],'height_m':hd[1][3],
                        'floors':floors,'scope_text':scope,'description':[q['geometry']['text'] for q in descriptions],
                        'fixed_glass_thickness_m':float(fixed[1])*.001 if fixed else None,
                        'leaf_glass_thickness_m':float(moving[1])*.001 if moving else None,
                        'frame_tube_section_m':[float(v)*.001 for v in tube.groups()] if tube else None,
                        'elevation_origin_cad':[xmin,ymin],
                        'elevation_lines':[{'points':list(l.coords),'cad_id':k} for l,k in bars],
                        'references':[{'drawing_id':'A10-001~','file':row['file'],'source_sha256':row['sha256'],
                                       'cad_ids':[tag['id'],numbers[0]['id'],scopes[0]['id'],wd[0]['id'],hd[0]['id'],outlines[0][1],*[k for l,k in bars],*[q['id'] for q in descriptions]]}],
                        'status':'dimensioned_elevation_not_design_approved'})
    return catalog


def restore_door_assemblies(elements,archive,specs):
    groups=native_door_groups(elements,archive,specs);report=[];removed=set()
    lookup={q['id']:q for q in archive['scene_entities']}
    for g in groups:
        target=g['elements'][0];src=target['source'];axis=g['axis'];cx,cy=axis['origin'];ux,uy=axis['direction'];w=axis['width_m']
        # Keep one existing identifier for each actual opening, with every
        # former leaf identifier and CAD arc retained as traceable aliases.
        others=g['elements'][1:];removed.update(e['id'] for e in others)
        links=[q for e in g['elements'] for q in e['source'].get('plan_schedule_links',[])]
        src['plan_schedule_links']=links
        original=[{'element_id':e['id'],'polygon':deepcopy(e['polygon']),
                   'arc_cad_id':e['source']['cad_ids'][0]} for e in g['elements']]
        src['native_door_evidence']={k:v for k,v in g.items() if k not in ('elements','polygon','axis')}
        src['native_door_evidence'].update(width_m=w,depth_m=axis['depth_m'],
            original_leaf_candidates=original,superseded_leaf_ids=[e['id'] for e in others],
            status='drawing_correlated_not_design_approved')
        src['cad_ids']=g['cad_ids'];src['door_plan_axis']=axis
        src['hinge']=[cx-ux*w/2,cy-uy*w/2];src['leaf_end']=[cx+ux*w/2,cy+uy*w/2]
        src.pop('swing_end',None)  # Each actual leaf has its own pivot below.
        target.update(profile_dict(g['polygon']))
        leaves=[]
        for e,o in zip(g['elements'],original):
            arc=lookup[o['arc_cad_id']];p=arc['geometry']['center'];ox,oy=specs[target['floor_id']]['origin']
            pos=[(p[0]-ox)*.001,(p[1]-oy)*.001]
            side=-1 if (pos[0]-cx)*ux+(pos[1]-cy)*uy<0 else 1
            ends=[[(arc['geometry'][k][0]-ox)*.001,(arc['geometry'][k][1]-oy)*.001] for k in ('start','end')]
            swing=max(ends,key=lambda p:abs(-(p[0]-cx)*uy+(p[1]-cy)*ux))
            leaves.append({'side':side,'swing_side':1 if -(swing[0]-cx)*uy+(swing[1]-cy)*ux>=0 else -1,
                           'arc_cad_id':o['arc_cad_id'],'native_leaf_plan':g['native_leaf_plans'].get(e['id'])})
        src['door_leaf_layout']=leaves
        # Leaf thickness is not silently inferred from the radius.
        src['assumptions']['door_leaf_layout']={'status':'provisional','reason':'Closed leaf split from native pivot sides; internal meeting gap and hardware unresolved.'}
        src['property_status']['profile']='drawing_correlated'
        report.append({'element_id':target['id'],'floor_id':target['floor_id'],'width_m':w,
                       'leaf_count':len(leaves),'superseded_leaf_ids':[e['id'] for e in others],
                       'cad_ids':g['cad_ids'],'width_bridge_residual_m':g['width_bridge_residual_m']})
    elements[:]=[e for e in elements if e['id'] not in removed]
    return report


def correlate_door_tags(elements,archive,row,specs,catalog,registration):
    """Use registered symbol centres, width and floor scope together.

    The result is a correlation, never a leader-confirmed design approval.
    Generic arc candidates must not steal a symbol from a recovered opening.
    """
    registered={r['floor_id'] for r in registration if r['registration_status']=='control_geometry_match'}
    clipped={w.get('entity_id') for w in archive['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
    report=[]
    for fid,spec in specs.items():
        if fid not in registered:continue
        ox,oy=spec['origin']
        ts=[q for q in archive['scene_entities'] if q['type']=='TEXT' and q['geometry'].get('insert')
            and ox<q['geometry']['insert'][0]<ox+100000 and oy<q['geometry']['insert'][1]<oy+90000 and safe(q,clipped)]
        circles=[q for q in archive['scene_entities'] if q['type']=='CIRCLE' and layer(q) in ('A-SYM','A-SYMB')
                 and ox<q['geometry']['center'][0]<ox+100000 and oy<q['geometry']['center'][1]<oy+90000 and safe(q,clipped)]
        for tag in ts:
            label=tag['geometry'].get('text','').strip()
            if label not in ('AD','SSD','SD','FSD','FSSD'):continue
            x,y=tag['geometry']['insert'][:2]
            nums=[q for q in ts if re.fullmatch(r'\d+[a-z]?',q['geometry'].get('text','').strip()) and abs(q['geometry']['insert'][0]-x)<400 and 150<q['geometry']['insert'][1]-y<800]
            if len(nums)!=1:continue
            mark=label+'-'+nums[0]['geometry']['text'].strip()
            types=[q for q in catalog if q['mark']==mark and fid in q['floors']]
            if len(types)!=1:continue
            symbol=[q for q in circles if 200<q['geometry']['radius']<800 and math.dist(q['geometry']['center'][:2],nums[0]['geometry']['insert'][:2])<600 and math.dist(q['geometry']['center'][:2],[x,y])<800]
            if len(symbol)!=1:continue
            center=symbol[0]['geometry']['center'];pt=Point((center[0]-ox)*.001,(center[1]-oy)*.001)
            choices=sorted([(Polygon(e['polygon'],e.get('holes',[])).distance(pt),e) for e in elements
                           if e['type']=='door' and e['floor_id']==fid and e['source'].get('door_plan_axis')
                           and abs(e['source']['door_plan_axis']['width_m']-types[0]['width_m'])<.002],key=lambda q:q[0])
            if not choices or choices[0][0]>2 or len(choices)>1 and choices[1][0]-choices[0][0]<.2:continue
            distance,e=choices[0]
            link={'mark':mark,'floor_id':fid,'distance_m':distance,'status':'registered_symbol_width_scope_correlation',
                  'assignment_verified':False,'drawing_id':'A10-001~','file':row['file'],'source_sha256':row['sha256'],
                  'cad_ids':[tag['id'],nums[0]['id'],symbol[0]['id']],
                  'reason':'Native jamb width, stated floor and unique nearby native symbol agree; leader/member association remains reviewable.'}
            e['source'].setdefault('dimensioned_door_plan_links',[]).append(link)
            report.append({'element_id':e['id'],**link})
    return report


def apply_door_assemblies(elements,catalog,parameters):
    assignments=[]
    for e in elements:
        s=e['source'];axis=s.get('door_plan_axis')
        if e['type']!='door' or not axis:continue
        w=axis['width_m'];d=axis['depth_m'];f=s['native_door_evidence']['jamb_width_m']
        marks={q['mark'] for q in s.get('dimensioned_door_plan_links',[])}
        matches=[q for q in catalog if len(marks)==1 and q['mark'] in marks and e['floor_id'] in q['floors'] and abs(q['width_m']-w)<.002]
        h=parameters['door_height'];zleaf=h-f;rails=[];a=None
        if len(matches)==1:
            a=deepcopy(matches[0]);h=a['height_m']
            a.update(width_residual_m=abs(w-a['width_m']),status='drawing_correlated_not_design_approved')
            s['door_schedule_assignment']=a
            s['type_definition']={k:a[k] for k in ('mark','width_m','height_m','status','references')};s['type_definition']['kind']='door'
            s['assumptions'].pop('door_height',None);s['property_status']['height']='drawing_correlated'
            # Native full-span horizontal bars distinguish the leaf head from
            # fixed upper glazing. A 2.8m assembly is not a 2.8m moving leaf.
            zs=sorted({round(p[1],6) for l in a['elevation_lines'] for p,q in zip(l['points'],l['points'][1:])
                       if abs(p[1]-q[1])<1e-6 and min(p[0],q[0])<=f+.001 and max(p[0],q[0])>=w-f-.001})
            rails=[(lo,hi) for lo,hi in zip(zs,zs[1:]) if .025<hi-lo<.081 and lo>.5]
            internal=[r for r in rails if r[1]<h-.1]
            zleaf=internal[0][0] if internal else h-f
            a['leaf_head_m']=zleaf;a['leaf_head_status']='native_elevation_bar' if internal else 'provisional_frame_offset'
            assignments.append({'element_id':e['id'],'floor_id':e['floor_id'],'mark':a['mark'],'height_m':h,'width_m':w,'leaf_head_m':zleaf})
        cx,cy=axis['origin'];ux,uy=axis['direction']
        def component(lo,hi,t0,t1,z,height,role,**extra):
            p=Polygon([(cx+ux*x-uy*y,cy+uy*x+ux*y) for x,y in [(lo,t0),(hi,t0),(hi,t1),(lo,t1)]])
            return {**profile_dict(p),'role':role,'z_offset':z,'height':height,
                    'source':{'geometry_status':'provisional','dimension_verified':False,'material':'metal' if role!='door_leaf' else 'door',
                              'native_plan_evidence':s['native_door_evidence'],'parameter_keys':['door_height'] if len(matches)!=1 else [],**extra}}
        left,right=-w/2,w/2
        cs=[component(left,left+f,-d/2,d/2,0,h,'jamb'),component(right-f,right,-d/2,d/2,0,h,'jamb')]
        if rails:
            cs.extend(component(left+f,right-f,-d/2,d/2,lo,hi-lo,'head_frame' if hi>h-.1 else 'transom') for lo,hi in rails)
        else:cs.append(component(left+f,right-f,-d/2,d/2,h-f,f,'head_frame'))
        leaves=s['door_leaf_layout'];thickness=parameters['door_leaf_thickness']
        for leaf in leaves:
            native_leaf=leaf.get('native_leaf_plan');thickness=native_leaf['thickness_m'] if native_leaf else parameters['door_leaf_thickness']
            lo,hi=(left+f,right-f) if len(leaves)==1 else (left+f,0) if leaf['side']==-1 else (0,right-f)
            pivot=lo if leaf['side']==-1 else hi;end=hi if leaf['side']==-1 else lo
            hinge=[cx+ux*pivot,cy+uy*pivot];leaf_end=[cx+ux*end,cy+uy*end]
            swing=[hinge[0]-uy*(hi-lo)*leaf['swing_side'],hinge[1]+ux*(hi-lo)*leaf['swing_side']]
            motion={'hinge':hinge,'leaf_end':leaf_end,'swing_end':swing,
                    'native_leaf_plan':native_leaf,'parameter_keys':(['door_leaf_thickness'] if not native_leaf else [])+['door_leaf_layout']}
            panes=[]
            if a and a.get('leaf_glass_thickness_m'):
                network=unary_union([set_precision(LineString(l['points']),1e-6) for l in a['elevation_lines']])
                for p in polygonize(network):
                    p=Polygon(p.exterior);bx=p.bounds
                    if p.area>.5 and bx[0]>=lo+w/2-.000001 and bx[2]<=hi+w/2+.000001 and bx[1]>.02 and bx[3]<zleaf-.02 and bx[3]-bx[1]>1:
                        panes.append(p)
            if len(panes)==1:
                pane=panes[0];x0,z0,x1,z1=pane.bounds;x0-=w/2;x1-=w/2
                # The opaque moving envelope is split by the actual native
                # elevation glass boundary, with independent leaf pivots.
                for p0,p1,v0,v1 in [(lo,x0,z0,z1),(x1,hi,z0,z1),(lo,hi,0,z0),(lo,hi,z1,zleaf)]:
                    cs.append(component(p0,p1,-thickness/2,thickness/2,v0,v1-v0,'door_leaf',**motion))
                glass=a['leaf_glass_thickness_m']
                c=component(x0,x1,-glass/2,glass/2,z0,z1-z0,'door_leaf',**{**motion,'parameter_keys':['door_leaf_layout'],'material':'glazing',
                            'glass_thickness_m':glass,'elevation_pane_boundary':profile_dict(pane),'elevation_references':a['references']})
                cs.append(c)
                a.setdefault('native_leaf_glazing',[]).append({'side':leaf['side'],'thickness_m':glass,**profile_dict(pane)})
            else:cs.append(component(lo,hi,-thickness/2,thickness/2,0,zleaf,'door_leaf',**motion))
        if rails and zleaf<h-f-.1:
            # Transom glass thickness remains explicit preview information.
            low=next(hi for lo,hi in rails if abs(lo-zleaf)<1e-6);high=max(lo for lo,hi in rails)
            if high>low:
                glass=a.get('fixed_glass_thickness_m') or parameters['glass_thickness']
                c=component(left+f,right-f,-glass/2,glass/2,low,high-low,'glass',parameter_keys=[] if a.get('fixed_glass_thickness_m') else ['glass_thickness'])
                c['source']['material']='glazing';cs.append(c)
                if not a.get('fixed_glass_thickness_m'):s['assumptions']['glass_thickness']={'value_m':parameters['glass_thickness'],'reason':'Door transom glazing specification not assigned.'}
        e['components']=cs
        if all(l.get('native_leaf_plan') for l in leaves):s['assumptions'].pop('door_leaf_thickness',None)
        tube=a.get('frame_tube_section_m') if a else None
        if tube and abs(tube[0]-d)<1e-6 and abs(tube[1]-f)<1e-6 and 0<tube[2]<min(d,f)/2:
            t=tube[2];hollow=[]
            for c in cs:
                if c['role']=='jamb':
                    p=Polygon(c['polygon']);inner=p.buffer(-t,join_style=2)
                    c.update(profile_dict(p.difference(inner)));c['source']['tube_wall_thickness_m']=t
                    c['source']['tube_section_evidence']=a['references'];hollow.append(c)
                elif c['role'] in ('head_frame','transom'):
                    z=c['z_offset'];height=c['height']
                    for t0,t1,zz,hh in [(-d/2,-d/2+t,z,height),(d/2-t,d/2,z,height),
                                         (-d/2+t,d/2-t,z,t),(-d/2+t,d/2-t,z+height-t,t)]:
                        hollow.append(component(left+f,right-f,t0,t1,zz,hh,c['role'],
                                                tube_wall_thickness_m=t,tube_section_evidence=a['references']))
                else:hollow.append(c)
            e['components']=hollow
            a['frame_tube_applied']=True
        s['provisional_opening']={'z_offset':0.,'height':h,'dimension_verified':False,'parameter_keys':[] if len(matches)==1 else ['door_height']}
    return assignments
