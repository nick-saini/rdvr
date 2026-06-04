# Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$Base = "C:\Users\Administrator\.rdp-dashboard"

Write-Host "[*] RDVR NVENC Patch Tool" -ForegroundColor Cyan
Write-Host "[*] Detected driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader)"
Write-Host ""

if ($args[0] -eq "--restore") {
    Write-Host "[*] Restoring original DLLs..." -ForegroundColor Yellow
    python "$Base\patch_nvenc.py" --restore
} else {
    Write-Host "[*] Dry-run first to verify patch compatibility..." -ForegroundColor Green
    python "$Base\patch_nvenc.py" --dry-run
    Write-Host ""
    $confirm = Read-Host "Do you want to apply the patch for real? (yes/no)"
    if ($confirm -eq "yes") {
        python "$Base\patch_nvenc.py" --patch
        Write-Host "[*] Done. Reboot before testing NVENC." -ForegroundColor Green
    } else {
        Write-Host "[*] Cancelled." -ForegroundColor Gray
    }
}
