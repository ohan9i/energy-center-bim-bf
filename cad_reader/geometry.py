"""Explicit geometry with raw DXF attributes retained by the reader."""

from __future__ import annotations

import math

from ezdxf import bbox
from ezdxf.math import Vec3, arc_angle_span_deg


def json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return {"encoding": "hex", "data": value.hex()}
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    try:
        return [json_value(v) for v in value]
    except TypeError:
        return str(value)


def point(value):
    return json_value(Vec3(value))


def entity_geometry(entity) -> tuple[dict, str]:
    """Coordinates are WCS of the current layout/block; raw DXF may use OCS."""
    kind, d = entity.dxftype(), entity.dxf
    if kind == "LINE":
        a, b = Vec3(d.start), Vec3(d.end)
        return {"start": point(a), "end": point(b), "length": a.distance(b)}, "full"
    if kind in ("CIRCLE", "ARC"):
        center = entity.ocs().to_wcs(d.center)
        g = {"center": point(center), "radius": d.radius,
             "normal": point(d.get("extrusion", (0, 0, 1)))}
        if kind == "CIRCLE":
            g.update(circumference=math.tau * d.radius, area=math.pi * d.radius**2)
        else:
            span = arc_angle_span_deg(d.start_angle, d.end_angle)
            g.update(start_angle_deg=d.start_angle, end_angle_deg=d.end_angle,
                     sweep_angle_deg=span, length=math.radians(span) * d.radius,
                     start=point(entity.start_point), end=point(entity.end_point))
        return g, "full"
    if kind in ("LWPOLYLINE", "POLYLINE"):
        if kind == "POLYLINE" and (entity.is_polygon_mesh or entity.is_poly_face_mesh):
            return {"vertices": [json_value(v.dxf.all_existing_dxf_attribs()) for v in entity.vertices]}, "partial"
        closed = bool(entity.closed if kind == "LWPOLYLINE" else entity.is_closed)
        vertices = (list(entity.vertices_in_wcs()) if kind == "LWPOLYLINE"
                    else list(entity.points_in_wcs()))
        g = {"vertices": [point(v) for v in vertices], "closed": closed}
        if kind == "LWPOLYLINE":
            g["vertices_ocs_xy_startwidth_endwidth_bulge"] = json_value(entity.get_points("xyseb"))
        else:
            g["vertex_attributes"] = [json_value(v.dxf.all_existing_dxf_attribs()) for v in entity.vertices]
        segments = []
        for sub in entity.virtual_entities():
            sub_g, status = entity_geometry(sub)
            if status != "full":
                return g, "partial"
            segments.append({"type": sub.dxftype(), **sub_g})
        g["segments"] = segments
        g["length"] = sum(s.get("length", 0) for s in segments)
        return g, "full"
    if kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
        location = d.insert if kind == "MTEXT" else entity.ocs().to_wcs(d.insert)
        g = {"insert": point(location), "text": entity.plain_text(),
             "raw_text": entity.text if kind == "MTEXT" else d.text,
             "height": d.get("char_height", None) if kind == "MTEXT" else d.get("height", None),
             "rotation_deg": entity.get_rotation() if kind == "MTEXT" else d.get("rotation", 0),
             "style": d.get("style", "Standard")}
        if kind in ("ATTRIB", "ATTDEF"):
            g["tag"] = d.tag
        if kind != "MTEXT" and d.hasattr("align_point"):
            g["align_point"] = point(entity.ocs().to_wcs(d.align_point))
        return g, "full"
    if kind == "DIMENSION":
        g = {"dimension_type": d.dimtype & 15, "flags": d.dimtype,
             "text_override": d.get("text", ""), "style": d.dimstyle,
             "geometry_block": d.get("geometry", None),
             "definition_points_raw": {key: json_value(d.get(key)) for key in
                 ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint")
                 if d.hasattr(key)}}
        # ezdxf returns degrees for angular dimensions, vectors for ordinate dimensions.
        g["measurement"] = json_value(entity.get_measurement())
        g["measurement_kind"] = ("angle_degrees" if (d.dimtype & 15) in (2, 5)
                                 else "ordinate_vector" if (d.dimtype & 15) == 6 else "drawing_units")
        return g, "full"
    if kind == "INSERT":
        g = {"block_name": d.name, "insert": point(entity.ocs().to_wcs(d.insert)),
             "rotation_deg": d.get("rotation", 0),
             "scale": [d.get(k, 1) for k in ("xscale", "yscale", "zscale")],
             "array": {k: d.get(k, default) for k, default in
                       (("row_count", 1), ("column_count", 1), ("row_spacing", 0), ("column_spacing", 0))},
             "block_to_layout_matrix_rows": [list(entity.matrix44().get_row(i)) for i in range(4)],
             "attributes": [{"handle": a.dxf.handle, "tag": a.dxf.tag,
                             "text": a.dxf.text, "insert": point(a.ocs().to_wcs(a.dxf.insert)),
                             "dxf": json_value(a.dxf.all_existing_dxf_attribs())}
                            for a in entity.attribs]}
        return g, "full"
    if kind == "POINT":
        return {"location": point(d.location)}, "full"
    if kind == "ELLIPSE":
        return {"center": point(d.center), "major_axis": point(d.major_axis),
                "ratio": d.ratio, "normal": point(d.get("extrusion", (0, 0, 1))),
                "start_param_rad": d.start_param, "end_param_rad": d.end_param,
                "start": point(entity.start_point), "end": point(entity.end_point)}, "full"
    if kind == "SPLINE":
        return {"control_points": json_value(entity.control_points),
                "fit_points": json_value(entity.fit_points), "knots": json_value(entity.knots),
                "weights": json_value(entity.weights), "degree": d.degree,
                "flags": d.flags}, "full"
    if kind == "HATCH":
        paths = []
        for path in entity.paths:
            item = {"flags": path.path_type_flags,
                    "source_boundary_handles": list(path.source_boundary_objects)}
            if hasattr(path, "vertices"):
                item.update(vertices_ocs_xy_bulge=json_value(path.vertices), closed=path.is_closed)
            else:
                item["edges"] = [{"type": type(edge).__name__,
                                  "data": json_value(vars(edge))} for edge in path.edges]
            paths.append(item)
        return {"boundary_paths_ocs": paths, "solid_fill": bool(d.solid_fill),
                "pattern_name": d.pattern_name}, "partial"
    return {}, "unsupported"


def entity_bounds(entity):
    # Bounding boxes for text are estimates; INSERT is expanded by our bounded traversal.
    if entity.dxftype() in ("INSERT", "ACAD_PROXY_ENTITY", "3DSOLID", "BODY", "REGION",
                           "RAY", "XLINE", "ACAD_TABLE", "DIMENSION"):
        return None
    bounds = bbox.extents([entity], fast=False)
    if not bounds.has_data:
        return None
    return {"min": point(bounds.extmin), "max": point(bounds.extmax),
            "quality": "approximate" if entity.dxftype() in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF")
                       else "ezdxf_bounds"}
