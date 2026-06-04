"""
config.py — Central configuration loader.
Reads config.ini from the same directory as this file.
All other modules import from here — no hardcoded values anywhere else.
"""
import configparser
import os
import secrets

_INI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

_cfg = configparser.ConfigParser()
_cfg.read(_INI, encoding="utf-8")

def _get(section, key, fallback=""):
    return _cfg.get(section, key, fallback=fallback)

def _int(section, key, fallback=0):
    return _cfg.getint(section, key, fallback=fallback)

def _float(section, key, fallback=0.0):
    return _cfg.getfloat(section, key, fallback=fallback)

# ---- Server ----
HOST       = _get("server", "host",       "0.0.0.0")
PORT       = _int("server", "port",       7777)
THREADS    = _int("server", "threads",    8)
SECRET_KEY = _get("server", "secret_key", secrets.token_hex(32))
SSL_CERT   = _get("server", "ssl_cert",   "")
SSL_KEY    = _get("server", "ssl_key",    "")

# ---- Auth ----
AUTH_USERNAME = _get("auth", "username",      "admin")
AUTH_HASH     = _get("auth", "password_hash", "")

# ---- Recording ----
FPS         = _float("recording", "fps",         0.5)
THUMB_FPS   = _float("recording", "thumb_fps",   0.1)
THUMB_W     = _int  ("recording", "thumb_width", 320)
SEGMENT_SEC = _int  ("recording", "segment_sec", 300)
CRF         = _int  ("recording", "crf",         28)
MAXRATE     = _get  ("recording", "maxrate",     "500k")
FFMPEG      = _get  ("recording", "ffmpeg",      r"C:\Users\Administrator\ffmpeg.exe")
ENCODER     = _get  ("recording", "encoder",     "")   # empty = auto-detect

# ---- Paths ----
BASE_DIR   = _get("paths", "base_dir", r"C:\Users\Public\sentineldesk")
PSEXEC     = _get("paths", "psexec",   r"C:\Users\Administrator\psexec.exe")
PYTHON_EXE = _get("paths", "python",   r"C:\Program Files\Python312\pythonw.exe")

THUMB_DIR  = os.path.join(BASE_DIR, "thumbs")
RECORD_DIR = os.path.join(BASE_DIR, "recordings")
LOG_DIR    = os.path.join(BASE_DIR, "logs")
AGENT_PY   = os.path.join(BASE_DIR, "agent.py")

# ---- Retention / Disk ----
AUTO_DAYS        = _int("retention", "auto_days",            7)
DISK_WARN_PCT    = _int("retention", "disk_warn_percent",    80)
DISK_CLEANUP_PCT = _int("retention", "disk_cleanup_percent", 90)
