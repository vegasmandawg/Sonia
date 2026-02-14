<#
.SYNOPSIS
    Stamp v2.9.0 release identity -- manifest with SHA-256 hashes
#>

$ErrorActionPreference = "Continue"

$manifest = @{
    version = "2.9.0"
    contract = "v2.9.0"
    timestamp = (Get-Date -Format "o")
    files = @()
}

$trackFiles = @(
    "services\shared\version.py",
    "services\shared\events.py",
    "services\model-router\providers.py",
    "services\model-router\main.py",
    "services\eva-os\main.py",
    "services\eva-os\service_supervisor.py",
    "services\memory-engine\main.py",
    "services\memory-engine\hybrid_search.py",
    "services\memory-engine\core\provenance.py",
    "services\memory-engine\core\bm25.py",
    "services\api-gateway\main.py",
    "services\openclaw\main.py",
    "services\pipecat\main.py",
    ".gitignore",
    "requirements-frozen.txt",
    "tests\integration\test_v29_model_routing.py",
    "tests\integration\test_v29_eva_supervision.py",
    "tests\integration\test_v29_memory_hybrid.py",
    "scripts\promotion-gate-v29.ps1",
    "docs\STAGE9_SYSTEM_CLOSURE.md"
)

foreach ($rel in $trackFiles) {
    $full = Join-Path "S:\" $rel
    if (Test-Path $full) {
        $hash = (Get-FileHash $full -Algorithm SHA256).Hash
        $size = (Get-Item $full).Length
        $manifest.files += @{
            path = $rel
            sha256 = $hash
            size_bytes = $size
        }
    } else {
        $manifest.files += @{
            path = $rel
            sha256 = "MISSING"
            size_bytes = 0
        }
    }
}

$outDir = "S:\releases\v2.9.0"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

$manifest | ConvertTo-Json -Depth 4 | Set-Content "$outDir\release-manifest.json" -Encoding UTF8
Write-Output "Manifest written: $outDir\release-manifest.json"
Write-Output "Files tracked: $($manifest.files.Count)"
$missing = ($manifest.files | Where-Object { $_.sha256 -eq "MISSING" }).Count
Write-Output "Missing: $missing"
