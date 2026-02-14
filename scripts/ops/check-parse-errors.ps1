<#
.SYNOPSIS
    Check PS1 parse errors in specified files.
#>
$files = @(
    "S:\scripts\diagnostics\doctor-openclaw-upstream.ps1",
    "S:\scripts\diagnostics\memory-smoke-test.ps1",
    "S:\scripts\testing\install-miniconda-elevated.ps1",
    "S:\scripts\testing\install-python-direct.ps1",
    "S:\scripts\testing\phase3-execute-gate1.ps1",
    "S:\scripts\testing\verify-and-gate1.ps1",
    "S:\scripts\testing\verify-python-and-report.ps1",
    "S:\scripts\testing\wait-and-execute-gate1.ps1",
    "S:\scripts\testing\wait-for-python.ps1"
)

foreach ($f in $files) {
    Write-Host "--- $f ---"
    $content = Get-Content $f -Raw
    $errors = $null
    [System.Management.Automation.PSParser]::Tokenize($content, [ref]$errors) | Out-Null
    foreach ($err in $errors) {
        Write-Host "  Line $($err.Token.StartLine): $($err.Message)"
    }
    # Also show first 3 lines of file
    $lines = Get-Content $f -TotalCount 3
    foreach ($l in $lines) {
        Write-Host "  > $l"
    }
    Write-Host ""
}
