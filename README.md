# RDVR — Remote Desktop Video Recorder

<p align="center">
  <b>CCTV &amp; DVR for Windows Remote Desktop Services</b><br>
  Real-time session monitoring · Automatic H.264 recording · Compliance auditing
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Platform-Windows%20Server-blue" alt="Windows Server">
  <img src="https://img.shields.io/badge/License-Proprietary-red" alt="License">
</p>

---

## Why RDVR?

Employee monitoring for RDS farms shouldn't cost thousands per month or require agents on every endpoint. **RDVR** turns your Windows Server into a full-featured session-recording NVR — live CCTV wall, automatic MP4 archiving, connection auditing, and remote session control — all from a single web dashboard.

Built for **IT administrators, MSPs, and compliance officers** who need visibility into Remote Desktop sessions without deploying expensive 3rd-party EDR tools.

---

## Features

| Feature | Description |
|---------|-------------|
| **Live Floor** | Real-time MJPEG grid of all active sessions. Adjustable layouts (1×1 up to 4×4). |
| **NVR Wall** | Dense multi-page CCTV view with pagination, slideshow mode, and fullscreen auto-switch. |
| **Automatic Recording** | H.264 screen capture via FFmpeg segment muxer. Rotating MP4s from connect to disconnect. |
| **Session Playback** | One-click MP4 playback in-browser with timeline scrubbing. Per-user filtering. |
| **Connection History** | Windows Event Log integration (TerminalServices-LocalSessionManager) for full audit trails. |
| **Audit Logs** | RDP login, logoff, and failed-auth events with IP attribution. |
| **Session Control** | Send messages, disconnect, or logoff sessions remotely from the dashboard. |
| **Admin Exclusion** | Administrator accounts are automatically excluded from recording and live preview. |
| **Resource Monitoring** | Per-process CPU/RAM breakdown for agents, FFmpeg, and server. |
| **CSV Export** | Filter and export any data table to CSV instantly. |
| **Retention Policies** | One-click cleanup of old recordings and thumbnails. |
| **Low Footprint** | ~33 MB RAM + ~28 MB FFmpeg per session. Idle-priority agents. |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  Windows Server 2022 / RDS                    │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
│  │  app.py │  │agent.py │  │  FFmpeg     │  │
│  │(waitress)│  │(per user)│  │(H.264 DVR)  │  │
│  └────┬────┘  └────┬────┘  └─────────────┘  │
│       │            │                         │
│       └────────────┴────────────────────────┘
│              mss GPU capture (GDI)
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
| `app.py` | Flask + Waitress WSGI | REST API, MJPEG streams, static dashboard |
| `agent.py` | `mss` + `pythonw` | Per-session screen capture daemon |
| `rdp_utils.py` | PsExec + Windows APIs | Session enumeration, agent injection, caching |
| `nvr.html` | Vanilla JS SPA | Enterprise dashboard (no build step) |
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

## Resource Usage (Per Session)

| Process | RAM | CPU | Notes |
|---------|-----|-----|-------|
| `pythonw` agent | ~33 MB | ~0.5% | `mss` capture, idle priority class |
| `ffmpeg` encoder | ~28 MB | ~0.2% | `libx264`, segment rotation every 120s |
| Disk write | ~60 MB/hr | — | 0.5 fps, CRF 32, 120k maxrate, 480px width |

**50 concurrent users** ≈ **3 GB RAM total**, **~35% of one modern CPU core**.

---

## Configuration

Edit `agent.py` constants for your environment:

```python
FPS = 0.5              # frames per second (1 frame every 2s)
SEGMENT_SECONDS = 120  # rotate MP4 every 2 minutes
CRF = 32               # quality (higher = smaller file)
BITRATE = "120k"       # max bitrate per stream
RECORD_W = 480         # output width (height auto)
```

---

## Screenshots

*(Add GIFs here: Live Floor grid, NVR fullscreen mode, Session playback, Connection History table)*

---

## Roadmap

- [ ] SAML / OIDC authentication
- [ ] Cloud archive to S3 / Azure Blob
- [ ] Role-based access control
- [ ] Email alerts on failed logins
- [ ] SaaS hosted tier (rdvr.io)

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Dashboard not loading | `Get-NetFirewallRule -DisplayName "RDVR-Inbound"` |
| No recordings | `Get-Process pythonw \| Where-Object { $_.CommandLine -match 'agent.py' }` |
| Service won't start | Check `C:\Users\Administrator\.sentineldesk\server.log` |
| Restart service | `Start-ScheduledTask -TaskName 'RDVR'` |

---

## License

Proprietary — Not for redistribution without written permission.

---

<p align="center">
  <b>Built for sysadmins who need eyes on every session.</b>
</p>
