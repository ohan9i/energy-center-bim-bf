from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Polygon, Point as ShapePoint

Kind = Literal['wall', 'column', 'floor', 'space', 'corridor', 'door', 'stair', 'ramp', 'elevator', 'obstacle', 'unclassified']
Point = tuple[float, float]

class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Properties(Record):
    clear_width: float | None = Field(None, gt=0, le=100)
    step: float | None = Field(None, ge=0, le=100)
    slope: float | None = Field(None, ge=0, le=10)
    operational: bool | None = None

class Element(Record):
    id: str = Field(min_length=1, max_length=160)
    name: str
    type: Kind
    floor_id: str
    polygon: list[Point] = Field(min_length=3, max_length=2000)
    holes: list[list[Point]] = []
    height: float | None = Field(None, gt=0, le=100)
    z_offset: float = 0
    verified: bool = False
    excluded: bool = False
    properties: Properties = Properties()
    source: dict = {}

    @model_validator(mode='after')
    def valid_polygon(self):
        poly = Polygon(self.polygon, self.holes)
        if not poly.is_valid or poly.area < 1e-8:
            raise ValueError(f'{self.id}: 유효한 비자기교차 면적 다각형이 필요합니다.')
        return self

class Floor(Record):
    id: str
    name: str
    elevation: float

class Place(Record):
    id: str
    name: str
    floor_id: str
    point: Point

class Link(Record):
    id: str
    element_id: str
    from_place: str
    to_place: str
    distance: float = Field(gt=0, le=1000)

class Model(Record):
    schema_version: Literal['1.0'] = '1.0'
    id: str
    name: str
    units: Literal['m'] = 'm'
    is_example: bool = False
    revision: int = Field(0, ge=0)
    floors: list[Floor] = Field(min_length=1, max_length=30)
    elements: list[Element] = Field(max_length=10000)
    places: list[Place] = Field(max_length=500)
    links: list[Link] = Field(max_length=500)
    warnings: list[str] = []
    provenance: dict = {}

    @model_validator(mode='after')
    def references(self):
        for records in (self.floors, self.elements, self.places, self.links):
            ids = [r.id for r in records]
            if len(ids) != len(set(ids)):
                raise ValueError('중복 ID가 있습니다.')
        floors = {r.id for r in self.floors}
        elems = {r.id: r for r in self.elements}
        places = {r.id: r for r in self.places}
        if any(r.floor_id not in floors for r in [*self.elements, *self.places]):
            raise ValueError('존재하지 않는 층 ID입니다.')
        for link in self.links:
            if link.element_id not in elems or link.from_place not in places or link.to_place not in places:
                raise ValueError('층간 연결 대상이 없습니다.')
            e = elems[link.element_id]
            if e.type not in ('stair', 'ramp', 'elevator'):
                raise ValueError('층간 연결은 계단·경사로·승강기만 가능합니다.')
            a, b = places[link.from_place], places[link.to_place]
            if a.floor_id == b.floor_id or e.floor_id != a.floor_id:
                raise ValueError('층간 연결의 시작층 또는 도착층이 잘못되었습니다.')
            footprint=Polygon(e.polygon,e.holes)
            if not footprint.covers(ShapePoint(a.point)) or not footprint.covers(ShapePoint(b.point)):
                raise ValueError('층간 연결 지점은 해당 시설 평면 영역 안에 있어야 합니다.')
            za=next(f.elevation for f in self.floors if f.id==a.floor_id)
            zb=next(f.elevation for f in self.floors if f.id==b.floor_id)
            if link.distance+1e-8<((a.point[0]-b.point[0])**2+(a.point[1]-b.point[1])**2+(za-zb)**2)**.5:
                raise ValueError('층간 이동 길이가 두 연결 지점 사이 직선거리보다 짧습니다.')
        return self
