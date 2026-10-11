# 공간이음 BIM / BF 작업 공간 재설계

2026-10-11, 기존 GitHub Pages 주소를 유지하는 전면 UI 재설계입니다.

## 설계 판단

첫 화면의 중심은 실제 BIM 건물입니다. 여러 줄로 쌓이던 프로젝트 정보와 패널 제어를 간결한 헤더와 작업 탭으로 정리하고, 화면 높이를 모델에 할당했습니다. 밝은 뉴트럴 바탕, 절제된 청록색, 얇은 테두리를 사용하며 장식 카드·그라데이션·글래스 효과는 사용하지 않습니다.

[Linear](https://linear.app)의 정리된 정보 위계, [Speckle](https://speckle.systems)의 모델 중심 작업 구성, [Autodesk 모델 관리](https://construction.autodesk.com/products/construction-model-management/)의 검토 흐름을 참고해 이 프로젝트에 맞게 구성했습니다. 로그인 뒤 제품 화면을 직접 비교하거나 복제한 작업은 아닙니다.

## 작업 화면

- **헤더:** 공간이음 브랜드, 현재 건축물, 개정 번호, 모델 상태, 도움말. 그 아래 BIM 모델 / BF 경로 탐색 작업 탭을 제공합니다.
- **모델 탐색기:** 건축물 선택, 층별 빠른 이동, 이름·종류·ID 검색, 건축 요소별 트리, 검토 상태. 건축 요소별 아이콘을 구분합니다.
- **중앙 뷰어:** 첫 화면은 전체 건물을 표시합니다. 평면/3D, 층 선택, 사선·정면·상부 시점, 전체 맞춤, 선택 확대, 실내 시점, 객체 숨기기·복원, 선택 객체만 보기, 표시 설정, 단면·층 분리를 제공합니다.
- **속성 패널:** 처음에는 닫혀 있으며 객체 선택 시 열립니다. 객체 치수·구성요소·CAD 출처·미확정 근거를 검토합니다.
- **BF 작업:** 출발지·목적지와 이동 조건, 경로 계산, 거리·시간·이동 층·층간 이동과 제외 근거를 같은 패널에서 확인합니다. 출발지·목적지를 바꿀 수 있습니다. 경로 선은 모델에 가려지지 않는 검토 오버레이로 표시합니다.
- **상태 바:** 단위, 작업 모드, 모델 주의사항. 상세 주의사항은 필요할 때 펼칩니다.

PC에서는 탐색기와 속성 패널을 독립적으로 접습니다. 1100px 이하에서는 측면 드로어로 전환하고, 패널 안에서 스크롤합니다. 모델 자체는 페이지 스크롤 없이 화면에 유지됩니다. 모바일에서도 표시 층과 주요 도구에 접근할 수 있습니다.

## 공통 디자인 시스템

`web/src/style.css`에서 색상·표면·테두리·글자 위계를 관리합니다. Pretendard Variable을 사이트 내부에 포함해 CDN 의존을 제거했습니다. 숫자에는 tabular-nums를 적용했습니다. 서체 라이선스는 `web/public/fonts/OFL.txt`에 보존합니다.

버튼·입력·비활성·선택·포커스·알림의 표현을 통일했습니다. 아이콘은 Lucide의 동일한 선 굵기를 사용합니다. 모바일 패널 전환에 짧은 이동 효과를 적용하며, 움직임 감소 설정에서는 전환 효과를 끕니다. 숨겨진 패널은 inert, 아이콘 버튼은 접근성 이름, 열림과 선택 상태는 aria 속성을 제공합니다.

## 기능과 데이터 보존

경로 계산, BF 평가, 모델 검증, Worker, 브라우저 저장, CAD 분석·IFC API의 처리 로직은 이번 디자인 작업에서 변경하지 않았습니다. 기존 작업 폴더의 BIM 모델과 형상 렌더러 개선 내용을 보존해 함께 사용할 수 있게 했습니다. 층 이동·단면·투명화·객체 숨김은 화면 표시 상태이며 원본 모델을 수정하지 않습니다.

GitHub Pages는 기존과 같은 이용자 전용 정적 빌드입니다. 로컬 설계자 모드의 편집·저장·CAD 처리·IFC 출력 기능은 보존합니다. 실제 건물의 미확정 조건과 예제 경로를 구분하며, 검토 결과를 공식 BF 인증으로 표현하지 않습니다.

## 검증 결과

- Vitest 7개 파일, 33개 테스트 통과.
- TypeScript 검사와 GitHub Pages용 production 빌드 통과.
- `/energy-center-bim-bf/` 하위 경로의 HTML·모델·규칙·정적 파일·Worker URL 확인 통과. 공개 빌드에 원본 DWG가 포함되지 않음을 확인.
- 실제 Chrome WebGL에서 6개 층, 외관, 투명화, 실 영역, 층 분리, X/Z 단면 절단면, 계단·창호·바닥·문 선택, 조립체 식별, 실내 WASD 이동, 평면 전환 확인.
- 1600×1000 PC와 360×740, 390×844, 768×1024 반응형 검증 통과. 가로·세로 페이지 넘침 및 JavaScript 오류 없음.
- 객체 선택 후 속성 패널, 숨김·복원, 카메라 방향, 도움말 Escape 닫기, 모바일 패널·스크롤·도구 위치 확인.
- 예제 휠체어 경로는 기존과 동일한 **32.6 m / 71초 / 승강기**. 이동 조건 변경 시 이전 경로를 무효화함을 확인.
- 로컬 설계자 객체 편집, 개정값 증가, JSON 출력의 ID·다각형·높이 보존, IndexedDB 저장, 편집창 Escape 닫기, 이용자 모드 전환, 편집 후 BF 경로 확인.

스크린샷과 실행 결과는 Git에서 제외된 `.runtime/workspace-qa/`, `.runtime/redesign-qa/`, `.runtime/designer-qa-results.json`에 있습니다. 소프트웨어 WebGL로 검증했으며 실제 기기 GPU의 FPS 측정은 포함하지 않습니다.

반응형 검사를 재실행하려면 별도 디렉터리의 Playwright와 설치된 Chrome을 사용합니다.

```powershell
$env:VITE_VIEWER_ONLY = 'true'
$env:VITE_BASE_PATH = '/energy-center-bim-bf/'
cd web
npm.cmd test
npm.cmd run build
npm.cmd run preview -- --port 4175
```

별도 터미널에서 프로젝트 루트를 작업 디렉터리로 두고 실행합니다.

```powershell
npm.cmd install --prefix "$env:TEMP/spatial-bim-qa" playwright --no-audit --no-fund
$env:UI_QA_MODULE = "$env:TEMP/spatial-bim-qa/node_modules/playwright"
$env:BIM_QA_URL = 'http://127.0.0.1:4175/energy-center-bim-bf/'
node tools/workspace_browser_qa.cjs
```

## 배포

기존 `main` 브랜치의 GitHub Actions가 테스트·정적 빌드·파일 검사를 수행하고 Pages에 배포합니다.

공개 주소: https://ohan9i.github.io/energy-center-bim-bf/
