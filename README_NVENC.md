# NVENC Session-Limit Patch Guide for RDVR

## Current Status

- **GPU**: NVIDIA GeForce RTX 4060
- **Driver**: 610.47 (DCH / Studio / Game Ready)
- **Patch support**: ❌ **Not yet available** for driver 610.47
- **✅ Confirmed patchable drivers**: **595.79 Studio**, **595.97 DCH**, **582.16 Quadro**
- **FFmpeg h264_nvenc**: Crashes with access violation (0xC0000005) because the session-limit enforcement path in the driver returns an unhandled error → FFmpeg segfaults.

## Why This Happens

Consumer NVIDIA cards (GeForce GTX/RTX) artificially limit simultaneous NVENC encoding sessions to **2–3 streams**. On an RDS server with 50 users, you will hit this limit immediately. The `nvidia-patch` project removes this artificial cap by patching `nvencodeapi64.dll` and `nvencodeapi.dll`. However, each driver version requires specific byte offsets, and **610.47 is too new** — the latest supported patch is for driver **582.16** (Quadro branch) / **595.97** (GeForce DCH branch).

## What Has Already Been Done

1. ✅ **GPU power limit** set to **90 W** (minimum allowed by RTX 4060; default was 115 W).
2. ✅ **Patch script** ready: `C:\Users\Administrator\.rdp-dashboard\patch_nvenc.py`
3. ✅ **Patch files** copied: `nvidia-patch\582.16\`
4. ✅ **Config** tuned for high-quality CPU encoding (`crf=26`, `maxrate=800k`) as a working fallback.

## Your Options

### Option A — Downgrade Driver (Recommended for NVENC)

1. **Download a supported driver**
   - ✅ **595.79 Studio** — confirmed working with patch
   - **595.97 DCH** — latest patchable GeForce driver
   - **582.16 Quadro/Studio** — also patchable
   - Download from [NVIDIA Driver Search](https://www.nvidia.com/drivers/)

2. **Install the driver**
   - Use **Custom (Advanced)** install.
   - Check **"Perform clean installation"** to avoid leftover 610.47 components.
   - Reboot.

3. **Apply the patch**
   Open an **Administrator PowerShell**:
   ```powershell
   cd C:\Users\Administrator\.rdp-dashboard
   python patch_nvenc.py --patch
   ```
   The script will:
   - Auto-detect the new driver version
   - Back up `nvencodeapi64.dll` and `nvencodeapi.dll` to `.bak`
   - Apply the byte patch

4. **Verify**
   ```powershell
   ffmpeg -f lavfi -i testsrc=duration=10:size=320x240:rate=30 -c:v h264_nvenc -f null -
   ```
   If it finishes without crashing, NVENC is unlocked.

5. **Enable NVENC in RDVR**
   Edit `config.ini` and uncomment the NVENC preset lines:
   ```ini
   encoder = h264_nvenc
   nvenc_preset = p4
   nvenc_rc = vbr_hq
   nvenc_cq = 26
   fps = 1.0
   maxrate = 2M
   ```
   Restart the RDVR service.

### Option B — Wait for Patch Maintainers

- Track [keylase/nvidia-patch](https://github.com/keylase/nvidia-patch)
- Once a `.1337` file for 610.xx appears, copy it into `nvidia-patch\610.47\` and run `patch_nvenc.py --patch`.

### Option C — Keep CPU Encoding (Working Today)

- CPU encoding with `gdigrab` + `libx264` is already functional.
- Current settings (`crf=26`, `maxrate=800k`, `fps=0.5`) give ~70 % CPU savings vs the old Python `mss` loop.
- You can run all 50 sessions on CPU if the server has enough cores (e.g., 16+ cores).
- NVENC only becomes necessary if you want **higher framerate** (`fps=1.0+`) or **lower CPU usage**.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `patch_nvenc.py` says "expected 0x8B, found 0xXX" | Patch file is for a different driver version | Use `--force-version` with the closest version, or downgrade driver |
| FFmpeg crashes with `-1073741819` | NVENC session limit hit / driver mismatch | Apply patch, or switch to CPU encoding |
| `nvidia-smi` shows GPU but no encoder info | GPU passthrough issue (Proxmox/KVM) | Ensure GPU is in PCI-E passthrough with ROM BAR enabled; verify WDDM mode |
| Power limit cannot go below 90 W | RTX 4060 hardware limit | 90 W is the minimum; still saves 25 W vs default 115 W |

## Rollback

If patching breaks the driver:
```powershell
cd C:\Users\Administrator\.rdp-dashboard
python patch_nvenc.py --restore
```
This restores the `.bak` files.

---
*Generated for RDVR v2 — Windows Server 2022 RDS*
