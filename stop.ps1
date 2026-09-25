$ErrorActionPreference = 'Stop'
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'control.json'), '{"enabled":false}', [System.Text.UTF8Encoding]::new($false))
try {
    $wxState = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/state' -TimeoutSec 5
    Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/control' -Method Post -Headers @{ 'X-CSRF-Token' = $wxState.csrf } -ContentType 'application/json' -Body '{"enabled":false,"all":true}' | Out-Null
    Write-Output 'Auto processing paused. The dashboard remains available for review.'
} catch {
    Write-Output 'Legacy auto-reply disabled. Dashboard is not reachable.'
}
