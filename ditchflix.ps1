# Start-Jellyfin.ps1
# ----------------------------------------
# Safe one-click Jellyfin launcher for Windows
# ----------------------------------------

$ErrorActionPreference = "Stop"
$composeDir = "C:\Users\jucid\Documents\DITCHFLIX"
$composeFile = Join-Path $composeDir "docker-compose.yml"
$dockerExe = "$Env:ProgramFiles\Docker\Docker\resources\bin\docker.exe"

# --- Auto-elevate to Administrator if needed ---
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "⚙️  Restarting PowerShell as Administrator..."
    Start-Process powershell "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

# --- Ensure Docker Desktop is running ---
function Start-Docker {
    if (-not (Get-Process -Name "com.docker" -ErrorAction SilentlyContinue)) {
        Write-Host "🐳 Launching Docker Desktop..."
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        Write-Host "⏳ Waiting for Docker to start (30s)..."
        Start-Sleep -Seconds 30
    }
}

# --- Validate environment ---
function Validate {
    if (-not (Test-Path $composeFile)) {
        throw "❌ docker-compose.yml not found at $composeFile"
    }
    if (-not (Test-Path $dockerExe)) {
        throw "❌ Docker CLI not found. Check Docker Desktop installation."
    }
    Write-Host "✅ Compose file and Docker found."
}

# --- Check Drives ---
function Check-Drives {
    foreach ($d in @("A:", "B:", "E:")) {
        if (Test-Path $d) { Write-Host "✅ $d mounted." }
        else { Write-Warning "⚠️  $d not detected. Check connections or sharing." }
    }
}

# --- Start containers ---
function Run-Compose {
    Set-Location $composeDir
    Write-Host "🚀 Building and starting Ditchflix stack..."
    # Use --build to ensure local images (Caddy/Search) are up to date
    & "$dockerExe" compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "❌ Compose up failed." }
    Write-Host "✅ Stack started successfully."
}

# --- Show Status ---
function Show-Status {
    Write-Host "`n📊 Container Status:"
    & "$dockerExe" compose ps
}

# --- Main Execution ---
try {
    Start-Docker
    Validate
    Check-Drives
    Run-Compose
    Show-Status
    
    Write-Host "`n🍿 DITCHFLIX IS LIVE!" -ForegroundColor Green
    Write-Host "---------------------------------------------------"
    Write-Host "🍿 Jellyfin:      https://flix.ditchworld.com"
    Write-Host "🔍 Search:        https://flix.ditchworld.com/download"
    Write-Host "---------------------------------------------------"
    Write-Host "🔧 Local Admin:"
    Write-Host "   Jackett:       http://localhost:9117"
    Write-Host "   qBittorrent:   http://localhost:8080"
    Write-Host "   Sonarr:        http://localhost:8989"
    Write-Host "   Radarr:        http://localhost:7878"
    Write-Host "---------------------------------------------------"
}
catch {
    Write-Host "`n❌ Error: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Write-Host "`nPress any key to close..."
    if ($Host.UI.RawUI.KeyAvailable) {
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    }
    else {
        Read-Host "Press Enter to exit"
    }
}
