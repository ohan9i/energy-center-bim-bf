$ErrorActionPreference='Stop'
$stateFile=Join-Path $PSScriptRoot '.runtime\processes.json'
if (!(Test-Path -LiteralPath $stateFile)) { Write-Host '이 실행 스크립트가 시작한 서버가 없습니다.'; exit }
$records=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
foreach ($record in $records) {
    $process=Get-Process -Id $record.id -ErrorAction SilentlyContinue
    if ($null -eq $process) { continue }
    if ($process.StartTime.ToUniversalTime().ToString('o') -eq $record.started -and $process.Path -eq $record.executable) {
        # Windows venv python.exe can forward execution to a child interpreter.
        # Capture and stop only descendants of this verified owned process.
        $pending = @([int]$process.Id)
        $descendants = @()
        $inventory = @(Get-CimInstance Win32_Process)
        while ($pending.Count -gt 0) {
            $next = @()
            foreach ($parentId in $pending) {
                $children = @($inventory | Where-Object { $_.ParentProcessId -eq $parentId -and $_.CreationDate -ge $process.StartTime })
                foreach ($child in $children) { $descendants += [int]$child.ProcessId; $next += [int]$child.ProcessId }
            }
            $pending = $next
        }
        [array]::Reverse($descendants)
        foreach ($childId in $descendants) { Stop-Process -Id $childId -ErrorAction SilentlyContinue }
        Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        Write-Host "중지한 프로젝트 서버 PID: $($process.Id)"
    }
}
'[]' | Set-Content -LiteralPath $stateFile -Encoding UTF8
