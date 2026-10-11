from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Polygon


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Reference(Record):
    drawing_id: str
    source_sha256: str
    drawing_number: str | None = None
    view: Literal['plan', 'structure', 'section', 'elevation', 'detail', 'schedule', 'unknown']
    cad_ids: list[str] = Field(min_length=1)
    relation: str


class Observation(Record):
    id: str
    member_id: str | None = None
    field: str
    value: float | str | list | dict
    unit: str | None = None
    interpretation: str
    reference: Reference
    status: Literal['observed', 'candidate', 'confirmed', 'rejected'] = 'observed'


class Dimension(Record):
    value: float | None = None
    unit: Literal['m'] = 'm'
    status: Literal['unknown', 'measured_geometry', 'confirmed', 'conflict'] = 'unknown'
    evidence_ids: list[str] = []

    @model_validator(mode='after')
    def evidence_required(self):
        if self.status in ('unknown', 'conflict') and self.value is not None:
            raise ValueError('Unknown/conflicting dimensions must not have a resolved value')
        if self.status in ('measured_geometry', 'confirmed') and (self.value is None or not self.evidence_ids):
            raise ValueError('Resolved dimension requires value and evidence')
        return self


class Member(Record):
    id: str
    kind: str
    kind_status: Literal['candidate', 'confirmed'] = 'candidate'
    floor_id: str = 'f1'
    location: tuple[float, float] | None = None
    member_mark: str | None = None
    references: list[Reference] = Field(min_length=1)
    cad_ids: list[str] = Field(min_length=1)
    # Exact native geometry remains in cad-native.json / the extraction archive.
    plan_polygon: list[tuple[float, float]] | None = None
    plan_status: Literal['trace_only', 'measured_geometry', 'confirmed'] = 'trace_only'
    plan_representation: Literal['trace_only', 'native_linear', 'native_curved'] = 'trace_only'
    tessellation_tolerance_m: float | None = None
    dimensions: dict[str, Dimension] = Field(default_factory=lambda: {
        name: Dimension() for name in ('base_elevation', 'height', 'thickness', 'sill', 'head')})
    evidence_ids: list[str] = []
    unknowns: list[str] = []
    conflicts: list[dict] = []
    verification: Literal['unresolved', 'plan_only', 'conflict', 'verified'] = 'unresolved'

    @model_validator(mode='after')
    def coherent(self):
        if self.plan_polygon is not None:
            p = Polygon(self.plan_polygon)
            if not p.is_valid or p.area <= 1e-8:
                raise ValueError('Native boundary must be a valid nonzero polygon; repair is prohibited')
        if self.verification == 'verified':
            required = ['base_elevation', 'height']
            if self.kind in ('door', 'window', 'opening'):
                required += ['sill', 'head']
            if (self.kind_status != 'confirmed' or self.plan_status != 'confirmed'
                    or self.plan_polygon is None or self.conflicts or self.unknowns
                    or any(self.dimensions.get(k, Dimension()).status != 'confirmed' for k in required)):
                raise ValueError('Verified member requires complete, conflict-free drawing evidence')
        return self


class Registration(Record):
    id: str
    drawing_id: str
    origin_cad: tuple[float, float]
    scale_m_per_unit: float = Field(gt=0)
    rotation_rad: float = 0
    status: Literal['local_view', 'candidate', 'confirmed'] = 'local_view'
    control_evidence_ids: list[str] = []
    residual_m: float | None = None
    # This translation is for numerical stability, not surveyed/georeferenced coordinates.
    @model_validator(mode='after')
    def confirmed_controls(self):
        if self.status == 'confirmed' and (len(set(self.control_evidence_ids)) < 3 or self.residual_m is None):
            raise ValueError('Registration requires at least three independent controls and a residual')
        return self
