"""Synthetic two-storey fixture. All dimensions are declared test inputs."""
import json
from pathlib import Path
from .schema import Model

def rect(x1, y1, x2, y2):
    return [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]

def example_model():
    elements = []
    def add(id, name, kind, floor, polygon, height=3, **props):
        elements.append(dict(id=id,name=name,type=kind,floor_id=floor,polygon=polygon,
                             height=height,verified=True,properties=props,source={'origin':'synthetic'}))
    for floor in ('f1','f2'):
        add(f'{floor}-floor', '바닥', 'floor', floor, rect(0,0,20,12), .15, step=0)
        for label, coords in [('남측',(0,0,20,.2)),('북측',(0,11.8,20,12)),('서측',(0,0,.2,12)),('동측',(19.8,0,20,12)),('강의실 칸막이',(0,6,20,6.2))]:
            add(f'{floor}-wall-{label}', label+' 벽체','wall',floor,rect(*coords))
        add(f'{floor}-door-class', '강의실 출입문', 'door',floor,rect(8.3,5.8,9.7,6.4),2.1,clear_width=1.1,step=0)
        add(f'{floor}-column', '구조 기둥', 'column',floor,rect(10,3,10.7,3.7))
        add(f'{floor}-room', '강의실', 'space',floor,rect(.3,6.3,19.7,11.7),None)
        add(f'{floor}-corridor', '로비 · 복도', 'corridor',floor,rect(.3,.3,19.7,5.9),None)
    add('main-door','정문','door','f1',rect(1.1,-.2,2.9,.4),2.1,clear_width=1.5,step=0)
    add('stairs','계단 · 1↔2층','stair','f1',rect(3,3.8,5,5.4),3,clear_width=1.2,step=.16,slope=.6)
    add('lift','승강기 · 1↔2층','elevator','f1',rect(16,3.8,18,5.4),3,clear_width=1.1,step=0,operational=True)
    add('ramp','완만한 로비 경사로','ramp','f1',rect(5,1.2,8,2.8),.25,clear_width=1.6,step=0,slope=.04)
    places = [dict(id='entrance',name='1층 정문',floor_id='f1',point=[2,1]),
              dict(id='lobby',name='1층 로비',floor_id='f1',point=[9,2]),
              dict(id='class1',name='1층 강의실',floor_id='f1',point=[6,9]),
              dict(id='class2',name='2층 강의실',floor_id='f2',point=[6,9])]
    for kind,point in [('stair',[4,4.5]),('lift',[17,4.5])]:
        for floor in ('f1','f2'):
            places.append(dict(id=f'{kind}-{floor}',name=f'{floor[1]}층 '+('계단' if kind=='stair' else '승강기'),floor_id=floor,point=point))
    for e in elements:
        if e['type']=='floor':e['z_offset']=-.15
    return Model.model_validate(dict(id='demo-two-storey',name='공간이음 교육관 · 2층 예제',is_example=True,
        floors=[dict(id='f1',name='1층',elevation=0),dict(id='f2',name='2층',elevation=3.3)],
        elements=elements, places=places,
        links=[dict(id='link-stair',element_id='stairs',from_place='stair-f1',to_place='stair-f2',distance=5.8),
               dict(id='link-lift',element_id='lift',from_place='lift-f1',to_place='lift-f2',distance=3.3)],
        warnings=['실제 건축 도면이 아닌 경로 탐색 검증용 예제입니다. 모든 치수는 테스트 입력값입니다.']))

if __name__ == '__main__':
    path=Path('web/public/models/demo.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(example_model().model_dump_json(indent=2),encoding='utf-8')
