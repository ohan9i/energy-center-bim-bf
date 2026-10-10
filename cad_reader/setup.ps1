param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv-cad\Scripts\python.exe'
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $Python -m venv .venv-cad
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 이상으로 가상환경을 생성하세요.' }
    }
    & $venvPython -m pip install -r cad_reader\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python 의존성 설치에 실패했습니다.' }
    & $venvPython -m cad_reader doctor
    if ($LASTEXITCODE -eq 2) {
        Write-Host 'Python 구성 완료. ODA 설치 방법은 cad_reader\README.md를 확인하세요.'
    } elseif ($LASTEXITCODE -ne 0) {
        throw '환경 확인에 실패했습니다.'
    }
} finally {
    Pop-Location
}
