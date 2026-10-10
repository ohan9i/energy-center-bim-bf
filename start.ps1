param([switch]$Install)
$ErrorActionPreference = 'Stop'
$workspacePath = $PSScriptRoot
$pythonPath = Join-Path $workspacePath '.venv-cad\Scripts\python.exe'
$frontendPath = Join-Path $workspacePath 'web'
$runtimePath = Join-Path $workspacePath '.runtime'
if (!(Test-Path -LiteralPath $pythonPath)) {
    Write-Error 'Python 환경이 없습니다. py -m venv .venv-cad 를 먼저 실행하세요.'
}
if ($Install) {
    & $pythonPath -m pip install -r (Join-Path $workspacePath 'requirements-bim.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python 의존성 설치 실패' }
    Push-Location $frontendPath
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw '프론트엔드 의존성 설치 실패' }
    } finally { Pop-Location }
}
$nodePath = (Get-Command node.exe).Source
$vitePath = Join-Path $frontendPath 'node_modules\vite\bin\vite.js'
if (!(Test-Path -LiteralPath $vitePath)) { throw '.\start.ps1 -Install 로 의존성을 설치하세요.' }
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$ownedProcesses = @()
try {
    $backendReady = $false
    try { $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2; $backendReady = ($health.mode -eq 'local-processing') } catch {}
    if (!$backendReady) {
        $process = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','bf_bim.app:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $workspacePath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimePath 'backend.log') -RedirectStandardError (Join-Path $runtimePath 'backend-error.log') -PassThru
        $ownedProcesses += @{id=$process.Id;started=$process.StartTime.ToUniversalTime().ToString('o');executable=$pythonPath}
    }
    $frontendReady = $false
    try { $page = Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2; $frontendReady = ($page.Content -match 'BIM &amp; BF|BIM & BF|공간이음') } catch {}
    if (!$frontendReady) {
        $process = Start-Process -FilePath $nodePath -ArgumentList @(('"'+$vitePath+'"'),'--host','127.0.0.1','--port','5173','--strictPort') -WorkingDirectory $frontendPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimePath 'frontend.log') -RedirectStandardError (Join-Path $runtimePath 'frontend-error.log') -PassThru
        $ownedProcesses += @{id=$process.Id;started=$process.StartTime.ToUniversalTime().ToString('o');executable=$nodePath}
    }
    if ($ownedProcesses.Count -gt 0) {
        $stateFile=Join-Path $runtimePath 'processes.json'
        $previous=@()
        if (Test-Path -LiteralPath $stateFile) { $previous=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json }
        ConvertTo-Json -InputObject @($previous + $ownedProcesses) | Set-Content -LiteralPath $stateFile -Encoding UTF8
    }
    $ready = $false
    for ($attempt=0; $attempt -lt 25; $attempt++) {
        Start-Sleep -Milliseconds 400
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
            $page = Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2
            if ($health.mode -eq 'local-processing' -and $page.StatusCode -eq 200) { $ready=$true; break }
        } catch {}
    }
    if (!$ready) { throw '.runtime 폴더의 오류 로그를 확인하세요. 8000/5173 포트가 사용 중일 수 있습니다.' }
    Write-Host '웹 애플리케이션: http://127.0.0.1:5173/'
    Write-Host 'API 문서: http://127.0.0.1:8000/docs'
    Write-Host '중지: .\stop.ps1'
} catch {
    foreach ($record in $ownedProcesses) { Stop-Process -Id $record.id -ErrorAction SilentlyContinue }
    throw
}
