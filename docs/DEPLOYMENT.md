# GitHub Pages 운영 안내

홈페이지: https://ohan9i.github.io/energy-center-bim-bf/

2026-10-12 최신 모델은 modelling_version 12 / revision 9이며, 사용자가 허용한 추정 보완을 포함합니다. [BIM 추정 보완과 접합 개선](BIM_ASSUMED_COMPLETION_2026-10-12.md)에 실제 수정·전후 측정·검증 한계를 기록합니다. 아래 revision 8 문구 정리 기록은 당시 배포 이력입니다.

커밋 `8bd8bfa`의 [Pages 배포 38206566298](https://github.com/ohan9i/energy-center-bim-bf/actions/runs/38206566298)이 성공했습니다. 공개 모델 JSON과 두 IFC의 SHA-256이 해당 Git 모델과 일치합니다. 공개 Chrome에서도 새 모델과 제목, 추정 보 속성, 작은 도구 바, 도움말과 공간 검토, 390/320px 모바일 화면을 확인했으며 실행·HTTP 오류는 0건입니다. 기록은 `cad_output/precision-rebuild/coordination-v2/completion-deployment.json`, `browser-current/branding-results.json`에 보존합니다.

사이트 이름은 **BIM 기반 BF개선**으로 유지합니다. 화면 문구에는 중간점을 쓰지 않으며, 모델의 원본 이름·근거는 변경하지 않고 표시 형식으로 정리합니다. 과도한 영문 장식과 반복 안내를 줄이고 기존 BIM/BF 기능과 검증 상태를 유지합니다. IFC 다운로드는 **검증 IFC**와 **검토 IFC**로 구분합니다.

2026-10-12 문구 정리에서 상단 이름·브라우저 제목·메타 설명을 변경했고, 건물·객체·층 이름의 중간점은 표시할 때만 제거했습니다. 상세 검토 자료는 필요할 때 펼쳐 보고, 주요 미확정 항목은 한국어로 표시합니다. 표시한 이름으로 객체를 검색할 수 있으며 원본 이름을 붙여 넣어도 동일하게 찾습니다. 웹 테스트 66개, TypeScript/Vite 빌드와 하위 경로 검사, 기존 기능 19개 화면과 문구·도움말·공간 검토·390/320px 모바일 화면 검사를 통과했습니다. revision 8 모델 JSON과 두 IFC는 그대로 유지합니다.

문구 변경 커밋 `ffae2dd`의 [Pages 배포 38197098302](https://github.com/ohan9i/energy-center-bim-bf/actions/runs/38197098302)이 성공했습니다. 공개 사이트에서도 새 제목, 중간점 제거, 객체 이름 검색, 공간 검토, 390/320px 모바일 화면을 확인했고 실행·HTTP 오류는 0건이었습니다. 공개 JSON과 두 IFC의 SHA-256은 기존 revision 8과 일치합니다. 기록은 `cad_output/precision-rebuild/coordination-v2/branding-deployment.json`, `browser-current/branding-results.json`에 보존합니다.

소스 저장소: https://github.com/ohan9i/energy-center-bim-bf

## 홈페이지에서 할 수 있는 일

기본 주소에서 최신 통합 3D Coordination Draft를 엽니다. 지하층·지상층·옥상·옥탑과 PIT를 3D/평면, 층 분리, 단면 및 실내 시점으로 검토할 수 있습니다. 표시 설정과 속성에서 도면 기반 형상과 추정 보완 상태를 확인합니다. 검증 완료 입체 부재는 0개이며, 이 모델은 설계 검증 완료나 BF 인증 결과가 아닙니다. 최신 revision 9의 전 층 보완은 [추정 보완 결과](BIM_ASSUMED_COMPLETION_2026-10-12.md), 앞선 구조 보와 출입문 수정은 [revision 8](BIM_STRUCTURAL_AUTHORING_2026-10-12.md)과 [revision 7](BIM_WHOLE_BUILDING_PRECISION_2026-10-12.md)을 참고하세요.

기본 제공 건축물은 최신 통합 3D 모델 하나입니다. 개선 전 v7 비교 모델·비교 버튼, 공간이음 교육관 예제와 이전 도면 기반 BIM은 공개 파일·자동 로딩에서 제거했습니다. 브라우저에 남아 있는 삭제 대상 모델의 저장본도 접속 시 정리하며 다시 불러오거나 저장할 수 없습니다. 별도로 불러온 사용자 모델은 유지합니다. 실제 도면 모델은 확인 전 상태이며 미확인 바닥이나 시설을 통과하는 경로를 만들지 않습니다.

GitHub Pages는 정적 홈페이지이므로 Python·ODA를 사용하는 DWG 업로드 및 IFC 생성은 로컬 앱에서 실행합니다. 공개 사이트의 이용자 모드는 JSON 불러오기, 브라우저 경로 계산 및 현재 모델의 Draft/Verified IFC 다운로드를 지원합니다. 현재 v12 / revision 9 모델은 부재 2,998개·입체 구성요소 6,926개이며 검증 기준을 충족한 입체는 0개입니다.

## 공개 범위

- 소스 코드와 사용자 정의 이동 조건. 경로 알고리즘 테스트 자료는 `web/tests/fixtures/`에서만 사용하며 정적 사이트에 포함하지 않습니다.
- `web/public/models/precision-rebuild.json`: 현재 통합 3D Coordination Draft의 형상·출처·적용 가정과 미확정 상태.
- `web/public/models/precision-rebuild-verified.ifc`, `precision-rebuild-coordination-draft.ifc`: 공개용 IFC. Verified IFC는 층 공간 구조만, Draft IFC는 미확정 검토용 입체를 포함합니다.
- 원본 DWG, `cad_output/`의 원시 분석 및 IFC, 로컬 절대 경로, 가상환경, ODA 실행 파일, 실행 로그는 제외.

전체 출처를 가진 로컬 모델과 공개 모델의 형상·검토 상태는 같습니다. 공개 모델의 `provenance`는 게시용 요약이며 누락된 정보는 통과 가능으로 바꾸지 않습니다.

## 수정과 재배포

2026-10-11 사용자 요청으로 **정밀 1층** 버튼과 별도 검토 화면 코드를 삭제했다. 최신 BF 공간 원장과 **공간 경계 검증**, **BF 공간 표시**를 함께 배포한다. 공개 사이트의 공간 검토는 읽기 전용이며 수정은 로컬 앱에서 수행한다. 공간 후보 31개·문 조립체 포털 88개·승강기 연결 후보 10개는 미확정 상태를 유지하므로 실제 건물의 검증된 BF 경로를 생성하지 않는다. 양개문 중복 문짝 포털 10개를 통합했으며 실제 출입구를 10개 삭제한 것은 아니다. 테스트 성공은 공식 BF 인증 적합 판정이 아니다.

`main`에 `web/` 또는 배포 설정 변경을 push하면 GitHub Actions가 테스트·빌드·하위 경로 HTTP 검사를 거쳐 Pages에 배포합니다. Actions의 **Build and deploy static navigation → Run workflow**에서도 수동 실행할 수 있습니다.

현재 모델 변경은 로컬 도면 재구축·조립체 생성과 검증 후 다음 순서로 반영합니다.

```powershell
.\.venv-cad\Scripts\python.exe -m bf_bim.precise.rebuild --coordination --sync-web
.\.venv-cad\Scripts\python.exe -m bf_bim.spatial_navigation --sync-web
git diff --stat -- web/public/models
git add web/public/models/precision-rebuild.json web/public/models/precision-rebuild-verified.ifc web/public/models/precision-rebuild-coordination-draft.ifc
git commit -m "Update published coordination model"
git push
```

Pages 빌드에는 `VITE_VIEWER_ONLY=true`, `VITE_BASE_PATH=/energy-center-bim-bf/`를 적용합니다. 폴더 이름을 바꾸지 않는 한 로컬 작업 폴더의 한글 이름은 공개 주소에 영향을 주지 않습니다.

빌드 또는 배포 실패는 저장소 Actions 탭에서 해당 실행을 열어 확인합니다. 이전에 정상 배포된 사이트는 새 배포가 성공할 때 갱신됩니다.
