param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [switch]$NoLlama
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $parts = $line -split '=', 2
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($name) { [Environment]::SetEnvironmentVariable($name, $value, 'Process') }
    }
}

Import-DotEnv (Join-Path $ProjectRoot '.env')
$runDir = Join-Path $ProjectRoot '.run'
$logDir = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Force -Path $runDir, $logDir | Out-Null

function Wait-Http([string]$Uri, [int]$TimeoutSeconds = 120) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { return }
        } catch { }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Uri"
}

function Resolve-LlamaServer {
    if ($env:LLAMA_SERVER_BIN) { return (Resolve-Path -LiteralPath $env:LLAMA_SERVER_BIN).Path }
    $onPath = Get-Command llama-server.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $local = 'D:\llamacpp\llama-server.exe'
    if (Test-Path -LiteralPath $local) { return $local }
    throw 'llama-server.exe not found. Set LLAMA_SERVER_BIN in .env or add it to PATH.'
}

$llamaPid = $null
if (-not $NoLlama -and $env:VLM_MODE -eq 'managed') {
    $llamaBin = Resolve-LlamaServer
    $preset = if ([IO.Path]::IsPathRooted($env:LLAMA_MODELS_PRESET)) {
        $env:LLAMA_MODELS_PRESET
    } else {
        Join-Path $ProjectRoot $env:LLAMA_MODELS_PRESET
    }
    if (-not (Test-Path -LiteralPath $preset)) { throw "Model preset not found: $preset" }
    $llamaOut = Join-Path $logDir 'llama-server.out.log'
    $llamaErr = Join-Path $logDir 'llama-server.err.log'
    $llama = Start-Process -FilePath $llamaBin -WorkingDirectory (Split-Path $llamaBin) -WindowStyle Hidden -PassThru `
        -ArgumentList @('--host', $env:LLAMA_HOST, '--port', $env:LLAMA_PORT, '--models-preset', $preset) `
        -RedirectStandardOutput $llamaOut -RedirectStandardError $llamaErr
    $llamaPid = $llama.Id
    Wait-Http "http://$($env:LLAMA_HOST):$($env:LLAMA_PORT)/health"
    Write-Host "llama-server healthy at http://$($env:LLAMA_HOST):$($env:LLAMA_PORT) (PID $llamaPid)"
}

$python = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { 'python' }
$pythonArgs = @('-m', 'uvicorn', 'app.main:app', '--host', $env:MARKERSERVE_HOST, '--port', $env:MARKERSERVE_PORT)
if (-not $env:PYTHON_EXE -and (Get-Command uv -ErrorAction SilentlyContinue)) {
    $python = 'uv'
    $pythonArgs = @('run', '--project', $ProjectRoot, 'python') + $pythonArgs
}
$markerOut = Join-Path $logDir 'markerserve.out.log'
$markerErr = Join-Path $logDir 'markerserve.err.log'
try {
    $marker = Start-Process -FilePath $python -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru `
        -ArgumentList $pythonArgs `
        -RedirectStandardOutput $markerOut -RedirectStandardError $markerErr
    Wait-Http "http://$($env:MARKERSERVE_HOST):$($env:MARKERSERVE_PORT)/health/live"
    Wait-Http "http://$($env:MARKERSERVE_HOST):$($env:MARKERSERVE_PORT)/health/ready"
} catch {
    if ($marker -and (Get-Process -Id $marker.Id -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $marker.Id -Force
    }
    if ($llamaPid -and (Get-Process -Id $llamaPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $llamaPid -Force
    }
    throw
}

@{ llama_server_pid = $llamaPid; markerserve_pid = $marker.Id } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDir 'processes.json') -Encoding utf8
Write-Host "MarkerServe ready at http://$($env:MARKERSERVE_HOST):$($env:MARKERSERVE_PORT) (PID $($marker.Id))"
