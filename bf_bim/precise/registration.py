"""Rigid metric registration from explicit, revision-checked CAD controls."""
import math
from .geometry import to_local
from .schema import Observation, Registration


def register_controls(identifier: str, drawing_id: str, scale_m_per_unit: float,
                      controls: list[Observation], drawing_hashes: dict[str,str], tolerance_m=0.002):
    if scale_m_per_unit<=0 or tolerance_m<=0:
        raise ValueError('Units and registration tolerance must be positive')
    if len({c.id for c in controls})<3:
        raise ValueError('Three independent controls are required')
    cad, targets = [], []
    for control in controls:
        if (control.status!='confirmed' or control.field!='grid_control'
            or control.reference.drawing_id!=drawing_id or not control.reference.drawing_number
            or control.reference.source_sha256!=drawing_hashes.get(drawing_id)
            or not isinstance(control.value,dict)):
            raise ValueError('Control is not confirmed against the active drawing/sheet revision')
        cad.append(control.value['cad_xy']);targets.append(control.value['model_xy_m'])
    # Reject collinear controls; a long grid line alone does not establish a
    # reliable 2D cross-drawing registration.
    area=max(abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
             for a in cad for b in cad for c in cad)
    if area*scale_m_per_unit**2<=1e-8:
        raise ValueError('Control points are collinear or coincident')
    n=len(cad)
    cx,cy=(sum(p[i] for p in cad)/n for i in (0,1))
    tx,ty=(sum(p[i] for p in targets)/n for i in (0,1))
    dot=cross=0.
    for a,b in zip(cad,targets):
        x,y=(a[0]-cx)*scale_m_per_unit,(a[1]-cy)*scale_m_per_unit
        u,v=b[0]-tx,b[1]-ty
        dot+=x*u+y*v;cross+=x*v-y*u
    angle=math.atan2(cross,dot)
    cos,sin=math.cos(angle),math.sin(angle)
    origin=(cx-(cos*tx+sin*ty)/scale_m_per_unit,
            cy-(-sin*tx+cos*ty)/scale_m_per_unit)
    candidate=Registration(id=identifier,drawing_id=drawing_id,origin_cad=origin,
                           scale_m_per_unit=scale_m_per_unit,rotation_rad=angle,status='candidate')
    residual=max(math.dist(to_local(a,candidate),b) for a,b in zip(cad,targets))
    if residual>tolerance_m:
        raise ValueError(f'Registration residual {residual:.6f} m exceeds tolerance; scale/shear/reflection not forced')
    candidate.status='confirmed';candidate.control_evidence_ids=[c.id for c in controls];candidate.residual_m=residual
    return Registration.model_validate(candidate.model_dump())
