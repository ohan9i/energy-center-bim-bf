"""Validate the exported file itself, including all product tessellations."""
import json
from pathlib import Path
import hashlib
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import ifcopenshell.validate
from shapely.geometry import Polygon
from .schema import Model
from .geometry import solid_parts
from .assembly_solids import mesh_volume


def validate_file(model: Model, path: Path):
    f = ifcopenshell.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, logger, express_rules=True)
    if logger.statements:
        raise AssertionError(f'IFC4 EXPRESS: {len(logger.statements)} issues; {logger.statements[0]}')
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    elements = {e.id: e for e in model.elements if not e.excluded}
    elevations = {floor.id: floor.elevation for floor in model.floors}
    products = 0
    parts = 0
    planar = 0
    maximum_error = 0.
    for obj in f.by_type('IfcProduct'):
        props = ifcopenshell.util.element.get_psets(obj)
        if obj.is_a('IfcBuildingElementPart'):
            evidence = props['Pset_ArchitecturalEvidence']
            e = elements[evidence['ParentElementId']]
            index = next(i for i,c in enumerate(e.components) if obj.GlobalId == ifcopenshell.guid.compress(hashlib.md5((model.id+'/'+(c.id or e.id+f'/component/{i}')).encode()).hexdigest()))
            c = e.components[index]
            expected = [(Polygon(c.polygon, c.holes), e.z_offset+c.z_offset, c.height)]
            parts += 1
        elif 'Pset_BFNavigation' in props:
            e = elements[props['Pset_BFNavigation']['ModelElementId']]
            products += 1
            if e.components:
                assert obj.Representation is None and len(obj.IsDecomposedBy[0].RelatedObjects) == len(e.components)
                continue
            expected = [] if e.source.get('unresolved_no_representation') else solid_parts(e, model.elements)
        else:
            continue
        if not expected:
            assert obj.Representation is None
            continue
        shape = ifcopenshell.geom.create_shape(settings, obj)
        mesh = shape.geometry
        vertices = list(zip(*[iter(mesh.verts)]*3))
        assert vertices, f'{obj.Name}: empty IFC geometry'
        actual_bounds = [min(v[i] for v in vertices) for i in range(3)] + [max(v[i] for v in vertices) for i in range(3)]
        expected_bounds = [min(p.bounds[i] for p, _, _ in expected) for i in (0, 1)]
        expected_bounds += [elevations[e.floor_id]+min(z for _, z, _ in expected)]
        expected_bounds += [max(p.bounds[i] for p, _, _ in expected) for i in (2, 3)]
        expected_bounds += [elevations[e.floor_id]+max(z+(depth or 0) for _, z, depth in expected)]
        error = max(abs(a-b) for a, b in zip(actual_bounds, expected_bounds))
        maximum_error = max(maximum_error, error)
        assert error < .002, f'{obj.Name}: IFC world coordinate deviation {error}'
        if all(depth is None for _, _, depth in expected):
            planar += 1
            area = sum(p.area for p, _, _ in expected)
            assert abs(ifcopenshell.util.shape.get_area(mesh)-area) < max(.001, area*1e-5), f'{obj.Name}: IFC surface area / holes mismatch'
        else:
            volume = mesh_volume(c.mesh) if obj.is_a('IfcBuildingElementPart') and c.mesh else sum(p.area*depth for p, _, depth in expected if depth is not None)
            assert abs(ifcopenshell.util.shape.get_volume(mesh)-volume) < max(.001, volume*1e-5), f'{obj.Name}: IFC solid volume mismatch'
    assert products == len(elements)
    assert parts == sum(len(e.components) for e in elements.values())
    return dict(status='passed',express_issues=0,products=products,assembly_parts=parts,
                planar_products=planar,maximum_world_coordinate_deviation_m=maximum_error,
                ifc_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def main():
    output = Path('cad_output')
    model = Model.model_validate_json((output/'energy-center-model.json').read_text(encoding='utf-8'))
    try:
        result = validate_file(model, output/'energy-center.ifc')
    except Exception as exc:
        (output/'ifc-validation.json').write_text(json.dumps(dict(status='failed',error=str(exc),
            ifc_sha256=hashlib.sha256((output/'energy-center.ifc').read_bytes()).hexdigest()),ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    (output/'ifc-validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
