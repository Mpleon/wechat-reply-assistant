param([switch]$Fresh, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$wxDir = $PSScriptRoot
$wxBase = 'http://127.0.0.1:8765'
$wxPython = $null
$wxRuntimeFile = Join-Path $wxDir 'local-runtime.json'
if (Test-Path -LiteralPath $wxRuntimeFile) { $wxLocalRuntime = Get-Content -LiteralPath $wxRuntimeFile -Raw -Encoding UTF8 | ConvertFrom-Json; $wxPython = $wxLocalRuntime.python_executable }
if (-not $wxPython) { $wxPython = (Get-Command python -ErrorAction Stop).Source }
[System.IO.File]::WriteAllText((Join-Path $wxDir 'control.json'), '{"enabled":false}', [System.Text.UTF8Encoding]::new($false))
function Get-ReplyHealth {
    try { return Invoke-RestMethod -Uri ($wxBase + '/api/health') -TimeoutSec 2 } catch { return $null }
}
$wxHealth = Get-ReplyHealth
if (-not $wxHealth) {
    $wxLegacy = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -and $_.CommandLine.Contains((Join-Path $wxDir 'worker.py')) })
    if ($wxLegacy.Count -gt 0) { throw 'Legacy worker is stopping. Wait for it to finish, then run this script again.' }
    $wxProcess = Start-Process -FilePath $wxPython -ArgumentList @('-X','utf8',('"' + (Join-Path $wxDir 'dashboard.py') + '"')) -WorkingDirectory $wxDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wxDir 'dashboard.stdout.log') -RedirectStandardError (Join-Path $wxDir 'dashboard.stderr.log') -PassThru
    $wxDeadline = (Get-Date).AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 300
        if ($wxProcess.HasExited) { throw 'Dashboard exited. See dashboard.stderr.log.' }
        $wxHealth = Get-ReplyHealth
    } while (-not $wxHealth -and (Get-Date) -lt $wxDeadline)
}
if (-not $wxHealth -or $wxHealth.service -ne 'wechat-reply-dashboard') { throw 'The dashboard did not become ready, or port 8765 belongs to another service.' }
$wxState = Invoke-RestMethod -Uri ($wxBase + '/api/state') -TimeoutSec 5
$wxHeaders = @{ 'X-CSRF-Token' = $wxState.csrf }
if ($Fresh) { Invoke-RestMethod -Uri ($wxBase + '/api/control') -Method Post -Headers $wxHeaders -ContentType 'application/json' -Body '{"enabled":false}' | Out-Null }
if ($Fresh -or -not $wxState.runtime.enabled) { Invoke-RestMethod -Uri ($wxBase + '/api/control') -Method Post -Headers $wxHeaders -ContentType 'application/json' -Body '{"enabled":true}' | Out-Null }
if (-not $NoBrowser) { Start-Process $wxBase }
Write-Output "Reply dashboard: $wxBase"
Write-Output 'Check the page for connection status, review drafts, and reply mode.'
