"""
agent.py — Per-session screen recorder for RDVR v2.1
Launched by PsExec -s -i <sid> inside each RDP session.
Uses mss for capture (gdigrab fails in some RDP contexts).
Pipes raw BGRA frames to FFmpeg for hardware encoding.
All settings loaded from config.ini — no hardcoded values.
"""
import os
import sys
import time
import random
import subprocess
import threading
from datetime import datetime

# ---------------------------------------------------------------------------
# Load config (graceful fallback if config.ini not found)
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

try:
    import config
    FPS         = config.FPS
    THUMB_FPS   = config.THUMB_FPS
    THUMB_W     = config.THUMB_W
    SEGMENT_SEC = config.SEGMENT_SEC
    CRF         = config.CRF
    MAXRATE     = config.MAXRATE
    FFMPEG      = config.FFMPEG
    ENCODER_CFG = config.ENCODER
    BASE_DIR    = config.BASE_DIR
    THUMB_DIR   = config.THUMB_DIR
    RECORD_DIR  = config.RECORD_DIR
    LOG_DIR     = config.LOG_DIR
except Exception:
    # Hard defaults if config.ini is missing
    FPS         = 1.0
    THUMB_FPS   = 1.0
    THUMB_W     = 320
    SEGMENT_SEC = 120
    CRF         = 28
    MAXRATE     = "500k"
    FFMPEG      = r"C:\Users\Administrator\ffmpeg.exe"
    ENCODER_CFG = ""
    BASE_DIR    = r"C:\Users\Public\sentineldesk"
    THUMB_DIR   = os.path.join(BASE_DIR, "thumbs")
    RECORD_DIR  = os.path.join(BASE_DIR, "recordings")
    LOG_DIR     = os.path.join(BASE_DIR, "logs")

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "unknown"

for d in (THUMB_DIR, RECORD_DIR, LOG_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_path = os.path.join(LOG_DIR, f"{USERNAME}.log")

def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {USERNAME}: {msg}\n")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Encoder detection — functional encode test (not just -encoders list)
# ---------------------------------------------------------------------------
ENCODER_ARGS = {
    "h264_nvenc": ["-c:v","h264_nvenc","-preset","p4","-rc","vbr","-cq","26","-b:v","0","-maxrate",MAXRATE,"-bufsize","2m"],
    "h264_qsv":   ["-c:v","h264_qsv","-global_quality","26","-preset","veryfast","-maxrate",MAXRATE,"-bufsize","2m"],
    "h264_amf":   ["-c:v","h264_amf","-quality","speed","-rc","vbr_latency","-b:v",MAXRATE,"-maxrate",MAXRATE],
    "libx264":    ["-c:v","libx264","-preset","veryfast","-crf",str(CRF),"-maxrate",MAXRATE,"-bufsize","2m"],
}

def detect_encoder() -> str:
    """Probe hardware encoders with a 1-second functional test; fall back to CPU."""
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            cmd = [
                FFMPEG, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=30",
                *ENCODER_ARGS[enc], "-f", "null", "-",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0:
                _log(f"[encoder] {enc} (hardware)")
                return enc
            else:
                _log(f"[encoder] {enc} probe failed: rc={r.returncode}")
        except Exception as e:
            _log(f"[encoder] {enc} probe error: {e}")
    _log("[encoder] libx264 (CPU)")
    return "libx264"

# ---------------------------------------------------------------------------
# Screen capture via mss
# ---------------------------------------------------------------------------
POPEN_FLAGS = subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW

def _get_screen_size():
    try:
        import mss
        with mss.MSS() as sct:
            mon = sct.monitors[1]  # primary monitor
            w, h = mon["width"], mon["height"]
            # H.264/YUV420P requires even width/height; round down
            w = w & ~1
            h = h & ~1
            return w, h
    except Exception:
        return 1920, 1080

_SCREEN_W, _SCREEN_H = _get_screen_size()
_log(f"[screen] {_SCREEN_W}x{_SCREEN_H}")

def build_record_cmd(template: str, encoder: str) -> list:
    g = max(1, int(FPS * 120))
    return [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgra",
        "-s", f"{_SCREEN_W}x{_SCREEN_H}", "-r", str(FPS),
        "-thread_queue_size", "512", "-i", "-",  # stdin
        *ENCODER_ARGS[encoder],
        "-g", str(g), "-pix_fmt", "yuv420p",
        "-f", "segment", "-segment_time", str(SEGMENT_SEC),
        "-reset_timestamps", "1", "-strftime", "1", "-y", template,
    ]

# ---------------------------------------------------------------------------
# Thumbnail thread — pure Python (mss + PIL), no FFmpeg needed
# Saves TWO files: small thumb for grid + large preview for enlarged view
# ---------------------------------------------------------------------------
PREVIEW_W = 1280

def _thumb_loop(thumb_path: str, preview_path: str, stop_event: threading.Event):
    """Capture screen with mss and save resized JPG via PIL (small + large)."""
    try:
        import mss
        from PIL import Image
        with mss.MSS() as sct:
            monitor = sct.monitors[1]
            while not stop_event.is_set():
                t0 = time.time()
                try:
                    img = sct.grab(monitor)
                    im = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                    w, h = im.size
                    # Small thumbnail for grid
                    new_h = max(1, int(h * THUMB_W / w))
                    thumb = im.resize((THUMB_W, new_h), Image.LANCZOS)
                    thumb.save(thumb_path, "JPEG", quality=75)
                    # Large preview for enlarged view (main feed)
                    prev_h = max(1, int(h * PREVIEW_W / w))
                    preview = im.resize((PREVIEW_W, prev_h), Image.LANCZOS)
                    preview.save(preview_path, "JPEG", quality=80)
                except Exception as e:
                    _log(f"[thumbnailer] save error: {e}")
                elapsed = time.time() - t0
                sleep_for = (1.0 / THUMB_FPS) - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)
    except Exception as e:
        _log(f"[thumbnailer] thread crashed: {e}")
    finally:
        _log("[thumbnailer] thread exiting")

# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------
def _ffmpeg_log(label: str):
    try:
        return open(os.path.join(LOG_DIR, f"{USERNAME}_{label}.log"), "a",
                    encoding="utf-8", errors="ignore")
    except Exception:
        return subprocess.DEVNULL

def start_proc(cmd: list, label: str, stdin_pipe: bool = False) -> subprocess.Popen:
    _log(f"[proc] start {label}")
    kw = dict(stdout=subprocess.DEVNULL, stderr=_ffmpeg_log(label),
              creationflags=POPEN_FLAGS)
    if stdin_pipe:
        kw["stdin"] = subprocess.PIPE
    return subprocess.Popen(cmd, **kw)

def is_alive(proc) -> bool:
    return proc is not None and proc.poll() is None

def stop_proc(proc, label: str):
    if not is_alive(proc):
        return
    _log(f"[proc] stop {label} pid={proc.pid}")
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Capture threads — write raw BGRA frames to FFmpeg stdin
# ---------------------------------------------------------------------------
def _capture_loop(proc: subprocess.Popen, fps: float, label: str):
    """Capture screen with mss and write raw BGRA to FFmpeg stdin."""
    try:
        import mss
        with mss.MSS() as sct:
            monitor = sct.monitors[1]  # primary monitor
            interval = 1.0 / fps
            frame_size = _SCREEN_W * _SCREEN_H * 4
            while is_alive(proc):
                t0 = time.time()
                try:
                    img = sct.grab(monitor)
                    # Truncate to even dimensions required by H.264 encoder
                    if img.size[0] == _SCREEN_W:
                        frame = img.bgra[:frame_size]
                    else:
                        # width is odd — reconstruct by stripping last column from each row
                        row_bytes = img.size[0] * 4
                        target_row = _SCREEN_W * 4
                        frame = bytearray()
                        raw = img.bgra
                        for row in range(_SCREEN_H):
                            frame.extend(raw[row*row_bytes : row*row_bytes + target_row])
                        frame = bytes(frame)
                    if is_alive(proc) and proc.stdin:
                        proc.stdin.write(frame)
                except (BrokenPipeError, OSError):
                    break
                except Exception as e:
                    _log(f"[{label}] capture error: {e}")
                elapsed = time.time() - t0
                sleep_for = interval - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)
    except Exception as e:
        _log(f"[{label}] thread crashed: {e}")
    finally:
        _log(f"[{label}] capture thread exiting")

# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------
def main():
    time.sleep(random.uniform(0.0, 5.0))     # thundering-herd prevention

    # Attach to interactive desktop so mss/gdigrab can capture screen
    # (needed when launched via PsExec / services)
    try:
        from win_desktop import attach_to_interactive_desktop
        attach_to_interactive_desktop()
        _log("[desktop] attached to WinSta0\\Default")
    except Exception as e:
        _log(f"[desktop] attach warning: {e}")

    if ENCODER_CFG and ENCODER_CFG in ENCODER_ARGS:
        encoder = ENCODER_CFG
        _log(f"[encoder] forced {encoder} from config.ini")
    else:
        encoder = detect_encoder()
    thumb_path    = os.path.join(THUMB_DIR, f"{USERNAME.lower()}.jpg")
    preview_path  = os.path.join(THUMB_DIR, f"{USERNAME.lower()}_preview.jpg")

    def fresh_template():
        return os.path.join(RECORD_DIR, f"{USERNAME}_%Y%m%d_%H%M%S.mp4")

    # --- start recorder ---
    rec_proc = start_proc(build_record_cmd(fresh_template(), encoder), "recorder", stdin_pipe=True)
    rec_thread = threading.Thread(target=_capture_loop, args=(rec_proc, FPS, "recorder"), daemon=True)
    rec_thread.start()

    # --- start thumbnailer (Python thread, no FFmpeg subprocess) ---
    thumb_stop = threading.Event()
    thumb_thread = threading.Thread(target=_thumb_loop, args=(thumb_path, preview_path, thumb_stop), daemon=True)
    thumb_thread.start()

    _log(f"[run] encoder={encoder} rec={rec_proc.pid} thumb=thread")

    try:
        while True:
            time.sleep(10)
            if not is_alive(rec_proc):
                _log(f"[recorder] exited code={rec_proc.returncode}, restarting")
                stop_proc(rec_proc, "recorder")
                rec_proc = start_proc(build_record_cmd(fresh_template(), encoder), "recorder", stdin_pipe=True)
                rec_thread = threading.Thread(target=_capture_loop, args=(rec_proc, FPS, "recorder"), daemon=True)
                rec_thread.start()
            if not thumb_thread.is_alive():
                _log("[thumbnailer] thread died, restarting")
                thumb_stop = threading.Event()
                thumb_thread = threading.Thread(target=_thumb_loop, args=(thumb_path, preview_path, thumb_stop), daemon=True)
                thumb_thread.start()
    except KeyboardInterrupt:
        _log("[stop] KeyboardInterrupt")
    finally:
        _log("[stop] shutting down")
        stop_proc(rec_proc, "recorder")
        thumb_stop.set()
        _log("[stop] done")

if __name__ == "__main__":
    main()
