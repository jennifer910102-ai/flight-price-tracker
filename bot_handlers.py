import os
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from linebot.v3.messaging import ApiClient, MessagingApi, ReplyMessageRequest, FlexMessage, FlexContainer, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent

from utils import load_config, save_config, save_price_history, sync_history_to_github

try:
    from server import scrape_flight_price
except ImportError:
    scrape_flight_price = None

WEEKDAYS = "一二三四五六日"
# 一次「查價」最多查幾筆，避免一個指令就用掉太多 SerpApi 額度
QUICK_CHECK_LIMIT = 8
# reply token 有使用期限，超過這個秒數就改用 push 送結果
REPLY_DEADLINE_SECONDS = 50

def _fmt_date(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.month:02d}/{d.day:02d} ({WEEKDAYS[d.weekday()]})"
    except ValueError:
        return date_str

def _check_one_flight(origin, dest, search_date, target_f):
    search_config = {
        "origin": origin, "destination": dest, "search_date": search_date,
        "trip_type": "one_way", "mode": "flight", "outbound_flight": target_f
    }
    try:
        return scrape_flight_price(search_config, mode="flight")
    except Exception as e:
        return {"min_price": None, "error": str(e)}

def quick_check_and_reply(user_id, reply_token, segments, configuration, started_at):
    """「查價」指令：平行查詢所有監控中的航班，整理成一則訊息回覆
    用 reply (不佔 LINE 每月推播額度)，只有查太久 reply token 過期時才改用 push"""
    from linebot.v3.messaging import PushMessageRequest

    tz_tw = timezone(timedelta(hours=8))
    today = datetime.now(tz_tw).strftime("%Y-%m-%d")
    jobs = []
    for seg in segments:
        for ds in seg.get("date_schedules", []):
            if not ds.get("date") or ds["date"] < today:
                continue
            for target_f in (ds.get("flights") or [""]):
                jobs.append((seg.get("origin", "TPE"), seg.get("destination", "KIX"), ds["date"], target_f))

    skipped = max(0, len(jobs) - QUICK_CHECK_LIMIT)
    jobs = jobs[:QUICK_CHECK_LIMIT]
    if not jobs:
        msg = "目前沒有尚未出發的監控航班。輸入「設定」可以新增。"
    else:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda j: _check_one_flight(*j), jobs))

        lines = [f"💵 即時查價結果（{datetime.now(tz_tw).strftime('%m/%d %H:%M')}）", "--------------------"]
        last_route = None
        for (origin, dest, date, target_f), r in zip(jobs, results):
            route = (origin, dest, date)
            if route != last_route:
                lines.append("")
                lines.append(f"✈️ {origin} → {dest}｜{_fmt_date(date)}")
                last_route = route
            if not isinstance(r, dict) or not r.get("min_price"):
                lines.append(f"   ⚠️ {target_f or '當日最低價'}：查詢失敗")
                continue
            if target_f and not r.get("outbound_target_found"):
                lines.append(f"   ⚠️ {target_f}：當日直飛清單中找不到")
                continue
            label = r.get("outbound_flight_no") or target_f or "當日最低價"
            lines.append(f"   {'🎯' if target_f else '🔥'} {label}：NT$ {r['min_price']:,}")
            save_price_history(flight_data=r.get("outbound_flight_no", "") or target_f, current_price=r["min_price"],
                               user_id=user_id, origin=origin, dest=dest, date=date, sync_github=False)
        if skipped:
            lines.append(f"\n（還有 {skipped} 筆沒有查，為了節省查價額度一次最多查 {QUICK_CHECK_LIMIT} 筆）")
        lines.append("\n💡 完整走勢請輸入「歷史」查看")
        msg = "\n".join(lines)

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        sent = False
        if time.time() - started_at < REPLY_DEADLINE_SECONDS:
            try:
                api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=msg)]))
                sent = True
            except Exception as e:
                print(f"⚠️ reply 失敗，改用 push: {e}")
        if not sent:
            try:
                api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=msg)]))
            except Exception as e:
                print(f"❌ 推播失敗 ({user_id}): {e}")

    # 回覆完才同步歷史紀錄，不拖慢回應
    sync_history_to_github()

def _show_loading(configuration, user_id, seconds=30):
    """在聊天室顯示「輸入中」動畫 (不佔推播額度)，舊版 SDK 沒有這個 API 時略過"""
    try:
        from linebot.v3.messaging import ShowLoadingAnimationRequest
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).show_loading_animation(ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=seconds))
    except Exception as e:
        print(f"⚠️ 無法顯示載入動畫: {e}")

def get_help_menu():
    return (
        "📖 【機票價格監控系統 - 操作說明】\n"
        "--------------------\n"
        "歡迎使用智慧機票追蹤助手！本系統支援以下完整功能：\n\n"
        "⚙️【1. 背景自動排程監控】\n"
        "   • 輸入指令「設定」或「監控」\n"
        "   • 點卡片上的按鈕開啟設定頁，可新增單程航班或長程來回比價。\n"
        "   • 系統每天自動查價，價格變動時主動通知！\n\n"
        "⚡【2. 獨立單次即時查價】\n"
        "   • 輸入指令「單次」或「臨時」\n"
        "   • 點卡片上的按鈕開啟即時查價面板。\n"
        "   • 可隨時查詢任意日期與直飛航班，完全不影響背景排程。\n\n"
        "🔍【3. 其他快捷指令】\n"
        "   • 「查價」：立刻查一次所有監控中的航班。\n"
        "   • 「檢查設定」：檢視目前已儲存的背景監控任務。\n"
        "   • 「歷史查詢」：開啟專屬面板，查看近期的查價波動紀錄。\n"
        "   • 「清除」：刪除當前的背景監控任務。"
    )

def register_bot_handlers(handler, configuration):
    @handler.add(FollowEvent)
    def handle_follow(event):
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="歡迎使用機票價格監控系統！\n\n" + get_help_menu())]
            ))

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message(event):
        text = event.message.text.strip()
        user_id = event.source.user_id
        LIFF_URL = os.getenv("LIFF_URL", "")

        if text in ["說明", "幫助", "help"]:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=get_help_menu())]
                    )
                )

        elif text in ["設定", "監控", "選單", "menu"]:
            uri = f"{LIFF_URL}/monitor" if not LIFF_URL.endswith("/monitor") and not LIFF_URL.endswith("/instant") else LIFF_URL.replace("/instant", "/monitor")
            flex_json = {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "md",
                    "contents": [
                        {"type": "text", "text": "⚙️ 背景機票監控設定", "weight": "bold", "size": "lg", "color": "#2563EB"},
                        {"type": "text", "text": "設定多航段與指定日期，系統將在背景定時為您追蹤最低價。", "wrap": True, "size": "sm", "color": "#666666"},
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#2563EB",
                            "action": {"type": "uri", "label": "📝 開啟監控表單", "uri": uri}
                        }
                    ]
                }
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="開啟監控設定表單", contents=FlexContainer.from_json(json.dumps(flex_json)))]
                    )
                )

        elif text in ["單次", "臨時", "單次查價", "臨時查價", "自訂查價", "面板"]:
            uri = f"{LIFF_URL}/instant" if not LIFF_URL.endswith("/monitor") and not LIFF_URL.endswith("/instant") else LIFF_URL.replace("/monitor", "/instant")
            flex_json = {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "md",
                    "contents": [
                        {"type": "text", "text": "⚡ 臨時單次查價", "weight": "bold", "size": "lg", "color": "#2563EB"},
                        {"type": "text", "text": "不影響您的背景排程，自由指定日期與航班進行一次性即時票價查詢。", "wrap": True, "size": "sm", "color": "#666666"},
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#2563EB",
                            "action": {"type": "uri", "label": "🚀 開啟查價面板", "uri": uri}
                        }
                    ]
                }
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="開啟臨時查價面板", contents=FlexContainer.from_json(json.dumps(flex_json)))]
                    )
                )

        elif text in ["查", "查價", "查詢", "即時查價"]:
            config = load_config()
            user_data = config.get("users", {}).get(user_id, {}).get("monitor_config", {})
            segments = user_data.get('segments', [])

            if not segments:
                reply_txt = "⚠️ 您目前尚未設定任何監控航段，請輸入「設定」打開表單進行配置！"
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_txt)])
                    )
            elif not scrape_flight_price:
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="⚠️ 系統尚未配置抓價模組。")])
                    )
            else:
                # 先顯示「輸入中」動畫，查完再用同一個 reply token 回覆結果 (不佔推播額度)
                _show_loading(configuration, user_id)
                threading.Thread(target=quick_check_and_reply,
                                 args=(user_id, event.reply_token, segments, configuration, time.time())).start()

        elif text in ["檢查設定", "查詢設定", "檢查", "當前設定", "目前設定"]:
            config = load_config()
            user_data = config.get("users", {}).get(user_id, {}).get("monitor_config", {})
            segments = user_data.get('segments', [])

            if not segments:
                reply_txt = "您目前尚未儲存任何機票監控設定喔！請輸入「設定」開啟表單。"
            else:
                msg_lines = ["📋 您目前的機票監控任務清單：\n"]
                for seg in segments:
                    seg_no = seg.get('segment_no', 1)
                    origin = seg.get('origin', '')
                    destination = seg.get('destination', '')

                    scheds = seg.get('date_schedules', []) or seg.get('schedules', [])
                    if scheds:
                        sub_lines = []
                        for ds in scheds:
                            d = ds.get('date', '') or ds.get('date_str', '')
                            fls_list = ds.get('flights', []) or ds.get('target_flights', []) or []
                            fls = ", ".join(fls_list) if fls_list else "當日最低價 (不限航班)"
                            if d:
                                sub_lines.append(f"  • {d} ➔ {fls}")
                        if sub_lines:
                            detail_str = "\n".join(sub_lines)
                            msg_lines.append(f"📌 航段 {seg_no}：{origin} ➔ {destination}\n{detail_str}\n")
                        else:
                            msg_lines.append(f"📌 航段 {seg_no}：{origin} ➔ {destination}\n📅 日期：(未指定)\n✈️ 航班：當日最低價 (不限航班)\n")
                    else:
                        dates_list = seg.get('dates', []) or seg.get('date_list', [])
                        dates = ", ".join(dates_list) if dates_list else "(未指定日期)"
                        fls_list = seg.get('flights', []) or []
                        flights = ", ".join(fls_list) if fls_list else "當日最低價 (不限航班)"
                        msg_lines.append(f"📌 航段 {seg_no}：{origin} ➔ {destination}\n📅 日期：{dates}\n✈️ 航班：{flights}\n")

                reply_txt = "\n".join(msg_lines)

            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_txt)])
                )

        elif text in ["紀錄", "歷史紀錄", "歷史", "歷史查詢"]:
            # 取得歷史查詢面板的 LIFF ID 並組成網址
            liff_id_history = os.getenv("LIFF_ID_HISTORY", "")
            if not liff_id_history:
                # 若未設定環境變數，則回傳純文字
                reply_txt = "⚠️ 系統尚未設定歷史查詢面板的 LIFF_ID_HISTORY。"
                with ApiClient(configuration) as api_client:
                    MessagingApi(api_client).reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_txt)])
                    )
                return

            liff_url_history = f"https://liff.line.me/{liff_id_history}"
            
            # 建立 Flex Message 卡片
            flex_json = {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "md",
                    "contents": [
                        {"type": "text", "text": "📊 歷史票價查詢", "weight": "bold", "size": "lg", "color": "#2563EB"},
                        {"type": "text", "text": "調閱資料庫中所有的查價紀錄，隨時追蹤特定航班或航線的票價波動。", "wrap": True, "size": "sm", "color": "#666666"},
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#2563EB",
                            "action": {"type": "uri", "label": "🔍 開啟查詢面板", "uri": liff_url_history}
                        }
                    ]
                }
            }
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="開啟歷史票價查詢面板", contents=FlexContainer.from_json(json.dumps(flex_json)))]
                    )
                )

        elif text in ["清除設定", "取消監控", "清除"]:
            config = load_config()
            if "users" in config and user_id in config["users"]:
                del config["users"][user_id]
                save_config(config)

            reply_txt = "🗑️ 已成功清除您所有的機票監控設定！"
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_txt)])
                )
