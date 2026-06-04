"""
auth.py — Authentication helpers.
Uses PBKDF2-HMAC-SHA256 (Python stdlib — no extra packages needed).
"""
import hashlib
import hmac
import secrets
from functools import wraps
from flask import session, redirect, url_for, request, jsonify
import config


def hash_password(password: str) -> str:
    """Hash a plaintext password. Returns a storable string."""
    salt   = secrets.token_hex(16)
    iters  = 260000
    dk     = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iters)
    return f"pbkdf2:sha256:{iters}:{salt}:{dk.hex()}"


def check_password(password: str, stored: str) -> bool:
    """Verify a plaintext password against a stored hash. Constant-time compare."""
    try:
        _, algo, iters, salt, expected = stored.split(":", 4)
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), expected)
    except Exception:
        return False


def verify_login(username: str, password: str) -> bool:
    """Check username + password against config."""
    if username != config.AUTH_USERNAME:
        return False
    if not config.AUTH_HASH:
        return False          # no password set — deny all
    return check_password(password, config.AUTH_HASH)


def login_required(f):
    """Decorator: redirect to /login if not authenticated. API routes return 401."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("authenticated"):
            return f(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("login_page", next=request.full_path))
    return wrapper
