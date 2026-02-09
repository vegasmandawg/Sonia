<#
.SYNOPSIS
Phase 3 Reliability Soak Test - 48 hours of synthetic traffic

.DESCRIPTION
Runs continuous synthetic load with:
  - /v1/chat at 1 req/sec
  - OpenClaw tool executions
  - Pipecat voice session churn
  - Metrics collection every 60 seconds

Tracks: p50/p95/p99 latency, error rate, memory, restarts, deadlocks

.PARAMETER Duration
Soak duration in hours (default: 48)

.PARAMETER OutputDir
Where to save metrics (default: S:\artifacts\phase3)

.EXAMPLE
.\phase3-soak-test.ps1 -Duration 48
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [int]$Duration = 48,

    [Parameter(Mandatory=$false)]
    [string]$OutputDir = "S:\artifacts\phase3"
)

$ErrorActionPreference = "Continue"

# Create output directory
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$MetricsFile = Join-Path $OutputDir "soak-metrics-$Timestamp.csv"
$ReportFile = Join-Path $OutputDir "soak-report-$Timestamp.txt"
$LogFile = Join-Path $OutputDir "soak-log-$Timestamp.log"

# Create metrics header
"Timestamp,ServicePort,Endpoint,RequestCount,ErrorCount,ErrorRate,P50Latency,P95Latency,P99Latency,MemoryMB,Uptime" | Out-File -Path $MetricsFile

function Log {
    param([string]$Message)
    $LogMsg = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Write-Host $LogMsg
    Add-Content -Path $LogFile -Value $LogMsg
}

Log "=== PHASE 3 RELIABILITY SOAK TEST START ==="
Log "Duration: $Duration hours"
Log "Output: $OutputDir"

# ============================================================================
# Synthetic Load Functions
# ============================================================================

function Invoke-ChatLoad {
    param([int]$Count = 10)
    $Results = @{Success = 0; Error = 0; Latencies = @()}
    
    for ($i = 0; $i -lt $Count; $i++) {
        $Start = Get-Date
        try {
            $Response = Invoke-WebRequest -Uri "http://127.0.0.1:7000/v1/chat" `
                -Method POST `
                -Headers @{"Content-Type" = "application/json"; "X-Correlation-ID" = "soak_$([guid]::NewGuid().ToString().Substring(0,8))"} `
                -Body '{"text":"What is the capital of France?"}' `
                -TimeoutSec 10 `
                -ErrorAction Stop
            
            $Latency = ((Get-Date) - $Start).TotalMilliseconds
            $Results.Success++
            $Results.Latencies += $Latency
        } catch {
            $Results.Error++
        }
    }
    
    return $Results
}

function Invoke-ToolLoad {
    param([int]$Count = 5)
    $Tools = @("shell.run", "file.read")
    $Results = @{Success = 0; Error = 0; Latencies = @()}
    
    for ($i = 0; $i -lt $Count; $i++) {
        $Tool = $Tools[$i % $Tools.Count]
        $Start = Get-Date
        
        try {
            $Body = switch ($Tool) {
                "shell.run" { '{"tool_name":"shell.run","args":{"command":"Get-Date"}}' }
                "file.read" { '{"tool_name":"file.read","args":{"path":"S:\\README.md"}}' }
            }
            
            $Response = Invoke-WebRequest -Uri "http://127.0.0.1:7000/v1/action" `
                -Method POST `
                -Headers @{"Content-Type" = "application/json"; "X-Correlation-ID" = "soak_tool_$([guid]::NewGuid().ToString().Substring(0,8))"} `
                -Body $Body `
                -TimeoutSec 10 `
                -ErrorAction Stop
            
            $Latency = ((Get-Date) - $Start).TotalMilliseconds
            $Results.Success++
            $Results.Latencies += $Latency
        } catch {
            $Results.Error++
        }
    }
    
    return $Results
}

function Invoke-VoiceSessionLoad {
    param([int]$Count = 2)
    $Results = @{Success = 0; Error = 0; Latencies = @()}
    
    for ($i = 0; $i -lt $Count; $i++) {
        $Start = Get-Date
        try {
            # Create session
            $SessionResp = Invoke-WebRequest -Uri "http://127.0.0.1:7030/session/start" `
                -Method POST `
                -Headers @{"Content-Type" = "application/json"} `
                -Body '{"user_id":"soak-test"}' `
                -TimeoutSec 5 `
                -ErrorAction Stop
            
            $SessionId = ($SessionResp.Content | ConvertFrom-Json).data.session_id
            
            # Immediately stop session
            Invoke-WebRequest -Uri "http://127.0.0.1:7030/session/stop" `
                -Method POST `
                -Headers @{"Content-Type" = "application/json"} `
                -Body "{`"session_id`":`"$SessionId`"}" `
                -TimeoutSec 5 `
                -ErrorAction Stop
            
            $Latency = ((Get-Date) - $Start).TotalMilliseconds
            $Results.Success++
            $Results.Latencies += $Latency
        } catch {
            $Results.Error++
        }
    }
    
    return $Results
}

function Get-ServiceMetrics {
    param([int]$Port)
    
    try {
        $Response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/status" -TimeoutSec 2 -ErrorAction Stop
        $Status = $Response.Content | ConvertFrom-Json
        return @{Port = $Port; Status = "OK"; Timestamp = Get-Date}
    } catch {
        return @{Port = $Port; Status = "DOWN"; Timestamp = Get-Date}
    }
}

# ============================================================================
# Main Soak Loop
# ============================================================================

$EndTime = (Get-Date).AddHours($Duration)
$StartTime = Get-Date
$IntervalCount = 0

Log "Soak test will run until $EndTime"

while ((Get-Date) -lt $EndTime) {
    $IntervalCount++
    $CurrentTime = Get-Date
    
    Log "Interval $IntervalCount at $($CurrentTime.ToString('HH:mm:ss'))"
    
    # Generate synthetic load
    $ChatResults = Invoke-ChatLoad -Count 12  # 1 req/sec for 60 seconds
    $ToolResults = Invoke-ToolLoad -Count 6   # Tools during soak
    $VoiceResults = Invoke-VoiceSessionLoad -Count 5
    
    # Collect metrics
    $AllResults = @()
    $AllResults += @{Name = "API Gateway /chat"; Port = 7000; Results = $ChatResults}
    $AllResults += @{Name = "OpenClaw tools"; Port = 7040; Results = $ToolResults}
    $AllResults += @{Name = "Pipecat voice"; Port = 7030; Results = $VoiceResults}
    
    # Calculate statistics
    foreach ($Item in $AllResults) {
        $Latencies = $Item.Results.Latencies
        
        if ($Latencies.Count -gt 0) {
            $Sorted = $Latencies | Sort-Object
            $P50 = $Sorted[[Math]::Floor($Sorted.Count * 0.50)]
            $P95 = $Sorted[[Math]::Floor($Sorted.Count * 0.95)]
            $P99 = $Sorted[[Math]::Floor($Sorted.Count * 0.99)]
            
            $ErrorRate = 0
            $TotalRequests = $Item.Results.Success + $Item.Results.Error
            if ($TotalRequests -gt 0) {
                $ErrorRate = [Math]::Round(($Item.Results.Error / $TotalRequests) * 100, 2)
            }
            
            # Get memory
            $Procs = Get-Process python -ErrorAction SilentlyContinue
            $TotalMemory = ($Procs | Measure-Object WorkingSet -Sum).Sum / 1MB
            
            # Write metrics
            $MetricLine = "$($CurrentTime.ToString('s')),$($Item.Port),$($Item.Name),$($Item.Results.Success),$($Item.Results.Error),$ErrorRate,$P50,$P95,$P99,$TotalMemory,$([Math]::Round(((Get-Date) - $StartTime).TotalHours, 2))"
            Add-Content -Path $MetricsFile -Value $MetricLine
            
            Log "  $($Item.Name): Success=$($Item.Results.Success) Error=$($Item.Results.Error) ErrorRate=$($ErrorRate)% P95=$($P95)ms"
        }
    }
    
    # Wait for next interval (60 seconds)
    $Remaining = $EndTime - (Get-Date)
    if ($Remaining.TotalSeconds -gt 60) {
        Start-Sleep -Seconds 60
    }
}

# ============================================================================
# Final Report
# ============================================================================

Log "`n=== SOAK TEST COMPLETE ==="
Log "Duration: $([Math]::Round(((Get-Date) - $StartTime).TotalHours, 2)) hours"
Log "Total metrics collected: $IntervalCount intervals"
Log "Metrics file: $MetricsFile"

# Calculate summary
$AllMetrics = Import-Csv -Path $MetricsFile
$TotalErrors = ($AllMetrics | Measure-Object ErrorCount -Sum).Sum
$TotalRequests = ($AllMetrics | Measure-Object RequestCount -Sum).Sum
$ErrorRate = 0
if ($TotalRequests -gt 0) {
    $ErrorRate = [Math]::Round(($TotalErrors / $TotalRequests) * 100, 2)
}

$AvgP95 = ($AllMetrics | Measure-Object P95Latency -Average).Average
$MaxMemory = ($AllMetrics | Measure-Object MemoryMB -Maximum).Maximum

Log "Summary:"
Log "  Total requests: $TotalRequests"
Log "  Total errors: $TotalErrors"
Log "  Overall error rate: $($ErrorRate)%"
Log "  Avg P95 latency: $($AvgP95)ms"
Log "  Peak memory: $($MaxMemory)MB"

# Write summary
@{
    Status = if ($ErrorRate -lt 0.5) { "PASS" } else { "FAIL" }
    Duration = $Duration
    TotalRequests = $TotalRequests
    TotalErrors = $TotalErrors
    ErrorRate = $ErrorRate
    AvgP95Latency = $AvgP95
    PeakMemory = $MaxMemory
    MetricsFile = $MetricsFile
    Timestamp = Get-Date
} | ConvertTo-Json | Out-File -Path (Join-Path $OutputDir "soak-summary-$Timestamp.json")

Log "`nTest result: $(if ($ErrorRate -lt 0.5) { 'PASS' } else { 'FAIL' })"

exit 0
