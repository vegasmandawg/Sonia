@echo off
setlocal EnableExtensions

set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "C:\Program Files\PowerShell\7\pwsh.exe" set "PS=C:\Program Files\PowerShell\7\pwsh.exe"

if not exist "%PS%" (
  echo [FATAL] PowerShell not found.
  exit /b 9009
)

cd /d S:\scripts\testing || exit /b 2

set "PYTHONHASHSEED=0"
set "SONIA_TEST_MODE=deterministic"

echo === PRECHECK ===
echo PowerShell: %PS%
echo PYTHONHASHSEED: %PYTHONHASHSEED%
echo SONIA_TEST_MODE: %SONIA_TEST_MODE%

echo === PREFLIGHT ===
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "S:\scripts\testing\phase3-preflight.ps1"
if errorlevel 1 (
  echo [FAIL] preflight - services not responding
  exit /b 10
)

echo === GATE 1 EXECUTION ===
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "S:\scripts\testing\phase3-go-no-go.ps1" -CycleCount 10 -HealthCheckDurationMinutes 30 -StartupTimeoutSeconds 90
if errorlevel 1 (
  echo [FAIL] gate1
  exit /b 11
)

echo === GATE 1 JSON VALIDATION ===
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command ^
"$s=Get-ChildItem 'S:\artifacts\phase3\go-no-go-summary-*.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if(-not $s){throw 'No summary json'}; $j=Get-Content $s.FullName -Raw|ConvertFrom-Json; if($j.Gate1.Cycles -ne 10){throw 'Gate1 cycles != 10'}; if(-not $j.Gate1.ZeroPIDs){throw 'ZeroPIDs false'}; if($j.Gate2.ExpectedChecks -ne 2160 -or $j.Gate2.TotalChecks -ne 2160){throw 'Health-check math mismatch'}; if($j.Gate2.Failures -ne 0){throw 'Health-check failures > 0'}; if(($j.Gate2B.Run1.Passed -ne $j.Gate2B.Run2.Passed) -or ($j.Gate2B.Run1.Failed -ne $j.Gate2B.Run2.Failed) -or (-not $j.Gate2B.Deterministic)){throw 'Determinism failed'}; Write-Host 'PASS: Gate 1 valid JSON evidence.'"
if errorlevel 1 exit /b 12

echo === HASH BUNDLE ===
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command ^
"$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'; $b='S:\artifacts\phase3\gate-results\gate1-'+$stamp; New-Item -ItemType Directory -Path $b -Force|Out-Null; $s=Get-ChildItem 'S:\artifacts\phase3\go-no-go-summary-*.json'|Sort-Object LastWriteTime -Descending|Select-Object -First 1; Copy-Item $s.FullName $b -Force; Copy-Item 'S:\artifacts\phase3\go-no-go-*.log' $b -Force -ErrorAction SilentlyContinue; Get-ChildItem $b -File|Get-FileHash -Algorithm SHA256|Sort-Object Path|Export-Csv ($b+'\SHA256SUMS.csv') -NoTypeInformation; Write-Host ('BUNDLE: '+$b)"
if errorlevel 1 exit /b 13

echo [SUCCESS] Gate 1 complete and hashed.
exit /b 0
