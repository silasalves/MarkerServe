param([string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")))

$ErrorActionPreference = "Stop"
$pidFile = Join-Path $ProjectRoot '.run\processes.json'
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host 'No MarkerServe process state found.'
    exit 0
}

$state = Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json
foreach ($name in @('markerserve_pid', 'llama_server_pid')) {
    $processId = $state.$name
    if ($processId) {
        $process = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $process.Id -Force
            Write-Host "Stopped $name (PID $processId)."
        }
    }
}
Remove-Item -LiteralPath $pidFile -Force
