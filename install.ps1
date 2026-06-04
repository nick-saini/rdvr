#Requires -RunAsAdministrator
<#
  RDVR Installer v2
  Remote Desktop Video Recorder
  Run as Administrator on the target Windows Server.
  Supports interactive setup OR silent install with parameters.

  INTERACTIVE:   .\install.ps1
  SILENT:        .\install.ps1 -AdminUser admin -AdminPass "MyPass123" -Port 7777
  UPGRADE:       .\install.ps1 -Upgrade
# >
param(
    [string]$TargetDir   = "C:\Users\Administrator\.sentineldesk",
    [string]$PublicDir   = "C:\Users\Public\sentineldesk",
    [string]$Port        = "",
    [string]$AdminUser   = "",
    [string]$AdminPass   = "",
    [string]$FPS         = "",
    [string]$MaxRate     = "",
    [string]$RetainDays  = "",
    [string]$DiskWarnPct = "",
    [switch]$Upgrade,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
$DeployDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step($msg) { Write-Host "[+] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    WARN: $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "    ERROR: $msg" -ForegroundColor Red }

function Ask([string]$prompt, [string]$default) {
    if ($Silent -or $default -ne "") { return $default }
    $val = Read-Host "$prompt [default: $default]"
    if ([string]::IsNullOrWhiteSpace($val)) { return $default }
    return $val
}

function AskSecret([string]$prompt) {
    if ($Silent) { return "" }
    $s = Read-Host $prompt -AsSecureString
    return [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

# ============================
# STEP 1: Interactive config
# ============================
Write-Host ""
Write-Host "  RDVR v2 Installer" -ForegroundColor White
Write-Host "  Remote Desktop Video Recorder" -ForegroundColor DarkGray
Write-Host "  ──────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

if (-not $Upgrade) {
    if (-not $Silent) {
        Write-Host "  Answer the following to customize this deployment." -ForegroundColor DarkGray
        Write-Host "  Press Enter to accept defaults." -ForegroundColor DarkGray
        Write-Host ""
    }

    if ([string]::IsNullOrWhiteSpace($Port))        { $Port        = Ask "Dashboard port"             "7777" }
    if ([string]::IsNullOrWhiteSpace($FPS))         { $FPS         = Ask "Recording FPS (0.5=1f/2s)"  "0.5" }
    if ([string]::IsNullOrWhiteSpace($MaxRate))     { $MaxRate     = Ask "Max video bitrate"           "500k" }
    if ([string]::IsNullOrWhiteSpace($RetainDays))  { $RetainDays  = Ask "Keep recordings N days"      "7" }
    if ([string]::IsNullOrWhiteSpace($DiskWarnPct)) { $DiskWarnPct = Ask "Disk warn % threshold"       "80" }

    if ([string]::IsNullOrWhiteSpace($AdminUser)) { $AdminUser = Ask "Admin username" "admin" }
    if ([string]::IsNullOrWhiteSpace($AdminPass)) {
        $AdminPass  = AskSecret "Admin password (min 8 chars)"
        $AdminPass2 = AskSecret "Confirm password"
        if ($AdminPass -ne $AdminPass2) {
            Write-Fail "Passwords do not match. Exiting."
            exit 1
        }
        if ($AdminPass.Length -lt 8) {
            Write-Fail "Password too short (min 8 chars). Exiting."
            exit 1
        }
    }
}

# ============================
# STEP 2: Python check
# ============================
Write-Step "Checking Python..."
$py = Get-Command "C:\Program Files\Python312\pythonw.exe" -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command pythonw.exe -ErrorAction SilentlyContinue }
if (-not $py) { Write-Fail "Python 3.12 not found. Install from python.org first."; exit 1 }
$pythonExe = $py.Source
$pipExe    = Join-Path (Split-Path $pythonExe) "Scripts\pip.exe"
if (-not (Test-Path $pipExe)) { $pipExe = Join-Path (Split-Path $pythonExe) "pip.exe" }
Write-Ok $pythonExe

# ============================
# STEP 3: Directories
# ============================
Write-Step "Creating directories..."
foreach ($d in @($TargetDir, $PublicDir,
                  "$PublicDir\thumbs", "$PublicDir\recordings", "$PublicDir\logs",
                  "$TargetDir\templates", "$TargetDir\static\css", "$TargetDir\static\js")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Write-Ok "Done"

# ============================
# STEP 4: Install packages
# ============================
Write-Step "Installing Python packages..."
& $pipExe install -r (Join-Path $DeployDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { Write-Warn "pip returned non-zero — continuing anyway" }
Write-Ok "Packages installed"

# ============================
# STEP 5: Copy files
# ============================
Write-Step "Copying application files..."
$appFiles = @("app.py","rdp_utils.py","config.py","auth.py","setup_auth.py","requirements.txt")
foreach ($f in $appFiles) {
    $src = Join-Path $DeployDir $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $TargetDir $f) -Force }
}
Copy-Item (Join-Path $DeployDir "agent.py") (Join-Path $PublicDir "agent.py") -Force
if (Test-Path "$DeployDir\templates") {
    Copy-Item -Recurse -Force "$DeployDir\templates\*" "$TargetDir\templates"
}
if (Test-Path "$DeployDir\static") {
    Copy-Item -Recurse -Force "$DeployDir\static\*" "$TargetDir\static"
}
Write-Ok "Files copied"

# ============================
# STEP 6: Generate config.ini
# ============================
Write-Step "Writing config.ini..."
$secretKey = -join ((65..90 + 97..122 + 48..57) | Get-Random -Count 64 | ForEach-Object { [char]$_ })

$configContent = @"
[server]
host       = 0.0.0.0
port       = $Port
threads    = 8
secret_key = $secretKey
ssl_cert   =
ssl_key    =

[auth]
username      = $AdminUser
password_hash =

[recording]
fps         = $FPS
thumb_fps   = 0.1
thumb_width = 320
segment_sec = 120
crf         = 28
maxrate     = $MaxRate
ffmpeg      = C:\Users\Administrator\ffmpeg.exe

[paths]
base_dir = $PublicDir
psexec   = C:\Users\Administrator\psexec.exe
python   = $pythonExe

[retention]
auto_days            = $RetainDays
disk_warn_percent    = $DiskWarnPct
disk_cleanup_percent = 90
"@
$configContent | Set-Content "$TargetDir\config.ini" -Encoding UTF8
Copy-Item "$TargetDir\config.ini" "$PublicDir\config.ini" -Force
Write-Ok "$TargetDir\config.ini"

# ============================
# STEP 7: Set admin password
# ============================
Write-Step "Setting admin password..."
$pyExe = $pythonExe -replace "pythonw", "python"
& $pyExe (Join-Path $TargetDir "setup_auth.py") --username $AdminUser --password $AdminPass
Write-Ok "Password set for '$AdminUser'"

# ============================
# STEP 8: Download FFmpeg
# ============================
$ffmpegPath = "C:\Users\Administrator\ffmpeg.exe"
if (-not (Test-Path $ffmpegPath)) {
    Write-Step "Downloading FFmpeg..."
    $zip = "$env:TEMP\ffmpeg.zip"
    try {
        Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip -UseBasicParsing -TimeoutSec 120
        Expand-Archive $zip "$env:TEMP\ffmpeg" -Force
        $ffExe = Get-ChildItem "$env:TEMP\ffmpeg" -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
        if ($ffExe) { Copy-Item $ffExe.FullName $ffmpegPath -Force; Write-Ok $ffmpegPath }
        else { Write-Warn "ffmpeg.exe not found in archive — download manually to $ffmpegPath" }
    } catch { Write-Warn "FFmpeg download failed — place ffmpeg.exe at $ffmpegPath manually" }
} else { Write-Ok "FFmpeg already present" }

# ============================
# STEP 9: Download PsExec
# ============================
$psexecPath = "C:\Users\Administrator\psexec.exe"
if (-not (Test-Path $psexecPath)) {
    Write-Step "Downloading PsExec..."
    try {
        Invoke-WebRequest "https://download.sysinternals.com/files/PSTools.zip" -OutFile "$env:TEMP\pstools.zip" -UseBasicParsing -TimeoutSec 60
        Expand-Archive "$env:TEMP\pstools.zip" "$env:TEMP\pstools" -Force
        Copy-Item "$env:TEMP\pstools\PsExec.exe" $psexecPath -Force
        Write-Ok $psexecPath
    } catch { Write-Warn "PsExec download failed — place psexec.exe at $psexecPath manually" }
} else { Write-Ok "PsExec already present" }

# ============================
# STEP 10: Firewall rule
# ============================
Write-Step "Firewall rule for port $Port..."
$ruleName = "RDVR-$Port"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
    Write-Ok "Rule created"
} else { Write-Ok "Rule already exists" }

# ============================
# STEP 11: Scheduled Task
# ============================
Write-Step "Registering Windows service (Scheduled Task)..."
$wrapperBat = Join-Path $TargetDir "start_service.bat"
@
@echo off
cd /d "$TargetDir"
start /b "$pythonExe" -u "$TargetDir\app.py" >> "$TargetDir\logs\server.log" 2>>&1
"@ | Set-Content $wrapperBat -Encoding ASCII

$taskName = "RDVR"
$action   = New-ScheduledTaskAction -Execute $wrapperBat -WorkingDirectory $TargetDir
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Ok "Task '$taskName' registered"

# ============================
# STEP 12: Start
# ============================
Write-Step "Starting RDVR..."
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3

# ============================
# Done
# ============================
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║     RDVR installed successfully          ║" -ForegroundColor Green
Write-Host "  ╠══════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "  ║  Dashboard:  http://$(hostname):$Port        " -ForegroundColor White -NoNewline; Write-Host "║" -ForegroundColor Green
Write-Host "  ║  Username:   $AdminUser" -ForegroundColor White -NoNewline; Write-Host "                              ║" -ForegroundColor Green
Write-Host "  ║  Config:     $TargetDir\config.ini" -ForegroundColor White -NoNewline; Write-Host "   ║" -ForegroundColor Green
Write-Host "  ║  Logs:       $TargetDir\logs\" -ForegroundColor White -NoNewline; Write-Host "         ║" -ForegroundColor Green
Write-Host "  ╠══════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "  ║  Manage task:" -ForegroundColor DarkGray
Write-Host "  ║    Start:   Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor DarkGray
Write-Host "  ║    Stop:    Stop-ScheduledTask  -TaskName '$taskName'" -ForegroundColor DarkGray
Write-Host "  ║    Password: python setup_auth.py" -ForegroundColor DarkGray
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
