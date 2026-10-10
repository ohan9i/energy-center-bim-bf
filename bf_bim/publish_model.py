"""Prepare the explicitly authorized, static project model for GitHub Pages."""
from pathlib import Path
from .schema import Model

PUBLIC_SOURCE_FIELDS={'origin','file','cad_id','cad_ids','layer','method','geometry_inferred',
    'height_source','leaf_radius_m','marker_width_m','clear_width_source',
    'coverage_verified','connected_floors_verified','slab_thickness_source',
    'geometry_status','material','measured_thickness_m','measured_profile_depth_m',
    'block_name','height_source','sill_source','schedule_match_status','hinge','leaf_end','swing_end',
    'closed_position_verified','host_wall_ids','adjacent_space_ids','closure_tolerance_m',
    'area_m2','boundary_status','constituent_labels','space_usage','courtyard_evidence_ids',
    'nosing_count','tread_pitch_m','riser_m','risers_per_flight','riser_evidence','flight_direction_verified',
    'central_gap_m','central_gap_source','detail_pitch_conflict','thickness_source','core_boundary_cad_id',
    'label_cad_id','car_dimensions_source','void_guard_m','coincident_profile_ids','flight_height_status','structural_section_candidates'}

def main():
    root=Path(__file__).resolve().parents[1]
    model=Model.model_validate_json((root/'cad_output/energy-center-model.json').read_text(encoding='utf-8'))
    for e in model.elements:
        e.source={key:value for key,value in e.source.items() if key in PUBLIC_SOURCE_FIELDS}
    model.provenance={'publication':'github_pages','source_units':'mm','coordinate_units':'m',
        'review_status':'unverified','relative_floor_levels':[f.elevation for f in model.floors],
        'modelling_version':model.provenance.get('modelling_version',1),
        'missing_information':model.provenance.get('missing_information',[]),
        'source_audit':model.provenance.get('source_audit',[]),'drawing_evidence':model.provenance.get('drawing_evidence',{})}
    payload=model.model_dump_json(indent=2)
    if 'C:\\Users\\' in payload or 'C:/Users/' in payload:
        raise ValueError('Local filesystem paths must not be published.')
    target=root/'web/public/models/project.json'
    target.write_text(payload,encoding='utf-8')
    print(f'Public model: {len(model.elements)} elements, {len(model.places)} places; {target.relative_to(root)}')

if __name__=='__main__':main()
