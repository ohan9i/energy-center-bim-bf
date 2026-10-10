# GitHub Pages 운영 안내

홈페이지: https://ohan9i.github.io/energy-center-bim-bf/

소스 저장소: https://github.com/ohan9i/energy-center-bim-bf

## 홈페이지에서 할 수 있는 일

설치 없이 실제 DWG 기반 지상 1·2층 모델을 3D/평면으로 보고 층을 전환할 수 있습니다. 건축물 선택에서 교육용 2층 예제로 바꾸면 보행자/휠체어 이용자의 계단·승강기 경로를 비교할 수 있습니다. 실제 도면 모델은 확인 전 상태이며 미확인 바닥이나 시설을 통과하는 경로를 만들지 않습니다.

GitHub Pages는 정적 홈페이지이므로 Python·ODA를 사용하는 DWG 업로드 및 IFC 생성은 로컬 앱에서 실행합니다. 공개 사이트의 이용자 모드는 JSON 불러오기와 브라우저 경로 계산을 지원합니다.

## 공개 범위

- 소스 코드, 사용자 정의 이동 조건, 교육용 예제.
- `web/public/models/project.json`: 공개 요청에 따라 선정한 실제 1·2층의 형상·실명·검토 상태와 제한된 CAD 근거.
- 원본 DWG, `cad_output/`의 원시 분석 및 IFC, 로컬 절대 경로, 가상환경, ODA 실행 파일, 실행 로그는 제외.

전체 출처를 가진 로컬 모델과 공개 모델의 형상·검토 상태는 같습니다. 공개 모델의 `provenance`는 게시용 요약이며 누락된 정보는 통과 가능으로 바꾸지 않습니다.

## 수정과 재배포

`main`에 `web/` 또는 배포 설정 변경을 push하면 GitHub Actions가 테스트·빌드·하위 경로 HTTP 검사를 거쳐 Pages에 배포합니다. Actions의 **Build and deploy static navigation → Run workflow**에서도 수동 실행할 수 있습니다.

실제 모델 변경은 다음 순서로 반영합니다.

```powershell
.\.venv-cad\Scripts\python.exe -m bf_bim.publish_model
git diff -- web/public/models/project.json
git add web/public/models/project.json
git commit -m "Update published project model"
git push
```

Pages 빌드에는 `VITE_VIEWER_ONLY=true`, `VITE_BASE_PATH=/energy-center-bim-bf/`를 적용합니다. 폴더 이름을 바꾸지 않는 한 로컬 작업 폴더의 한글 이름은 공개 주소에 영향을 주지 않습니다.

빌드 또는 배포 실패는 저장소 Actions 탭에서 해당 실행을 열어 확인합니다. 이전에 정상 배포된 사이트는 새 배포가 성공할 때 갱신됩니다.
