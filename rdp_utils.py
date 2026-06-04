"""
rdp_utils.py — Windows RDS utilities.
All paths, thresholds, and settings loaded from config.py.
"""
import subprocess
import json
import os
import re
import time
import threading
import datetime
from typing import List, Dict
import httpx
import psutil

import config

# External API keys from environment (not hardcoded)
MEM0_API = os.getenv("MEM0_API", "https://api-mem0.endeavoracademy.us")
MEM0_KEY = os.getenv("MEM0_KEY", "")

# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------
_cache: dict = {}
_cache_lock = threading.Lock()

def _cached(key: str, ttl: float, factory):
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    val = factory()
    with _cache_lock:
        _cache[key] = (now, val)
    return val

# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------
def _run(cmd: list, shell: bool = False) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", shell=shell,
                           timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return r.stdout + r.stderr
    except Exception as e:
        return str(e)

def _ps(script: str) -> str:
    return _run(["powershell.exe", "-NoProfile", "-Command", script])

# ---------------------------------------------------------------------------
# Session enumeration
# ---------------------------------------------------------------------------
def parse_quser() -> List[Dict]:
    return _cached("quser", 5.0, _parse_quser_raw)

def _parse_quser_raw() -> List[Dict]:
    out = _run(["quser"])
    lines = out.strip().splitlines()
    if not lines:
        return []
    sessions = []
    for raw in lines[1:]:
        line = raw.rstrip()
        if not line.strip():
            continue
        current = line.startswith(">")
        line = line.lstrip("> ").strip()
        parts = line.split()
        if len(parts) < 4:
            continue
        username = parts[0]
        sid = state = session_name = idle = logon_str = ""
        for i, p in enumerate(parts[1:], 1):
            if p.isdigit() and i + 1 < len(parts) and parts[i + 1] in (
                "Active", "Idle", "Disc", "Disconnected", "Listen", "Conn", "Connect", "Down"
            ):
                sid = p; state = parts[i + 1]
                session_name = " ".join(parts[1:i]) if i > 1 else ""
                idle = parts[i + 2] if i + 2 < len(parts) else ""
                logon_str = " ".join(parts[i + 3:]) if i + 3 < len(parts) else ""
                break
        if not sid:
            sid = parts[1] if parts[1].isdigit() else (parts[2] if len(parts) > 2 and parts[2].isdigit() else "0")
            state = parts[2] if len(parts) > 2 else ""
            idle = parts[3] if len(parts) > 3 else ""
            logon_str = " ".join(parts[4:]) if len(parts) > 4 else ""

        duration = logon_iso = ""
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p"):
            try:
                dt = datetime.datetime.strptime(logon_str, fmt)
                logon_iso = dt.isoformat()
                delta = datetime.datetime.now() - dt
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m, _ = divmod(rem, 60)
                duration = f"{h}h {m}m"
                break
            except Exception:
                continue

        sessions.append({"username": username, "session_id": sid,
                          "session_name": session_name, "state": state,
                          "idle_time": idle, "logon_time": logon_str,
                          "logon_iso": logon_iso, "duration": duration,
                          "current": current, "client_ip": ""})
    return sessions

# ---------------------------------------------------------------------------
# Windows Event Log
# ---------------------------------------------------------------------------
def get_rdp_logs(days: int = 7) -> List[Dict]:
    ps = f"""
    $Start = (Get-Date).AddDays(-{days})
    $Filter = @{{ LogName='Security','Microsoft-Windows-TerminalServices-LocalSessionManager/Operational'; StartTime=$Start }}
    Get-WinEvent -FilterHashtable $Filter -ErrorAction SilentlyContinue |
        Where-Object {{ $_.Id -in @(4624,4634,4647,4778,4779,21,23,24,25) }} |
        ForEach-Object {{
            $e = $_
            $obj = [PSCustomObject]@{{
                TimeCreated=$e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'); EventId=$e.Id
                Username=$null; IpAddress=$null; SessionId=$null; EventType=$null
                Message=($e.Message -replace '`r`n',' ')
            }}
            switch ($e.Id) {{
                4624 {{ $obj.Username=$e.Properties[5].Value; $obj.IpAddress=$e.Properties[18].Value; $obj.EventType=if($e.Properties[8].Value -eq 10){{'RDP_Login'}}else{{'Login'}} }}
                4634 {{ $obj.Username=$e.Properties[1].Value; $obj.EventType='Logoff' }}
                4647 {{ $obj.Username=$e.Properties[1].Value; $obj.EventType='UserInitiatedLogoff' }}
                4778 {{ $obj.Username=$e.Properties[0].Value; $obj.IpAddress=$e.Properties[2].Value; $obj.EventType='SessionReconnected' }}
                4779 {{ $obj.Username=$e.Properties[0].Value; $obj.IpAddress=$e.Properties[2].Value; $obj.EventType='SessionDisconnected' }}
                21   {{ $obj.Username=$e.Properties[0].Value; $obj.SessionId=$e.Properties[1].Value; $obj.IpAddress=$e.Properties[2].Value; $obj.EventType='LocalSessionLogin' }}
                23   {{ $obj.Username=$e.Properties[0].Value; $obj.SessionId=$e.Properties[1].Value; $obj.EventType='LocalSessionLogoff' }}
                24   {{ $obj.Username=$e.Properties[0].Value; $obj.SessionId=$e.Properties[1].Value; $obj.IpAddress=$e.Properties[2].Value; $obj.EventType='LocalSessionDisconnect' }}
                25   {{ $obj.Username=$e.Properties[0].Value; $obj.SessionId=$e.Properties[1].Value; $obj.IpAddress=$e.Properties[2].Value; $obj.EventType='LocalSessionReconnect' }}
            }}
            $obj
        }} | Sort-Object TimeCreated -Descending | ConvertTo-Json -Depth 3
    """
    out = _ps(ps)
    if not out or out.strip() == "":
        return []
    try:
        data = json.loads(out)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []

def get_failed_logins(days: int = 1) -> List[Dict]:
    ps = f"""
    $Start=(Get-Date).AddDays(-{days})
    Get-WinEvent -FilterHashtable @{{LogName='Security';ID=4625;StartTime=$Start}} -ErrorAction SilentlyContinue |
        Select-Object TimeCreated,@{{N='Username';E={{$_.Properties[5].Value}}}},@{{N='IpAddress';E={{$_.Properties[19].Value}}}},@{{N='FailureReason';E={{$_.Properties[8].Value}}}} |
        Sort-Object TimeCreated -Descending | ConvertTo-Json -Depth 3
    """
    out = _ps(ps)
    if not out or out.strip() == "":
        return []
    try:
        data = json.loads(out)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []

def get_recent_events_summary(hours: int = 24) -> Dict:
    ps = f"""
    $Start=(Get-Date).AddHours(-{hours})
    $conn=@(Get-WinEvent -FilterHashtable @{{LogName='Security';ID=4624;StartTime=$Start}} -ErrorAction SilentlyContinue|Where-Object{{$_.Properties[8].Value -eq 10}}).Count
    $disc=@(Get-WinEvent -FilterHashtable @{{LogName='Security';ID=4634,4647;StartTime=$Start}} -ErrorAction SilentlyContinue).Count
    $fail=@(Get-WinEvent -FilterHashtable @{{LogName='Security';ID=4625;StartTime=$Start}} -ErrorAction SilentlyContinue).Count
    [PSCustomObject]@{{connections=$conn;disconnections=$disc;failed_logins=$fail}} | ConvertTo-Json
    """
    try:
        return json.loads(_ps(ps))
    except Exception:
        return {"connections": 0, "disconnections": 0, "failed_logins": 0}

def get_connection_history(hours: int = 24) -> List[Dict]:
    ps = f"""
    $Start=(Get-Date).AddHours(-{hours})
    $events=Get-WinEvent -FilterHashtable @{{LogName='Microsoft-Windows-TerminalServices-LocalSessionManager/Operational';StartTime=$Start}} -ErrorAction SilentlyContinue |
        Where-Object{{$_.Id -in @(21,23,24,25)}} |
        Select-Object TimeCreated,Id,@{{N='Username';E={{$_.Properties[0].Value}}}},@{{N='SessionId';E={{$_.Properties[1].Value}}}},@{{N='IpAddress';E={{$_.Properties[2].Value}}}}
    $sdict=@{{}}
    foreach($e in $events){{if(-not $sdict.ContainsKey($e.SessionId)){{$sdict[$e.SessionId]=@()}} $sdict[$e.SessionId]+=$e}}
    $result=@()
    foreach($sid in $sdict.Keys){{
        $evts=$sdict[$sid]|Sort-Object TimeCreated
        $conn=$evts|Where-Object{{$_.Id -in @(21,25)}}|Select-Object -First 1
        $disc=$evts|Where-Object{{$_.Id -in @(23,24)}}|Select-Object -Last 1
        if($conn){{
            $dur=""; $status="Connected"; $discTime=""
            if($disc -and $disc.TimeCreated -le (Get-Date)){{
                $discTime=$disc.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss')
                $ts=$disc.TimeCreated-$conn.TimeCreated
                $dur="{0}h {1}m" -f $ts.Hours,$ts.Minutes
                $status="Disconnected"
            }}
            $user=$conn.Username; if($user -match '\\\\'){{$user=$user.Split('\\')[1]}}
            $result+=[PSCustomObject]@{{Username=$user;SessionId=$sid;ConnectedAt=$conn.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');DisconnectedAt=$discTime;Duration=$dur;Status=$status;IpAddress=$conn.IpAddress}}
        }}
    }}
    $result|Sort-Object ConnectedAt -Descending|ConvertTo-Json -Depth 3
    """
    out = _ps(ps)
    if not out or out.strip() == "":
        return []
    try:
        data = json.loads(out)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Agent management
# ---------------------------------------------------------------------------
_PIDS_CACHE: dict = {}
_PIDS_TS = 0.0

def _agent_pids() -> dict:
    global _PIDS_TS, _PIDS_CACHE
    now = time.time()
    if now - _PIDS_TS < 5.0:
        return _PIDS_CACHE
    result = {}
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if name in ("python.exe", "pythonw.exe") and "agent.py" in cmdline:
                    parts = cmdline.split()
                    for i, p in enumerate(parts):
                        if p.endswith("agent.py") and i + 1 < len(parts):
                            user = parts[i + 1].lower()
                            if user not in result or proc.info.get("create_time", 0) > result[user][1]:
                                result[user] = (proc.info["pid"], proc.info.get("create_time", 0))
                            break
            except Exception:
                continue
    except Exception:
        pass
    _PIDS_CACHE = result
    _PIDS_TS = now
    return result

def _is_agent_running(username: str) -> bool:
    return username.lower() in _agent_pids()

def _kill_duplicates(username: str):
    user_lower = username.lower()
    try:
        agents = [p for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"])
                  if (p.info.get("name") or "").lower() in ("python.exe", "pythonw.exe")
                  and "agent.py" in " ".join(p.info.get("cmdline") or [])
                  and user_lower in " ".join(p.info.get("cmdline") or []).lower()]
        if len(agents) > 1:
            for old in sorted(agents, key=lambda p: p.info.get("create_time", 0), reverse=True)[1:]:
                try:
                    old.kill()
                except Exception:
                    pass
    except Exception:
        pass

def inject_agents():
    sessions = parse_quser()
    launched = []
    for s in sessions:
        if s["state"] not in ("Active", "Idle", "Disc", "Disconnected"):
            continue
        user = s["username"]
        if user.lower() == "administrator":
            continue
        if _is_agent_running(user):
            continue
        cmd = [config.PSEXEC, "-s", "-i", str(s["session_id"]), "-d",
               config.PYTHON_EXE, config.AGENT_PY, user]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        launched.append({"session_id": s["session_id"], "username": user})
    return launched

def sync_recordings():
    sessions = parse_quser()
    for s in sessions:
        if s["state"] not in ("Active", "Idle"):
            continue
        user = s["username"]
        if user.lower() == "administrator":
            continue
        _kill_duplicates(user)
        if not _is_agent_running(user):
            try:
                cmd = [config.PSEXEC, "-s", "-i", str(s["session_id"]), "-d",
                       config.PYTHON_EXE, config.AGENT_PY, user]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass

_record_thread = None

def _monitor_loop():
    while True:
        try:
            sync_recordings()
        except Exception:
            pass
        time.sleep(45)

def start_recording_monitor():
    global _record_thread
    if _record_thread is None or not _record_thread.is_alive():
        _record_thread = threading.Thread(target=_monitor_loop, daemon=True)
        _record_thread.start()

# ---------------------------------------------------------------------------
# Disk guard  —  auto-cleanup when disk is critically full
# ---------------------------------------------------------------------------
_disk_thread = None

def get_disk_status() -> Dict:
    try:
        usage = psutil.disk_usage("C:\\")
        return {
            "total_gb":  round(usage.total / (1024**3), 1),
            "used_gb":   round(usage.used  / (1024**3), 1),
            "free_gb":   round(usage.free  / (1024**3), 1),
            "percent":   usage.percent,
            "warn":      usage.percent >= config.DISK_WARN_PCT,
            "critical":  usage.percent >= config.DISK_CLEANUP_PCT,
        }
    except Exception:
        return {}

def _disk_guard_loop():
    import logging
    log = logging.getLogger("rdvr")
    while True:
        try:
            status = get_disk_status()
            pct = status.get("percent", 0)
            if pct >= config.DISK_CLEANUP_PCT:
                log.warning(f"Disk {pct}% full — auto-running retention cleanup")
                result = apply_retention(days=3)    # aggressive: keep 3 days
                log.info(f"Auto-cleanup freed {result.get('mb_freed', 0)} MB")
            elif pct >= config.DISK_WARN_PCT:
                log.warning(f"Disk {pct}% full — approaching limit")
        except Exception:
            pass
        time.sleep(300)     # check every 5 minutes

def start_disk_guard():
    global _disk_thread
    if _disk_thread is None or not _disk_thread.is_alive():
        _disk_thread = threading.Thread(target=_disk_guard_loop, daemon=True)
        _disk_thread.start()

# ---------------------------------------------------------------------------
# Recording file management
# ---------------------------------------------------------------------------
def get_recordings() -> List[Dict]:
    recs = []
    if not os.path.isdir(config.RECORD_DIR):
        return recs
    for f in os.listdir(config.RECORD_DIR):
        if not f.lower().endswith(".mp4"):
            continue
        path = os.path.join(config.RECORD_DIR, f)
        try:
            st = os.stat(path)
        except Exception:
            continue
        if st.st_size < 1024:
            continue
        parts = f.replace(".mp4", "").split("_", 1)
        username = parts[0] if len(parts) > 1 else "unknown"
        if username.lower() == "administrator":
            continue
        recs.append({
            "filename": f, "username": username,
            "size": st.st_size,
            "size_mb": round(st.st_size / (1024 * 1024), 2),
            "mtime": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
            "duration_sec": int(st.st_size / 12000),
        })
    return sorted(recs, key=lambda x: x["mtime"], reverse=True)

def get_recordings_for_user(username: str) -> List[Dict]:
    return [r for r in get_recordings() if r["username"].lower() == username.lower()]

def get_total_recording_size() -> float:
    total = 0
    if os.path.isdir(config.RECORD_DIR):
        for f in os.listdir(config.RECORD_DIR):
            if f.lower().endswith(".mp4"):
                try:
                    total += os.path.getsize(os.path.join(config.RECORD_DIR, f))
                except Exception:
                    pass
    return round(total / (1024**3), 3)

def apply_retention(days: int = 7) -> Dict:
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    deleted = {"recordings": 0, "thumbs": 0, "bytes_freed": 0}
    for base, ext in [(config.RECORD_DIR, ".mp4"), (config.THUMB_DIR, ".jpg")]:
        if not os.path.isdir(base):
            continue
        for f in os.listdir(base):
            if not f.lower().endswith(ext):
                continue
            fp = os.path.join(base, f)
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fp))
                if mtime < cutoff:
                    sz = os.path.getsize(fp)
                    os.remove(fp)
                    if ext == ".mp4":
                        deleted["recordings"] += 1
                    else:
                        deleted["thumbs"] += 1
                    deleted["bytes_freed"] += sz
            except Exception:
                pass
    deleted["mb_freed"] = round(deleted["bytes_freed"] / (1024 * 1024), 2)
    return deleted

# ---------------------------------------------------------------------------
# Session control (inputs sanitized in app.py before reaching here)
# ---------------------------------------------------------------------------
def logoff_session(sid: str):     _run(["logoff", sid])
def disconnect_session(sid: str): _run(["tsdiscon", sid])
def msg_session(sid: str, msg: str): _run(["msg", sid, msg[:500]])
def msg_all(msg: str):            _run(["msg", "*", msg[:500]])
def disable_local_user(u: str):   _run(["net", "user", u, "/active:no"])
def enable_local_user(u: str):    _run(["net", "user", u, "/active:yes"])
def reset_password(u: str, pw: str): _run(["net", "user", u, pw])

# ---------------------------------------------------------------------------
# System stats (cached)
# ---------------------------------------------------------------------------
def get_system_stats() -> Dict:
    return _cached("stats", 3.0, _system_stats_raw)

def _system_stats_raw() -> Dict:
    stats = {"cpu": 0, "memory": 0, "disk": 0, "uptime": ""}
    try:
        stats["cpu"]    = psutil.cpu_percent(interval=0.3)
        stats["memory"] = psutil.virtual_memory().percent
        stats["disk"]   = psutil.disk_usage("C:\\").percent
        delta = datetime.datetime.now() - datetime.datetime.fromtimestamp(psutil.boot_time())
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m, _ = divmod(rem, 60)
        stats["uptime"] = f"{h}h {m}m"
    except Exception:
        pass
    return stats

def get_rdvr_stats() -> Dict:
    return _cached("rdvr_stats", 5.0, _rdvr_stats_raw)

def _rdvr_stats_raw() -> Dict:
    stats = {"total_cpu": 0.0, "total_ram_mb": 0.0, "processes": [],
             "agent_count": 0, "ffmpeg_count": 0}
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent", "memory_info"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmd  = " ".join(proc.info.get("cmdline") or [])
                if   name in ("python.exe", "pythonw.exe") and "agent.py" in cmd: ptype = "agent"
                elif name in ("python.exe", "pythonw.exe") and "app.py"   in cmd: ptype = "server"
                elif name == "ffmpeg.exe":   ptype = "ffmpeg"
                elif name == "psexec.exe":   ptype = "psexec"
                else: continue
                cpu  = proc.info.get("cpu_percent") or 0.0
                ram  = proc.info.get("memory_info")
                rmb  = round(ram.rss / (1024 * 1024), 2) if ram else 0.0
                stats["total_cpu"]    += cpu
                stats["total_ram_mb"] += rmb
                if ptype == "agent":  stats["agent_count"]  += 1
                if ptype == "ffmpeg": stats["ffmpeg_count"] += 1
                stats["processes"].append({"pid": proc.info["pid"], "name": proc.info.get("name",""),
                                            "type": ptype, "cpu": round(cpu,2), "ram_mb": rmb,
                                            "cmdline": cmd[:100]})
            except Exception:
                continue
        stats["total_cpu"]    = round(stats["total_cpu"], 2)
        stats["total_ram_mb"] = round(stats["total_ram_mb"], 2)
    except Exception:
        pass
    return stats

def get_active_processes_top5() -> List[Dict]:
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except Exception:
                pass
        return sorted(procs, key=lambda x: x.get("cpu_percent", 0), reverse=True)[:5]
    except Exception:
        return []

# ---------------------------------------------------------------------------
# User notes
# ---------------------------------------------------------------------------
def save_user_note(username: str, note: str) -> bool:
    if not MEM0_KEY:
        return False
    try:
        r = httpx.post(f"{MEM0_API}/v1/memories/",
                        headers={"Authorization": f"Token {MEM0_KEY}"},
                        json={"messages": [{"role": "user", "content": f"RDP note for {username}: {note}"}],
                              "user_id": f"rdp-note-{username}", "agent_id": "rdp-dashboard",
                              "run_id": datetime.datetime.now().isoformat(),
                              "metadata": {"source": "rdp-dashboard", "username": username}},
                        timeout=15.0)
        return r.status_code in (200, 201)
    except Exception:
        return False

def get_user_notes(username: str) -> List[str]:
    if not MEM0_KEY:
        return []
    try:
        r = httpx.get(f"{MEM0_API}/v1/memories/",
                       headers={"Authorization": f"Token {MEM0_KEY}"},
                       params={"user_id": f"rdp-note-{username}"}, timeout=15.0)
        if r.status_code == 200:
            return [i.get("memory", "") for i in r.json().get("results", [])]
    except Exception:
        pass
    return []
