<#
.SYNOPSIS
    Verify all tracked .ps1 files parse without errors.
#>
Set-Location S:\
$files = git ls-files "*.ps1"
$bad = @()
foreach ($f in $files) {
    $resolved = Resolve-Path $f -ErrorAction SilentlyContinue
    if (-not $resolved) { continue }
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($resolved, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors -and $errors.Count -gt 0) {
        $bad += $f
        foreach ($e in $errors) {
            Write-Host "FAIL ${f}: $($e.Message)"
        }
    }
}
Write-Host ""
Write-Host "TOTAL_PS1=$($files.Count)"
Write-Host "TOTAL_BAD=$($bad.Count)"
if ($bad.Count -gt 0) {
    Write-Host ""
    Write-Host "Bad files:"
    foreach ($b in $bad) { Write-Host "  $b" }
    exit 1
} else {
    Write-Host "[OK] All tracked .ps1 files parse clean"
    exit 0
}
