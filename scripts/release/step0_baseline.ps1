$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

$outDir = "S:\reports\release"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Push-Location S:\

git rev-parse --abbrev-ref HEAD | Set-Content "$outDir\branch-$stamp.txt"
git rev-parse HEAD | Set-Content "$outDir\head-$stamp.txt"
git status --porcelain=v1 | Set-Content "$outDir\status-$stamp.txt"
git ls-files --others --exclude-standard | Set-Content "$outDir\untracked-$stamp.txt"

$untracked = Get-Content "$outDir\untracked-$stamp.txt"
$count = ($untracked | Measure-Object -Line).Lines
Write-Output "Baseline snapshot taken: $stamp"
Write-Output "Untracked file count: $count"

# Quarantine untracked files (non-destructive)
$quarantine = "S:\quarantine\sonia-untracked-$stamp"
New-Item -ItemType Directory -Force -Path $quarantine | Out-Null

# Skip files under scripts/release/ (our own release tooling)
$skipPrefixes = @("scripts/release/")

$moved = 0
$skipped = 0
foreach ($f in $untracked) {
    if ([string]::IsNullOrWhiteSpace($f)) { continue }
    # Strip leading/trailing quotes that git may add for special chars
    $clean = $f.Trim('"')

    # Skip our own release scripts
    $skip = $false
    foreach ($prefix in $skipPrefixes) {
        if ($clean.StartsWith($prefix)) { $skip = $true; break }
    }
    if ($skip) { $skipped++; continue }

    try {
        $src = Join-Path (Get-Location) $clean
        if (Test-Path -LiteralPath $src) {
            $dst = Join-Path $quarantine $clean
            $parent = Split-Path $dst -Parent
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
            Move-Item -LiteralPath $src -Destination $dst -Force
            $moved++
        }
    } catch {
        Write-Output "SKIP (path error): $clean"
        $skipped++
    }
}

Write-Output "Quarantined $moved files to: $quarantine"
Write-Output "Skipped: $skipped"

Pop-Location
