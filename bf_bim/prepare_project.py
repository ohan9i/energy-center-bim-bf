"""Reproduce the approved project model; generated outputs stay under cad_output/."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
from cad_reader import analyze_drawing, export_json

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    folder=Path('에너지-건축도면')
    plan=next(folder.glob('A04-001*.dwg'),None)
    section=next(folder.glob('A04-021*.dwg'),None)
    if plan is None or section is None:
        raise RuntimeError('에너지-건축도면 폴더에 A04-001 평면도와 A04-021 단면도가 필요합니다.')
    out=Path('cad_output');out.mkdir(exist_ok=True)
    plan_before,section_before=sha(plan),sha(section)
    cache=out/'actual-floorplans.json';reuse=False
    if cache.exists():
        # Inventory is small; avoid loading the 500 MB raw cache merely to check its hash.
        inventory=out/'project-inventory.json'
        if inventory.exists():reuse=json.loads(inventory.read_text(encoding='utf-8')).get('sha256')==plan_before
    if not reuse:
        print('1/5 실제 평면도 DWG를 ODA로 분석합니다. 수 분이 걸릴 수 있습니다.',flush=True)
        data=analyze_drawing(plan)
        export_json(data,cache,overwrite=True)
        del data
    else:print('1/5 원본 해시가 일치하는 평면도 분석 캐시를 사용합니다.',flush=True)
    from .inspect_project import main as inspect
    from .read_sections import main as read_sections
    from .project_model import main as build
    from .plot_project import main as plot
    from .preview_model import main as preview
    from .audit_drawings import main as audit
    from .validate_ifc import main as validate_ifc
    with contextlib.redirect_stdout(io.StringIO()):inspect()
    print('2/5 단면도의 층 기준 높이를 읽습니다.',flush=True)
    cached_section=out/'section-texts.json'
    section_reuse=cached_section.exists() and json.loads(cached_section.read_text(encoding='utf-8'))['source']['sha256_before']==section_before
    if not section_reuse:
        with contextlib.redirect_stdout(io.StringIO()):read_sections()
    audit()
    print('3/5 상세 형상이 남은 지하 1층·지상 1~4층과 지붕층을 분리하고 모델을 생성합니다.',flush=True)
    with contextlib.redirect_stdout(io.StringIO()):build()
    print('4/5 CAD 대조 이미지와 모델 미리보기를 생성합니다.',flush=True)
    with contextlib.redirect_stdout(io.StringIO()):plot();preview()
    print('5/5 최종 IFC의 EXPRESS 규칙, 전체 객체 좌표·면적·체적을 검증합니다.',flush=True)
    with contextlib.redirect_stdout(io.StringIO()):validate_ifc()
    if sha(plan)!=plan_before or sha(section)!=section_before:raise RuntimeError('처리 중 원본 도면이 변경되었습니다.')
    print('완료: cad_output/energy-center-model.json, energy-center.ifc, energy-center-preview.png, ifc-validation.json. 원본 해시 일치.',flush=True)

if __name__=='__main__':main()
