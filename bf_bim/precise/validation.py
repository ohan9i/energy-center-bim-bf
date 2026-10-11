"""Independent source reprojection and explicit unresolved comparisons."""
from __future__ import annotations

from shapely.geometry import Polygon
from .geometry import sample, to_local, to_cad
from .schema import Dimension, Member, Observation, Registration


def resolve_dimension(field: str, evidence: list[Observation], tolerance_m=0.001) -> Dimension:
    candidates = [e for e in evidence if e.field == field and e.status == 'confirmed' and e.unit == 'm'
                  and isinstance(e.value, (float, int))]
    if not candidates:
        return Dimension()
    values = [float(e.value) for e in candidates]
    if max(values)-min(values) > tolerance_m:
        return Dimension(status='conflict', evidence_ids=[e.id for e in candidates])
    return Dimension(value=values[0], status='confirmed', evidence_ids=[e.id for e in candidates])


def compare_plan(member: Member, native: dict, frame: Registration, tolerance_m=0.002):
    if member.plan_polygon is None:
        return {'member_id': member.id, 'status': 'insufficient_source', 'reason': 'No closed native member boundary'}
    try:
        # Re-sample source, do not compare two copies of the generated polygon.
        points = sample(native['type'], native['geometry'], 0.00025/frame.scale_m_per_unit)
        a = Polygon([to_local(p, frame) for p in points])
        b = Polygon(member.plan_polygon)
        if not a.is_valid or not b.is_valid:
            raise ValueError('Invalid source/model polygon')
        distance = a.boundary.hausdorff_distance(b.boundary)
        center = a.centroid.distance(b.centroid)
        return {'member_id': member.id, 'status': 'match' if distance <= tolerance_m else 'mismatch',
                'boundary_distance_m': distance, 'centroid_distance_m': center,
                'symmetric_difference_m2': a.symmetric_difference(b).area,
                'area_delta_m2': b.area-a.area, 'tolerance_m': tolerance_m,
                'source_cad_id': native['id'], 'scope': 'same_drawing_geometry_roundtrip',
                'registration_status': frame.status,
                'cad_roundtrip_max_units': max(abs(v-p[i]) for p in points for i,v in enumerate(to_cad(to_local(p,frame),frame)))}
    except (ValueError, KeyError, ZeroDivisionError) as exc:
        return {'member_id': member.id, 'status': 'insufficient_source', 'reason': str(exc)}


def compare_vertical(member: Member, evidence: list[Observation], frame: Registration | None, tolerance_m=0.002):
    result = {'member_id': member.id, 'status': 'insufficient_source', 'fields': {}}
    if frame is None or frame.status != 'confirmed':
        result['reason'] = 'Section/elevation registration not confirmed'
        return result
    for field in ('base_elevation', 'height', 'sill', 'head'):
        expected = resolve_dimension(field, [e for e in evidence if e.member_id==member.id])
        actual = member.dimensions.get(field, Dimension())
        if expected.status == 'conflict':
            result['fields'][field] = {'status': 'source_conflict', 'evidence_ids': expected.evidence_ids}
        elif expected.value is None or actual.value is None:
            result['fields'][field] = {'status': 'insufficient_source'}
        else:
            delta = actual.value-expected.value
            result['fields'][field] = {'status': 'match' if abs(delta)<=tolerance_m else 'mismatch',
                                       'delta_m': delta, 'evidence_ids': expected.evidence_ids}
    states = [v['status'] for v in result['fields'].values()]
    result['status'] = ('mismatch' if 'mismatch' in states else 'source_conflict' if 'source_conflict' in states
                        else 'insufficient_source' if 'insufficient_source' in states else 'match')
    return result


def export_verified_ifc(members: list[Member], observations: list[Observation], registration: Registration):
    """Fail closed before calling the existing exporter, never export preview."""
    from bf_bim.schema import Model
    from bf_bim.ifc_export import export_ifc
    if registration.status != 'confirmed':
        raise ValueError('Common coordinate registration is not confirmed; precise IFC export blocked')
    index = {e.id: e for e in observations}
    elements = []
    for raw_member in members:
        member = Member.model_validate(raw_member.model_dump())
        if member.verification != 'verified':
            raise ValueError(f'{member.id}: not a verified solid; precise IFC export blocked')
        if member.plan_representation!='native_linear':
            raise ValueError('Analytic curved IFC profiles are not implemented in stage 1; sampled display geometry cannot be exported as exact geometry')
        member_facts=[index.get(i) for i in member.evidence_ids]
        if any(e is None for e in member_facts):
            raise ValueError('Missing member evidence')
        for required_field in ('plan_geometry','member_kind'):
            if not any(e.field==required_field and e.status=='confirmed' and e.reference.drawing_number
                       and e.member_id==member.id for e in member_facts):
                raise ValueError(f'Missing confirmed {required_field} evidence')
        kinds=[e for e in member_facts if e.field=='member_kind' and e.status=='confirmed']
        if any(e.value!=member.kind for e in kinds):
            raise ValueError('Confirmed kind evidence conflicts with exported member type')
        plans=[e for e in member_facts if e.field=='plan_geometry' and e.status=='confirmed']
        for plan in plans:
            value=plan.value
            if (not isinstance(value,dict) or value.get('native_id') not in member.cad_ids
                or value.get('native_id') not in plan.reference.cad_ids
                or value.get('registration_id')!=registration.id or not value.get('polygon_m')):
                raise ValueError('Confirmed plan evidence does not identify the native profile and coordinate frame')
            approved=Polygon(value['polygon_m'])
            actual=Polygon(member.plan_polygon)
            if not approved.is_valid or approved.boundary.hausdorff_distance(actual.boundary)>1e-7:
                raise ValueError('Exported plan differs from the confirmed source profile')
        for field,dimension in member.dimensions.items():
            if dimension.status == 'confirmed':
                refs = [index.get(i) for i in dimension.evidence_ids]
                if not refs or any(e is None or e.status != 'confirmed' or e.member_id!=member.id for e in refs):
                    raise ValueError('Unconfirmed or missing evidence in IFC dimension')
                if any(e.field!=field for e in refs):
                    raise ValueError('IFC dimension evidence belongs to a different field')
                expected = resolve_dimension(field, refs)
                if expected.value is None or abs(expected.value-dimension.value)>1e-7:
                    raise ValueError('IFC dimension disagrees with source evidence')
        elements.append(dict(id=member.id, name=member.id, type=member.kind, floor_id='f1',
                             polygon=member.plan_polygon, height=member.dimensions['height'].value,
                             z_offset=member.dimensions['base_elevation'].value, verified=True,
                             source={'precision_member': member.model_dump(), 'geometry_status':'verified'}))
    if not elements:
        raise ValueError('No verified solids to export')
    if any(index.get(i) is None or index[i].status!='confirmed' or index[i].field!='grid_control' for i in registration.control_evidence_ids):
        raise ValueError('Missing confirmed coordinate control evidence')
    # Recompute from the actual control coordinates. Three IDs and a manually
    # supplied 'confirmed' flag alone must not authorize an IFC coordinate frame.
    from .registration import register_controls
    import math
    controls=[index[i] for i in registration.control_evidence_ids]
    register_controls(registration.id,registration.drawing_id,registration.scale_m_per_unit,controls,
                      {registration.drawing_id:controls[0].reference.source_sha256})
    if any(math.dist(to_local(e.value['cad_xy'],registration),e.value['model_xy_m'])>.002 for e in controls):
        raise ValueError('IFC coordinate frame disagrees with confirmed controls')
    model = Model.model_validate(dict(id='precision-f1', name='Verified 1F', floors=[dict(id='f1',name='1F',elevation=0)],
                                     elements=elements, places=[], links=[],provenance={'precision_coordinate_frame':registration.model_dump()}))
    return export_ifc(model)
