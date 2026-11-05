import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from utils import load_config, save_price_history, sync_history_to_github
from notifier import channels_for, notify as notify_user

try:
    from server import scrape_flight_price, search_itineraries, fetch_return_options, get_serpapi_searches_left, format_minutes
except ImportError:
    scrape_flight_price = None

# 與上次「已推播」的價格相差至少這麼多才推播，避免 NT$10 的小浮動浪費 LINE 每月推播額度
PRICE_ALERT_MIN_DIFF = 200
# SerpApi 免費方案每月 250 次，排程至少保留這麼多次給 Bot 即時查價
SERPAPI_RESERVE = 20
WEEKDAYS = "一二三四五六日"

class _SearchBudget:
    """追蹤這一輪還能用多少次 SerpApi；查不到剩餘額度時不設限"""
    def __init__(self, left):
        self.left = left

    def take(self, n=1):
        if self.left is None:
            return True
        if self.left - n < SERPAPI_RESERVE:
            return False
        self.left -= n
        return True

def _normalize_flight(text):
    return str(text or "").replace(" ", "").upper()

def _user_history(user_id):
    if not os.path.exists("history.json"):
        return []
    try:
        with open("history.json", "r", encoding="utf-8") as f:
            user_hist = json.load(f).get(user_id, [])
    except Exception:
        return []
    return user_hist if isinstance(user_hist, list) else []

def _find_baseline_price(user_id, origin, destination, search_date, target_f):
    """找出比價基準：最近一筆「已推播」的同航線、同日期、同航班價格
    舊版紀錄沒有 notified 欄位，視為已推播；notified=False (未達門檻或推播失敗) 的紀錄會略過"""
    curr_target = _normalize_flight(target_f)
    for h in reversed(_user_history(user_id)):
        if h.get("track_label"):
            continue
        if h.get("origin") != origin or h.get("destination") != destination or h.get("date") != search_date:
            continue
        # 指定航班時，歷史紀錄必須是同一班 (用結尾比對，避免 GK5 誤配到 GK57)
        if curr_target and not _normalize_flight(h.get("flight_details")).endswith(curr_target):
            continue
        if h.get("notified", True):
            return h.get("price")
    return None

def _config_is_broken():
    """config.json 存在但格式錯誤 (load_config 已印出錯在哪一行)"""
    try:
        with open("config.json", encoding="utf-8") as f:
            json.load(f)
        return False
    except FileNotFoundError:
        return False
    except json.JSONDecodeError:
        return True

def run_scheduled_checks(dry_run=False):
    """執行一輪監控，回傳失敗的次數 (推播失敗或設定錯誤)
    dry_run=True 時只查價、記錄，不發通知"""
    print("⏳ 開始執行背景機票價格監控排程...")
    # 設定錯誤要回報失敗，讓 GitHub Actions 顯示紅燈，不然使用者只會看到「沒收到通知」
    if scrape_flight_price and not os.getenv("SERPAPI_KEY"):
        print("❌ 未設定 SERPAPI_KEY，無法查價。請到 GitHub repo 的 Settings → Secrets and variables → Actions 新增")
        return 1
    config = load_config()  # 格式錯誤時會印出錯在哪一行
    if not config and _config_is_broken():
        return 1
    users_data = config.get("users", {})
    push_failures = 0

    if not users_data:
        print("ℹ️ 目前沒有任何使用者設定監控任務。")
        return push_failures

    tz_tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(tz_tw)
    today_str = now_tw.strftime("%Y-%m-%d")

    budget = _SearchBudget(get_serpapi_searches_left() if scrape_flight_price else None)
    if budget.left is not None:
        print(f"ℹ️ SerpApi 本月剩餘 {budget.left} 次 (保留 {SERPAPI_RESERVE} 次給即時查價)")

    for user_id, user_info in users_data.items():
        # 這位使用者有可用的通知管道 (LINE / Discord) 才推播
        can_notify = not dry_run and bool(channels_for(user_id, user_info))
        if not dry_run and not can_notify:
            print(f"⚠️ 使用者 {user_id} 沒有可用的通知管道 (沒有設定 DISCORD_WEBHOOK_URL 或 LINE)，只會查價不會通知")
        monitor_config = user_info.get("monitor_config", {})
        segments = monitor_config.get("segments", [])

        for seg in segments:
            origin = seg.get("origin", "TPE")
            destination = seg.get("destination", "KIX")
            date_schedules = seg.get("date_schedules", [])

            for ds in date_schedules:
                search_date = ds.get("date", "")
                target_flights = ds.get("flights", [])

                if not search_date:
                    continue

                # 出發日已過就不再查價，節省 SerpApi 額度
                if search_date < today_str:
                    print(f"  ➔ 略過已過期的日期：{origin} ➔ {destination} ({search_date})")
                    continue

                flights_to_check = target_flights if target_flights else [""]

                for target_f in flights_to_check:
                    print(f"  ➔ 執行背景抓價：{origin} ➔ {destination} ({search_date}), 指定航班: {target_f or '不限 (當日最低價)'}")

                    if not scrape_flight_price:
                        continue
                    if not budget.take():
                        print("  └ ⚠️ SerpApi 剩餘額度不足，略過。")
                        continue

                    try:
                        push_failures += _check_one(can_notify, user_id, origin, destination, search_date, target_f)
                    except Exception as e:
                        print(f"❌ 背景抓價發生例外錯誤: {e}")

                    time.sleep(2)

        # 長程 / 轉機行程監控 (例如美國)
        for trip in user_info.get("trips", []):
            if not scrape_flight_price:
                continue
            try:
                push_failures += _check_trip(can_notify, user_id, trip, now_tw, budget)
            except Exception as e:
                print(f"❌ 行程監控發生例外錯誤 ({trip.get('name')}): {e}")

    # 整輪查完才把 history.json 推回 GitHub 一次
    sync_history_to_github()

    print("🏁 背景機票價格監控排程執行完畢。")
    return push_failures

def _check_one(can_notify, user_id, origin, destination, search_date, target_f):
    """查一個航班並視情況推播，回傳推播失敗次數 (0 或 1)"""
    search_config = {
        "origin": origin,
        "destination": destination,
        "search_date": search_date,
        "trip_type": "one_way",
        "mode": "flight",
        "outbound_flight": target_f
    }

    price_result = scrape_flight_price(search_config, mode="flight")

    if not (isinstance(price_result, dict) and price_result.get("min_price")):
        print("  └ 查無價格，略過。")
        return 0

    # 指定航班不在當日直飛清單時，min_price 其實是別班的最低價，不能拿來比價或記錄
    if target_f and not price_result.get("outbound_target_found"):
        print(f"  └ 指定航班 {target_f} 不在當日直飛清單中 (可能已售完或停飛)，略過紀錄與推播。")
        return 0

    min_p = price_result["min_price"]
    out_m = price_result.get("outbound_flight", "")
    url = price_result.get("booking_url", "")
    flight_details = price_result.get("outbound_flight_no", "") or out_m

    # 1. 與上次已推播的價格比較，判斷是否需要推播
    last_price = _find_baseline_price(user_id, origin, destination, search_date, target_f)
    should_notify = last_price is None or abs(min_p - last_price) >= PRICE_ALERT_MIN_DIFF

    notified = False
    push_failed = 0
    if not should_notify:
        print(f"  └ 價格 NT$ {min_p:,} 與上次通知的 NT$ {last_price:,} 差距未達 NT$ {PRICE_ALERT_MIN_DIFF}，略過推播。")
    elif can_notify:
        if last_price is None:
            trend_msg = "✨ 已為您建立首筆基準追蹤價"
        else:
            icon = "📉" if min_p < last_price else "📈"
            trend_msg = f"{icon} 價格發生變動：原價 NT$ {last_price:,} ➔ 新價 NT$ {min_p:,}"

        msg = (
            "🔔 【機票價格浮動通知】\n"
            "--------------------\n"
            f"✈️ 航線：{origin} ➔ {destination}\n"
            f"📅 日期：{search_date}\n"
            f"🎯 航班：{target_f if target_f else '當日最低價'}\n\n"
            f"{trend_msg}\n\n"
            f"{out_m}\n\n"
            f"🔗 購票連結：\n{url}"
        )
        try:
            notify_user(user_id, msg)
            notified = True
            print(f"✅ 價格有變動或為新追蹤，已推播給 {user_id}")
        except Exception as push_err:
            push_failed = 1
            print(f"❌ 推播失敗: {push_err}")

    # 2. 寫入最新的歷史紀錄 (notified 決定下次比價的基準；推播失敗下次會再嘗試)
    save_price_history(
        flight_data=flight_details,
        current_price=min_p,
        user_id=user_id,
        origin=origin,
        dest=destination,
        date=search_date,
        notified=notified,
        sync_github=False
    )
    return push_failed

def _weekday(date_str):
    try:
        return WEEKDAYS[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except ValueError:
        return ""

def _check_trip(can_notify, user_id, trip, now_tw, budget):
    """查一個行程的所有飛法 (例如 SAN 轉機 vs LAX 直飛)，有任一個價格變動就推播一則比較訊息
    回傳推播失敗次數 (0 或 1)"""
    name = trip.get("name", "行程")
    out_date = trip.get("outbound_date", "")
    ret_date = trip.get("return_date") or None
    options = trip.get("options", [])
    if not out_date or not options:
        return 0

    print(f"  ➔ 行程監控：{name} ({out_date}{' ~ ' + ret_date if ret_date else ''})")
    if out_date < now_tw.strftime("%Y-%m-%d"):
        print("  └ 出發日已過，略過。")
        return 0

    # 依設定的間隔查價 (預設約一天一次)，SerpApi 免費額度有限
    labels = {f"{name} · {o.get('label', '')}" for o in options}
    interval = timedelta(hours=float(trip.get("min_interval_hours", 20)))
    last_check = max((h.get("updated_at", "") for h in _user_history(user_id) if h.get("track_label") in labels), default="")
    if last_check:
        last_dt = datetime.strptime(last_check, "%Y-%m-%d %H:%M:%S").replace(tzinfo=now_tw.tzinfo)
        if now_tw - last_dt < interval:
            print(f"  └ 上次查價 {last_check}，未滿 {interval.total_seconds() / 3600:g} 小時，略過。")
            return 0

    alert_min_diff = trip.get("alert_min_diff", 500)
    results = []
    for opt in options:
        label = f"{name} · {opt.get('label', '')}"
        if not budget.take():
            print(f"  └ ⚠️ SerpApi 剩餘額度不足，略過 {label}。")
            continue
        try:
            itineraries, params = search_itineraries(
                opt["origin"], opt["destination"], out_date, ret_date,
                max_stops=opt.get("max_stops", 0),
                max_layover_hours=trip.get("max_layover_hours"),
                allow_overnight_layover=trip.get("allow_overnight_layover", False)
            )
        except Exception as e:
            print(f"  └ ❌ {label} 查詢失敗: {e}")
            continue
        time.sleep(2)
        if not itineraries:
            print(f"  └ {label}：找不到符合條件的行程")
            continue

        best = itineraries[0]
        baseline = None
        for h in reversed(_user_history(user_id)):
            if (h.get("track_label") == label and h.get("date") == out_date
                    and h.get("return_date") == ret_date and h.get("notified", True)):
                baseline = h.get("price")
                break
        changed = baseline is None or abs(best["price"] - baseline) >= alert_min_diff
        print(f"  └ {label}：NT$ {best['price']:,} ({best['route']}，{best['flights']})" + ("" if changed else "，變動未達門檻"))
        results.append({"opt": opt, "label": label, "best": best, "baseline": baseline, "changed": changed, "params": params})

    if not results:
        return 0

    notify = can_notify and any(r["changed"] for r in results)
    cheapest = min(results, key=lambda r: r["best"]["price"])

    # 只在要推播時才查最便宜那個飛法的回程細節 (多花 1 次額度)
    return_info = None
    if (notify and ret_date and trip.get("fetch_return_details", True)
            and cheapest["best"]["departure_token"] and budget.take()):
        try:
            returns = fetch_return_options(cheapest["params"], cheapest["best"]["departure_token"],
                                           trip.get("max_layover_hours"), trip.get("allow_overnight_layover", False))
            return_info = returns[0] if returns else None
        except Exception as e:
            print(f"  └ ⚠️ 回程細節查詢失敗: {e}")

    notified = False
    push_failed = 0
    if notify:
        try:
            notify_user(user_id, _trip_message(trip, results, cheapest, return_info))
            notified = True
            print(f"✅ 行程價格有變動，已推播給 {user_id}")
        except Exception as push_err:
            push_failed = 1
            print(f"❌ 推播失敗: {push_err}")

    # 訊息裡列出了所有飛法的現價，所以推播成功時每個飛法的基準都一起更新
    for r in results:
        best = r["best"]
        save_price_history(
            flight_data=best["flights"],
            current_price=best["price"],
            user_id=user_id,
            origin=r["opt"]["origin"],
            dest=r["opt"]["destination"],
            date=out_date,
            notified=notified,
            sync_github=False,
            extra={
                "track_label": r["label"],
                "return_date": ret_date,
                "route": best["route"],
                "stops": best["stops"],
                "layovers": best["layovers"],
                "total_duration": best["total_duration"]
            }
        )
    return push_failed

def _trip_message(trip, results, cheapest, return_info):
    out_date, ret_date = trip.get("outbound_date", ""), trip.get("return_date")
    lines = [
        f"🔔 【{trip.get('name', '行程')} 機票比價】",
        "--------------------",
        f"📅 去程 {out_date[5:].replace('-', '/')} ({_weekday(out_date)})"
        + (f"｜回程 {ret_date[5:].replace('-', '/')} ({_weekday(ret_date)})｜來回總價" if ret_date else "｜單程")
    ]
    ranked = sorted(results, key=lambda r: r["best"]["price"])
    for r in ranked:
        best, opt = r["best"], r["opt"]
        if r["baseline"] is None:
            trend = "首筆"
        elif best["price"] == r["baseline"]:
            trend = "持平"
        else:
            diff = best["price"] - r["baseline"]
            trend = f"{'▼' if diff < 0 else '▲'} {abs(diff):,}"
        icon = "🏆" if r is cheapest and len(results) > 1 else "✈️"
        lines.append("")
        lines.append(f"{icon} {opt.get('label', '')}：NT$ {best['price']:,} ({trend})")
        lines.append(f"   {best['route']}｜{best['flights']}")
        detail = f"   總時間 {format_minutes(best['total_duration'])}"
        if best["layovers"]:
            detail += f"｜轉機 {best['layovers']}"
        lines.append(detail)
        if opt.get("note"):
            lines.append(f"   ＋ {opt['note']}")
        if r is cheapest and return_info:
            lines.append(f"   回程：{return_info['route']}｜{return_info['flights']}｜{format_minutes(return_info['total_duration'])}")

    if len(ranked) > 1:
        gap = ranked[1]["best"]["price"] - ranked[0]["best"]["price"]
        lines.append("")
        lines.append(f"💡 {ranked[0]['opt'].get('label', '')} 比 {ranked[1]['opt'].get('label', '')} 便宜 NT$ {gap:,}")

    opt = cheapest["opt"]
    url = (f"https://www.google.com/travel/flights?q=Flights%20to%20{opt['destination']}%20from%20{opt['origin']}%20on%20{out_date}"
           + (f"%20through%20{ret_date}" if ret_date else "") + "&curr=TWD&hl=zh-TW")
    lines.append("")
    lines.append(f"🔗 Google Flights：\n{url}")
    return "\n".join(lines)

if __name__ == "__main__":
    failures = run_scheduled_checks()

    # 推播失敗時讓 GitHub Actions 顯示紅燈並寄信通知 (常見原因：LINE 每月推播額度用完)
    if failures:
        print(f"❌ 本輪有 {failures} 個錯誤 (推播失敗或設定錯誤)，請看上方的 ❌ 訊息")
        sys.exit(1)
