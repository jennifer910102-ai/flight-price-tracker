import os
import json
import re
from serpapi import GoogleSearch

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

def time_to_minutes(time_str):
    if not time_str:
        return None
    match = re.search(r'(\d{1,2}):(\d{2})', str(time_str))
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    return None

def is_time_in_range(flight_dep_time, time_range_str):
    if not time_range_str or "-" not in str(time_range_str):
        return True
    
    dep_min = time_to_minutes(flight_dep_time)
    if dep_min is None:
        return True

    try:
        parts = str(time_range_str).split("-")
        if len(parts) != 2:
            return True
            
        start_min = time_to_minutes(parts[0].strip())
        end_min = time_to_minutes(parts[1].strip())

        if start_min is None or end_min is None:
            return True

        if start_min > end_min:
            return dep_min >= start_min or dep_min <= end_min
        else:
            return start_min <= dep_min <= end_min
    except Exception:
        return True

def scrape_flight_price(user_config, mode="flight"):
    current_mode = str(user_config.get("mode", mode)).lower()
    config_str = str(user_config)
    
    is_range_mode = (
        current_mode in ["cheapest_in_time", "range", "time", "時段最低价", "時段最低價"] 
        or "時段" in config_str
    )
    is_one_way = user_config.get("trip_type") == "one_way"

    out_date = user_config.get("search_date") or user_config.get("去程日期")
    ret_date = user_config.get("return_date") or user_config.get("回程日期")
    origin = user_config.get("origin", "TPE")
    destination = user_config.get("destination", "KIX")

    out_time_range = (
        user_config.get("outbound_time") 
        or user_config.get("outbound_time_range") 
        or user_config.get("去程時段", "")
    )
    in_time_range = (
        user_config.get("inbound_time_a") 
        or user_config.get("inbound_time_range") 
        or user_config.get("回程時段", "")
    )

    outbound_target = str(user_config.get("outbound_flight", "")).replace(" ", "").upper()
    inbound_target = str(user_config.get("inbound_flight_a", "")).replace(" ", "").upper()

    booking_url = f"https://www.google.com/travel/flights?q=Flights%20to%20{destination}%20from%20{origin}%20on%20{out_date}" + (f"%20through%20{ret_date}" if not is_one_way else "") + "&curr=TWD&hl=zh-TW"

    if not SERPAPI_KEY:
        return {
            "min_price": None,
            "outbound_flight": "⚠️ 未設定 SERPAPI_KEY 環境變數",
            "inbound_flight": "",
            "booking_url": booking_url
        }

    def fetch_one_way(dep, arr, date_str):
        params = {
            "engine": "google_flights",
            "departure_id": dep,
            "arrival_id": arr,
            "outbound_date": date_str,
            "currency": "TWD",
            "hl": "zh-tw",
            "type": "2",
            "stops": "1", # 強制只搜尋直飛航班，過濾掉轉機
            "api_key": SERPAPI_KEY
        }
        try:
            search = GoogleSearch(params)
            res = search.get_dict()
            flights = res.get("best_flights", []) + res.get("other_flights", [])
            parsed_list = []
            for item in flights:
                price = item.get("price")
                legs = item.get("flights", [])
                if not legs:
                    continue
                # 由於已設定 stops=1，這裡的 legs[0] 就是唯一的直飛航段
                leg = legs[0]
                airline = leg.get("airline", "")
                f_num = leg.get("flight_number", "")
                code = f"{airline} {f_num}".strip()
                dep_t = leg.get("departure_airport", {}).get("time", "")
                arr_t = leg.get("arrival_airport", {}).get("time", "")
                time_str = f"{dep_t} - {arr_t}" if dep_t and arr_t else "時間請點連結確認"
                
                parsed_list.append({
                    "code": code,
                    "dep_time": dep_t,
                    "arr_time": arr_t,
                    "time": time_str,
                    "price": price
                })
            return parsed_list
        except Exception as e:
            print(f"❌ 查詢失敗 ({dep}->{arr}): {e}")
            return []

    try:
        all_outbound = fetch_one_way(origin, destination, out_date)
        filtered_outbound = [f for f in all_outbound if is_time_in_range(f["dep_time"], out_time_range)]

        all_inbound = fetch_one_way(destination, origin, ret_date) if (not is_one_way and ret_date) else []
        filtered_inbound = [f for f in all_inbound if is_time_in_range(f["dep_time"], in_time_range)]

        # ----------------------------------------------------
        # 情境 A：【時段最低價模式】
        # ----------------------------------------------------
        if is_range_mode:
            target_out_list = filtered_outbound if filtered_outbound else all_outbound
            target_in_list = filtered_inbound if filtered_inbound else all_inbound

            best_out = min(target_out_list, key=lambda x: x["price"]) if target_out_list else None
            best_in = min(target_in_list, key=lambda x: x["price"]) if target_in_list else None

            min_out_price = best_out["price"] if best_out else 0
            min_in_price = best_in["price"] if best_in else 0
            min_total_price = (min_out_price + min_in_price) if (min_out_price and min_in_price and not is_one_way) else (min_out_price or None)

            out_sorted = sorted(target_out_list, key=lambda x: x["price"])[:5]
            title_tag = f"【去程】最低價 Top 5（時段：{out_time_range}）" if filtered_outbound and out_time_range else "【去程】最低價 Top 5"
            out_lines = [f"\n✈️ {title_tag}："]
            for idx, f in enumerate(out_sorted, 1):
                out_lines.append(f"   {idx}. {f['code']}｜{f['time']}｜估算 NT$ {f['price']:,}")

            if not filtered_outbound and out_time_range:
                out_lines.append(f"   ⚠️ 指定時段（{out_time_range}）內無符合班次，已為您顯示全天最低價。")

            in_lines = []
            if not is_one_way and target_in_list:
                in_sorted = sorted(target_in_list, key=lambda x: x["price"])[:5]
                in_title_tag = f"【回程】最低價 Top 5（時段：{in_time_range}）" if filtered_inbound and in_time_range else "【回程】最低價 Top 5"
                in_lines.append(f"\n✈️ {in_title_tag}：")
                for idx, f in enumerate(in_sorted, 1):
                    in_lines.append(f"   {idx}. {f['code']}｜{f['time']}｜估算 NT$ {f['price']:,}")

            return {
                "min_price": min_total_price,
                "outbound_flight_no": best_out["code"] if best_out else "",
                "outbound_time": best_out["time"] if best_out else "",
                "outbound_price": min_out_price,
                "inbound_flight_no": best_in["code"] if (best_in and not is_one_way) else "",
                "inbound_time": best_in["time"] if (best_in and not is_one_way) else "",
                "inbound_price": min_in_price if not is_one_way else 0,
                "outbound_flight": "\n".join(out_lines),
                "inbound_flight": "\n".join(in_lines) if in_lines else "",
                "booking_url": booking_url
            }

        # ----------------------------------------------------
        # 情境 B：【指定班次模式】
        # ----------------------------------------------------
        else:
            # 沒指定航班時不比對 (空字串會配到清單第一班)，交給下面的「當日最低價」處理
            target_out = next((f for f in all_outbound if outbound_target in f["code"].replace(" ", "").upper()), None) if outbound_target else None
            target_in = next((f for f in all_inbound if inbound_target in f["code"].replace(" ", "").upper()), None) if (inbound_target and not is_one_way) else None

            out_target_price = target_out["price"] if target_out else 0
            in_target_price = target_in["price"] if target_in else 0

            if is_one_way:
                specified_total_price = out_target_price if out_target_price > 0 else None
            else:
                specified_total_price = (out_target_price + in_target_price) if (out_target_price > 0 and in_target_price > 0) else (out_target_price or in_target_price or None)

            # 抓取當日最便宜的前 3 名直飛航班
            out_sorted = sorted(filtered_outbound if filtered_outbound else all_outbound, key=lambda x: x["price"])[:3] if all_outbound else []
            min_out = out_sorted[0] if out_sorted else None
            
            in_sorted = sorted(filtered_inbound if filtered_inbound else all_inbound, key=lambda x: x["price"])[:3] if (all_inbound and not is_one_way) else []
            min_in = in_sorted[0] if in_sorted else None

            out_lines = []
            if target_out:
                out_lines.append(f"🎯 指定去程【{target_out['code']}】")
                out_lines.append(f"   └ 時間：{target_out['time']}｜票價：NT$ {target_out['price']:,}")
            elif outbound_target:
                out_lines.append(f"🎯 指定去程【{outbound_target}】")
                out_lines.append(f"   └ 狀態：當日直飛清單中未找到該班次")

            if out_sorted:
                out_lines.append(f"\n🔥 當日直飛最低價 Top 3：")
                for idx, f in enumerate(out_sorted, 1):
                    out_lines.append(f"   {idx}. {f['code']}｜{f['time']}｜NT$ {f['price']:,}")

            in_lines = []
            if not is_one_way:
                if target_in:
                    in_lines.append(f"🎯 指定回程【{target_in['code']}】")
                    in_lines.append(f"   └ 時間：{target_in['time']}｜票價：NT$ {target_in['price']:,}")
                elif inbound_target:
                    in_lines.append(f"🎯 指定回程【{inbound_target}】")
                    in_lines.append(f"   └ 狀態：當日直飛清單中未找到該班次")

                if in_sorted:
                    in_lines.append(f"\n🔥 當日直飛最低價 Top 3：")
                    for idx, f in enumerate(in_sorted, 1):
                        in_lines.append(f"   {idx}. {f['code']}｜{f['time']}｜NT$ {f['price']:,}")

            return {
                "min_price": specified_total_price or (min_out["price"] if min_out else None),
                # 指定的去程班次是否真的有找到 (找不到時 min_price 會退回當日最低價，排程端需要分辨)
                "outbound_target_found": bool(target_out),
                "outbound_flight_no": target_out["code"] if target_out else (min_out["code"] if min_out else outbound_target),
                "outbound_time": target_out["time"] if target_out else (min_out["time"] if min_out else ""),
                "outbound_price": out_target_price or (min_out["price"] if min_out else 0),
                "inbound_flight_no": target_in["code"] if (target_in and not is_one_way) else (min_in["code"] if min_in else inbound_target),
                "inbound_time": target_in["time"] if (target_in and not is_one_way) else (min_in["time"] if min_in else ""),
                "inbound_price": in_target_price or (min_in["price"] if min_in else 0) if not is_one_way else 0,
                "outbound_flight": "\n".join(out_lines),
                "inbound_flight": "\n".join(in_lines),
                "booking_url": booking_url
            }

    except Exception as e:
        print(f"❌ 執行異常: {e}")

    return {
        "min_price": None,
        "outbound_flight_no": outbound_target,
        "outbound_time": "",
        "outbound_price": 0,
        "inbound_flight_no": inbound_target if not is_one_way else "",
        "inbound_time": "",
        "inbound_price": 0,
        "outbound_flight": f"🎯 指定去程：{outbound_target}\n⚠️ 查詢發生異常",
        "inbound_flight": f"🎯 指定回程：{inbound_target}" if not is_one_way else "",
        "booking_url": booking_url
    }


# ==========================================
# 轉機 / 來回行程查價 (長程線用，例如美國)
# ==========================================

# SerpApi 的 stops 參數：0 不限、1 只要直飛、2 最多轉 1 次、3 最多轉 2 次
_STOPS_PARAM = {0: "1", 1: "2", 2: "3"}

def format_minutes(minutes):
    minutes = int(minutes or 0)
    return f"{minutes // 60}h{minutes % 60:02d}m"

def _parse_itinerary(item):
    """把 SerpApi 的一個行程整理成好閱讀的格式"""
    legs = item.get("flights", [])
    layovers = item.get("layovers", []) or []
    codes = [str(leg.get("flight_number", "")).strip() for leg in legs]
    airports = [legs[0].get("departure_airport", {}).get("id", "")] + [leg.get("arrival_airport", {}).get("id", "") for leg in legs]
    return {
        "price": item.get("price"),
        "flights": " → ".join(c for c in codes if c),
        "airlines": "、".join(dict.fromkeys(leg.get("airline", "") for leg in legs if leg.get("airline"))),
        "route": " → ".join(a for a in airports if a),
        "stops": len(legs) - 1,
        "layovers": "、".join(f"{l.get('id', '')} {format_minutes(l.get('duration'))}" + (" (過夜)" if l.get("overnight") else "") for l in layovers),
        "total_duration": item.get("total_duration", 0),
        "depart_time": legs[0].get("departure_airport", {}).get("time", ""),
        "arrive_time": legs[-1].get("arrival_airport", {}).get("time", ""),
        "departure_token": item.get("departure_token", "")
    }

def _filter_itineraries(res, max_layover_hours=None, allow_overnight_layover=True):
    results = []
    for item in res.get("best_flights", []) + res.get("other_flights", []):
        if not item.get("flights") or not item.get("price"):
            continue
        layovers = item.get("layovers", []) or []
        if not allow_overnight_layover and any(l.get("overnight") for l in layovers):
            continue
        if max_layover_hours and any((l.get("duration") or 0) > max_layover_hours * 60 for l in layovers):
            continue
        results.append(_parse_itinerary(item))
    return sorted(results, key=lambda x: x["price"])

def search_itineraries(origin, destination, out_date, return_date=None, max_stops=0,
                       max_layover_hours=None, allow_overnight_layover=True):
    """查詢可含轉機的行程 (1 次 SerpApi 額度)，依價格由低到高排序
    來回時每個行程的價格是「來回總價」，回程細節要另外用 fetch_return_options 查"""
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": out_date,
        "currency": "TWD",
        "hl": "zh-tw",
        "type": "1" if return_date else "2",
        "stops": _STOPS_PARAM.get(max_stops, "0"),
        "api_key": SERPAPI_KEY
    }
    if return_date:
        params["return_date"] = return_date
    if max_stops and max_layover_hours:
        params["layover_duration"] = f"0,{int(max_layover_hours * 60)}"

    res = GoogleSearch(params).get_dict()
    if res.get("error"):
        raise RuntimeError(res["error"])
    return _filter_itineraries(res, max_layover_hours, allow_overnight_layover), params

def fetch_return_options(search_params, departure_token, max_layover_hours=None, allow_overnight_layover=True):
    """用去程的 departure_token 查對應的回程選項 (再花 1 次 SerpApi 額度)"""
    params = dict(search_params, departure_token=departure_token)
    res = GoogleSearch(params).get_dict()
    if res.get("error"):
        raise RuntimeError(res["error"])
    return _filter_itineraries(res, max_layover_hours, allow_overnight_layover)

def get_serpapi_searches_left():
    """查詢本月剩餘的 SerpApi 額度 (查帳號資訊不扣額度)，查不到時回傳 None"""
    if not SERPAPI_KEY:
        return None
    try:
        import requests
        data = requests.get("https://serpapi.com/account.json", params={"api_key": SERPAPI_KEY}, timeout=10).json()
        return data.get("total_searches_left", data.get("plan_searches_left"))
    except Exception as e:
        print(f"⚠️ 無法查詢 SerpApi 剩餘額度: {e}")
        return None
