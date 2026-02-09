# Direct Python 3.11 installation via direct download (non-interactive)
$pythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$installerPath = "$env:TEMP\python-3.11.9-amd64.exe"
$logPath = "$env:TEMP\python-install.log"

Write-Host "Downloading Python 3.11.9..." -ForegroundColor Cyan
(New-Object System.Net.ServicePointManager)::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath -ErrorAction Stop

Write-Host "Running Python installer (will request admin elevation)..." -ForegroundColor Cyan
# Non-interactive install with default options + Add Python to PATH
Start-Process -FilePath $installerPath `
    -ArgumentList "/quiet PrependPath=1" `
    -NoNewWindow -Wait

Write-Host "Verifying installation..." -ForegroundColor Cyan
Start-Sleep -Seconds 2

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

py -3.11 --version
if ($LASTEXITCODE -eq 0) {
    Write-Host "Python 3.11 installed successfully!" -ForegroundColor Green
} else {
    Write-Host "Python installation verification failed" -ForegroundColor Red
    exit 1
}
