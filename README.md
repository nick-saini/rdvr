# RDVR — Remote Desktop Video Recorder v2.1

<p align="center">
  <b>Enterprise CCTV & DVR for Windows Remote Desktop Services</b><br>
  Real-time session monitoring · Automatic H.264 hardware recording · Compliance auditing
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Platform-Windows%20Server-blue" alt="Windows Server">
  <img src="https://img.shields.io/badge/GPU-NVENC%2FQSV%2FAMF-green" alt="Hardware Encoding">
  <img src="https://img.shields.io/badge/License-Proprietary-red" alt="License">
</p>

---

## What is RDVR?

**RDVR** turns your Windows Server into a full-featured session-recording NVR — live CCTV wall, automatic MP4 archiving, connection auditing, and remote session control — all from a single web dashboard.

Built for **IT administrators, MSPs, and compliance officers** who need visibility into Remote Desktop sessions without deploying expensive 3rd-party EDR tools.

---

## Features

| Feature | Description |
|---------|-------------|
| **Live CCTV Wall** | Real-time MJPEG grid of all active sessions. Adjustable columns (2-6). Click any card for full-screen enlarge. |
| **NVR Dashboard** | Dense multi-view dashboard with session grid, connection table, events, alerts, recordings, and user notes. |
| **Dual-Resolution Feeds** | Grid uses 320px thumbnails (fast). Enlarged view uses 1280px previews (sharp). |
| **Automatic Recording** | H.264 screen capture via FFmpeg with NVENC, QSV, AMF, or libx264. Rotating MP4 segments. |
| **Hardware Encoding** | Auto-detects NVIDIA NVENC, Intel QSV, AMD AMF. Falls back to CPU x264. |
| **NVENC Patch Tool** | Built-in patcher for GeForce consumer cards (session limit unlock). |
| **Session Playback** | One-click MP4 download. Per-user filtering. |
| **Connection History** | Windows Event Log integration for full audit trails. |
| **Failed Login Alerts** | Real-time banner showing brute-force attempts. |
| **Session Control** | Send messages, disconnect, logoff, shadow (remote control) sessions from dashboard. |
| **Admin Exclusion** | Administrator accounts automatically excluded from recording and live preview. |
| **Resource Monitoring** | Live CPU/RAM/DISK/Session stats in toolbar. |
| **CSV Export** | Export sessions, events, and recordings to CSV. |
| **Retention Policies** | One-click cleanup of old recordings and thumbnails (7-day default). |
| **User Notes (mem0)** | Tag users with compliance notes stored in persistent memory. |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  Windows Server 2022 / RDS                    │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
│  │  app.py │  │agent.py │  │  FFmpeg     │  │
│  │(waitress)│  │(per user)│  │(H.264 DVR)  │
│  └────┬────┘  └────┬────┘  └─────────────┘  │
│       │            │                         │
│       └────────────┴────────────────────────┘
│              mss GPU capture (raw BGRA)
│                     │
│              ┌──────▼──────┐
│              │  Browser    │
│              │  :7777      │
│              │  Dashboard  │
│              └─────────────┘
└─────────────────────────────────────────────┘
```

| Component | Tech | Purpose |
|-----------|------|---------|
| `app.py` | Flask + Waitress WSGI | REST API, MJPEG `/stream/` + `/preview/`, static dashboard |
| `agent.py` | `mss` + `pythonw` | Per-session screen capture daemon (rawvideo → FFmpeg) |
| `win_desktop.py` | Windows C APIs | Attach to `WinSta0\Default` for RDP session capture |
| `rdp_utils.py` | PsExec + Windows APIs | Session enumeration, agent injection, caching |
| `patch_nvenc.py` | Python `.1337` patcher | Unlock NVENC on consumer GeForce cards |
| `nvr.html` | Vanilla JS SPA | Enterprise dashboard (no build step) |
| `live.html` | Vanilla JS | CCTV Live Wall with modal enlarge |
| `install.ps1` | PowerShell | One-click deploy: deps, firewall, scheduled task |

---

## Quick Start

1. **Copy** this repo to your Windows Server 2022/2019 machine.
2. Open **PowerShell as Administrator**.
3. Run:
   ```powershell
   .\install.ps1
   ```
4. Open your browser to `http://<server-ip>:7777`

The installer handles Python dependencies, downloads FFmpeg + PsExec automatically, creates firewall rules, and registers a boot-time scheduled task running as `SYSTEM`.

---

## Dual-Feed Architecture

RDVR v2.1 saves **two JPEGs** per capture cycle:

| File | Resolution | Endpoint | Used By |
|------|-----------|----------|---------|
| `user.jpg` | 320px | `/stream/<user>` | Grid cards, small previews |
| `user_preview.jpg` | 1280px | `/preview/<user>` | Full-screen enlarge, lightbox |

This ensures the grid stays fast (small files) while the enlarged view is sharp (4× resolution).

---

## Resource Usage (Per Session, NVENC)

| Process | RAM | CPU | GPU | Notes |
|---------|-----|-----|-----|-------|
| `pythonw` agent | ~55 MB | ~1-2% | — | mss capture, thumbnailer, idle priority |
| `ffmpeg` encoder | ~150 MB | ~0.5% | ~5% | NVENC hardware encoding |
| Disk write | ~120 MB/hr | — | — | 1 fps, CRF 26, 2M maxrate |

**50 concurrent users** ≈ **~8-10 GB RAM**, **~25-35% CPU**, **GPU handles encoding**.

---

## Configuration (`config.ini`)

```ini
[recording]
fps = 1.0              # recording framerate
thumb_fps = 1.0        # thumbnail capture rate (also preview rate)
thumb_width = 320      # grid thumbnail width
segment_sec = 120      # rotate MP4 every N seconds
crf = 26               # quality (lower = better, 18-28 typical)
maxrate = 2M           # max bitrate per stream
encoder = h264_nvenc   # h264_nvenc | h264_qsv | h264_amf | libx264
nvenc_preset = p4      # NVENC preset (p1-p7)
nvenc_rc = vbr         # rate control mode
nvenc_cq = 26          # CQ quality level
```

---

## NVENC Consumer GPU Setup

If you have a GeForce (not Quadro/Tesla) card, NVIDIA limits concurrent encode sessions to 3. RDVR includes an auto-patcher:

```powershell
# Run as Administrator
python patch_nvenc.py --auto
```

See `README_NVENC.md` for full driver downgrade + patch workflow.

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Main NVR dashboard |
| `GET /live` | CCTV Live Wall |
| `GET /stream/<user>` | MJPEG sub-feed (320px) |
| `GET /preview/<user>` | MJPEG main-feed (1280px) |
| `GET /api/sessions` | Active session list |
| `POST /api/inject` | Launch agents in all sessions |
| `GET /api/recordings` | List MP4 recordings |
| `GET /recording/<file>` | Download MP4 |
| `POST /api/retention` | Run 7-day cleanup |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Dashboard not loading | `Get-NetFirewallRule -DisplayName "RDVR-Inbound"` |
| No recordings / black screen | Check `agent.py` log in `C:\Users\Public\sentineldesk\logs\` |
| High CPU usage | Kill duplicate agents: `Get-Process pythonw` / `Get-Process ffmpeg` |
| NVENC error | Run `python patch_nvenc.py --auto` as Admin |
| Agent crashes on attach | Ensure `win_desktop.py` is in same folder as `agent.py` |
| Service won't start | Check `C:\Users\Public\sentineldesk\logs\app.log` |
| Restart service | `Start-ScheduledTask -TaskName 'RDVR'` |

---

## File Reference

| File | Purpose |
|------|---------|
| `agent.py` | Per-session screen recorder (mss + FFmpeg rawvideo pipe) |
| `app.py` | Flask dashboard server (Waitress WSGI) |
| `auth.py` | PBKDF2 password hashing |
| `config.py` / `config.ini` | Settings loader |
| `rdp_utils.py` | Session enumeration, PsExec injection, Windows API helpers |
| `win_desktop.py` | Attach process to `WinSta0\Default` desktop |
| `patch_nvenc.py` | `.1337` patch applier for NVENC DLLs |
| `setup_auth.py` | Generate password hash for `config.ini` |
| `install.ps1` | One-click Windows installer |
| `start_silent.bat` | Silent startup script |
| `nvr.html` | Main dashboard SPA |
| `live.html` | CCTV Live Wall |
| `index.html` | Legacy dashboard entry (loads `dashboard.js`) |
| `dashboard.js` | Frontend logic for index.html |
| `style.css` | Main stylesheet |
| `nvidia-patch/` | `.1337` patch files per driver version |

---

## Roadmap

- [ ] SAML / OIDC authentication
- [ ] Cloud archive to S3 / Azure Blob
- [ ] Role-based access control
- [ ] Email alerts on failed logins
- [ ] WebSocket streaming (lower latency)
- [ ] SaaS hosted tier (rdvr.io)

---

## License

Proprietary — Not for redistribution without written permission.

---

<p align="center">
  <b>Built for sysadmins who need eyes on every session.</b>
</p>
