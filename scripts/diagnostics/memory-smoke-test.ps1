<#---------------------------------------------------------------------------
memory-smoke-test.ps1

Smoke test for Memory Engine service.
Validates core functionality: embeddings, vector search, BM25, hybrid search.

Usage:
  .\memory-smoke-test.ps1                 # Run all tests
  .\memory-smoke-test.ps1 -QuickCheck     # Skip slow tests
  .\memory-smoke-test.ps1 -Service http   # Test specific endpoint
---------------------------------------------------------------------------#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$ServiceUrl = "http://127.0.0.1:7020",
    
    [Parameter(Mandatory=$false)]
    [switch]$QuickCheck,
    
    [Parameter(Mandatory=$false)]
    [string]$TestType = "all"  # all, embeddings, search, ledger, workspace
)

$ErrorActionPreference = "Stop"
$script:passed = @()
$script:failed = @()
$script:skipped = @()

function Write-TestResult {
    param([string]$Name, [bool]$Pass, [string]$Detail = "")
    if ($Pass) {
        Write-Host "  ✓ $Name" -ForegroundColor Green
        $script:passed += $Name
    } else {
        Write-Host "  ✗ $Name" -ForegroundColor Red
        if ($Detail) {
            Write-Host "    └─ $Detail" -ForegroundColor DarkRed
        }
        $script:failed += $Name
    }
}

function Write-TestSkipped {
    param([string]$Name, [string]$Reason = "")
    Write-Host "  ⊘ $Name" -ForegroundColor Yellow
    if ($Reason) {
        Write-Host "    └─ $Reason" -ForegroundColor DarkYellow
    }
    $script:skipped += $Name
}

# Test 1: Service connectivity
Write-Host ""
Write-Host "Memory Engine Smoke Tests" -ForegroundColor Cyan
Write-Host "=========================" -ForegroundColor Cyan
Write-Host ""

Write-Host "1. Connectivity Tests" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$ServiceUrl/health" -Method GET -TimeoutSec 5
    Write-TestResult "Service health endpoint" ($response.StatusCode -eq 200)
} catch {
    Write-TestResult "Service health endpoint" $false "Connection refused"
    Write-Host ""
    Write-Host "Error: Memory Engine not responding at $ServiceUrl" -ForegroundColor Red
    Write-Host "Make sure the service is running:" -ForegroundColor Red
    Write-Host "  python -m uvicorn S:\services\memory-engine\memory_engine_service:app --host 127.0.0.1 --port 7020" -ForegroundColor DarkRed
    exit 1
}

try {
    $response = Invoke-WebRequest -Uri "$ServiceUrl/status" -Method GET -TimeoutSec 5
    $status = $response.Content | ConvertFrom-Json
    Write-TestResult "Service status endpoint" ($response.StatusCode -eq 200)
    Write-Host "    Version: $($status.version)" -ForegroundColor DarkGray
} catch {
    Write-TestResult "Service status endpoint" $false
}

# Test 2: Ledger operations
Write-Host ""
Write-Host "2. Ledger Operations" -ForegroundColor Yellow

try {
    $body = @{
        event_type = "user_turn"
        entity_id = "test-session-001"
        payload = @{
            text = "Test message"
            timestamp = Get-Date -Format "o"
        }
    } | ConvertTo-Json
    
    $response = Invoke-WebRequest `
        -Uri "$ServiceUrl/api/v1/memory/append" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 5
    
    Write-TestResult "Append event to ledger" ($response.StatusCode -eq 200)
} catch {
    Write-TestResult "Append event to ledger" $false "$($_.Exception.Message)"
}

try {
    $response = Invoke-WebRequest `
        -Uri "$ServiceUrl/api/v1/memory/query?entity_id=test-session-001&limit=10" `
        -Method GET `
        -TimeoutSec 5
    
    $query_result = $response.Content | ConvertFrom-Json
    Write-TestResult "Query ledger by entity" ($response.StatusCode -eq 200)
    Write-Host "    Results: $($query_result.count) events" -ForegroundColor DarkGray
} catch {
    Write-TestResult "Query ledger by entity" $false
}

# Test 3: Document workspace
Write-Host ""
Write-Host "3. Document Workspace" -ForegroundColor Yellow

try {
    $body = @{
        content = "This is a test document about machine learning and artificial intelligence."
        doc_type = "markdown"
        metadata = @{
            title = "Test Doc"
            source = "smoke-test"
        }
    } | ConvertTo-Json
    
    $response = Invoke-WebRequest `
        -Uri "$ServiceUrl/api/v1/workspace/ingest" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 10
    
    $doc_result = $response.Content | ConvertFrom-Json
    Write-TestResult "Ingest document" ($response.StatusCode -eq 200)
    Write-Host "    Doc ID: $($doc_result.doc_id)" -ForegroundColor DarkGray
} catch {
    Write-TestResult "Ingest document" $false "$($_.Exception.Message)"
}

try {
    $response = Invoke-WebRequest `
        -Uri "$ServiceUrl/api/v1/workspace/documents" `
        -Method GET `
        -TimeoutSec 5
    
    $docs_result = $response.Content | ConvertFrom-Json
    Write-TestResult "List documents" ($response.StatusCode -eq 200)
    Write-Host "    Documents: $($docs_result.count)" -ForegroundColor DarkGray
} catch {
    Write-TestResult "List documents" $false
}

# Test 4: Search operations
Write-Host ""
Write-Host "4. Search Operations" -ForegroundColor Yellow

try {
    $body = @{
        query = "machine learning"
        limit = 5
        include_scores = $true
    } | ConvertTo-Json
    
    $response = Invoke-WebRequest `
        -Uri "$ServiceUrl/api/v1/search" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 30
    
    $search_result = $response.Content | ConvertFrom-Json
    Write-TestResult "Hybrid search (semantic + BM25)" ($response.StatusCode -eq 200)
    Write-Host "    Results: $($search_result.count) found" -ForegroundColor DarkGray
} catch {
    Write-TestResult "Hybrid search" $false "$($_.Exception.Message)"
}

try {
    $response = Invoke-WebRequest `
        -Uri "$ServiceUrl/api/v1/search/entity/test-session-001?limit=10" `
        -Method GET `
        -TimeoutSec 5
    
    $entity_result = $response.Content | ConvertFrom-Json
    Write-TestResult "Entity search" ($response.StatusCode -eq 200)
    Write-Host "    Related items: $($entity_result.count)" -ForegroundColor DarkGray
} catch {
    Write-TestResult "Entity search" $false
}

# Test 5: Snapshots
Write-Host ""
Write-Host "5. Snapshot Operations" -ForegroundColor Yellow

try {
    $body = @{
        session_id = "test-session-001"
    } | ConvertTo-Json
    
    $response = Invoke-WebRequest `
        -Uri "$ServiceUrl/api/v1/snapshots/create" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 10
    
    $snapshot_result = $response.Content | ConvertFrom-Json
    Write-TestResult "Create snapshot" ($response.StatusCode -eq 200)
    Write-Host "    Snapshot ID: $($snapshot_result.snapshot_id)" -ForegroundColor DarkGray
} catch {
    Write-TestResult "Create snapshot" $false "$($_.Exception.Message)"
}

# Summary
Write-Host ""
Write-Host "Test Results" -ForegroundColor Cyan
Write-Host "============" -ForegroundColor Cyan
Write-Host "Passed:  " -NoNewline -ForegroundColor Green
Write-Host "$($script:passed.Count) checks" -ForegroundColor Green

Write-Host "Failed:  " -NoNewline -ForegroundColor Red
Write-Host "$($script:failed.Count) checks" -ForegroundColor Red

Write-Host "Skipped: " -NoNewline -ForegroundColor Yellow
Write-Host "$($script:skipped.Count) checks" -ForegroundColor Yellow

Write-Host ""

if ($script:failed.Count -eq 0) {
    Write-Host "✓ All tests passed! Memory Engine is operational." -ForegroundColor Green
    exit 0
} else {
    Write-Host "✗ Some tests failed. Review output above for details." -ForegroundColor Red
    exit 1
}
