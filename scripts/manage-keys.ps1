<#
.SYNOPSIS
    Manage SONIA API keys for user identity.

.DESCRIPTION
    Creates, lists, rotates, and revokes API keys via the memory-engine API.

.PARAMETER Create
    Create a new user + API key.

.PARAMETER List
    List all users.

.PARAMETER Rotate
    Rotate the API key for a user.

.PARAMETER Revoke
    Soft-delete a user (revoke access).

.PARAMETER DisplayName
    Display name for new user (required with -Create).

.PARAMETER UserId
    User ID (required with -Rotate or -Revoke).

.PARAMETER MemoryUrl
    Memory engine base URL (default: http://127.0.0.1:7020).
#>
param(
    [switch]$Create,
    [switch]$List,
    [switch]$Rotate,
    [switch]$Revoke,
    [string]$DisplayName = "",
    [string]$UserId = "",
    [string]$MemoryUrl = "http://127.0.0.1:7020"
)

$ErrorActionPreference = "Stop"

function Invoke-MemoryApi {
    param([string]$Method, [string]$Path, [hashtable]$Body = $null)
    $url = "$MemoryUrl$Path"
    $params = @{ Uri = $url; Method = $Method; ContentType = "application/json"; TimeoutSec = 10 }
    if ($Body) {
        $params["Body"] = ($Body | ConvertTo-Json -Depth 5)
    }
    try {
        $resp = Invoke-RestMethod @params
        return $resp
    } catch {
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.Exception.Response) {
            $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
            $detail = $reader.ReadToEnd()
            Write-Host "  Detail: $detail" -ForegroundColor Yellow
        }
        exit 1
    }
}

if ($Create) {
    if (-not $DisplayName) {
        Write-Host "ERROR: -DisplayName is required with -Create" -ForegroundColor Red
        exit 1
    }
    Write-Host "Creating user: $DisplayName" -ForegroundColor Cyan
    $resp = Invoke-MemoryApi -Method POST -Path "/v1/users" -Body @{ display_name = $DisplayName }
    Write-Host ""
    Write-Host "  User ID:      $($resp.user_id)" -ForegroundColor Green
    Write-Host "  Display Name: $($resp.display_name)" -ForegroundColor Green
    Write-Host "  API Key:      $($resp.api_key)" -ForegroundColor Yellow
    Write-Host "  Created At:   $($resp.created_at)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  WARNING: Store the API key securely. It will not be shown again." -ForegroundColor Red
}
elseif ($List) {
    Write-Host "Listing users..." -ForegroundColor Cyan
    $resp = Invoke-MemoryApi -Method GET -Path "/v1/users"
    if ($resp.count -eq 0) {
        Write-Host "  No users found." -ForegroundColor Yellow
    } else {
        foreach ($u in $resp.users) {
            $statusColor = if ($u.status -eq "active") { "Green" } else { "Red" }
            Write-Host "  $($u.user_id)  $($u.display_name)  [$($u.status)]  $($u.created_at)" -ForegroundColor $statusColor
        }
        Write-Host ""
        Write-Host "  Total: $($resp.count)" -ForegroundColor Cyan
    }
}
elseif ($Rotate) {
    if (-not $UserId) {
        Write-Host "ERROR: -UserId is required with -Rotate" -ForegroundColor Red
        exit 1
    }
    Write-Host "Rotating key for: $UserId" -ForegroundColor Cyan
    $resp = Invoke-MemoryApi -Method POST -Path "/v1/users/$UserId/rotate-key"
    Write-Host ""
    Write-Host "  New API Key: $($resp.api_key)" -ForegroundColor Yellow
    Write-Host "  Rotated At:  $($resp.rotated_at)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  WARNING: Store the new API key securely. The old key is now invalid." -ForegroundColor Red
}
elseif ($Revoke) {
    if (-not $UserId) {
        Write-Host "ERROR: -UserId is required with -Revoke" -ForegroundColor Red
        exit 1
    }
    Write-Host "Revoking user: $UserId" -ForegroundColor Cyan
    $resp = Invoke-MemoryApi -Method DELETE -Path "/v1/users/$UserId"
    Write-Host "  Status: $($resp.status)" -ForegroundColor Green
}
else {
    Write-Host "Usage:" -ForegroundColor Cyan
    Write-Host "  manage-keys.ps1 -Create -DisplayName 'Sonia UI'"
    Write-Host "  manage-keys.ps1 -List"
    Write-Host "  manage-keys.ps1 -Rotate -UserId 'usr_xxxx'"
    Write-Host "  manage-keys.ps1 -Revoke -UserId 'usr_xxxx'"
}
