# DWG 도면 추출과 기하학 분석

이 모듈은 **DWG 경로를 Python에 바로 입력**해 도면을 분석합니다. 내부적으로 ODA File Converter가 임시 복사본을 DXF로 변환하고 `ezdxf`가 읽습니다. 사용자가 도면을 수동 변환할 필요는 없습니다. `ezdxf` 자체는 DWG 해석기가 아닙니다.

기존 도면 폴더는 수정하지 않습니다. 코드 `cad_reader/`, 전용 Python 환경 `.venv-cad/`, VS Code 인터프리터 설정만 추가했습니다. ODA가 프로젝트 `.tools/oda/`에 있으면 자동으로 탐색합니다.

## 1. 환경 확인 및 설치

프로젝트 루트의 VS Code PowerShell 터미널에서 실행합니다.

```powershell
.\.venv-cad\Scripts\python.exe -m cad_reader doctor
```

`ready_for_dwg: true`이면 DWG를 처리할 준비가 된 상태입니다. 종료 코드 `2`는 ODA 또는 Python 의존성이 부족하다는 뜻입니다. 실행 파일을 찾은 것만 검사하므로 실제 도면을 읽어야 변환기 동작까지 검증할 수 있습니다.

새 PC에서는 Python 3.10 이상을 설치한 뒤 다음을 실행합니다. 현재 프로젝트에는 Python 3.12 전용 가상환경을 구성했습니다.

```powershell
py -m venv .venv-cad
.\.venv-cad\Scripts\python.exe -m pip install -r cad_reader\requirements.txt
```

또는 `cad_reader/setup.ps1`을 실행하면 가상환경 생성, 의존성 설치, 환경 확인을 순서대로 수행합니다. 특정 Python을 사용하려면 `-Python 'C:\경로\python.exe'`로 지정합니다. 가상환경을 활성화하지 않아도 위 명령은 정확한 인터프리터를 사용합니다.

VS Code에서 `Ctrl+Shift+P` → **Python: Select Interpreter** → `.venv-cad\Scripts\python.exe`를 선택하세요. `.vscode/settings.json`에도 기본 인터프리터를 지정했습니다. Python 확장이 없으면 Microsoft Python 확장을 설치하세요.

### ODA가 없을 때

1. [ODA 공식 다운로드 페이지](https://www.opendesign.com/guestfiles/oda_file_converter)를 엽니다.
2. Windows 10 이상용 **Windows x64** 설치 프로그램을 내려받아 설치합니다.
3. `doctor`를 다시 실행합니다. 기본 ODA 설치 폴더, 버전별 폴더, PATH, 프로젝트 `.tools/oda/`를 탐색합니다.
4. 사용자 지정 경로가 자동 탐색되지 않으면 아래처럼 지정합니다. 예시의 버전·경로는 실제 설치 경로로 바꿉니다.

```powershell
$env:ODA_FILE_CONVERTER = 'C:\Program Files\ODA\ODAFileConverter 27.9.0\ODAFileConverter.exe'
.\.venv-cad\Scripts\python.exe -m cad_reader doctor
```

환경변수 대신 매 실행 시 `--oda 'C:\실제경로\ODAFileConverter.exe'`를 사용할 수도 있습니다. 명시적 `--oda` → 환경변수 → 자동 탐색 순서이며, 명시한 경로가 잘못되면 다른 프로그램으로 임의 전환하지 않고 오류를 냅니다.

## 2. 실제 도면 읽기

```powershell
.\.venv-cad\Scripts\python.exe -m cad_reader inspect '.\에너지-건축도면-2022.9.02\A04-001~008 평면도.dwg' --json '.\cad_output\평면도.json'
```

명령은 원본 해시 일치 여부, 단위, 레이어·블록 수, 객체 종류, 경고, 외부 참조를 요약합니다. `--json`을 생략하면 파일을 내보내지 않고 요약만 표시합니다. DXF 파일도 같은 명령으로 읽을 수 있습니다.

기존 JSON 파일이 있으면 실수로 덮어쓰지 않도록 실패합니다. 의도적으로 갱신하려면 `--overwrite`를 붙입니다. 출력은 `.json`만 허용하며 원본 파일 또는 원본에 연결된 경로에는 쓸 수 없습니다.

## 3. Python에서 활용

```python
from cad_reader import analyze_drawing, export_json
from cad_reader.analysis import (
    select_entities, query_bounds, endpoint_connections, line_intersections,
)

data = analyze_drawing(
    r"에너지-건축도면-2022.9.02\A04-001~008 평면도.dwg"
)
print([layer["name"] for layer in data["layers"]])
print(data["units"])

# 모델 공간에 실제 배치된 객체: 블록 내부도 회전·축척·이동 반영.
lines = select_entities(data, types=["LINE"])
for line in lines[:5]:
    print(line["id"], line["effective_layer"], line["geometry"])

# 특정 레이어는 실제 레이어 이름으로 지정합니다.
# walls = select_entities(data, layer="실제 벽체 레이어", types=["LINE", "LWPOLYLINE"])

# 3차원 경계 상자와 겹치는 후보 객체. 실제 접촉 판정은 별도로 해야 합니다.
candidates = query_bounds(data, (0, 0, -1), (10000, 10000, 1))

# 끝점 연결과 직선 교차. tolerance는 '도면 단위'입니다.
connections = endpoint_connections(data, tolerance=0.01)
crossings = line_intersections(data, max_pairs=100_000)
data["analysis"] = {"connections": connections, "crossings": crossings}
export_json(data, "cad_output/analysis.json")
```

실행 가능한 예제:

```powershell
.\.venv-cad\Scripts\python.exe -m cad_reader.example_analysis '.\에너지-건축도면-2022.9.02\A04-001~008 평면도.dwg' --output '.\cad_output\analysis.json'
```

큰 도면의 직선 교차는 대상 레이어를 `--layer '레이어 이름'`으로 좁히세요. 함수의 `truncated`가 `true`이면 계산 상한에 도달한 부분 결과입니다.

## 4. 데이터 구조와 좌표 해석

반환값은 JSON으로 저장 가능한 Python `dict`입니다.

| 키 | 저장 내용 |
| --- | --- |
| `source` | 입력 경로, 변환 방식, 실행 파일 경로, 원본 SHA-256 전후 비교 |
| `units` | `$INSUNITS`, 단위 이름, 도면 1단위당 미터 환산계수, 표시 단위·UCS 헤더 |
| `layers` | 전체 레이어와 색상·선종류 원시 속성, off/frozen/locked 상태 |
| `layouts` | 모델 공간과 모든 종이 공간의 원본 객체 |
| `blocks` | 블록 정의, 기준점, 블록 단위, 내부 객체, XREF 플래그·경로 |
| `scene_entities` | 블록 배치 변환을 적용한 객체, 부모 블록 참조, 원본 정의 handle |
| `tables` | 문자 스타일·치수 스타일 |
| `relationships` | 레이어별·종류별 객체 ID, 원본 레이아웃 객체와 배치 객체의 대응 |
| `external_references` | XREF·이미지·PDF/DWF/DGN 참조 경로와 존재 여부 |
| `unplaced_entities` | 레이아웃·블록에서 확인되지 않은 그래픽 객체 |
| `coverage` | 객체 수·종류, 지원 상태, 확장 중단 여부, OBJECTS 종류·CLASS 목록 |
| `warnings` | 미지원·변환 실패·외부 참조·분석 한계의 코드와 객체 식별 정보 |

각 객체는 `id`, `handle`, `type`, `layer`, `effective_layer`, `coordinate_system`, `dxf`, `geometry`, `bounds`, `support`를 가집니다. 배치 객체에는 `root_entity_id`, `parent_insert_id`, `insert_ancestry`, `definition_handle`도 있습니다. 가상 배치 객체는 DXF handle이 없을 수 있으므로 **연결에는 `id`를 사용**합니다. 블록 원본 좌표를 찾을 때는 `definition_handle`을 사용합니다. 일부 비균일 변환이 객체를 분해하면 원본 handle 대응이 없어질 수 있습니다.

* `dxf`: 원시 DXF 속성입니다. 객체 종류에 따라 OCS와 WCS가 섞여 있으므로 무조건 전역 좌표로 해석하면 안 됩니다.
* `geometry`: LINE 시작·끝·길이, CIRCLE 중심·반지름·면적, ARC 시작·끝·각도·길이, 폴리라인 정점·직선/호 구간·길이, 문자 내용·위치, 치수값과 정의점, 블록 배치행렬·속성 문자 등을 담습니다. 타원과 스플라인도 매개변수를 저장합니다.
* `blocks[].entities`: 블록 자체의 로컬 WCS입니다. `scene_entities`와 함께 합산하면 정의와 배치를 중복 계산하게 됩니다.
* `scene_entities`: 각 레이아웃의 WCS입니다. 모델 공간과 종이 공간은 서로 다른 공간이므로 직접 거리·교차를 비교하지 않습니다. 기본 분석 대상은 `Model`입니다.
* 블록 레이어 `0`은 상위 INSERT 레이어를 상속한 `effective_layer`로 분류합니다. 색상·선종류의 BYBLOCK 렌더링은 별도 구현이 필요합니다.
* `INSERT.geometry.block_to_layout_matrix_rows`는 `ezdxf.math.Matrix44`의 행 순서입니다. CAD 기준점도 반영됩니다. 다른 라이브러리의 열벡터 행렬로 직접 해석하지 마세요.
* `$INSUNITS=0`은 단위 미지정입니다. mm라고 가정하지 않고 환산계수를 `None`으로 반환합니다. `$LUNITS`는 숫자 표시 형식이며 길이 단위를 결정하지 않습니다.
* 길이·좌표는 원래 도면 단위입니다. mm 도면의 길이 1000을 m로 바꾸려면 `meters_per_drawing_unit`을 곱합니다. 단위 메타데이터가 실제 작성 관행과 일치하는지는 치수·축척과 대조해야 합니다.
* 치수 `measurement`는 기하학 측정값입니다. 각도 치수는 **도**, 좌표 치수는 벡터입니다. 표시 치수는 `text_override`, 치수 스타일의 `DIMLFAC`, 정밀도·반올림 등 때문에 다를 수 있습니다. 표시 문자열을 실측 길이로 바로 사용하지 마세요.

## 5. 분석 범위와 누락 확인

`support`는 `full`, `partial`, `unsupported`, `failed` 중 하나입니다. `full`은 이 모듈이 제공하는 해당 객체의 명시적 기하학·문자·배치 필드가 추출되었다는 뜻이며 모든 CAD 동작의 재현을 보장하지 않습니다.

* LINE, 일반 2D/3D POLYLINE, LWPOLYLINE, CIRCLE, ARC, TEXT/MTEXT, ATTRIB/ATTDEF, DIMENSION, INSERT, POINT, ELLIPSE, SPLINE을 구조화합니다. 폴리라인의 bulge는 호 구간으로 해석하며 곡선 길이를 직선 길이로 대체하지 않습니다.
* HATCH 경계는 원시 OCS 경계로 보존하지만 면적·영역 결합은 구현하지 않았습니다. 폴리페이스·메시 POLYLINE도 부분 지원입니다.
* ACIS 3DSOLID/BODY/REGION, 프록시, RAY/XLINE, TABLE 등 미지원 객체는 속성과 가능한 원시 태그를 보존하고 경고합니다. 일반 DXF 헤더 속성만으로 독점 AEC 객체의 의미를 복원할 수는 없습니다.
* 동적 블록 파라미터·AEC 속성 의미 해석, 글꼴 렌더링, 뷰포트 투영, 주석 축척 재현은 포함하지 않습니다. 문자 경계는 근삿값입니다. off/frozen 레이어의 객체도 반환합니다.
* XREF는 경로·존재 여부만 조사합니다. 파일이 존재해도 자동으로 로드·병합하지 않으며, 중첩 외부 파일의 내용도 조사하지 않습니다. 이미지·언더레이 내용도 추출하지 않습니다. `contents_extracted=false`를 반드시 확인하세요. 참조 경로는 **원본 DWG의 폴더**를 기준으로 계산합니다.
* INSERT는 중첩·회전·축척과 MINSERT 배열을 확장합니다. 비균일 축척은 원을 타원으로 바꿀 수 있으며 문자는 부정확할 수 있습니다. 변환기가 확장하지 못한 객체는 `BLOCK_ENTITIES_SKIPPED`로 보고합니다.
* XCLIP은 적용하지 않습니다. 경계 밖 객체도 포함될 수 있어 `XCLIP_NOT_APPLIED` 경고를 확인해야 합니다.
* 깊이 32, 배치 객체 500,000개가 기본 상한입니다. 순환·상한으로 확장이 멈추면 경고하며 원본 레이아웃과 블록 정의는 보존합니다. CLI의 `--max-depth`, `--max-scene-entities`로 조정할 수 있습니다.
* 끝점 연결은 LINE/ARC/폴리라인 구간의 3D 끝점 거리만 비교합니다. 직선 교차는 XY에서 교차 위치를 찾은 후 보간 Z까지 비교합니다. 곡선 교차, 공선 중첩, 수직선의 XY 퇴화, 객체 자체 교차는 별도 계산이 필요합니다. 미해결 평행·퇴화 후보 수를 결과에 표시합니다.
* ODA가 DWG에서 DXF로 변환하면서 이미 누락한 독점 데이터는 `ezdxf`로 역검증할 수 없습니다. `full_dwg_fidelity_verified`는 `false`이며 DWG 입력에는 `CONVERSION_LOSS_NOT_VERIFIABLE` 경고가 있습니다. JSON의 경고가 없다는 이유만으로 완전한 무손실 변환이라고 판단하지 마세요.

원본 도면에 `save`, `saveas`, ODA export를 호출하지 않습니다. DWG는 격리된 임시 폴더의 복사본만 변환하고 ODA audit/repair를 끕니다. 처리 전후 원본 SHA-256을 비교합니다. ODA 실행 경로 설정은 처리 후 복원하지만 `ezdxf` 설정이 프로세스 전역이므로 병렬 변환은 스레드 대신 별도 프로세스로 실행하세요.

## 6. 검증

```powershell
.\.venv-cad\Scripts\python.exe -m unittest discover -s cad_reader\tests -v
.\.venv-cad\Scripts\python.exe -m pip check
```

테스트는 좌표 변환·단위·곡선 길이·치수·문자, 종이 공간 분리, 높이가 다른 선의 교차 제외, XREF·미지원 객체 보고, 순환·배열 블록, 해시·덮어쓰기 방지를 검사합니다. ODA 경계 모의 테스트는 임시 복사본 사용과 설정 복원을 확인하며 실제 DWG 변환 검증과 구분됩니다.

관련 공식 문서: [ezdxf ODA 연동](https://ezdxf.readthedocs.io/en/stable/addons/odafc.html), [좌표와 기하학](https://ezdxf.readthedocs.io/en/stable/math/core.html), [객체 분해·경계의 한계](https://ezdxf.readthedocs.io/en/stable/disassemble.html).
