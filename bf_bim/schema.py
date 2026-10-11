from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Polygon, Point as ShapePoint

Kind = Literal['wall', 'column', 'beam', 'floor', 'roof', 'window', 'opening', 'space', 'corridor', 'door', 'stair', 'ramp', 'elevator', 'obstacle', 'unclassified']
Point = tuple[float, float]

class SolidMesh(BaseModel):
    """Closed, consistently oriented triangles; component-local Z, model XY."""
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    vertices: list[tuple[float, float, float]] = Field(min_length=4, max_length=10000)
    triangles: list[tuple[int, int, int]] = Field(min_length=4, max_length=20000)

    @model_validator(mode='after')
    def valid_mesh(self):
        from collections import Counter
        edges = Counter()
        volume = 0.
        for a,b,c in self.triangles:
            if min(a,b,c)<0 or max(a,b,c)>=len(self.vertices) or len({a,b,c})!=3:
                raise ValueError('솔리드 삼각형의 정점 참조가 잘못되었습니다.')
            for i,j in ((a,b),(b,c),(c,a)):edges[(i,j)]+=1
            u,v,w=(self.vertices[i] for i in (a,b,c))
            volume += sum(u[i]*(v[(i+1)%3]*w[(i+2)%3]-v[(i+2)%3]*w[(i+1)%3]) for i in range(3))/6
        if any(n!=1 or edges[(j,i)]!=1 for (i,j),n in edges.items()) or volume<=1e-10:
            raise ValueError('솔리드는 닫힌 양의 체적과 일관된 면 방향이 필요합니다.')
        return self

class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Properties(Record):
    clear_width: float | None = Field(None, gt=0, le=100)
    step: float | None = Field(None, ge=0, le=100)
    slope: float | None = Field(None, ge=0, le=10)
    operational: bool | None = None

class Component(Record):
    """Measured assembly geometry in model XY, Z relative to the parent base."""
    id: str = ''
    role: str
    polygon: list[Point] = Field(min_length=3, max_length=2000)
    holes: list[list[Point]] = []
    height: float | None = Field(None, gt=0, le=100)
    z_offset: float = 0
    source: dict = {}
    mesh: SolidMesh | None = None

    @model_validator(mode='after')
    def valid_geometry(self):
        if not Polygon(self.polygon, self.holes).is_valid or Polygon(self.polygon, self.holes).area < 1e-8:
            raise ValueError('조립체 구성요소의 다각형이 유효하지 않습니다.')
        if self.mesh:
            zs=[v[2] for v in self.mesh.vertices]
            if self.height is None or abs(min(zs))>1e-7 or abs(max(zs)-self.height)>1e-7:
                raise ValueError('솔리드 정점 Z와 구성요소 높이가 다릅니다.')
        return self

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
    components: list[Component] = Field(default_factory=list, max_length=500)

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
        component_ids=[c.id for e in self.elements for c in e.components if c.id]
        if len(component_ids)!=len(set(component_ids)) or set(component_ids)&{e.id for e in self.elements}:
            raise ValueError('조립체 구성요소 ID가 중복됩니다.')
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
