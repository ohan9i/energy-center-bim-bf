"""Rule-based adapter over the existing reader. Unsupported geometry stays explicit."""
import hashlib
import math
from collections import Counter
from shapely.geometry import Polygon, LineString, Point
from .schema import Model

LAYER_RULES={'wall':('WALL','벽'), 'column':('COLM','COLUMN','기둥'), 'door':('DOOR','문'),
             'floor':('FLOOR','SLAB','바닥'), 'stair':('STAIR','계단'), 'ramp':('RAMP','경사'),
             'elevator':('LIFT','ELEV','승강'), 'corridor':('CORRIDOR','복도'), 'space':('ROOM','SPACE','실')}

def classify(layer):
    text=layer.upper()
    return next((kind for kind,keys in LAYER_RULES.items() if any(key in text for key in keys)), 'unclassified')

def summary(data):
    entities=[e for e in data['scene_entities'] if e.get('layout')=='Model']
    counts=Counter(e['effective_layer'] for e in entities)
    return {'units':data['units'],'layers':[{'name':r['name'],'count':counts[r['name']],
        'suggested':classify(r['name']),'off':r['off'],'frozen':r['frozen']} for r in data['layers']],
        'entity_count':len(entities),'types':dict(Counter(e['type'] for e in entities)),
        'warnings':data['warnings'], 'external_references':data['external_references'],
        'original_unchanged':data['source']['original_unchanged']}

def build_model(data, mapping, scale, height, thickness, floor_name='1층', elevation=0):
    scale=scale or data['units']['meters_per_drawing_unit']
    if scale is None or not math.isfinite(scale) or scale<=0:
        raise ValueError('도면 단위가 미지정입니다. 1 도면단위당 미터 환산계수를 직접 입력하세요.')
    if not 0.01<=height<=100 or not 0.01<=thickness<=5:
        raise ValueError('입력 층고·벽 두께를 확인하세요.')
    elements=[];warnings=[];unmodelled=Counter()
    model_entities=[e for e in data['scene_entities'] if e.get('layout')=='Model']
    for entity in model_entities:
        layer=entity['effective_layer'];kind=mapping.get(layer,classify(layer))
        if kind=='ignore':continue
        g=entity['geometry'];geom=None;inferred=False
        try:
            if 'vertices' in g and g.get('closed') and all(s['type']=='LINE' for s in g.get('segments',[])):
                geom=Polygon([(p[0]*scale,p[1]*scale) for p in g['vertices']])
            elif entity['type']=='LINE':
                line=LineString([(g['start'][0]*scale,g['start'][1]*scale),(g['end'][0]*scale,g['end'][1]*scale)])
                if kind in ('wall','door'):
                    geom=line.buffer(thickness/2 if kind=='wall' else max(thickness,.4),cap_style=2)
                    inferred=True
            elif entity['type']=='CIRCLE' and kind in ('column','obstacle'):
                geom=Point(g['center'][0]*scale,g['center'][1]*scale).buffer(g['radius']*scale,quad_segs=16)
            if geom is None or geom.is_empty or not geom.is_valid or geom.area<1e-8:
                unmodelled[f'{layer}:{entity["type"]}']+=1;continue
            eid='cad-'+hashlib.sha256(entity['id'].encode()).hexdigest()[:16]
            elements.append(dict(id=eid,name=f'{layer} · {entity.get("handle") or eid[-5:]}',type=kind,
                floor_id='f1',polygon=list(geom.exterior.coords)[:-1],
                holes=[list(r.coords)[:-1] for r in geom.interiors],
                height=.15 if kind=='floor' else height if kind in ('wall','column','stair','elevator') else 2.1 if kind=='door' else None,
                verified=False,properties={},source={'origin':'cad','layer':layer,'cad_id':entity['id'],
                'cad_handle':entity.get('handle'),'definition_handle':entity.get('definition_handle'),
                'geometry_inferred':inferred,'height_source':'user_modelling_assumption',
                'wall_thickness_source':'user_modelling_assumption' if inferred else 'cad_polygon',
                'meters_per_drawing_unit':scale}))
        except (ValueError,TypeError,KeyError) as exc:
            warnings.append(f'{entity["id"]}: {exc}')
    if unmodelled:
        warnings.append('BIM 형상으로 변환하지 않은 객체: '+', '.join(f'{k}={v}' for k,v in unmodelled.items()))
    warnings.extend(f'{w["code"]}: {w["message"]}' for w in data['warnings'])
    warnings.append('자동 분류·층고·벽 두께는 확인 전 입력입니다. 바닥 영역, 문 유효폭, 단차 및 층간 연결을 검토하세요.')
    places=[]
    for i,e in enumerate(x for x in elements if x['type'] in ('space','corridor')):
        p=Polygon(e['polygon']).representative_point()
        places.append(dict(id=f'place-{e["id"]}',name=e['name'],floor_id='f1',point=[p.x,p.y]))
    return Model.model_validate(dict(id='cad-'+data['source']['sha256_before'][:12],name='CAD에서 생성한 '+floor_name,
        floors=[dict(id='f1',name=floor_name,elevation=elevation)],elements=elements,places=places,links=[],warnings=warnings,
        provenance={'cad_sha256':data['source']['sha256_before'],'original_unchanged':data['source']['original_unchanged'],
                    'source_units':data['units'],'mapping':mapping}))
