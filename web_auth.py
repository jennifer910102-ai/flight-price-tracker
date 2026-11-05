"""網頁密碼登入 (Render + Discord 版)

設定環境變數 WEB_PASSWORD 後，網頁改用密碼登入，不需要 LINE：
- 所有網頁和 API 都要先登入，沒登入的網頁會導到 /login，API 回 401
- 登入後一律使用 WEB_USER_ID (預設 "me") 這個使用者，跟只用 GitHub 時 config.json 裡的 "me" 是同一個
沒設定 WEB_PASSWORD 時完全不影響原本的 LINE (LIFF) 登入
"""
import os
import hashlib
from datetime import timedelta
from urllib.parse import quote
from flask import request, session, redirect, jsonify

# 不用登入就能存取的路徑 (LINE Webhook 是 LINE 伺服器呼叫的)
PUBLIC_PATHS = {"/login", "/callback"}

def password_mode():
    return bool(os.getenv("WEB_PASSWORD"))

def web_user_id():
    return os.getenv("WEB_USER_ID", "me")

def current_user_id(requested_id):
    """API 要操作哪個使用者：密碼模式一律用登入的使用者 (不信任網頁送來的 ID)，LINE 模式沿用 LIFF 給的 userId"""
    return session.get("web_user") if password_mode() else requested_id

def init_app(app):
    if not password_mode():
        return
    # 沒另外設定 SECRET_KEY 時由密碼推導；改密碼後舊的登入會自動失效
    app.secret_key = os.getenv("SECRET_KEY") or hashlib.sha256(("price-tracker:" + os.environ["WEB_PASSWORD"]).encode()).hexdigest()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(os.getenv("RENDER")),  # Render 上一律是 https
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    app.before_request(_require_login)

def _require_login():
    if request.path in PUBLIC_PATHS or session.get("web_user"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "status": "error", "error": "請先登入", "message": "請先登入"}), 401
    return redirect("/login?next=" + quote(request.full_path.rstrip("?")))

def safe_next(target):
    """登入後要回到的頁面，只允許站內路徑，避免被拿來導到別的網站"""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/liff/monitor"
