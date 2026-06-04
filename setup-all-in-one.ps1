#Requires -RunAsAdministrator
<#
.SYNOPSIS
    RDVR v2.1 — One-Click Complete Setup
    Run this after a fresh Windows install to deploy everything automatically.
.DESCRIPTION
    Handles: Python deps, FFmpeg, PsExec, firewall, NVENC patch, scheduled tasks, auth setup.
.NOTES
    Run in PowerShell as Administrator.
    Supports: Windows Server 2022 / 2019 / Windows 11
#>
param(
    [string]$InstallDir = "C:\Users\Administrator\.rdp-dashboard",
    [string]$BaseDir    = "C:\Users\Public\sentineldesk",
    [string]$Password   = "",  # If empty, prompts for dashboard password
    [switch]$SkipNvencPatch
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

# ── Banner ───────────────────────────────────────────────────────────────
Write-Host @"
╔══════════════════════════════════════════════════════════════╗
║           RDVR v2.1 — Enterprise RDP Monitoring                ║
║           One-Click Setup & Auto-Configuration               ║
╚══════════════════════════════════════════════════════════════╝
"@ -ForegroundColor Cyan

# ── Helpers ────────────────────────────────────────────────────────────────
function Test-Admin {
    $current = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
if (-not (Test-Admin)) {
    Write-Host "ERROR: Must run as Administrator. Right-click PowerShell → 'Run as Administrator'." -ForegroundColor Red
    exit 1
}

function Wait-ProcessExit($proc, $label, $timeoutSec = 60) {
    $proc | Wait-Process -Timeout $timeoutSec -ErrorAction SilentlyContinue
    if (-not $proc.HasExited) {
        Write-Warning "$label did not exit in ${timeoutSec}s — forcing stop"
        Stop-Process -Id $proc.Id -Force
    }
}

# ── 1. Create directories ────────────────────────────────────────────────
Write-Host "`n[1/9] Creating directories..." -ForegroundColor Yellow
$dirs = @($InstallDir, "$BaseDir\recordings", "$BaseDir\thumbs", "$BaseDir\logs")
$dirs | ForEach-Object {
    New-Item -ItemType Directory -Path $_ -Force | Out-Null
    Write-Host "  ✅ $_"
}

# ── 2. Copy source files ─────────────────────────────────────────────────
Write-Host "`n[2/9] Copying source files..." -ForegroundColor Yellow
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$coreFiles  = @(
    "agent.py","app.py","auth.py","config.py","rdp_utils.py",
    "win_desktop.py","patch_nvenc.py","setup_auth.py",
    "Apply-NVENC-Patch.ps1","start_silent.bat",
    "config.ini","requirements.txt","README.md","README_NVENC.md",
    "GPU-AND-CLOUDFLARE-SETUP.md","install.ps1",".gitignore"
)
foreach ($f in $coreFiles) {
    $src = Join-Path $scriptRoot $f
    if (Test-Path $src) {
        Copy-Item $src $InstallDir -Force
        Write-Host "  ✅ $f"
    } else {
        Write-Host "  ⚠ Missing: $f" -ForegroundColor DarkYellow
    }
}

# Templates & static
New-Item -ItemType Directory -Path "$InstallDir\templates","$InstallDir\static\css","$InstallDir\static\js" -Force | Out-Null
Copy-Item "$scriptRoot\templates\*.html" "$InstallDir\templates\" -Force -ErrorAction SilentlyContinue
Copy-Item "$scriptRoot\static\css\style.css" "$InstallDir\static\css\" -Force -ErrorAction SilentlyContinue
Copy-Item "$scriptRoot\static\js\dashboard.js" "$InstallDir\static\js\" -Force -ErrorAction SilentlyContinue

# Patch files
if (Test-Path "$scriptRoot\nvidia-patch") {
    Copy-Item "$scriptRoot\nvidia-patch" "$InstallDir\" -Recurse -Force
    Write-Host "  ✅ nvidia-patch/"
}

# ── 3. Python dependencies ───────────────────────────────────────────────
Write-Host "`n[3/9] Installing Python packages..." -ForegroundColor Yellow
$py = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command "C:\Program Files\Python312\python.exe" -ErrorAction SilentlyContinue }
if (-not $py) { $py = Get-Command "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe" -ErrorAction SilentlyContinue }

if (-not $py) {
    Write-Host "  Python not found. Please install Python 3.12+ from python.org first." -ForegroundColor Red
    exit 1
}
Write-Host "  Using: $($py.Source)"
& $py -m pip install --upgrade pip 2>$null | Out-Null
& $py -m pip install -r "$InstallDir\requirements.txt" --no-warn-script-location
Write-Host "  ✅ pip packages installed"

# ── 4. FFmpeg ────────────────────────────────────────────────────────────
Write-Host "`n[4/9] Checking FFmpeg..." -ForegroundColor Yellow
$ffmpeg = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    $candidate = "C:\Users\Administrator\ffmpeg.exe"
    if (Test-Path $candidate) { $ffmpeg = $candidate }
}
if (-not $ffmpeg) {
    Write-Host "  Downloading FFmpeg..." -ForegroundColor Cyan
    $zipUrl  = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    $zipPath = "$env:TEMP\ffmpeg.zip"
    $extract = "$env:TEMP\ffmpeg_extract"
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -MaximumRedirection 5
        Expand-Archive -Path $zipPath -DestinationPath $extract -Force
        $bin = Get-ChildItem "$extract\ffmpeg-*\bin\ffmpeg.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($bin) {
            Copy-Item $bin.FullName "C:\Users\Administrator\ffmpeg.exe" -Force
            Write-Host "  ✅ ffmpeg.exe placed at C:\Users\Administrator\ffmpeg.exe"
        } else {
            Write-Warning "FFmpeg download succeeded but ffmpeg.exe not found in archive."
        }
    } catch {
        Write-Warning "Failed to download FFmpeg: $_"
        Write-Host "  Please manually download from https://www.gyan.dev/ffmpeg/builds/ and place ffmpeg.exe in PATH." -ForegroundColor Yellow
    }
} else {
    Write-Host "  ✅ ffmpeg found: $($ffmpeg.Source)"
}

# ── 5. PsExec ────────────────────────────────────────────────────────────
Write-Host "`n[5/9] Checking PsExec..." -ForegroundColor Yellow
$psexec = "C:\Users\Administrator\psexec.exe"
if (-not (Test-Path $psexec)) {
    $zipUrl  = "https://download.sysinternals.com/files/PSTools.zip"
    $zipPath = "$env:TEMP\pstools.zip"
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\pstools" -Force
        Copy-Item "$env:TEMP\pstools\PsExec.exe" $psexec -Force
        Write-Host "  ✅ psexec.exe placed at $psexec"
    } catch {
        Write-Warning "Failed to download PsExec: $_"
        Write-Host "  Please manually download from https://docs.microsoft.com/sysinternals/downloads/psexec" -ForegroundColor Yellow
    }
} else {
    Write-Host "  ✅ psexec.exe found"
}

# ── 6. Update config.ini paths ──────────────────────────────────────────
Write-Host "`n[6/9] Updating configuration..." -ForegroundColor Yellow
$cfgPath = "$InstallDir\config.ini"
if (Test-Path $cfgPath) {
    $cfg = Get-Content $cfgPath -Raw
    # Update paths
    $cfg = $cfg -replace "(?m)^ffmpeg\s*=.*", "ffmpeg = C:\Users\Administrator\ffmpeg.exe"
    $cfg = $cfg -replace "(?m)^psexec\s*=.*",  "psexec = C:\Users\Administrator\psexec.exe"
    $cfg = $cfg -replace "(?m)^python\s*=.*",   "python = C:\Program Files\Python312\pythonw.exe"
    $cfg = $cfg -replace "(?m)^base_dir\s*=.*",  "base_dir = C:\Users\Public\sentineldesk"
    $cfg | Set-Content $cfgPath -NoNewline
    Write-Host "  ✅ config.ini updated"
}

# ── 7. Auth setup ───────────────────────────────────────────────────────
Write-Host "`n[7/9] Setting up dashboard authentication..." -ForegroundColor Yellow
if ([string]::IsNullOrWhiteSpace($Password)) {
    $Password = Read-Host "Enter dashboard password (min 8 chars)" -AsSecureString | ForEach-Object { [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($_)) }
}
& $py "$InstallDir\setup_auth.py" "$Password"
Write-Host "  ✅ Password hash generated"

# ── 8. Firewall ──────────────────────────────────────────────────────────
Write-Host "`n[8/9] Configuring firewall..." -ForegroundColor Yellow
$ruleName = "RDVR-Inbound"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  Rule exists, updating..."
    Remove-NetFirewallRule -DisplayName $ruleName -Confirm:$false
}
New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort 7777 -Action Allow -Profile Any | Out-Null
Write-Host "  ✅ Firewall rule 'RDVR-Inbound' created (port 7777 TCP)"

# ── 9. Scheduled Tasks (Auto-start) ──────────────────────────────────────
Write-Host "`n[9/9] Registering auto-start scheduled tasks..." -ForegroundColor Yellow
$taskNameServer = "RDVR_Server"
$taskNameAgent  = "RDVR_Agent_ea001"

# Server task
$actionServer = New-ScheduledTaskAction -Execute "C:\Program Files\Python312\pythonw.exe" -Argument "$InstallDir\app.py" -WorkingDirectory $InstallDir
$triggerBoot  = New-ScheduledTaskTrigger -AtStartup
$triggerLogon = New-ScheduledTaskTrigger -AtLogon
$settings     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable:$false
$principal    = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $taskNameServer -Action $actionServer -Trigger $triggerBoot,$triggerLogon -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "  ✅ Scheduled task '$taskNameServer' created (runs as SYSTEM)"

# Agent task (for ea001 — customize usernames as needed)
$actionAgent = New-ScheduledTaskAction -Execute "C:\Program Files\Python312\pythonw.exe" -Argument "$InstallDir\agent.py ea001"
$triggerAgent = New-ScheduledTaskTrigger -AtLogon
Register-ScheduledTask -TaskName $taskNameAgent -Action $actionAgent -Trigger $triggerAgent -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "  ✅ Scheduled task '$taskNameAgent' created (auto-starts ea001 agent)"

# ── 10. NVENC Patch (optional) ───────────────────────────────────────────
if (-not $SkipNvencPatch) {
    Write-Host "`n[Bonus] NVENC Consumer GPU Patch..." -ForegroundColor Yellow
    $nvidia = Get-WmiObject Win32_VideoController | Where-Object { $_.Name -like "*NVIDIA*" }
    if ($nvidia) {
        Write-Host "  NVIDIA GPU detected: $($nvidia.Name)"
        Write-Host "  Attempting auto-patch..."
        & $py "$InstallDir\patch_nvenc.py" --auto
        Write-Host "  ✅ NVENC patch applied (if needed)"
    } else {
        Write-Host "  No NVIDIA GPU detected — skipping NVENC patch" -ForegroundColor DarkGray
    }
}

# ── 11. Start services now ─────────────────────────────────────────────
Write-Host "`n[Start] Launching RDVR now..." -ForegroundColor Green
Start-ScheduledTask -TaskName $taskNameServer
Write-Host "  ▶ Server started (http://localhost:7777)"

Start-ScheduledTask -TaskName $taskNameAgent
Write-Host "  ▶ Agent started for ea001"

Start-Sleep 3

# ── Done ──────────────────────────────────────────────────────────────────
Write-Host @"

╔══════════════════════════════════════════════════════════════╗
║                    SETUP COMPLETE ✅                         ║
╠══════════════════════════════════════════════════════════════╣
║  Dashboard:     http://localhost:7777                        ║
║  Username:     admin                                         ║
║  Password:     (what you entered above)                      ║
╠══════════════════════════════════════════════════════════════╣
║  Install Dir:  $InstallDir                      ║
║  Recordings:   $BaseDir\recordings               ║
║  Thumbnails:   $BaseDir\thumbs                   ║
╠══════════════════════════════════════════════════════════════╣
║  To re-start:  Start-ScheduledTask -TaskName 'RDVR_Server'   ║
║  To stop:      Stop-ScheduledTask  -TaskName 'RDVR_Server'   ║
╚══════════════════════════════════════════════════════════════╝
"@ -ForegroundColor Green

# Verify
$proc = Get-Process pythonw -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "Running pythonw processes: $($proc.Count)" -ForegroundColor Cyan
}
