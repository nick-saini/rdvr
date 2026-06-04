"""
app.py — SentinelDesk Flask server
Features: session auth, HTTPS, log rotation, graceful shutdown, disk guard, input sanitization
"""
import os
import ssl
import time
import atexit
import signal
import logging
from logging.handlers import RotatingFileHandler

import psutil
from flask import (Flask, Response, send_from_directory, request,
                   jsonify, send_file, render_template, session, redirect, url_for)

import config
import rdp_utils
from auth import login_required, verify_login

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = config.SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 3600 * 8    # 8-hour sessions

# ---------------------------------------------------------------------------
# Logging with rotation
# ---------------------------------------------------------------------------
os.makedirs(config.LOG_DIR, exist_ok=True)
_log_path = os.path.join(config.LOG_DIR, "server.log")
_handler  = RotatingFileHandler(_log_path, maxBytes=5*1024*1024, backupCount=5,
                                 encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger("rdvr")

# ---------------------------------------------------------------------------
# Single-instance guard (kill any stale app.py before starting)
# ---------------------------------------------------------------------------
_me = os.getpid()
for _p in psutil.process_iter(["pid", "cmdline"]):
    try:
        if _p.info["pid"] != _me and "app.py" in " ".join(_p.info.get("cmdline") or []):
            try:
                _p.terminate()
                time.sleep(0.3)
                if _p.is_running():
                    _p.kill()
            except Exception:
                pass
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
def _shutdown(signum=None, frame=None):
    log.info("Shutdown signal received — killing all agents and FFmpeg processes")
    try:
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (p.info.get("name") or "").lower()
                cmd  = " ".join(p.info.get("cmdline") or [])
                if (name in ("python.exe", "pythonw.exe") and "agent.py" in cmd) \
                        or name == "ffmpeg.exe":
                    p.terminate()
            except Exception:
                pass
    except Exception:
        pass

atexit.register(_shutdown)
for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, _shutdown)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Input sanitization helpers
# ---------------------------------------------------------------------------
import re

def _safe_sid(sid: str) -> str:
    """Session IDs must be numeric."""
    if not re.match(r"^\d{1,10}$", str(sid)):
        raise ValueError(f"Invalid session_id: {sid!r}")
    return str(sid)

def _safe_username(username: str) -> str:
    """Usernames: alphanumeric + dash/underscore/dot, max 64 chars."""
    if not re.match(r"^[A-Za-z0-9._\-]{1,64}$", str(username)):
        raise ValueError(f"Invalid username: {username!r}")
    return str(username)

def _bad_input(e: Exception):
    log.warning(f"Bad input: {e}")
    return jsonify({"error": "invalid input"}), 400

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("authenticated"):
        return redirect(url_for("index"))

    error = None
    username = ""
    next_url = request.args.get("next", "/")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        next_url = request.form.get("next", "/")

        if verify_login(username, password):
            session.permanent = True
            session["authenticated"] = True
            session["user"] = username
            log.info(f"Login: {username} from {request.remote_addr}")
            return redirect(next_url if next_url.startswith("/") else "/")
        else:
            log.warning(f"Failed login: {username!r} from {request.remote_addr}")
            error = "Invalid username or password"

    return render_template("login.html", error=error, username=username,
                           next=next_url if next_url != "/" else "")


@app.route("/logout")
def logout():
    user = session.get("user", "unknown")
    session.clear()
    log.info(f"Logout: {user}")
    return redirect(url_for("login_page"))


# ---------------------------------------------------------------------------
# MJPEG streaming
# ---------------------------------------------------------------------------
@app.route("/stream/<username>")
@login_required
def stream_user(username):
    try:
        username = _safe_username(username)
    except ValueError as e:
        return _bad_input(e)
    if username.lower() == "administrator":
        return "", 204

    thumb_path = os.path.join(config.THUMB_DIR, f"{username.lower()}.jpg")

    def generate():
        last_frame = None
        last_mtime = 0.0
        last_check = 0.0
        while True:
            now = time.time()
            if now - last_check >= 1.0:
                last_check = now
                try:
                    mtime = os.path.getmtime(thumb_path)
                    if mtime != last_mtime:
                        with open(thumb_path, "rb") as f:
                            last_frame = f.read()
                        last_mtime = mtime
                except Exception:
                    pass
            if last_frame:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + last_frame + b"\r\n")
            time.sleep(1)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/preview/<username>")
@login_required
def preview_user(username):
    """MJPEG stream of high-res preview image (1280px) for enlarged view."""
    try:
        username = _safe_username(username)
    except ValueError as e:
        return _bad_input(e)
    if username.lower() == "administrator":
        return "", 204

    preview_path = os.path.join(config.THUMB_DIR, f"{username.lower()}_preview.jpg")

    def generate():
        last_frame = None
        last_mtime = 0.0
        last_check = 0.0
        while True:
            now = time.time()
            if now - last_check >= 1.0:
                last_check = now
                try:
                    mtime = os.path.getmtime(preview_path)
                    if mtime != last_mtime:
                        with open(preview_path, "rb") as f:
                            last_frame = f.read()
                        last_mtime = mtime
                except Exception:
                    pass
            if last_frame:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + last_frame + b"\r\n")
            time.sleep(1)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/thumb/<filename>")
@login_required
def thumb(filename):
    user = filename.replace(".jpg", "").lower()
    if user == "administrator":
        return "", 404
    return send_from_directory(config.THUMB_DIR, filename)


@app.route("/recording/<filename>")
@login_required
def recording(filename):
    try:
        user = _safe_username(filename.split("_", 1)[0])
    except ValueError as e:
        return _bad_input(e)
    if user.lower() == "administrator":
        return "", 404
    path = os.path.join(config.RECORD_DIR, filename)
    if not os.path.isfile(path):
        return "", 404
    return send_file(path, mimetype="video/mp4")


# ---------------------------------------------------------------------------
# Dashboard API — all protected
# ---------------------------------------------------------------------------
def _json(data):
    resp = jsonify(data)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/api/sessions")
@login_required
def api_sessions():
    return _json(rdp_utils.parse_quser())


@app.route("/api/sessions/<sid>", methods=["DELETE"])
@login_required
def delete_session(sid):
    try:
        rdp_utils.logoff_session(_safe_sid(sid))
    except ValueError as e:
        return _bad_input(e)
    return _json({"status": "logged_off"})


@app.route("/api/sessions/<sid>/disconnect", methods=["POST"])
@login_required
def disconnect_session_api(sid):
    try:
        rdp_utils.disconnect_session(_safe_sid(sid))
    except ValueError as e:
        return _bad_input(e)
    return _json({"status": "disconnected"})


@app.route("/api/sessions/<sid>/message", methods=["POST"])
@login_required
def message_session_api(sid):
    try:
        rdp_utils.msg_session(_safe_sid(sid), request.json.get("message", "")[:500])
    except ValueError as e:
        return _bad_input(e)
    return _json({"status": "message_sent"})


@app.route("/api/users/<username>/disable", methods=["POST"])
@login_required
def disable_user(username):
    try:
        rdp_utils.disable_local_user(_safe_username(username))
    except ValueError as e:
        return _bad_input(e)
    return _json({"status": "disabled"})


@app.route("/api/users/<username>/enable", methods=["POST"])
@login_required
def enable_user(username):
    try:
        rdp_utils.enable_local_user(_safe_username(username))
    except ValueError as e:
        return _bad_input(e)
    return _json({"status": "enabled"})


@app.route("/api/users/<username>/reset", methods=["POST"])
@login_required
def reset_user_password(username):
    try:
        rdp_utils.reset_password(_safe_username(username),
                                  request.json.get("password", "")[:128])
    except ValueError as e:
        return _bad_input(e)
    return _json({"status": "password_reset"})


@app.route("/api/rdp_logs")
@login_required
def api_rdp_logs():
    return _json(rdp_utils.get_rdp_logs(days=7))


@app.route("/api/failed_logins")
@login_required
def api_failed_logins():
    return _json(rdp_utils.get_failed_logins(days=1))


@app.route("/api/connection_history")
@login_required
def api_connection_history():
    return _json(rdp_utils.get_connection_history(hours=24))


@app.route("/api/recent_summary")
@login_required
def api_recent_summary():
    return _json(rdp_utils.get_recent_events_summary(hours=24))


@app.route("/api/system_stats")
@login_required
def api_system_stats():
    return _json(rdp_utils.get_system_stats())


@app.route("/api/top_processes")
@login_required
def api_top_processes():
    return _json(rdp_utils.get_active_processes_top5())


@app.route("/api/record/sync", methods=["POST"])
@login_required
def sync_recordings():
    rdp_utils.sync_recordings()
    return _json({"status": "synced", "sessions": rdp_utils.parse_quser()})


@app.route("/api/recordings")
@login_required
def api_recordings():
    user = request.args.get("user", "")
    if user:
        try:
            user = _safe_username(user)
        except ValueError as e:
            return _bad_input(e)
        return _json(rdp_utils.get_recordings_for_user(user))
    return _json(rdp_utils.get_recordings())


@app.route("/api/recordings/<username>")
@login_required
def api_recordings_user(username):
    try:
        return _json(rdp_utils.get_recordings_for_user(_safe_username(username)))
    except ValueError as e:
        return _bad_input(e)


@app.route("/api/rdvr_stats")
@login_required
def api_rdvr_stats():
    return _json(rdp_utils.get_rdvr_stats())


@app.route("/api/recording/size")
@login_required
def api_total_size():
    return _json({"total_gb": rdp_utils.get_total_recording_size()})


@app.route("/api/disk_status")
@login_required
def api_disk_status():
    return _json(rdp_utils.get_disk_status())


@app.route("/api/retention", methods=["POST"])
@login_required
def api_retention():
    days = request.json.get("days", config.AUTO_DAYS)
    result = rdp_utils.apply_retention(days=int(days))
    log.info(f"Retention applied: {result}")
    return _json(result)


@app.route("/api/notes/<username>", methods=["GET", "POST"])
@login_required
def user_notes(username):
    try:
        username = _safe_username(username)
    except ValueError as e:
        return _bad_input(e)
    if request.method == "POST":
        note = request.json.get("note", "")[:2000]
        ok = rdp_utils.save_user_note(username, note)
        return _json({"status": "saved" if ok else "failed"})
    return _json({"notes": rdp_utils.get_user_notes(username)})


@app.route("/api/inject_agents", methods=["POST"])
@login_required
def api_inject_agents():
    result = rdp_utils.inject_agents()
    log.info(f"Agents injected: {result}")
    return _json(result)


# ---------------------------------------------------------------------------
# Dashboard entry point
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    return send_file("templates/nvr.html")


@app.route("/live")
@login_required
def live_wall():
    return send_file("templates/live.html")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    rdp_utils.start_recording_monitor()
    rdp_utils.start_disk_guard()        # background disk watcher
    log.info(f"RDVR starting on port {config.PORT}")

    import waitress

    ssl_ctx = None
    if config.SSL_CERT and config.SSL_KEY:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(config.SSL_CERT, config.SSL_KEY)
        log.info("HTTPS enabled")
    else:
        log.warning("Running over HTTP — set ssl_cert/ssl_key in config.ini for HTTPS")

    serve_kw = dict(host=config.HOST, port=config.PORT,
                    threads=config.THREADS, channel_timeout=300)
    try:
        if ssl_ctx:
            serve_kw["ssl_context"] = ssl_ctx
        waitress.serve(app, **serve_kw)
    except ValueError as e:
        if "ssl_context" in str(e):
            log.warning("Installed waitress does not support ssl_context; serving HTTP only.")
            serve_kw.pop("ssl_context", None)
            waitress.serve(app, **serve_kw)
        else:
            raise
