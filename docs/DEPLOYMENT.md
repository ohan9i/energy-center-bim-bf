# GitHub Pages 운영 안내

홈페이지: https://ohan9i.github.io/energy-center-bim-bf/

소스 저장소: https://github.com/ohan9i/energy-center-bim-bf

## 홈페이지에서 할 수 있는 일

기본 주소에서 최신 통합 3D Coordination Draft를 엽니다. 지하층·지상층·옥상과 상부 도면 관측을 3D/평면, 층 분리, 단면 및 실내 시점으로 검토할 수 있습니다. 표시 설정에서 도면 기반 형상과 미확정 상태를 확인합니다. 검증 완료 입체 부재는 0개이며, 이 모델은 설계 검증 완료나 BF 인증 결과가 아닙니다. 최신 revision 7의 출입문·벽 접합부 수정과 미완성 공간 경계는 [건물 전체 정밀 검토 결과](BIM_WHOLE_BUILDING_PRECISION_2026-10-12.md)를 참고하세요.

기본 제공 건축물은 최신 통합 3D 모델 하나입니다. 개선 전 v7 비교 모델·비교 버튼, 공간이음 교육관 예제와 이전 도면 기반 BIM은 공개 파일·자동 로딩에서 제거했습니다. 브라우저에 남아 있는 삭제 대상 모델의 저장본도 접속 시 정리하며 다시 불러오거나 저장할 수 없습니다. 별도로 불러온 사용자 모델은 유지합니다. 실제 도면 모델은 확인 전 상태이며 미확인 바닥이나 시설을 통과하는 경로를 만들지 않습니다.

GitHub Pages는 정적 홈페이지이므로 Python·ODA를 사용하는 DWG 업로드 및 IFC 생성은 로컬 앱에서 실행합니다. 공개 사이트의 이용자 모드는 JSON 불러오기, 브라우저 경로 계산 및 현재 모델의 Draft/Verified IFC 다운로드를 지원합니다. 현재 v10 / revision 7 모델은 부재 2,284개·입체 구성요소 4,761개이며 검증 기준을 충족한 입체는 0개입니다.

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
git diff --stat -- web/public/models
git add web/public/models/precision-rebuild.json web/public/models/precision-rebuild-verified.ifc web/public/models/precision-rebuild-coordination-draft.ifc
git commit -m "Update published coordination model"
git push
```

Pages 빌드에는 `VITE_VIEWER_ONLY=true`, `VITE_BASE_PATH=/energy-center-bim-bf/`를 적용합니다. 폴더 이름을 바꾸지 않는 한 로컬 작업 폴더의 한글 이름은 공개 주소에 영향을 주지 않습니다.

빌드 또는 배포 실패는 저장소 Actions 탭에서 해당 실행을 열어 확인합니다. 이전에 정상 배포된 사이트는 새 배포가 성공할 때 갱신됩니다.
