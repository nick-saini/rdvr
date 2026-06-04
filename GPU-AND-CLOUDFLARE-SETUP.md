# RDVR — GPU & Remote Access Setup Guide

For internal team use. Run all commands in **PowerShell as Administrator** on the Windows Server.

---

## Part 1 — NVIDIA NVENC Setup

### Why This Matters
The RTX 4060 has a dedicated NVENC hardware encoder chip that handles all video encoding
at near-zero CPU cost. Without the patch below, only 3 sessions can use NVENC at once —
the remaining users fall back to CPU encoding and the benefit is lost.

---

### Step 1 — Verify GPU Is Visible to Windows

```powershell
nvidia-smi
```

Expected output shows the RTX 4060, driver version, and memory. If this fails, the GPU
is not passed through correctly in Proxmox — fix the PCIe passthrough first.

---

### Step 2 — Apply the NVENC Session Limit Patch

NVIDIA artificially limits consumer GPUs to ~3 simultaneous NVENC sessions via the driver.
This patch removes that limit so all 50 RDS sessions can encode simultaneously.

```powershell
# Download the patch
Invoke-WebRequest `
  -Uri "https://github.com/keylase/nvidia-patch/raw/master/win/patch.bat" `
  -OutFile "C:\nvidia-patch.bat"

# Run the patch (modifies the NVIDIA driver DLL)
C:\nvidia-patch.bat
```

> No reboot required. Takes about 10 seconds.

**Verify the patch worked:**
```powershell
C:\Users\Administrator\ffmpeg.exe -f lavfi -i testsrc -c:v h264_nvenc -t 3 C:\test_nvenc.mp4
# Should complete without error. Delete the test file after.
Remove-Item C:\test_nvenc.mp4 -ErrorAction SilentlyContinue
```

If you see `NVENC_OUT_OF_SESSIONS` — the patch didn't apply. Re-run `patch.bat`.

---

### Step 3 — Limit GPU Power Draw

The RTX 4060's default TDP is **115W**. For screen recording only (NVENC, no gaming),
you can cap it at **60W** — NVENC performance is identical because it runs on a
dedicated hardware block, not the CUDA cores.

```powershell
# Enable persistence mode (keeps GPU settings across reboots)
nvidia-smi -pm 1

# Set power limit to 60W (safe minimum for NVENC workloads)
nvidia-smi -pl 60

# Verify
nvidia-smi --query-gpu=power.limit,power.draw --format=csv
# Should show: 60.00 W limit, and ~15-30 W actual draw under load
```

**Make the power limit survive reboots** — add it to a scheduled task:

```powershell
$action = New-ScheduledTaskAction -Execute "nvidia-smi" -Argument "-pl 60"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Register-ScheduledTask -TaskName "NVIDIA-PowerLimit" `
  -Action $action -Trigger $trigger -Principal $principal -Force
```

> At 60W cap with NVENC encoding 50 sessions at 1fps: expect ~20–30W actual draw.
> That's less than a light bulb.

---

### Step 4 — Update config.ini for GPU Mode

Edit `C:\Users\Administrator\.sentineldesk\config.ini`:

```ini
[recording]
fps          = 1.0     ; smoother recording (was 0.5) — GPU handles it easily
thumb_fps    = 2.0     ; live CCTV feel — 1 frame every 0.5s (was 0.1)
thumb_width  = 480     ; wider thumbnail for clearer live view (was 320)
segment_sec  = 300
crf          = 24      ; better quality (was 28) — GPU doesn't care about CRF
maxrate      = 1500k   ; sharper video (was 500k)
ffmpeg       = C:\Users\Administrator\ffmpeg.exe
```

> The `detect_encoder()` function in `agent.py` auto-picks NVENC at boot.
> No other code changes needed.

---

### Step 5 — Restart RDVR

```powershell
Stop-ScheduledTask -TaskName "RDVR"
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName "RDVR"
```

New sessions connecting after this will automatically use NVENC.
Existing sessions will switch on next reconnect.

---

### Expected Resource Usage After GPU Setup (50 users)

| Resource | Usage |
|---|---|
| CPU total | ~3–5% |
| GPU NVENC | ~20–30% |
| GPU power draw | ~20–30W (capped at 60W) |
| RAM | ~1.5 GB (FFmpeg processes) |
| Disk write | ~120 MB/hr per user at 1fps |

---

## Part 2 — Cloudflare Tunnel (Remote Access)

### Why Cloudflare Tunnel
- No port forwarding required on your router
- Free HTTPS certificate automatically
- Your server IP stays hidden
- Works through firewalls and NAT
- Dashboard accessible from anywhere (phone, laptop, office)

> **Note on live view through Cloudflare:** The MJPEG stream may buffer through
> Cloudflare. The dashboard thumbnail polling (1–2s refresh) works reliably.
> For best live view experience, access from inside the office network directly.

---

### Step 1 — Create a Cloudflare Account & Add Your Domain

1. Go to https://cloudflare.com — create free account
2. Add your domain (or use a free subdomain via Cloudflare Pages)
3. Note your domain name (e.g., `monitor.yourcompany.com`)

---

### Step 2 — Install cloudflared on Windows Server

```powershell
# Download cloudflared
Invoke-WebRequest `
  -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
  -OutFile "C:\cloudflared.exe"
```

---

### Step 3 — Authenticate with Cloudflare

```powershell
C:\cloudflared.exe tunnel login
# Opens browser — log in to your Cloudflare account and select your domain
```

---

### Step 4 — Create the Tunnel

```powershell
C:\cloudflared.exe tunnel create rdvr
# Note the tunnel ID shown — e.g. a1b2c3d4-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

### Step 5 — Create Config File

Create `C:\Users\Administrator\.cloudflared\config.yml`:

```yaml
tunnel: rdvr
credentials-file: C:\Users\Administrator\.cloudflared\<YOUR-TUNNEL-ID>.json

ingress:
  - hostname: monitor.yourcompany.com
    service: http://localhost:7777
    originRequest:
      noTLSVerify: true
      connectTimeout: 30s
      tcpKeepAlive: 30s
      keepAliveConnections: 10
  - service: http_status:404
```

> Replace `<YOUR-TUNNEL-ID>` with the actual ID from Step 4.
> Replace `monitor.yourcompany.com` with your actual domain.

---

### Step 6 — Point DNS to Tunnel

```powershell
C:\cloudflared.exe tunnel route dns rdvr monitor.yourcompany.com
# Automatically creates a CNAME record in Cloudflare DNS
```

---

### Step 7 — Install as Windows Service (Auto-start)

```powershell
C:\cloudflared.exe service install
net start cloudflared
```

The tunnel now starts automatically on every boot.

---

### Step 8 — Test

Open `https://monitor.yourcompany.com` from your phone or an external network.
You should see the RDVR login page with a valid HTTPS certificate.

---

### Managing the Tunnel

```powershell
# Start
net start cloudflared

# Stop
net stop cloudflared

# Status
C:\cloudflared.exe tunnel info rdvr

# View logs
C:\cloudflared.exe tunnel log rdvr
```

---

### Optional: Add Cloudflare Access (Extra Security Layer)

Cloudflare Access adds a second login screen in front of your app — useful if
you want to restrict access by email or IP before the RDVR login even loads.

1. In Cloudflare dashboard → Zero Trust → Access → Applications
2. Add application → Self-hosted
3. Domain: `monitor.yourcompany.com`
4. Add policy: allow only your team's email addresses
5. Free for up to 50 users

---

## Quick Reference — All Commands

```powershell
# Apply NVENC patch
C:\nvidia-patch.bat

# Limit GPU power to 60W
nvidia-smi -pm 1 && nvidia-smi -pl 60

# Check GPU power
nvidia-smi --query-gpu=power.limit,power.draw --format=csv,noheader

# Restart RDVR
Stop-ScheduledTask -TaskName "RDVR"; Start-Sleep 3; Start-ScheduledTask -TaskName "RDVR"

# Start Cloudflare tunnel
net start cloudflared

# Stop Cloudflare tunnel
net stop cloudflared

# Check active NVENC sessions
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `NVENC_OUT_OF_SESSIONS` in logs | Re-run `C:\nvidia-patch.bat` |
| GPU showing 0W after reboot | Re-run `nvidia-smi -pl 60` or check the scheduled task |
| Cloudflare tunnel not connecting | Run `C:\cloudflared.exe tunnel run rdvr` manually and check output |
| Live view slow through Cloudflare | Expected — use direct IP on local network for live view |
| NVENC not detected by agent | Verify with `ffmpeg -encoders \| findstr nvenc`, then restart RDVR |
| GPU not visible (`nvidia-smi` fails) | PCIe passthrough issue in Proxmox — check VM hardware settings |
