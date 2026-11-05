"""通知模組：依使用者設定把訊息送到 LINE 和 / 或 Discord

規則
- LINE：使用者 ID 是 LINE userId (U 開頭 33 碼) 且有設定 LINE_CHANNEL_ACCESS_TOKEN
- Discord：使用者在 config.json 有 "discord_webhook"；
  沒有任何通知管道的使用者 (例如只用 GitHub Actions 的分享版) 會改用環境變數 DISCORD_WEBHOOK_URL
"""
import os
import re
import requests
from utils import load_config

DISCORD_LIMIT = 2000  # Discord 單則訊息字數上限

class NotifyError(Exception):
    pass

def _is_line_user(user_id):
    return bool(re.fullmatch(r"U[0-9a-f]{32}", str(user_id)))

def channels_for(user_id, user_info=None):
    """回傳這位使用者可用的通知管道，例如 [("line", "U..."), ("discord", "https://...")]"""
    if user_info is None:
        user_info = load_config().get("users", {}).get(user_id, {})
    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    default_webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    channels = []
    if line_token and _is_line_user(user_id):
        channels.append(("line", user_id))
    if user_info.get("discord_webhook"):
        channels.append(("discord", user_info["discord_webhook"]))
    if not channels and default_webhook:
        channels.append(("discord", default_webhook))
    return channels

def _send_line(user_id, text):
    from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, PushMessageRequest, TextMessage
    with ApiClient(Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""))) as api_client:
        MessagingApi(api_client).push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=text)]))

def _send_discord(webhook_url, text):
    # 超過字數上限就拆成多則 (以換行為界)
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > DISCORD_LIMIT:
            chunks.append(current)
            current = ""
        current += line + "\n"
    chunks.append(current)
    for chunk in chunks:
        res = requests.post(webhook_url, json={"content": chunk[:DISCORD_LIMIT]}, timeout=15)
        if res.status_code >= 300:
            raise NotifyError(f"Discord 回應 {res.status_code}: {res.text[:200]}")

def notify(user_id, text, user_info=None):
    """送出通知；至少一個管道成功就算成功，全部失敗時丟出 NotifyError"""
    channels = channels_for(user_id, user_info)
    if not channels:
        raise NotifyError("沒有可用的通知管道 (請設定 LINE 或 DISCORD_WEBHOOK_URL)")
    errors = []
    for kind, target in channels:
        try:
            _send_line(target, text) if kind == "line" else _send_discord(target, text)
        except Exception as e:
            errors.append(f"{kind}: {e}")
            print(f"❌ {kind} 通知失敗 ({user_id}): {e}")
    if len(errors) == len(channels):
        raise NotifyError("；".join(errors))
