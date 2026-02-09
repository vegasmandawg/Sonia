Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$checks = @(
  @{ Name = "S drive"; Test = { Test-Path "S:\" } },
  @{ Name = "config/runtime"; Test = { Test-Path "S:\config\runtime.yaml" } },
  @{ Name = "model routing"; Test = { Test-Path "S:\config\models\model-routing.yaml" } },
  @{ Name = "services config"; Test = { Test-Path "S:\config\services\services.yaml" } },
  @{ Name = "logs dir"; Test = { Test-Path "S:\logs" } },
  @{ Name = "state dir"; Test = { Test-Path "S:\state" } }
)

$failed = 0
foreach ($c in $checks) {
  $ok = & $c.Test
  if ($ok) {
    Write-Host "[OK]   $($c.Name)"
  } else {
    Write-Host "[FAIL] $($c.Name)"
    $failed++
  }
}

if ($failed -gt 0) {
  Write-Error "Doctor check failed: $failed issue(s)."
} else {
  Write-Host "Doctor check passed."
}
