import json
import os
import psycopg2
from datetime import datetime, timezone, timedelta
from github import Github

# 讀取環境變數
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO") 
DATABASE_URL = os.getenv("DATABASE_URL") 

def load_config():
    """讀取本地 config.json 設定檔"""
    file_path = 'config.json'
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                # 手動編輯最常見的錯誤是少逗號、多逗號或引號不對，直接指出位置
                print(f"❌ config.json 格式錯誤：第 {e.lineno} 行第 {e.colno} 個字附近（{e.msg}），請檢查逗號和引號")
                return {}
    return {}

def save_config(data):
    """將設定寫入本地 config.json，並同步到 GitHub"""
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    # 自動將新設定 Commit 回 GitHub
    update_github_config(data)

def save_price_history(flight_data, current_price, user_id="system", origin="", dest="", date="", notified=None, sync_github=True, extra=None):
    """主函式：同時執行 JSON 更新、GitHub 備份與 PostgreSQL 儲存
    notified：排程是否已針對這筆價格成功推播 (排程用來當下次比價基準)，None 表示不記錄
    sync_github：False 時只寫本地，由呼叫端最後呼叫 sync_history_to_github() 一次推送
    extra：額外寫入 JSON 紀錄的欄位 (例如轉機行程的 track_label、return_date)"""
    # 宣告台灣時區 UTC+8
    tz_tw = timezone(timedelta(hours=8))
    timestamp = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")
    
    # 採用扁平化的時間序列結構，保留所有關鍵條件且利於 append
    new_record = {
        "updated_at": timestamp, 
        "origin": origin,
        "destination": dest,
        "date": date,
        "price": current_price,
        "flight_details": flight_data,
        "source": "SerpApi"
    }
    if notified is not None:
        new_record["notified"] = notified
    if extra:
        new_record.update(extra)

    # 1. 更新本地 JSON 檔案
    history_data = _update_local_json(new_record, user_id)

    # 2. 同步至 GitHub
    if sync_github:
        sync_history_to_github()

    # 3. 寫入 PostgreSQL 資料庫 (帶入 user_id, origin, dest, date)
    if DATABASE_URL:
        _save_to_postgres(timestamp, flight_data, current_price, "SerpApi", user_id, origin, dest, date)

    return history_data

# 已停用的使用者鍵值：合併時忽略，避免舊副本把刪掉的資料又帶回來
IGNORED_HISTORY_KEYS = {"DEFAULT"}

def normalize_history_records(records):
    """把歷史紀錄統一成扁平格式；舊版 app.py 寫入的 {"flights": [...]} 會拆成多筆"""
    if not isinstance(records, list):
        return []
    flat = []
    for r in records:
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("flights"), list):
            for f in r["flights"]:
                flat.append({
                    "updated_at": r.get("updated_at", ""),
                    "origin": f.get("origin", ""),
                    "destination": f.get("destination", ""),
                    "date": f.get("date", ""),
                    "price": f.get("price"),
                    "flight_details": f"{f.get('airline', '')} {f.get('flight_no', '')}".strip(),
                    "source": "SerpApi"
                })
        else:
            flat.append(r)
    return flat

def _record_key(r):
    return (r.get("updated_at"), r.get("origin"), r.get("destination"), r.get("date"),
            str(r.get("flight_details")), r.get("price"))

def merge_history(base, extra):
    """以 base (通常是 GitHub 上的最新版) 為主，補上 extra 中 base 沒有的紀錄，依時間排序"""
    merged = {}
    for uid in list(base.keys()) + [k for k in extra.keys() if k not in base]:
        if uid in IGNORED_HISTORY_KEYS:
            continue
        records = normalize_history_records(base.get(uid, []))
        seen = {_record_key(r) for r in records}
        for r in normalize_history_records(extra.get(uid, [])):
            if _record_key(r) not in seen:
                records.append(r)
                seen.add(_record_key(r))
        records.sort(key=lambda r: r.get("updated_at") or "")
        merged[uid] = records
    return merged

def _read_local_history():
    if os.path.exists('history.json'):
        with open('history.json', 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {}

def _write_local_history(data):
    with open('history.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def sync_history_to_github(retries=3):
    """把本地 history.json 合併進 GitHub 上的最新版再推送
    Render 與 GitHub Actions 都會寫歷史紀錄，直接整份覆蓋會把對方新增的紀錄蓋掉，所以一律先合併"""
    if not (GITHUB_TOKEN and GITHUB_REPO):
        return
    for attempt in range(retries):
        try:
            repo = Github(GITHUB_TOKEN).get_repo(GITHUB_REPO)
            contents = repo.get_contents("history.json")
            remote = json.loads(contents.decoded_content.decode("utf-8") or "{}")
            merged = merge_history(remote, _read_local_history())
            _write_local_history(merged)
            if merged == remote:
                return
            repo.update_file(
                contents.path,
                "chore: update history.json via auto-tracker [skip ci] [skip render]",
                json.dumps(merged, ensure_ascii=False, indent=4),
                contents.sha
            )
            print("成功同步 history.json 至 GitHub")
            return
        except Exception as e:
            # 409 代表剛好有人同時寫入，重新抓最新版合併再試
            print(f"GitHub 同步失敗 (第 {attempt + 1} 次): {e}")

_history_cache = {"at": 0, "data": None}

def load_history(max_age_seconds=60):
    """讀取最新的歷史紀錄：有設定 GitHub 時抓 GitHub 版本與本地合併 (排程寫入的資料在 GitHub 上)，快取 60 秒"""
    import time
    if not (GITHUB_TOKEN and GITHUB_REPO):
        return merge_history(_read_local_history(), {})
    if _history_cache["data"] is not None and time.time() - _history_cache["at"] < max_age_seconds:
        return _history_cache["data"]
    try:
        contents = Github(GITHUB_TOKEN).get_repo(GITHUB_REPO).get_contents("history.json")
        remote = json.loads(contents.decoded_content.decode("utf-8") or "{}")
        data = merge_history(remote, _read_local_history())
    except Exception as e:
        print(f"讀取 GitHub 歷史紀錄失敗，改用本地檔案: {e}")
        data = merge_history(_read_local_history(), {})
    _history_cache.update(at=time.time(), data=data)
    return data

def update_github_config(new_config_data):
    """將更新後的 config.json 同步回 GitHub"""
    if GITHUB_TOKEN and GITHUB_REPO:
        _push_to_github("config.json", new_config_data)

def _update_local_json(new_record, user_id):
    """處理本地端 JSON 附加邏輯，並包含舊格式的自動轉型"""
    file_path = 'history.json'
    history_data = {}
    
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                history_data = json.load(f)
            except json.JSONDecodeError:
                history_data = {}
        
    _history_cache["data"] = None  # 有新紀錄，讓 load_history 下次重新讀取

    # 確保該 user_id 的鍵值存在
    if user_id not in history_data:
        history_data[user_id] = []
    # ⚠️ 關鍵修復：如果發現舊版的 {"segments": [...]} 字典結構，強制轉為陣列
    elif isinstance(history_data[user_id], dict):
        history_data[user_id] = []
        
    history_data[user_id].append(new_record)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(history_data, f, ensure_ascii=False, indent=4)
        
    return history_data

def _push_to_github(file_path, data):
    """透過 PyGithub 將更新推送回儲存庫"""
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
        content_str = json.dumps(data, ensure_ascii=False, indent=4)
        contents = repo.get_contents(file_path)
        
        repo.update_file(
            contents.path, 
            f"chore: update {file_path} via auto-tracker [skip ci] [skip render]", 
            content_str, 
            contents.sha
        )
        print(f"成功同步 {file_path} 至 GitHub")
    except Exception as e:
        print(f"GitHub 同步失敗: {e}")

def _save_to_postgres(timestamp, flight_data, price, source, user_id, origin="", dest="", date=""):
    """建立資料庫連線並寫入 PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id SERIAL PRIMARY KEY,
                check_time TIMESTAMP,
                origin VARCHAR(10),
                destination VARCHAR(10),
                flight_date VARCHAR(50),
                price NUMERIC,
                flight_data TEXT,
                source VARCHAR(50),
                user_id VARCHAR(255)
            )
        """)

        # 確保若先前已建過舊表，能自動補充新欄位
        cursor.execute("""
            ALTER TABLE price_history 
            ADD COLUMN IF NOT EXISTS origin VARCHAR(10),
            ADD COLUMN IF NOT EXISTS destination VARCHAR(10),
            ADD COLUMN IF NOT EXISTS flight_date VARCHAR(50);
        """)

        flight_str = json.dumps(flight_data, ensure_ascii=False) if isinstance(flight_data, (dict, list)) else str(flight_data)
        
        cursor.execute("""
            INSERT INTO price_history (check_time, origin, destination, flight_date, price, flight_data, source, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (timestamp, origin, dest, date, price, flight_str, source, user_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        print("成功寫入 PostgreSQL (包含起降機場與日期)")
    except Exception as e:
        print(f"PostgreSQL 寫入失敗: {e}")
