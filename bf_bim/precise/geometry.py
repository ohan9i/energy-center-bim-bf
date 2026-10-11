"""Native curve sampling for display; never snap, extend, connect or buffer CAD."""
from __future__ import annotations

import math
from ezdxf.math import BSpline, OCS, Vec3, fit_points_to_cad_cv
from .schema import Registration


def to_local(point, frame: Registration):
    x = (point[0] - frame.origin_cad[0]) * frame.scale_m_per_unit
    y = (point[1] - frame.origin_cad[1]) * frame.scale_m_per_unit
    c, s = math.cos(frame.rotation_rad), math.sin(frame.rotation_rad)
    return [c*x-s*y, s*x+c*y]


def to_cad(point, frame: Registration):
    c, s = math.cos(frame.rotation_rad), math.sin(frame.rotation_rad)
    x, y = point
    return [(c*x+s*y)/frame.scale_m_per_unit + frame.origin_cad[0],
            (-s*x+c*y)/frame.scale_m_per_unit + frame.origin_cad[1]]


def _curve_count(radius, span, tolerance):
    if radius <= 0 or tolerance <= 0:
        raise ValueError('Positive radius and chord tolerance required')
    step = 2*math.acos(max(-1, min(1, 1-tolerance/radius)))
    count = max(4, math.ceil(abs(span)/max(step, 1e-12)))
    if count > 100000:
        raise ValueError('Curve tessellation exceeds safety limit')
    return count


def sample(kind: str, g: dict, tolerance_units: float):
    """Return WCS XYZ. Canonical analytic data is not replaced by these samples.

    Circle/arc/ellipse use a conservative sagitta bound. Control-point splines
    use ezdxf adaptive flattening; fit-only splines need an explicit conversion
    and are deliberately left unresolved (fit tangents are not in old caches).
    """
    if kind == 'LINE':
        return [g['start'], g['end']]
    if kind in ('ARC', 'CIRCLE'):
        center, radius = Vec3(g['center']), g['radius']
        ocs = OCS(g.get('normal', [0, 0, 1]))
        start = math.radians(g.get('start_angle_deg', 0))
        span = math.tau if kind == 'CIRCLE' else math.radians(g['sweep_angle_deg'])
        n = _curve_count(radius, span, tolerance_units)
        return [list(center + ocs.to_wcs(Vec3(radius*math.cos(start+span*i/n),
                                              radius*math.sin(start+span*i/n), 0))) for i in range(n+1)]
    if kind == 'ELLIPSE':
        center, major = Vec3(g['center']), Vec3(g['major_axis'])
        normal = Vec3(g.get('normal', [0, 0, 1])).normalize()
        minor = normal.cross(major).normalize(major.magnitude*g['ratio'])
        start, end = g['start_param_rad'], g['end_param_rad']
        span = (end-start) % math.tau or math.tau
        n = _curve_count(max(major.magnitude, minor.magnitude), span, tolerance_units)
        return [list(center + major*math.cos(start+span*i/n) + minor*math.sin(start+span*i/n)) for i in range(n+1)]
    if kind == 'SPLINE':
        if not g.get('control_points'):
            if (len(g.get('fit_points', [])) < 2 or g.get('degree') != 3
                    or not g.get('start_tangent') or not g.get('end_tangent')):
                raise ValueError('Fit-only spline requires cubic degree and explicit endpoint tangents')
            curve = fit_points_to_cad_cv(g['fit_points'], tangents=[g['start_tangent'],g['end_tangent']])
        else:
            curve = BSpline(g['control_points'], order=g['degree']+1,
                            knots=g.get('knots') or None, weights=g.get('weights') or None)
        return [list(p) for p in curve.flattening(tolerance_units, segments=8)]
    if kind in ('LWPOLYLINE', 'POLYLINE'):
        if 'segments' not in g:
            raise ValueError('Polyline segments unavailable')
        points = []
        for segment in g['segments']:
            next_points = sample(segment['type'], segment, tolerance_units)
            expected_start=points[-1] if points else (g.get('vertices') or next_points)[0]
            # DXF ARC primitives are CCW. A negative polyline bulge traverses
            # that same arc backwards. Use the recorded vertex order, never
            # bridge a gap or choose a direction by a proximity heuristic.
            if (segment['type'] in ('ARC','ELLIPSE')
                and Vec3(expected_start).distance(Vec3(next_points[0]))>1e-6
                and Vec3(expected_start).distance(Vec3(next_points[-1]))<=1e-6):
                next_points.reverse()
            if Vec3(expected_start).distance(Vec3(next_points[0])) > 1e-6:
                raise ValueError('Discontinuous native polyline segments; no implicit joining')
            points.extend(next_points if not points else next_points[1:])
        return points
    raise ValueError(f'No display sampler for {kind}; native data retained')


def sample_hatch_paths(g: dict, tolerance_units: float):
    """Separate WCS loops, with bulges/edge direction and holes preserved.

    Older archives did not store OCS elevation and must not be interpreted
    using a guessed zero elevation. Missing fields fail closed.
    """
    from ezdxf.entities.boundary_paths import PolylinePath, EdgePath
    from ezdxf.path import from_hatch_boundary_path
    if tolerance_units <= 0 or 'elevation_ocs' not in g or 'normal' not in g:
        raise ValueError('Hatch requires explicit OCS elevation/normal and positive tolerance')
    loops=[]
    for raw in g['boundary_paths_ocs']:
        if 'vertices_ocs_xy_bulge' in raw:
            boundary=PolylinePath.from_vertices(raw['vertices_ocs_xy_bulge'],is_closed=raw['closed'],flags=raw['flags'])
        else:
            boundary=EdgePath();boundary.path_type_flags=raw['flags']
            for edge in raw.get('edges',[]):
                data=edge['data'];kind=edge['type']
                if kind=='LineEdge': boundary.add_line(data['start'],data['end'])
                elif kind=='ArcEdge': boundary.add_arc(data['center'],data['radius'],data['start_angle'],data['end_angle'],data['ccw'])
                elif kind=='EllipseEdge': boundary.add_ellipse(data['center'],data['major_axis'],data['ratio'],data['start_angle'],data['end_angle'],data['ccw'])
                else: raise ValueError(f'Unsupported hatch edge {kind}; native edge retained')
        path=from_hatch_boundary_path(boundary,ocs=OCS(g['normal']),elevation=g['elevation_ocs'][2])
        points=[list(p) for p in path.flattening(tolerance_units)]
        if not points or Vec3(points[0]).distance(Vec3(points[-1]))>1e-6:
            raise ValueError('Open hatch boundary; implicit closure prohibited')
        loops.append({'flags':raw['flags'],'points':points,'source_boundary_handles':raw['source_boundary_handles']})
    return loops


def closed_native(kind, geometry):
    return (kind == 'CIRCLE'
            or kind in ('LWPOLYLINE', 'POLYLINE') and geometry.get('closed') is True
            or kind == 'ELLIPSE' and math.isclose(abs(geometry['end_param_rad']-geometry['start_param_rad']),math.tau,abs_tol=1e-10)
            or kind == 'SPLINE' and bool(geometry.get('flags',0)&1))
