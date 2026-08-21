param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$BaseUrl = "",
    [ValidateSet("markdown", "json", "html")]
    [string]$OutputFormat = "markdown",
    [switch]$SkipReady
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $serviceHost = if ($env:MARKERSERVE_HOST) { $env:MARKERSERVE_HOST } else { "127.0.0.1" }
    $servicePort = if ($env:MARKERSERVE_PORT) { $env:MARKERSERVE_PORT } else { "8000" }
    $BaseUrl = "http://$serviceHost`:$servicePort"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

$sampleDir = Join-Path $ProjectRoot "samples"
if (-not (Test-Path -LiteralPath $sampleDir -PathType Container)) {
    throw "Sample directory not found: $sampleDir"
}

$expectedFiles = @(
    "blank.pdf",
    "images_en.pdf",
    "images_rotated_en.pdf",
    "simple_en.pdf",
    "simple_rotated_en.pdf"
)
$sampleFiles = @(Get-ChildItem -LiteralPath $sampleDir -Filter "*.pdf" -File | Sort-Object Name)
$missingFiles = @($expectedFiles | Where-Object { $_ -notin $sampleFiles.Name })
if ($missingFiles.Count -gt 0) {
    throw "Expected sample PDF(s) are missing: $($missingFiles -join ", ")"
}

function Get-ResponseText([System.Net.Http.HttpResponseMessage]$Response) {
    return $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
}

function Assert-HealthyResponse(
    [System.Net.Http.HttpResponseMessage]$Response,
    [string]$Endpoint
) {
    $body = Get-ResponseText $Response
    if (-not $Response.IsSuccessStatusCode) {
        throw "$Endpoint returned HTTP $([int]$Response.StatusCode): $body"
    }
    try {
        $payload = $body | ConvertFrom-Json
    } catch {
        throw "$Endpoint returned invalid JSON: $body"
    }
    if ($payload.status -notin @("ok", "ready")) {
        throw "$Endpoint returned unexpected status '$($payload.status)'"
    }
}

$client = [System.Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromMinutes(10)
$results = @()

try {
    $liveResponse = $client.GetAsync("$BaseUrl/health/live").GetAwaiter().GetResult()
    try {
        Assert-HealthyResponse $liveResponse "/health/live"
    } finally {
        $liveResponse.Dispose()
    }
    Write-Host "PASS /health/live"

    if (-not $SkipReady) {
        $readyResponse = $client.GetAsync("$BaseUrl/health/ready").GetAwaiter().GetResult()
        try {
            Assert-HealthyResponse $readyResponse "/health/ready"
        } finally {
            $readyResponse.Dispose()
        }
        Write-Host "PASS /health/ready"
    }

    foreach ($sampleFile in $sampleFiles) {
        $fileStream = $null
        $multipart = $null
        $response = $null
        try {
            $multipart = [System.Net.Http.MultipartFormDataContent]::new()
            $fileStream = [System.IO.File]::OpenRead($sampleFile.FullName)
            $fileContent = [System.Net.Http.StreamContent]::new($fileStream)
            $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/pdf")
            $multipart.Add($fileContent, "file", $sampleFile.Name)
            $multipart.Add([System.Net.Http.StringContent]::new($OutputFormat), "output_format")

            $response = $client.PostAsync("$BaseUrl/v1/convert", $multipart).GetAwaiter().GetResult()
            $body = Get-ResponseText $response
            if (-not $response.IsSuccessStatusCode) {
                throw "HTTP $([int]$response.StatusCode): $body"
            }

            try {
                $responseFormat = [string]$response.Headers.GetValues("X-MarkerServe-Output-Format")[0]
            } catch {
                throw "missing X-MarkerServe-Output-Format response header"
            }
            if ($responseFormat -ne $OutputFormat) {
                throw "expected output format '$OutputFormat', got '$responseFormat'"
            }

            $isBlankSample = $sampleFile.BaseName -eq "blank"
            if (-not $isBlankSample -and [string]::IsNullOrWhiteSpace($body)) {
                throw "non-blank sample returned an empty response"
            }
            if ($OutputFormat -eq "json") {
                try {
                    $null = $body | ConvertFrom-Json
                } catch {
                    throw "JSON output could not be parsed"
                }
            }

            $results += [pscustomobject]@{
                Name = $sampleFile.Name
                Status = "PASS"
                Bytes = $body.Length
            }
            Write-Host ("PASS {0} ({1} response characters)" -f $sampleFile.Name, $body.Length)
        } catch {
            $results += [pscustomobject]@{
                Name = $sampleFile.Name
                Status = "FAIL"
                Bytes = 0
            }
            Write-Host ("FAIL {0}: {1}" -f $sampleFile.Name, $_.Exception.Message) -ForegroundColor Red
        } finally {
            if ($response) { $response.Dispose() }
            if ($multipart) { $multipart.Dispose() }
            if ($fileStream) { $fileStream.Dispose() }
        }
    }
} finally {
    $client.Dispose()
}

$failures = @($results | Where-Object Status -eq "FAIL")
Write-Host ""
Write-Host ("Sample test summary: {0} passed, {1} failed" -f ($results.Count - $failures.Count), $failures.Count)
if ($failures.Count -gt 0) {
    exit 1
}
