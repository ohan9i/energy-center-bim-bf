"""Run: python -m bf_bim.precise.stage1 [--extract-all]. No legacy writes.

Audit metadata for all 30 DWGs is hash checked. Full reader archives can be
refreshed independently; the pilot only uses the complete A04 native archive.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import uuid

from cad_reader import analyze_drawing
from .geometry import closed_native, sample, to_local
from .schema import Member, Observation, Reference, Registration
from .validation import compare_plan, compare_vertical
from .transform_check import check_transforms

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT/'docs/bim-audit-2026-10-11'
OUTPUT = ROOT/'cad_output/precision-stage1'
NAMESPACE = uuid.UUID('2868c8e9-341e-4771-bb8e-3fdf5ab2c306')
CURVES = {'LINE','LWPOLYLINE','POLYLINE','ARC','CIRCLE','SPLINE','ELLIPSE'}
KINDS = {'A-COL':'column', 'A-CON':'wall', 'A-WALL':'wall', 'A-WAL':'wall', 'A-BRICK':'wall', 'A-SLAB':'floor',
         'A-DOOR':'door', 'A-WIN':'window', 'S-COL':'column', 'S-WALL':'wall',
         'S-BEAM':'beam', 'S-SLAB':'floor', 'A-STAIR':'stair'}


def read(path):
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    # Only our isolated output directory is writable through this function.
    if not path.resolve().is_relative_to(OUTPUT.resolve()):
        raise ValueError('Output must stay in the precision-stage1 directory')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    if path.suffix == '.gz':
        with gzip.open(temporary, 'wt', encoding='utf-8', compresslevel=3) as f:
            # C JSON encoding per top-level record avoids millions of tiny
            # Python writes for large expanded CAD scenes, without duplicating
            # the entire archive in memory.
            encode=lambda item:json.dumps(item,ensure_ascii=False,allow_nan=False,separators=(',',':'))
            f.write('{')
            for index,(key,item) in enumerate(value.items()):
                if index:f.write(',')
                f.write(encode(key)+':')
                if isinstance(item,list):
                    f.write('[')
                    for n,entry in enumerate(item):
                        if n:f.write(',')
                        f.write(encode(entry))
                    f.write(']')
                else:
                    f.write(encode(item))
            f.write('}')
    else:
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def drawing_id(row):
    return Path(row['file']).name.split()[0]


def audit_for(row):
    return read(AUDIT/(drawing_id(row)+'-audit.json'))


def role(identifier):
    if identifier.startswith(('S04','A03','A10-001')): return 'schedule'
    if identifier.startswith('A04-021') or identifier.startswith('S02-021'): return 'section'
    if identifier.startswith('A04-011'): return 'elevation'
    if identifier.startswith(('A05','A06','A07','A08','A10-041','A02-037','A02-067')): return 'detail'
    if identifier.startswith('S02') or identifier.startswith('S03'): return 'structure'
    if identifier.startswith(('A04','A02','A09')): return 'plan'
    return 'unknown'


def archive_path(identifier):
    return OUTPUT/'extractions'/(identifier+'.json.gz')


def load_native(row, refresh=False):
    identifier = drawing_id(row)
    source = ROOT/row['file']
    current = sha256(source)
    if current != row['sha256']:
        raise ValueError(f'{identifier}: source revision differs from audit; re-audit before using evidence')
    path = archive_path(identifier)
    if path.exists() and not refresh:
        data = read(path)
        if data['source']['sha256_before'] == current and data.get('precision_identity_version') == 1:
            if check_transforms(data):
                write(path,data)
            return data
    # Old flattened caches can lose definition handles on circle -> ellipse
    # conversions. Reuse only versioned precision archives with those links.
    print(f'Extracting {identifier}: isolated temporary conversion', flush=True)
    data = analyze_drawing(source,precise_identity=True)
    data['precision_identity_version'] = 1
    check_transforms(data)
    if data['source']['sha256_before'] != current or not data['source']['original_unchanged']:
        raise ValueError('Source changed during extraction')
    write(path, data)
    return data


def catalog(rows):
    manifest, observations = [], []
    for row in rows:
        identifier = drawing_id(row)
        audit = audit_for(row)
        path = ROOT/row['file']
        current = sha256(path) if path.exists() else None
        full = archive_path(identifier)
        # Archive metadata is exported separately to avoid decompressing all geometry on each review.
        metadata = OUTPUT/'extractions'/(identifier+'.metadata.json')
        extraction = read(metadata) if metadata.exists() else None
        archive_valid = bool(full.exists() and extraction and extraction['sha256'] == current
                             and extraction.get('precision_identity_version')==1)
        manifest.append({'id':identifier, 'file':row['file'], 'audit_sha256':row['sha256'],
                         'current_sha256':current, 'hash_matches_audit':current==row['sha256'],
                         'view_role':role(identifier), 'extraction_state': 'full_native_archive' if archive_valid else 'audited_metadata_and_annotations',
                         'precision_identity_version':extraction.get('precision_identity_version',0) if extraction else 0,
                         'archive':str(full.relative_to(OUTPUT)).replace('\\','/') if archive_valid else None,
                         'coverage':extraction['coverage'] if archive_valid else audit['coverage'],
                         'warning_counts':extraction['warning_counts'] if archive_valid else audit['warning_counts'],
                         'external_references':audit['external_references'], 'layers':audit['layers'],
                         'blocks':audit['blocks'], 'units':audit['units'],
                         'full_dwg_fidelity_verified':False,
                         'loss_verification':'DXF extraction coverage recorded; native DWG/custom-object fidelity unverified'})
        if current!=row['sha256']:
            manifest[-1]['extraction_state']='source_revision_mismatch'
            manifest[-1]['warning_counts']={**manifest[-1]['warning_counts'],'SOURCE_REVISION_MISMATCH':1}
            continue
        text_path = (OUTPUT/'extractions'/(identifier+'.annotations.json')) if archive_valid else AUDIT/(identifier+'-texts-dimensions.json')
        content = read(text_path) if text_path.exists() else []
        # The audit contains full expanded annotations, not layer-name guesses.
        if isinstance(content, dict):
            content = content.get('entities', content.get('texts_dimensions', []))
        for entity in content:
            g = entity['geometry']
            entity_id = entity['id']
            ref = Reference(drawing_id=identifier,source_sha256=row['sha256'],view=role(identifier),
                            cad_ids=[entity_id],relation='unassigned_annotation')
            field = 'cad_dimension' if entity['type']=='DIMENSION' else 'annotation'
            value = g if field=='cad_dimension' else g.get('text','')
            observations.append(Observation(id=identifier+'::'+entity_id, field=field, value=value,
                unit=None, interpretation='Observed CAD text/dimension; member, sheet, revision and semantic meaning require matching',
                reference=ref).model_dump())
    # Candidate slab table relationships from the reviewed embedded schedules.
    schedules = read(AUDIT/'embedded-structural-schedules.json')
    links = []
    for schedule in schedules:
        ident = next((drawing_id(r) for r in rows if drawing_id(r)==schedule['file']), None)
        if not ident: continue
        source_hash = next(r['sha256'] for r in rows if drawing_id(r)==ident)
        for table in schedule['tables']:
            for entry in table['slab_candidates']:
                # Audit candidate rows may use an older expansion strategy.
                # Only retain links whose CAD IDs still exist in this extraction.
                available={o['id'] for o in observations if o['reference']['drawing_id']==ident}
                ids_available=all(ident+'::'+cid in available for cid in entry['cad_ids'])
                if not ids_available:
                    links.append({'member_mark':entry['mark'],'member_id':None,'status':'source_ids_unresolved',
                                  'original_audit_cad_ids':entry['cad_ids'],'evidence_ids':[]})
                    continue
                oid = ident+'::'+table['root']+'::slab::'+entry['mark']
                observations.append(Observation(id=oid,field='thickness',value=float(entry['thickness_text'])/1000,unit='m',
                    status='candidate',interpretation='Embedded schedule row; no verified member assignment',
                    reference=Reference(drawing_id=ident,source_sha256=source_hash,view='schedule',
                                        cad_ids=entry['cad_ids'],relation='same_row_candidate')).model_dump())
                links.append({'id':oid,'member_mark':entry['mark'],'floor_scope':'unconfirmed',
                              'evidence_ids':[oid],'member_id':None,'status':'unassigned'})
    return manifest, observations, links


def metadata(row, data):
    write(OUTPUT/'extractions'/(drawing_id(row)+'.annotations.json'),[
        {'id':e['id'],'type':e['type'],'layout':e['layout'],'layer':e['effective_layer'],
         'geometry':e['geometry'],'definition_handle':e.get('definition_handle'),
         'insert_ancestry':e.get('insert_ancestry',[])}
        for e in data['scene_entities'] if e['type'] in ('TEXT','MTEXT','ATTRIB','ATTDEF','DIMENSION')])
    write(OUTPUT/'extractions'/(drawing_id(row)+'.metadata.json'), {
        'sha256':row['sha256'], 'coverage':data['coverage'],
        'warning_counts':dict(Counter(w['code'] for w in data['warnings'])),
        'source':data['source'], 'native_geometry_preserved':True,
        'block_definitions_and_layouts_preserved':True,
        'precision_identity_version':data.get('precision_identity_version',0),
        'precision_transform_check_version':data.get('precision_transform_check_version',0),
        'block_transform_losses':data.get('precision_block_transform_losses',0),
        'expanded_definition_identity_missing':sum(bool(e.get('insert_ancestry')) and not e.get('definition_handle') for e in data['scene_entities'])})


def in_region(entity, region):
    # Selection is not clipping: straddling objects remain in CAD context but
    # cannot become complete member boundaries.
    b = entity.get('bounds')
    if b:
        return not (b['max'][0]<region[0] or b['min'][0]>region[2] or b['max'][1]<region[1] or b['min'][1]>region[3])
    g = entity.get('geometry',{})
    p = g.get('insert') or g.get('definition_points_raw',{}).get('defpoint')
    return bool(p and region[0]<=p[0]<=region[2] and region[1]<=p[1]<=region[3])


def pilot(data, row, observations):
    if data['coverage']['scene_truncated']:
        raise ValueError('Cannot build a pilot from a truncated plan')
    ident = drawing_id(row)
    # Local display origin and sheet window inherited from the audited A04
    # sheet location. Neither is a verified cross-drawing control network.
    region = [32920000,-5730000,33020000,-5640000]
    frame = Registration(id='a04-f1-local', drawing_id=ident, origin_cad=tuple(region[:2]),
                         scale_m_per_unit=data['units']['meters_per_drawing_unit'])
    selected = [e for e in data['scene_entities'] if e.get('layout')=='Model' and in_region(e,region)]
    parent_ids = {i for e in selected for i in e.get('insert_ancestry',[])}
    # Preserve transform chains even if a parent insertion point lies outside the view.
    selected_ids = {e['id'] for e in selected}
    selected += [e for e in data['scene_entities'] if e['id'] in parent_ids and e['id'] not in selected_ids]
    clipped = {w['entity_id'] for w in data['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
    native, traces, members, errors = {}, [], [], []
    for e in selected:
        native[e['id']] = e
        layer = e.get('effective_layer', e['layer']).split('$')[-1].upper()
        if e['type'] not in CURVES or layer not in KINDS:
            continue
        ref = Reference(drawing_id=ident,source_sha256=row['sha256'],view='plan',
                        cad_ids=[e['id']],relation='native_plan_geometry; semantic classification pending')
        uid = str(uuid.uuid5(NAMESPACE, row['file']+'::'+e['id']))
        points, polygon, unknowns = [], None, ['architectural_identity','member_mark','structural_assignment','base_elevation','height','cross_drawing_registration']
        blocked = e.get('support')!='full' or bool(clipped.intersection(e.get('insert_ancestry',[])))
        try:
            if e.get('precision_geometry_blocked'):
                raise ValueError('Original composed block transform differs; geometry is not used')
            points = sample(e['type'],e['geometry'],0.5) # mm; canonical curves retained
            if any(abs(p[2]-points[0][2])>1e-5 for p in points):
                blocked = True
                unknowns.append('nonplanar_native_geometry')
            local = [to_local(p,frame) for p in points]
            if closed_native(e['type'],e['geometry']) and not blocked:
                from shapely.geometry import Polygon
                from ezdxf.math import Vec3
                shape = Polygon(local)
                wholly_inside = all(region[0]<=p[0]<=region[2] and region[1]<=p[1]<=region[3] for p in points)
                closure_matches=Vec3(points[0]).distance(Vec3(points[-1]))<=1e-6
                if shape.is_valid and shape.area>1e-8 and wholly_inside and closure_matches:
                    polygon = local
                else:
                    unknowns.append('invalid_straddling_or_inconsistent_closure')
            traces.append({'cad_id':e['id'],'kind':KINDS[layer],'layer':e.get('effective_layer',e['layer']),
                           'points':local,'member_id':uid, 'display_tolerance_m':0.0005,
                           'status':'blocked' if blocked else 'measured_geometry' if polygon else 'trace_only'})
        except (ValueError,KeyError,ZeroDivisionError) as exc:
            errors.append({'cad_id':e['id'],'type':e['type'],'reason':str(exc)})
            unknowns.append('curve_sampling_unavailable')
        if blocked: unknowns.append('partial_geometry_or_unapplied_clip')
        if KINDS[layer] in ('door','window','stair'):
            # A door swing or window frame symbol is not an opening/leaf solid.
            polygon = None
            unknowns += (['run_rise','landing_levels','core_assignment'] if KINDS[layer]=='stair'
                         else ['opening_boundary','host_wall','sill','head','schedule_assignment'])
        member = Member(id=uid,kind=KINDS[layer],references=[ref],cad_ids=[e['id']],
            location=tuple(to_local(points[0],frame)) if points else None,plan_polygon=polygon,
            plan_status='measured_geometry' if polygon else 'trace_only',
            plan_representation=('native_linear' if e['type'] in ('LWPOLYLINE','POLYLINE')
                and all(s['type']=='LINE' for s in e['geometry'].get('segments',[])) else 'native_curved') if polygon else 'trace_only',
            tessellation_tolerance_m=0.0005 if polygon and (e['type'] not in ('LWPOLYLINE','POLYLINE')
                or any(s['type']!='LINE' for s in e['geometry'].get('segments',[]))) else None,
            unknowns=unknowns, verification='plan_only' if polygon else 'unresolved')
        oid = ident+'::'+e['id']+'::native_geometry'
        observations.append(Observation(id=oid,member_id=member.id,field='plan_geometry',
            value={'native_id':e['id'],'polygon_m':polygon,'registration_id':frame.id},
            interpretation='Transformed native CAD geometry; architectural/structural identity not certified',reference=ref).model_dump())
        member.evidence_ids.append(oid)
        if polygon:
            from shapely.geometry import Polygon
            member.location=tuple(Polygon(polygon).centroid.coords[0])
            # CAD-derived sizes are observations, never schedule assignments.
            if e['type']=='CIRCLE':
                size = {'diameter_m':e['geometry']['radius']*2*frame.scale_m_per_unit}
            else:
                size = {'native_segment_lengths_m':[s.get('length',0)*frame.scale_m_per_unit for s in e['geometry'].get('segments',[])]}
            size_id=oid+'::measured_sizes'
            observations.append(Observation(id=size_id,member_id=member.id,field='cad_measured_sizes',value=size,unit='m',
                interpretation='Native CAD geometry measurements; not dimensions certified by schedule/annotation',reference=ref).model_dump())
            member.evidence_ids.append(size_id)
        members.append(member)
    # Overlap is reported; nothing is unioned/deleted/repaired. Concentric
    # column outlines and duplicated instances require schedule interpretation.
    from shapely.geometry import Polygon
    profiles = [m for m in members if m.plan_polygon]
    for i, a in enumerate(profiles):
        pa = Polygon(a.plan_polygon)
        for b in profiles[i+1:]:
            if a.kind != b.kind: continue
            pb = Polygon(b.plan_polygon)
            overlap = pa.intersection(pb).area
            if overlap > 1e-6:
                for current, other in ((a,b),(b,a)):
                    current.conflicts.append({'type':'overlapping_native_profiles','other_member_id':other.id,'overlap_m2':overlap})
                    current.verification='conflict'
    comparisons = [compare_plan(m,native[m.cad_ids[0]],frame) for m in members]
    vertical = [compare_vertical(m,[],None) for m in members]
    titles = [e for e in selected if e['type'] in ('TEXT','MTEXT') and '1층' in e['geometry'].get('text','')]
    return {'schema_version':'precision-stage1/1','created_at':datetime.now(timezone.utc).isoformat(),
            'name':'1층 원본 경계 시범 모델', 'registration':frame.model_dump(),
            'sheet_selection':{'region_cad':region,'status':'candidate','title_cad_ids':[e['id'] for e in titles],
                              'drawing_number':None,'reason':'Sheet number, grid controls and revision require confirmation'},
            'members':[m.model_dump() for m in members], 'preview_members':[],
            'native_entities':list(native.values()),'cad_traces':traces,'sampling_issues':errors,
            'comparisons':{'plan':comparisons,'vertical':vertical},
            'summary':{'member_candidates':len(members),'plan_profiles':len(profiles),
                       'verified_solids':sum(m.verification=='verified' for m in members),
                       'conflicts':sum(bool(m.conflicts) for m in members),
                       'kinds':dict(Counter(m.kind for m in members)),
                       'plan_comparison':dict(Counter(c['status'] for c in comparisons)),
                       'vertical_comparison':dict(Counter(c['status'] for c in vertical))}}, observations


def build(extract_all=False, refresh=False):
    rows = read(AUDIT/'drawing-index.json')
    if len(rows)!=30: raise ValueError('Expected audited set of 30 DWGs')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    # Source and legacy outputs preservation snapshot, excluding our own new outputs.
    protected = [ROOT/r['file'] for r in rows]
    protected += [p for p in (ROOT/'cad_output').rglob('*') if p.is_file() and not p.is_relative_to(OUTPUT)]
    protected += [p for directory in (ROOT/'web/public',ROOT/'web/dist') if directory.exists() for p in directory.rglob('*') if p.is_file()]
    before = {str(p.relative_to(ROOT)).replace('\\','/'):sha256(p) for p in protected}
    plan_row = next(r for r in rows if drawing_id(r).startswith('A04-001'))
    data = load_native(plan_row,refresh=refresh)
    metadata(plan_row,data)
    manifest, observations, links = catalog(rows)
    model, observations = pilot(data,plan_row,observations)
    write(OUTPUT/'pilot.json',model)
    write(OUTPUT/'observations.json',observations)
    write(OUTPUT/'cross-references.json', {'schedule_links':links,'member_links':[],
         'policy':'Candidate relationships never resolve dimensions automatically; approved links require source CAD IDs and sheet/revision matching'})
    write(OUTPUT/'drawings.json',manifest)
    if extract_all:
        del data
        for row in rows:
            if row==plan_row: continue
            data = load_native(row,refresh=refresh)
            metadata(row,data)
            print(f"{drawing_id(row)}: {data['coverage']['scene_entity_count']} scene entities; truncated={data['coverage']['scene_truncated']}",flush=True)
            del data
        pilot_observations=[o for o in observations if o['field'] in ('plan_geometry','cad_measured_sizes')]
        manifest, observations, links = catalog(rows)
        write(OUTPUT/'observations.json',observations+pilot_observations)
        write(OUTPUT/'cross-references.json',{'schedule_links':links,'member_links':[],
              'policy':'Explicit member matching required; unresolved source IDs and unassigned schedules never provide resolved dimensions'})
        write(OUTPUT/'drawings.json',manifest)
    after = {str(p.relative_to(ROOT)).replace('\\','/'):sha256(p) for p in protected}
    differences = [p for p,h in before.items() if after.get(p)!=h]
    preservation = {'checked_files':len(before),'changed_files':differences,'unchanged':not differences,
                    'hashes_before':before,'hashes_after':after}
    write(OUTPUT/'preservation.json',preservation)
    if differences: raise RuntimeError('Protected files changed during run')
    write(OUTPUT/'build-summary.json',{'pilot':model['summary'], 'drawing_count':len(manifest),
          'full_native_archives':sum(r['extraction_state']=='full_native_archive' for r in manifest),
          'scene_truncated':[r['id'] for r in manifest if r['coverage']['scene_truncated']],
          'missing_xrefs':sorted({Path(r['stored_path'].replace('\\','/')).name for d in manifest for r in d['external_references'] if r['kind']=='xref' and not r['exists']}),
          'preservation':{'checked_files':len(before),'unchanged':not differences},
          'ifc_export':'blocked: no fully verified solids / common coordinate registration',
          'scope':'Native 1F plan geometry pilot; not a certified 3D building reconstruction'})
    print(json.dumps(model['summary'],ensure_ascii=True),flush=True)


def main():
    import logging
    logging.getLogger('ezdxf').setLevel(logging.ERROR)
    logging.getLogger('fontTools').setLevel(logging.ERROR)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract-all',action='store_true',help='Archive full native extraction for all 30 DWGs')
    parser.add_argument('--refresh',action='store_true',help='Reconvert using temporary copies rather than a hash-matched archive')
    args=parser.parse_args()
    build(args.extract_all,args.refresh)


if __name__=='__main__': main()
