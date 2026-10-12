"""Structural drafting from native axes, girder marks, supports and section rows.

This is an explicit interpreted placement, not a recovered native beam outline.
Unsupported spans, alternate sections and ambiguous tags stay unresolved.
"""
from collections import defaultdict
import hashlib, math, re
import numpy as np
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from bf_bim.geometry import polygon_parts
from .rebuild import layer, profile_dict, safe


def native_grids(archive):
    groups=defaultdict(list)
    clipped={w.get('entity_id') for w in archive.get('warnings',[]) if w['code']=='XCLIP_NOT_APPLIED'}
    for e in archive['scene_entities']:
        if safe(e,clipped):groups[e.get('root_entity_id',e['id'])].append(e)
    result=[]
    for root,es in groups.items():
        ts=[e for e in es if e['type']=='TEXT' and re.fullmatch(r'[XYZAB]\d+',e['geometry']['text'].strip()) and '주열' in layer(e)]
        cs=[e for e in es if e['type']=='CIRCLE' and 'AXIS' in layer(e)]
        if len(ts)<8:continue
        controls={}
        for t in ts:
            matches=[c for c in cs if math.dist(t['geometry']['insert'][:2],c['geometry']['center'][:2])<c['geometry']['radius']]
            if len(matches)!=1:continue
            c=matches[0]
            ls=[q for q in es if q['type']=='LINE' and 'AXIS' in layer(q) and any(math.dist(c['geometry']['center'][:2],q['geometry'][k][:2])<2*c['geometry']['radius'] for k in ('start','end'))]
            if len(ls)!=1:continue
            q=ls[0];v=np.array(q['geometry']['end'][:2])-q['geometry']['start'][:2];v=v/np.linalg.norm(v)
            label=t['geometry']['text'].strip()
            if label in controls:raise ValueError('Duplicate structural grid label '+label)
            controls[label]={'xy':c['geometry']['center'][:2],'normal':[-float(v[1]),float(v[0])],'cad_ids':[t['id'],c['id'],q['id']]}
        if len(controls)>=8:result.append({'root':root,'controls':controls})
    return result


def register_grid_lines(source,target,origin,tolerance=.002):
    """Bubble centres can slide along an axis; constrain the infinite axis line."""
    labels=sorted(set(source['controls'])&set(target['controls']))
    if len(labels)<8:raise ValueError('Too few labelled native grid axes')
    normals=np.array([source['controls'][l]['normal'] for l in labels])
    if np.linalg.matrix_rank(normals)<2:raise ValueError('Parallel controls cannot register 2D placement')
    for l in labels:
        if abs(np.dot(source['controls'][l]['normal'],target['controls'][l]['normal']))<.999999:
            raise ValueError('Axis rotation/reflection requires explicit registration')
    cad=np.array([source['controls'][l]['xy'] for l in labels])*.001
    dst=(np.array([target['controls'][l]['xy'] for l in labels])-origin)*.001
    rhs=np.sum(normals*(dst-cad),axis=1);shift=np.linalg.lstsq(normals,rhs,rcond=None)[0]
    residual=max(abs(normals@shift-rhs))
    if residual>tolerance:raise ValueError('Structural axis registration mismatch')
    controls=[{'label':l,'source_cad_ids':source['controls'][l]['cad_ids'],'target_cad_ids':target['controls'][l]['cad_ids'],
        'normal_residual_m':float(abs(np.dot(normals[i],shift)-rhs[i]))} for i,l in enumerate(labels)]
    return {'translation_m':shift.tolist(),'max_normal_residual_m':float(residual),'controls':controls,
            'method':'corresponding labelled native axis lines; do not equate displaced bubble centres'}


def section_matches(mark,schedule,kind='beam'):
    def applies(value):
        if value==mark:return True
        m=re.fullmatch(r'([1-4])~([1-4r])([GBS]\d+)',value)
        q=re.fullmatch(r'([1-4r])([GBS]\d+)',mark)
        return bool(m and q and m[3]==q[2] and '1234r'.index(m[1])<='1234r'.index(q[1])<='1234r'.index(m[2]))
    rows=[r for r in schedule['embedded_rows'] if r['kind']==kind and applies(r['mark'])]
    if len({tuple(r['dimensions_m']) for r in rows})!=1:return []
    return rows


def support_pairs(columns,pos,angle):
    """Require one adjacent, nearly parallel support span containing the tag."""
    u=np.array([math.cos(angle),math.sin(angle)]);choices=[]
    points=[np.array(Polygon(c['polygon'],c.get('holes',[])).centroid.coords[0]) for c in columns]
    for i,p in enumerate(points):
        for j in range(i+1,len(points)):
            q=points[j];v=q-p;length=float(np.linalg.norm(v))
            if not 2<length<15 or abs(u[0]*v[1]-u[1]*v[0])/length>math.sin(math.radians(.1)):continue
            along=float(np.dot(pos-p,v)/length);offset=abs((pos-p)[0]*v[1]-(pos-p)[1]*v[0])/length
            if not .25*length<along<.75*length or offset>1.2:continue
            axis=LineString([p,q])
            if any(axis.distance(Polygon(c['polygon']).centroid)<.05 and .01<axis.project(Polygon(c['polygon']).centroid,normalized=True)<.99 for k,c in enumerate(columns) if k not in (i,j)):continue
            choices.append({'support_ids':[columns[i]['id'],columns[j]['id']],'axis':[p.tolist(),q.tolist()],
                            'span_m':length,'annotation_offset_m':float(offset)})
    return choices


def build_girders(elements,specs,plan,structure,row,schedule):
    if any(a['units']['meters_per_drawing_unit']!=.001 for a in (plan,structure)):
        raise ValueError('This structural adapter requires verified millimetre drawings')
    native_ids={e['id'] for e in structure['scene_entities'] if safe(e,set())}
    schedule={'embedded_rows':[r for r in schedule['embedded_rows'] if r['drawing_id']=='S02-001~'
        and r['source_sha256']==row['sha256'] and set(r['cad_ids'])<=native_ids]}
    source_grids=native_grids(structure);target_grids=native_grids(plan)
    clipped={w.get('entity_id') for w in structure.get('warnings',[]) if w['code']=='XCLIP_NOT_APPLIED'}
    reports=[];beams=[];unresolved=[];slab_assignments=[]
    ordered=['b1','f1','f2','f3','f4','roof','phroof']
    # The titles and repeated 126150 mm sheet translation are observations in S02.
    source_first=188844.299705;spacing=126150.00007091
    for index,fid in enumerate(ordered):
        spec=specs[fid];origin=np.array(spec['origin'])
        src=[g for g in source_grids if 'Z1' in g['controls'] and abs(g['controls']['Z1']['xy'][0]-(source_first+(index-1)*spacing))<1 and -625000<g['controls']['Z1']['xy'][1]<-600000]
        dst=[g for g in target_grids if 'Z1' in g['controls'] and origin[0]-10000<g['controls']['Z1']['xy'][0]<origin[0]+20000 and origin[1]+50000<g['controls']['Z1']['xy'][1]<origin[1]+90000]
        if not src or len(dst)!=1:
            unresolved.append({'floor_id':fid,'reason':'Native labelled grid sheet not uniquely located'});continue
        registration=register_grid_lines(src[0],dst[0],origin);reports.append({'floor_id':fid,**registration})
        if fid in ('b1','phroof'):continue # no located supporting storey / unresolved upper datum
        prefix={'f1':'1','f2':'2','f3':'3','f4':'4','roof':'r'}[fid]
        cx=src[0]['controls']['Z1']['xy'][0]
        slab_tags=[e for e in structure['scene_entities'] if e['type']=='TEXT' and safe(e,clipped) and re.fullmatch(prefix+r'S\d+',e['geometry']['text'].strip()) and cx-10000<e['geometry']['insert'][0]<cx+85000 and -677000<e['geometry']['insert'][1]<-622000]
        slab_rows=[section_matches(e['geometry']['text'].strip(),schedule,'slab') for e in slab_tags]
        thicknesses={r[0]['dimensions_m'][0] for r in slab_rows if r}
        # A mixed S1/S4 sheet cannot become a blanket 150 mm slab. The existing
        # outline remains provisional even where all located marks agree.
        if len(slab_tags)>=3 and all(slab_rows) and len(thicknesses)==1:
            thickness=next(iter(thicknesses))
            for e in elements:
                if e['floor_id']!=fid or e['type'] not in ('floor','roof') or not e['components']:continue
                refs=[r for rows_ in slab_rows for r in rows_]
                changes=[]
                for c in e['components']:
                    if c['role']!='structural_slab':continue
                    old=c['height'];top=c['z_offset']+old
                    c.update(height=thickness,z_offset=top-thickness)
                    c['source']['structural_thickness_assignment']={'status':'uniform_observed_sheet_schedule_candidate',
                        'thickness_m':thickness,'marks':sorted({q['geometry']['text'].strip() for q in slab_tags}),
                        'native_boundary_verified':False,'unlabelled_region_assignment_verified':False}
                    changes.append({'previous_thickness_m':old,'thickness_m':thickness,'top_offset_m':top})
                if changes:
                    evidence={'element_id':e['id'],'floor_id':fid,'changes':changes,'cad_ids':[q['id'] for q in slab_tags],
                              'section_references':refs,'status':'uniform_observed_sheet_schedule_candidate','boundary_verified':False}
                    e['source']['structural_slab_evidence']=evidence;slab_assignments.append(evidence)
                    e['source']['assumptions'].pop('slab_thickness',None)
                    e['source']['unknowns']+=['Structural thickness applies to observed sheet marks; unlabelled region and native slab perimeter remain unverified.']
        else:
            unresolved.append({'floor_id':fid,'kind':'slab','reason':'Mixed or unassigned slab marks require located panel boundaries',
                               'marks':sorted({q['geometry']['text'].strip() for q in slab_tags}),'thicknesses_m':sorted(thicknesses)})
        tags=[e for e in structure['scene_entities'] if e['type']=='TEXT' and safe(e,clipped) and re.fullmatch(prefix+r'G\d+[A-Z]?',e['geometry']['text'].strip()) and cx-10000<e['geometry']['insert'][0]<cx+85000 and -677000<e['geometry']['insert'][1]<-622000]
        below=ordered[index-1]
        columns=[e for e in elements if e['type']=='column' and e['floor_id']==below and not e['source'].get('section_candidate_suppressed')]
        used={};floor_polys=[Polygon(e['polygon'],e.get('holes',[])) for e in elements if e['floor_id']==fid and e['type'] in ('floor','roof')]
        floor_region=unary_union(floor_polys)
        for tag in tags:
            mark=tag['geometry']['text'].strip();rows=section_matches(mark,schedule)
            pos=np.array(tag['geometry']['insert'][:2])*.001+registration['translation_m']
            choices=support_pairs(columns,pos,math.radians(tag['geometry'].get('rotation_deg',0)))
            reason='section unavailable/conflicting' if not rows else 'support span ambiguous/unlocated' if len(choices)!=1 else None
            if reason:
                unresolved.append({'floor_id':fid,'cad_id':tag['id'],'mark':mark,'reason':reason,'support_candidates':choices});continue
            match=choices[0];key=tuple(sorted(match['support_ids']))
            if key in used:
                # Duplicate or conflicting marks are resolved after collecting this sheet.
                used[key].append((tag,rows,match));continue
            used[key]=[(tag,rows,match)]
        for key,entries in used.items():
            if len({(e[0]['geometry']['text'].strip(),tuple(e[1][0]['dimensions_m'])) for e in entries})!=1:
                unresolved.append({'floor_id':fid,'support_ids':list(key),'reason':'Conflicting girder marks for same span'});continue
            tag,rows,match=entries[0];width,depth=rows[0]['dimensions_m'];axis=LineString(match['axis'])
            footprint=axis.buffer(width/2,cap_style=2)
            if not floor_region.buffer(width).covers(axis):
                unresolved.append({'floor_id':fid,'cad_id':tag['id'],'reason':'Span outside current slab/roof candidate support'});continue
            # The existing finish top is FL and concrete top is FL-30. Use the
            # current slab underside; local recesses stay unassigned.
            bottoms={round(c['z_offset'],8) for e in elements if e['floor_id']==fid and e['type'] in ('floor','roof') for c in e['components'] if c['role']=='structural_slab'}
            if len(bottoms)!=1:
                unresolved.append({'floor_id':fid,'cad_id':tag['id'],'reason':'Slab underside not uniformly located'});continue
            bottom=-.03-depth;top=next(iter(bottoms))
            col_union=unary_union([Polygon(c['polygon'],c.get('holes',[])) for c in columns])
            net=footprint.difference(col_union)
            identity='struct-'+hashlib.sha256((fid+'::'+tag['id']).encode()).hexdigest()[:20]
            src={'drawing_id':'S02-001~','file':row['file'],'source_sha256':row['sha256'],'cad_ids':[e[0]['id'] for e in entries],
                 'method':'interpreted structural girder: native grid registration + plan G mark + unique adjacent architectural column span + literal section schedule',
                 'validation_status':'provisional','geometry_status':'interpreted_drawing_assembly','material':'concrete',
                 'property_status':{'position':'drawing_interpretation','section':'drawing_correlated','height':'provisional','material':'drawing_correlated'},
                 'structural_girder':{'mark':tag['geometry']['text'].strip(),**match,'section_m':[width,depth],
                     'section_references':rows,'registration':registration,'native_outline_recovered':False,'member_assignment_verified':False},
                 'assumptions':{'beam_top':{'value_m':-.03,'status':'provisional','reason':'Inherited FL-30 concrete datum; local SL recess and beam section elevation unassigned'},
                                'slab_underside':{'value_m':top,'status':'provisional','reason':'Current slab underside; sheet-correlated thickness where uniform, local recess and native perimeter unverified'}},
                 'unknowns':['native_beam_outline','individual_SL_level','beam_member_assignment','local_joint_detail','reinforcement'],
                 'position_status':'drawing_interpretation','section_status':'drawing_correlated','design_verified':False}
            components=[{**profile_dict(p),'role':'structural_girder','height':top-bottom,'z_offset':bottom,
                'source':{'material':'concrete','section_mark':tag['geometry']['text'].strip(),'dimension_verified':False,'geometry_status':'provisional'}} for p in polygon_parts(net) if p.area>1e-6]
            if not components:continue
            beams.append({'id':identity,'name':spec['name']+' · 구조 보 '+tag['geometry']['text'].strip(),'type':'beam','floor_id':fid,
                          **profile_dict(footprint),'height':None,'z_offset':0,'verified':False,'excluded':False,'properties':{},'source':src,'components':components})
    return beams,{'registrations':reports,'slab_assignments':slab_assignments,'girders':[{'element_id':e['id'],'floor_id':e['floor_id'],**e['source']['structural_girder']} for e in beams],
                  'unresolved':unresolved,'design_verified':False,'policy':'interpreted placement; no nearest-label approval; no unlocated B beams or generic grid infill'}


def trim_wall_heads(elements,beams,specs):
    """Remove only overlapping volumes; preserve body/plan/BF boundaries."""
    audit=[]
    for wall in elements:
        if wall['type']!='wall':continue
        base=specs[wall['floor_id']]['elevation'];result=[];volume=0.
        for c in wall['components']:
            if c.get('mesh'):c={k:v for k,v in c.items() if k!='mesh'}
            if c['height'] is None:result.append(c);continue
            low=base+c['z_offset'];high=low+c['height'];profile=Polygon(c['polygon'],c.get('holes',[]))
            cuts=[]
            for beam in beams:
                for bc in beam['components']:
                    bbase=specs[beam['floor_id']]['elevation'];lo=bbase+bc['z_offset'];hi=lo+bc['height']
                    p=Polygon(bc['polygon'],bc['holes'])
                    if min(high,hi)-max(low,lo)>1e-6 and profile.intersection(p).area>1e-7:cuts.append((max(low,lo),min(high,hi),p,beam['id']))
            if not cuts:result.append(c);continue
            levels=sorted({low,high,*[v for lo,hi,_,_ in cuts for v in (lo,hi)]})
            for lo,hi in zip(levels,levels[1:]):
                if hi-lo<1e-7:continue
                active=[p for a,b,p,_ in cuts if a<hi-1e-8 and b>lo+1e-8]
                net=profile.difference(unary_union(active));volume+=(profile.area-net.area)*(hi-lo)
                for p in polygon_parts(net):
                    if p.area>1e-7:result.append({**c,**profile_dict(p),'height':hi-lo,'z_offset':lo-base,
                        'source':{**c['source'],'structural_head_cut':sorted({i for a,b,_,i in cuts if a<hi and b>lo})}})
        if volume>0:
            wall['components']=result;wall['source']['structural_head_cut_volume_m3']=volume
            audit.append({'wall_id':wall['id'],'floor_id':wall['floor_id'],'removed_duplicate_volume_m3':volume})
    return audit
