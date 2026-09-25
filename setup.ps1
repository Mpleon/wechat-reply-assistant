$ErrorActionPreference = 'Stop'
$wxRoot = $PSScriptRoot
$wxPython = (Get-Command python -ErrorAction Stop).Source
& $wxPython -c "import sys; assert sys.version_info >= (3,12), 'Python 3.12+ required'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }
& $wxPython -m pip install --target (Join-Path $wxRoot '.deps') -r (Join-Path $wxRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$wxConfig = Join-Path $wxRoot 'local-runtime.json'
if (-not (Test-Path -LiteralPath $wxConfig)) {
    $wxExample = Get-Content -LiteralPath (Join-Path $wxRoot 'local-runtime.example.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $wxExample.python_executable = $wxPython
    $wxExample.deps_dir = Join-Path $wxRoot '.deps'
    [System.IO.File]::WriteAllText($wxConfig, ($wxExample | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
}
if (-not (Test-Path -LiteralPath (Join-Path $wxRoot 'stickers.json'))) { [System.IO.File]::WriteAllText((Join-Path $wxRoot 'stickers.json'), '[]', [System.Text.UTF8Encoding]::new($false)) }
Write-Output 'Dependencies installed. Configure local-runtime.json and the target contact before starting.'
