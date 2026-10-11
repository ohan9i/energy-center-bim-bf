import json
import tempfile
import threading
import time
import uuid
from typing import get_args
from pathlib import Path
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import Response
from fastapi.responses import FileResponse
from pydantic import Field
from cad_reader import analyze_drawing
from cad_reader.environment import find_oda
from .schema import Model, Record, Kind
from .example import example_model
from .cad import summary, build_model
from .ifc_export import export_ifc

app=FastAPI(title='공간이음 CAD / BIM API',version='0.1.0')
# Serialize existing reader's process-global ODA option. Bind API to loopback only.
cad_lock=threading.Lock()
cache={}
TTL=3600

def clean_cache():
    now=time.monotonic()
    for token,(created,_) in list(cache.items()):
        if now-created>TTL:cache.pop(token,None)

@app.get('/api/health')
def health():
    return {'status':'ok','oda_available':find_oda() is not None,'mode':'local-processing'}

@app.get('/api/example')
def example():
    return example_model()

@app.get('/api/project-model')
def project_model():
    path=Path('cad_output/energy-center-model.json')
    if not path.is_file():raise HTTPException(404,'실제 도면 모델이 아직 생성되지 않았습니다.')
    return Model.model_validate_json(path.read_text(encoding='utf-8'))

REBUILD_DIR=Path(__file__).resolve().parents[1]/'cad_output/precision-rebuild'

@app.get('/api/rebuilt-model')
def rebuilt_model():
    path=REBUILD_DIR/'coordination-v2/preview.json'
    if not path.is_file():path=REBUILD_DIR/'preview.json'
    if not path.is_file():raise HTTPException(404,'python -m bf_bim.precise.rebuild를 실행하세요.')
    return FileResponse(path,media_type='application/json')

@app.get('/api/rebuilt-ifc')
def rebuilt_ifc():
    path=REBUILD_DIR/'coordination-v2/energy-center-Verified.ifc'
    if not path.is_file():path=REBUILD_DIR/'verified.ifc'
    if not path.is_file():raise HTTPException(404,'검증 형상 IFC가 아직 생성되지 않았습니다.')
    return FileResponse(path,media_type='application/x-step',filename='energy-center-verified.ifc')

@app.get('/api/rebuilt-draft-ifc')
def rebuilt_draft_ifc():
    path=REBUILD_DIR/'coordination-v2/energy-center-Coordination-Draft.ifc'
    if not path.is_file():raise HTTPException(404,'Coordination Draft를 먼저 생성하세요.')
    return FileResponse(path,media_type='application/x-step',filename='energy-center-Coordination-Draft.ifc')

# Phase-1 precision review is a separate, read-only artifact namespace.
# It never activates, persists, publishes or replaces the legacy model.
PRECISION_DIR=Path(__file__).resolve().parents[1]/'cad_output/precision-stage1'

@app.get('/api/precision/{artifact}')
def precision_artifact(artifact:str):
    allowed={'pilot':'pilot.json','drawings':'drawings.json','observations':'observations.json',
             'cross-references':'cross-references.json','summary':'build-summary.json'}
    name=allowed.get(artifact)
    if name is None:raise HTTPException(404,'지원하지 않는 정밀 검토 자료입니다.')
    path=PRECISION_DIR/name
    if not path.is_file():raise HTTPException(404,'정밀 1층 자료가 없습니다. python -m bf_bim.precise.stage1 --extract-all을 실행하세요.')
    return FileResponse(path,media_type='application/json')

@app.get('/api/precision-export/ifc')
def precision_ifc():
    from .precise.schema import Member,Observation,Registration
    from .precise.validation import export_verified_ifc
    try:
        data=json.loads((PRECISION_DIR/'pilot.json').read_text(encoding='utf-8'))
        facts=json.loads((PRECISION_DIR/'observations.json').read_text(encoding='utf-8'))
        output=export_verified_ifc([Member.model_validate(m) for m in data['members']],
                                  [Observation.model_validate(e) for e in facts],
                                  Registration.model_validate(data['registration']))
        return Response(output,media_type='application/x-step')
    except FileNotFoundError:raise HTTPException(404,'정밀 검토 자료가 없습니다.')
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/project-plan/{floor}')
def project_plan(floor:str):
    paths={'b1':Path('cad_output/detailed-basement.png'),'f1':Path('cad_output/detailed-first.png'),'f2':Path('cad_output/detailed-second.png'),
        'f3':Path('cad_output/detailed-third.png'),'f4':Path('cad_output/detailed-fourth.png'),'roof':Path('cad_output/detailed-roof.png')}
    path=paths.get(floor)
    if path is None or not path.is_file():raise HTTPException(404,'해당 층 원본 도면 미리보기가 없습니다.')
    return FileResponse(path,media_type='image/png')

@app.post('/api/cad/analyze')
def analyze(file:UploadFile):
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.dwg','.dxf'):
        raise HTTPException(415,'DWG 또는 DXF 파일만 지원합니다.')
    try:
        with tempfile.TemporaryDirectory(prefix='bf-upload-') as folder:
            path=Path(folder)/('drawing'+suffix)
            with path.open('wb') as out:
                total=0
                while chunk:=file.file.read(1024*1024):
                    total+=len(chunk)
                    if total>50*1024*1024:raise HTTPException(413,'50 MB 이하 도면을 사용하세요.')
                    out.write(chunk)
            with cad_lock:
                clean_cache()
                if len(cache)>=4:raise HTTPException(429,'현재 분석 세션이 4개입니다. 서버를 재시작하거나 기존 세션 만료 후 진행하세요.')
                data=analyze_drawing(path,max_scene_entities=100000)
                token=uuid.uuid4().hex;cache[token]=(time.monotonic(),data)
            return {'token':token,**summary(data)}
    except HTTPException:raise
    except Exception as exc:
        raise HTTPException(422,f'도면 분석 실패: {exc}. ODA 상태와 외부 참조를 확인하거나 DXF로 다시 저장하세요.') from exc

class BuildRequest(Record):
    token:str
    mapping:dict[str,Kind | str]
    scale:float|None=Field(None,gt=0,le=1000)
    height:float=Field(gt=.01,le=100)
    thickness:float=Field(gt=.01,le=5)
    floor_name:str='1층'
    elevation:float=0

@app.post('/api/cad/build')
def build(req:BuildRequest):
    clean_cache()
    if req.token not in cache:raise HTTPException(410,'CAD 분석 세션이 만료되었습니다. 도면을 다시 업로드하세요.')
    if any(v not in (*get_args(Kind),'ignore') for v in req.mapping.values()):
        raise HTTPException(422,'지원하지 않는 요소 분류입니다.')
    try:return build_model(cache[req.token][1],req.mapping,req.scale,req.height,req.thickness,req.floor_name,req.elevation)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/cad/{token}/report')
def report(token:str):
    clean_cache()
    if token not in cache:raise HTTPException(410,'분석 세션이 만료되었습니다.')
    return Response(json.dumps(cache[token][1],ensure_ascii=False),media_type='application/json',headers={'Content-Disposition':'attachment; filename="cad-report.json"'})

@app.post('/api/ifc')
def ifc(model:Model):
    try:
        return Response(export_ifc(model),media_type='application/x-step',headers={'Content-Disposition':'attachment; filename="building.ifc"'})
    except Exception as exc:raise HTTPException(422,f'IFC 생성 실패: {exc}') from exc
