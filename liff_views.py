import os
import json
import requests
import time
import hmac
from flask import Blueprint, request, render_template_string, jsonify, session, redirect
from utils import load_config, save_config, load_history
from web_auth import password_mode, web_user_id, current_user_id, safe_next

liff_bp = Blueprint('liff', __name__)

LIFF_ID = os.getenv("LIFF_ID", "")
AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_KEY", "")
flight_cache = {}

def fetch_flights_from_api(dep_iata, arr_iata):
    if not AVIATIONSTACK_KEY:
        return []

    url = "http://api.aviationstack.com/v1/flights"
    params = {'access_key': AVIATIONSTACK_KEY, 'dep_iata': dep_iata, 'arr_iata': arr_iata, 'limit': 100}

    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        flights = []
        seen_codes = set()

        if 'data' in data and data['data']:
            for item in data['data']:
                flight_info = item.get('flight', {})
                airline_info = item.get('airline', {})
                departure_info = item.get('departure', {})
                arrival_info = item.get('arrival', {})

                if departure_info.get('iata', '').upper() != dep_iata.upper() or arrival_info.get('iata', '').upper() != arr_iata.upper():
                    continue

                flight_number = flight_info.get('iata')
                airline_name = airline_info.get('name', '未知航空')
                
                dep_time = departure_info.get('scheduled', '')
                arr_time = arrival_info.get('scheduled', '')
                
                dep_str = dep_time.split('T')[1][:5] if 'T' in dep_time else "??"
                arr_str = arr_time.split('T')[1][:5] if 'T' in arr_time else "??"
                time_str = f"{dep_str} ➔ {arr_str}"

                if flight_number and flight_number not in seen_codes:
                    seen_codes.add(flight_number)
                    flights.append({"code": flight_number, "text": f"{airline_name} {flight_number} ({time_str})"})
        return flights
    except Exception as e:
        print(f"航班 API 呼叫失敗: {e}")
        return []

# --- 共用樣式：三個 LIFF 頁面使用同一組設計 (含深色模式) ---
BASE_CSS = """
        :root {
            --bg: #f3f5f9; --card: #ffffff; --ink: #0f172a; --ink-2: #475569; --ink-3: #94a3b8;
            --line: #e5e9f0; --line-strong: #cbd5e1; --chip: #eef2f7; --accent: #2563eb; --accent-soft: #e8efff;
            --down: #059669; --down-soft: #e6f6ef; --up: #dc2626; --up-soft: #fdecec;
            --best: #b45309; --best-soft: #fff4e0; --shadow: 0 1px 2px rgba(15,23,42,.04), 0 6px 20px rgba(15,23,42,.05);
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg: #0b1120; --card: #131b2e; --ink: #e8edf6; --ink-2: #a3b0c4; --ink-3: #64748b;
                --line: #222c42; --line-strong: #334155; --chip: #1c2539; --accent: #6b9bff; --accent-soft: #1b2a4d;
                --down: #34d399; --down-soft: #10302a; --up: #f87171; --up-soft: #3a1b1f;
                --best: #fbbf24; --best-soft: #3a2c10; --shadow: none;
            }
        }
        * { box-sizing: border-box; }
        body { margin: 0; background: var(--bg); color: var(--ink); -webkit-font-smoothing: antialiased;
               font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif; }
        .wrap { max-width: 680px; margin: 0 auto; padding: 20px 16px 48px; }
        .wrap.has-bar { padding-bottom: 120px; }
        .num { font-variant-numeric: tabular-nums; }
        .hidden { display: none !important; }

        header h1 { font-size: 1.35rem; margin: 0 0 4px; letter-spacing: .01em; }
        header p { margin: 0; color: var(--ink-3); font-size: .85rem; line-height: 1.6; }

        .card { background: var(--card); border-radius: 16px; box-shadow: var(--shadow); border: 1px solid var(--line); }
        .section-title { display: flex; justify-content: space-between; align-items: baseline; margin: 22px 2px 10px; }
        .section-title h2 { font-size: .95rem; margin: 0; color: var(--ink-2); font-weight: 600; }
        .link { background: none; border: 0; color: var(--accent); font-size: .82rem; cursor: pointer; padding: 0; }
        .tag { display: inline-block; font-size: .72rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; background: var(--chip); color: var(--ink-2); }
        .tag.accent { background: var(--accent-soft); color: var(--accent); }

        .chips { display: flex; gap: 8px; overflow-x: auto; padding: 16px 0 4px; scrollbar-width: none; }
        .chips::-webkit-scrollbar { display: none; }
        .chip { flex: none; border: 1px solid var(--line); background: var(--card); color: var(--ink-2);
                border-radius: 999px; padding: 7px 14px; font-size: .85rem; cursor: pointer; white-space: nowrap; }
        .chip.on { background: var(--ink); color: var(--card); border-color: var(--ink); }

        .state { text-align: center; color: var(--ink-3); padding: 48px 16px; font-size: .92rem; line-height: 1.7; }
        .skeleton { height: 150px; margin-bottom: 12px; background: linear-gradient(90deg, var(--card) 0%, var(--chip) 50%, var(--card) 100%);
                    background-size: 200% 100%; animation: shimmer 1.4s infinite; }
        @keyframes shimmer { to { background-position: -200% 0; } }

        /* 表單 */
        .field { margin-bottom: 14px; }
        .field > label, .label { display: block; font-size: .78rem; font-weight: 600; color: var(--ink-2); margin-bottom: 6px; }
        .route-row { display: grid; grid-template-columns: 1fr 28px 1fr; gap: 6px; align-items: end; }
        .route-row .arrow { height: 46px; display: flex; align-items: center; justify-content: center; color: var(--ink-3); }
        .route-row > div, .opt-row > * { min-width: 0; }
        /* 單選下拉固定一行高，避免搜尋框換行把高度撐大 */
        .ts-wrapper.single .ts-control { height: 46px; flex-wrap: nowrap !important; align-items: center; overflow: hidden; }
        .ts-wrapper.single .ts-control .item { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
        .ts-wrapper.single .ts-control input { min-width: 0 !important; }
        input[type="date"], .input { width: 100%; height: 46px; padding: 0 12px; border: 1px solid var(--line-strong); border-radius: 10px;
                                     background: var(--card); color: var(--ink); font: inherit; font-size: 16px; }
        input[type="date"]:focus, .input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
        .ts-wrapper .ts-control { min-height: 46px; border: 1px solid var(--line-strong) !important; border-radius: 10px !important; background: var(--card) !important;
                                  color: var(--ink) !important; font-size: 16px !important; padding: 10px 12px !important; box-shadow: none !important; }
        .ts-wrapper.focus .ts-control { border-color: var(--accent) !important; box-shadow: 0 0 0 3px var(--accent-soft) !important; }
        .ts-control input, .ts-control input::placeholder { color: var(--ink) !important; font-size: 16px !important; }
        .ts-control input::placeholder { color: var(--ink-3) !important; }
        .ts-wrapper.multi .ts-control > div { background: var(--accent-soft) !important; color: var(--accent) !important; border: 0 !important; border-radius: 6px !important; }
        .ts-dropdown { background: var(--card); color: var(--ink); border: 1px solid var(--line); border-radius: 10px; box-shadow: var(--shadow); margin-top: 4px; overflow: hidden; }
        .ts-dropdown .option, .ts-dropdown .create, .ts-dropdown .no-results { padding: 10px 12px; font-size: .9rem; }
        .ts-dropdown .active { background: var(--accent-soft) !important; color: var(--ink) !important; }

        .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 0; border-radius: 12px;
               font: inherit; font-weight: 600; cursor: pointer; -webkit-tap-highlight-color: transparent; }
        .btn:disabled { opacity: .55; cursor: default; }
        .btn-primary { width: 100%; height: 50px; background: var(--accent); color: #fff; font-size: 1rem; }
        .btn-soft { height: 36px; padding: 0 12px; background: var(--accent-soft); color: var(--accent); font-size: .82rem; border-radius: 10px; white-space: nowrap; }
        .btn-dashed { width: 100%; height: 48px; background: none; border: 1.5px dashed var(--line-strong); color: var(--ink-2); font-size: .9rem; }
        .btn-text { background: none; border: 0; color: var(--ink-3); font-size: .8rem; cursor: pointer; padding: 4px; font-family: inherit; }
        .btn-text.danger { color: var(--up); }
        .bottom-bar { position: fixed; left: 0; right: 0; bottom: 0; padding: 16px 16px calc(14px + env(safe-area-inset-bottom));
                      background: linear-gradient(to bottom, transparent, var(--bg) 35%); }
        .bottom-bar .inner { max-width: 680px; margin: 0 auto; }
        .page-nav { position: sticky; top: 0; z-index: 10; display: flex; justify-content: center; gap: 4px; padding: 8px;
                    background: var(--card); border-bottom: 1px solid var(--line); flex-wrap: wrap; }
        .page-nav a { color: var(--ink-2); text-decoration: none; font-size: .88rem; padding: 7px 12px; border-radius: 999px; }
        .page-nav a.on { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
        .page-nav a.logout { color: var(--ink-3); }
        .spinner { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,.4); border-top-color: #fff; border-radius: 50%; animation: spin .8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
"""

TOM_SELECT_ASSETS = """
    <link href="https://cdn.jsdelivr.net/npm/tom-select@2.2.2/dist/css/tom-select.bootstrap5.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/tom-select@2.2.2/dist/js/tom-select.complete.min.js"></script>
"""

# 兩個表單頁面共用的機場搜尋下拉選單
AIRPORT_SELECT_JS = """
    function createAirportSelect(elementId, defaultValue) {
        const ts = new TomSelect(elementId, {
            valueField: 'code', labelField: 'text', searchField: ['text', 'code'], maxOptions: 20,
            options: [{ code: 'TPE', text: '🇹🇼 桃園 (TPE)' }, { code: 'KIX', text: '🇯🇵 大阪關西 (KIX)' }],
            create: input => ({ code: input.toUpperCase(), text: input.toUpperCase() }),
            load: (query, callback) => {
                if (!query.length) return callback();
                fetch(`/api/airports?q=${encodeURIComponent(query)}`).then(r => r.json()).then(callback).catch(() => callback());
            }
        });
        if (defaultValue) {
            if (!ts.options[defaultValue]) ts.addOption({ code: defaultValue, text: defaultValue });
            ts.setValue(defaultValue);
        }
        return ts;
    }
    const todayStr = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);  // 台灣日期
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
"""

# --- 1. 背景監控專屬網頁 HTML ---
MONITOR_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>我的監控</title>
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    {{ tom_select_assets|safe }}
    <style>
        {{ base_css|safe }}
        .quota { padding: 14px 16px; margin-top: 18px; }
        .quota-top { display: flex; justify-content: space-between; align-items: baseline; font-size: .85rem; color: var(--ink-2); }
        .quota-top b { font-size: 1.05rem; color: var(--ink); }
        .bar { height: 8px; border-radius: 99px; background: var(--chip); margin: 10px 0 8px; overflow: hidden; }
        .bar i { display: block; height: 100%; border-radius: 99px; background: var(--accent); transition: width .3s; }
        .bar.warn i { background: var(--up); }
        .quota p { margin: 0; font-size: .75rem; color: var(--ink-3); line-height: 1.6; }

        .item { padding: 16px; margin-bottom: 12px; }
        .item-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
        .item-title { font-size: 1.1rem; font-weight: 700; }
        .item-sub { font-size: .8rem; color: var(--ink-3); margin-top: 3px; }
        .item-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
        .item-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; padding-top: 10px; border-top: 1px dashed var(--line); }
        .item-foot span { font-size: .75rem; color: var(--ink-3); }
        .item-foot .actions { display: flex; gap: 4px; }
        .empty { padding: 32px 16px; text-align: center; color: var(--ink-3); font-size: .9rem; line-height: 1.7; }

        .toast { position: fixed; left: 50%; top: 16px; transform: translate(-50%, -80px); background: var(--ink); color: var(--card);
                 padding: 10px 16px; border-radius: 999px; font-size: .85rem; transition: transform .25s; z-index: 50; white-space: nowrap; }
        .toast.show { transform: translate(-50%, 0); }

        /* 編輯面板 */
        .sheet { position: fixed; inset: 0; background: var(--bg); z-index: 20; display: flex; flex-direction: column; }
        .sheet-head { display: grid; grid-template-columns: 70px 1fr 70px; align-items: center; padding: 12px 8px; border-bottom: 1px solid var(--line); background: var(--card); }
        .sheet-head b { text-align: center; font-size: 1rem; }
        .sheet-head .btn-text { font-size: .92rem; }
        .sheet-head .save { color: var(--accent); font-weight: 700; text-align: right; }
        .sheet-body { flex: 1; overflow-y: auto; padding: 16px 16px 40px; }
        .sheet-body .wrap-in { max-width: 680px; margin: 0 auto; }
        .group { padding: 16px; margin-bottom: 14px; }
        .group h3 { margin: 0 0 12px; font-size: .9rem; color: var(--ink-2); }
        .seg { display: flex; background: var(--chip); border-radius: 12px; padding: 3px; margin-bottom: 14px; }
        .seg button { flex: 1; border: 0; background: none; color: var(--ink-2); font: inherit; font-size: .88rem; padding: 9px 6px; border-radius: 10px; cursor: pointer; }
        .seg button.on { background: var(--card); color: var(--ink); font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
        .seg button small { display: block; font-size: .7rem; color: var(--ink-3); font-weight: 400; margin-top: 1px; }
        .swap { width: 28px; height: 46px; border: 0; background: none; color: var(--accent); font-size: 1.1rem; cursor: pointer; padding: 0; }
        .quick { display: flex; gap: 6px; overflow-x: auto; margin-top: 10px; scrollbar-width: none; }
        .quick::-webkit-scrollbar { display: none; }
        .quick button { flex: none; border: 1px solid var(--line); background: var(--card); color: var(--ink-2); border-radius: 999px; padding: 5px 11px; font: inherit; font-size: .78rem; cursor: pointer; }
        .date-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
        .date-chip { display: inline-flex; align-items: center; gap: 4px; background: var(--accent-soft); color: var(--accent); border-radius: 8px; padding: 6px 6px 6px 10px; font-size: .85rem; font-weight: 600; }
        .date-chip button { border: 0; background: none; color: inherit; font-size: 1rem; cursor: pointer; padding: 0 4px; line-height: 1; }
        .add-date { display: flex; gap: 8px; }
        .add-date input { flex: 1; }
        .add-date .btn-soft { height: 46px; }
        .choice { display: block; border: 1.5px solid var(--line); border-radius: 12px; padding: 12px 14px; margin-bottom: 8px; cursor: pointer; }
        .choice.on { border-color: var(--accent); background: var(--accent-soft); }
        .choice b { display: block; font-size: .92rem; }
        .choice span { font-size: .78rem; color: var(--ink-3); }
        .flights-box { margin-top: 10px; }
        .flights-box .row { display: flex; justify-content: flex-end; margin-top: 8px; }
        .opt-row { display: grid; grid-template-columns: 1fr auto 28px; gap: 8px; align-items: center; margin-bottom: 10px; }
        .mini-seg { display: flex; background: var(--chip); border-radius: 10px; padding: 3px; }
        .mini-seg button { border: 0; background: none; font: inherit; font-size: .78rem; padding: 8px 9px; border-radius: 8px; color: var(--ink-2); cursor: pointer; white-space: nowrap; }
        .mini-seg button.on { background: var(--card); color: var(--ink); font-weight: 600; }
        .opt-row .del { border: 0; background: none; color: var(--ink-3); font-size: 1.2rem; cursor: pointer; }
        .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .check { display: flex; align-items: center; gap: 8px; font-size: .88rem; color: var(--ink-2); margin-top: 6px; }
        .check input { width: 18px; height: 18px; accent-color: var(--accent); }
        select.native { width: 100%; height: 46px; padding: 0 10px; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--card); color: var(--ink); font: inherit; font-size: 16px; }
        .cost { font-size: .8rem; color: var(--ink-3); text-align: center; margin-top: 4px; }
        .err { color: var(--up); font-size: .85rem; margin: 0 2px 12px; }
    </style>
</head>
<body>
{{ page_nav|safe }}
<div class="toast" id="toast"></div>
<div class="wrap has-bar">
    <header>
        <h1>⚙️ 我的監控</h1>
        <p>系統每天自動查價，價格變動時會通知你。修改後會自動儲存。</p>
    </header>

    <div id="loading" style="margin-top:20px"><div class="card skeleton"></div><div class="card skeleton"></div></div>
    <div id="main" class="hidden">
        <div class="card quota">
            <div class="quota-top"><span>預估未來 30 天查價用量</span><span><b class="num" id="quotaUse">0</b> / <span id="quotaCap">230</span> 次</span></div>
            <div class="bar" id="quotaBar"><i style="width:0"></i></div>
            <p>SerpApi 免費方案每月 250 次，其中保留 20 次給即時查價。單程航班每天查 3 次、來回比價每天查 1 次。</p>
        </div>

        <div class="section-title"><h2>追蹤中</h2></div>
        <div id="list"></div>

        {% if page_user %}
        <!-- Discord 通知設定只在密碼登入版 (沒有 LINE) 出現；LINE 版用 LINE 通知就夠了 -->
        <div class="section-title"><h2>Discord 通知</h2></div>
        <div class="card group">
            <div class="field"><label>Discord Webhook 網址</label>
                <input class="input" id="discordInput" placeholder="https://discord.com/api/webhooks/…" autocomplete="off"></div>
            <div style="display:flex;gap:8px">
                <button type="button" class="btn btn-soft" onclick="saveDiscord()">儲存</button>
                <button type="button" class="btn btn-soft" id="testBtn" onclick="testNotify()">傳送測試通知</button>
            </div>
            <p style="margin:12px 0 0;font-size:.78rem;color:var(--ink-3);line-height:1.6">
                留空的話會使用 Render 上設定的 DISCORD_WEBHOOK_URL。想改發到別的頻道，在 Discord 頻道的「編輯頻道 → 整合 → Webhook」建立後複製網址貼上。</p>
        </div>
        {% endif %}
    </div>
</div>
<div class="bottom-bar">
    <div class="inner"><button type="button" class="btn btn-primary" onclick="openEditor()">＋ 新增追蹤</button></div>
</div>

<div class="sheet hidden" id="sheet">
    <div class="sheet-head">
        <button type="button" class="btn-text" onclick="closeEditor()">取消</button>
        <b id="sheetTitle">新增追蹤</b>
        <button type="button" class="btn-text save" onclick="saveEditor()">完成</button>
    </div>
    <div class="sheet-body"><div class="wrap-in" id="sheetBody"></div></div>
</div>

<script>
    let userId = "{{ page_user }}";
    const liffId = "{{ liff_id }}";
    {{ airport_select_js|safe }}

    const POPULAR = { KIX: '大阪', NRT: '東京成田', HND: '東京羽田', FUK: '福岡', OKA: '沖繩', CTS: '札幌', ICN: '首爾', BKK: '曼谷',
                      TPE: '桃園', TSA: '松山', KHH: '高雄', LAX: '洛杉磯', SFO: '舊金山', SAN: '聖地牙哥', SEA: '西雅圖', OIT: '大分' };
    const QUOTA_CAP = 230;          // 250 - 保留給即時查價的 20 次
    const RUNS_PER_DAY = 3;         // GitHub Actions 每天執行 3 次
    const WEEK = '日一二三四五六';

    let items = [];       // 畫面上的追蹤項目
    let editing = null;   // 編輯中的草稿
    let tsList = [];      // 編輯面板裡的 TomSelect，關閉時要清掉
    let nextId = 1;
    let discordWebhook = '';  // 使用者的 Discord Webhook (選填)

    const cityName = code => POPULAR[code] ? `${POPULAR[code]} ${code}` : code;
    const mmdd = d => `${d.slice(5, 7)}/${d.slice(8, 10)}`;
    const dateText = d => `${mmdd(d)} (${WEEK[new Date(d + 'T12:00:00').getDay()]})`;
    const daysLeft = d => Math.max(0, Math.round((new Date(d + 'T00:00:00+08:00') - new Date(todayStr() + 'T00:00:00+08:00')) / 86400e3));

    // ---------- 額度估算 ----------
    function itemCost(it) {
        if (it.type === 'oneway') {
            const perRun = Math.max(1, it.flights.length);
            return it.dates.reduce((sum, d) => sum + Math.min(30, daysLeft(d) + 1) * RUNS_PER_DAY * perRun, 0);
        }
        if (!it.out) return 0;
        // 來回比價：每個機場每天 1 次，另外推播時多查 1 次回程細節 (估每月 3 次)
        return it.options.length * Math.min(30, daysLeft(it.out) + 1) + (it.options.length ? 3 : 0);
    }

    function renderQuota() {
        const use = items.reduce((s, it) => s + itemCost(it), 0);
        document.getElementById('quotaUse').textContent = use;
        document.getElementById('quotaCap').textContent = QUOTA_CAP;
        const bar = document.getElementById('quotaBar');
        bar.classList.toggle('warn', use > QUOTA_CAP);
        bar.querySelector('i').style.width = Math.min(100, use / QUOTA_CAP * 100) + '%';
    }

    // ---------- config.json ⇄ 畫面資料 ----------
    function fromConfig(saved) {
        const out = [];
        const today = todayStr();
        (saved.segments || []).forEach(seg => {
            // 同一航段裡航班設定相同的日期合成一個項目
            const groups = new Map();
            (seg.date_schedules || []).filter(ds => ds.date && ds.date >= today).forEach(ds => {
                const key = (ds.flights || []).join(',');
                if (!groups.has(key)) groups.set(key, { flights: ds.flights || [], dates: [] });
                groups.get(key).dates.push(ds.date);
            });
            groups.forEach(g => out.push({ id: nextId++, type: 'oneway', origin: seg.origin, dest: seg.destination, dates: g.dates.sort(), flights: g.flights }));
        });
        (saved.trips || []).forEach(t => {
            const opts = t.options || [];
            out.push({
                id: nextId++, type: 'trip', name: t.name || '長程行程', origin: (opts[0] || {}).origin || 'TPE',
                out: t.outbound_date || '', ret: t.return_date || '',
                options: opts.map(o => ({ dest: o.destination, stops: o.max_stops || 0, note: o.note || '' })),
                maxLayover: t.max_layover_hours || 0, overnight: !!t.allow_overnight_layover, raw: t
            });
        });
        return out;
    }

    function toConfig() {
        const segments = items.filter(it => it.type === 'oneway').map((it, i) => ({
            segment_no: i + 1, origin: it.origin, destination: it.dest,
            date_schedules: it.dates.map(d => ({ date: d, flights: it.flights }))
        }));
        const trips = items.filter(it => it.type === 'trip').map(it => Object.assign({}, it.raw || {}, {
            name: it.name, outbound_date: it.out, return_date: it.ret || null,
            options: it.options.map(o => ({ label: `${o.dest} ${o.stops ? '轉機' : '直飛'}`, origin: it.origin, destination: o.dest, max_stops: o.stops,
                                            ...(o.note ? { note: o.note } : {}) })),
            max_layover_hours: it.maxLayover || null, allow_overnight_layover: it.overnight,
            alert_min_diff: (it.raw && it.raw.alert_min_diff) || 500, min_interval_hours: (it.raw && it.raw.min_interval_hours) || 20
        }));
        return { segments, trips };
    }

    async function persist(message) {
        try {
            const res = await fetch('/api/save_setting', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                // 頁面上沒有 Discord 欄位 (LINE 版) 時不送，避免清掉 config.json 裡原有的設定
                body: JSON.stringify(Object.assign({ user_id: userId }, document.getElementById('discordInput') ? { discord_webhook: discordWebhook } : {}, toConfig()))
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            toast(message || '已儲存');
        } catch (err) { toast('⚠️ 儲存失敗，請稍後再試'); }
    }

    function saveDiscord() {
        const url = document.getElementById('discordInput').value.trim();
        const isWebhook = ['https://discord.com/api/webhooks/', 'https://discordapp.com/api/webhooks/'].some(p => url.startsWith(p));
        if (url && !isWebhook) {
            toast('⚠️ 這看起來不是 Discord Webhook 網址'); return;
        }
        discordWebhook = url;
        persist(url ? '已儲存 Discord 設定' : '已移除 Discord 通知');
    }

    async function testNotify() {
        const btn = document.getElementById('testBtn');
        btn.disabled = true; btn.textContent = '傳送中…';
        try {
            const res = await fetch('/api/test_notify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ userId }) });
            const data = await res.json();
            toast(data.ok ? '✅ 已送出測試通知，請到 LINE / Discord 查看' : '⚠️ ' + (data.error || '傳送失敗'));
        } catch (err) { toast('⚠️ 傳送失敗'); }
        btn.disabled = false; btn.textContent = '傳送測試通知';
    }

    function toast(text) {
        const t = document.getElementById('toast');
        t.textContent = text; t.classList.add('show');
        clearTimeout(t._timer); t._timer = setTimeout(() => t.classList.remove('show'), 2000);
    }

    // ---------- 清單 ----------
    function renderList() {
        const box = document.getElementById('list');
        if (!items.length) {
            box.innerHTML = '<div class="card empty">還沒有任何追蹤<br>按下方「新增追蹤」開始，例如 TPE → 大阪的特定日期。</div>';
        } else {
            box.innerHTML = items.map(it => {
                const cost = itemCost(it);
                if (it.type === 'oneway') {
                    return `<div class="card item">
                        <div class="item-head"><div>
                            <div class="item-title">${esc(it.origin)} → ${esc(it.dest)}</div>
                            <div class="item-sub">${esc(cityName(it.origin))} 到 ${esc(cityName(it.dest))} · 單程</div>
                        </div><span class="tag ${it.flights.length ? '' : 'accent'}">${it.flights.length ? '指定 ' + it.flights.length + ' 班' : '追最低價'}</span></div>
                        <div class="item-chips">${it.dates.map(d => `<span class="tag">${dateText(d)}</span>`).join('')}
                            ${it.flights.map(f => `<span class="tag accent">${esc(f)}</span>`).join('')}</div>
                        <div class="item-foot"><span>每月約 ${cost} 次查價</span><div class="actions">
                            <button class="btn-text" onclick="openEditor(${it.id})">編輯</button>
                            <button class="btn-text danger" onclick="removeItem(${it.id})">刪除</button></div></div>
                    </div>`;
                }
                return `<div class="card item">
                    <div class="item-head"><div>
                        <div class="item-title">${esc(it.name)}</div>
                        <div class="item-sub">${dateText(it.out)}${it.ret ? ' ～ ' + dateText(it.ret) + ' · 來回' : ' · 單程'} · 從 ${esc(it.origin)} 出發</div>
                    </div><span class="tag accent">比價 ${it.options.length} 種飛法</span></div>
                    <div class="item-chips">${it.options.map(o => `<span class="tag">${esc(cityName(o.dest))} · ${o.stops ? '可轉機' : '直飛'}</span>`).join('')}</div>
                    <div class="item-foot"><span>每月約 ${cost} 次查價</span><div class="actions">
                        <button class="btn-text" onclick="openEditor(${it.id})">編輯</button>
                        <button class="btn-text danger" onclick="removeItem(${it.id})">刪除</button></div></div>
                </div>`;
            }).join('');
        }
        renderQuota();
    }

    function removeItem(id) {
        const it = items.find(x => x.id === id);
        if (!it || !confirm(`確定要刪除「${it.type === 'trip' ? it.name : it.origin + ' → ' + it.dest}」嗎？`)) return;
        items = items.filter(x => x.id !== id);
        renderList(); persist('已刪除');
    }

    // ---------- 編輯面板 ----------
    function openEditor(id) {
        const it = items.find(x => x.id === id);
        editing = it ? JSON.parse(JSON.stringify(it)) : { id: null, type: 'oneway', origin: 'TPE', dest: 'KIX', dates: [], flights: [],
                                                           name: '', out: '', ret: '', options: [{ dest: 'LAX', stops: 0 }], maxLayover: 6, overnight: false };
        document.getElementById('sheetTitle').textContent = it ? '編輯追蹤' : '新增追蹤';
        document.getElementById('sheet').classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        renderEditor();
    }

    function closeEditor() {
        tsList.forEach(ts => ts.destroy()); tsList = [];
        document.getElementById('sheet').classList.add('hidden');
        document.body.style.overflow = '';
        editing = null;
    }

    function setType(type) { syncEditor(); editing.type = type; renderEditor(); }

    function renderEditor() {
        tsList.forEach(ts => ts.destroy()); tsList = [];
        const e = editing;
        let html = '';
        if (!e.id) {
            html += `<div class="seg">
                <button class="${e.type === 'oneway' ? 'on' : ''}" onclick="setType('oneway')">單程航班<small>日本、韓國等短程</small></button>
                <button class="${e.type === 'trip' ? 'on' : ''}" onclick="setType('trip')">來回比價<small>長程、可比較轉機</small></button>
            </div>`;
        }
        html += '<div id="formErr" class="err hidden"></div>';
        html += e.type === 'oneway' ? onewayForm(e) : tripForm(e);
        html += `<div class="cost" id="costHint"></div>`;
        document.getElementById('sheetBody').innerHTML = html;

        if (e.type === 'oneway') {
            tsList.push(createAirportSelect('#ed_origin', e.origin), createAirportSelect('#ed_dest', e.dest));
            const fts = new TomSelect('#ed_flights', { valueField: 'value', labelField: 'text', plugins: ['remove_button'], onChange: () => updateCost(), create: input => ({ value: input.toUpperCase().replace(/\\s/g, ''), text: input.toUpperCase().replace(/\\s/g, '') }) });
            e.flights.forEach(f => { fts.addOption({ value: f, text: f }); fts.addItem(f, true); });
            tsList.push(fts);
        } else {
            tsList.push(createAirportSelect('#ed_origin', e.origin));
            e.options.forEach((o, i) => tsList.push(createAirportSelect(`#ed_opt_${i}`, o.dest)));
        }
        const dateInput = document.getElementById('ed_new_date');
        if (dateInput) { dateInput.min = todayStr(); dateInput.value = e.dates.length ? '' : todayStr(); }
        ['ed_out', 'ed_ret'].forEach(idName => { const el = document.getElementById(idName); if (el) el.min = todayStr(); });
        updateCost();
    }

    function onewayForm(e) {
        const quick = ['KIX', 'NRT', 'HND', 'FUK', 'OKA', 'CTS', 'ICN', 'BKK'];
        return `
        <div class="card group"><h3>航線</h3>
            <div class="route-row">
                <div><label class="label">出發</label><select id="ed_origin" placeholder="搜尋機場"></select></div>
                <button type="button" class="swap" onclick="swapRoute()" aria-label="對調">⇄</button>
                <div><label class="label">抵達</label><select id="ed_dest" placeholder="搜尋機場"></select></div>
            </div>
            <div class="quick">${quick.map(c => `<button type="button" onclick="pickDest('${c}')">${POPULAR[c]}</button>`).join('')}</div>
        </div>
        <div class="card group"><h3>出發日期（可以加好幾天）</h3>
            <div class="date-chips">${e.dates.map(d => `<span class="date-chip num">${dateText(d)}<button type="button" onclick="removeDate('${d}')" aria-label="移除">×</button></span>`).join('')
                || '<span style="font-size:.82rem;color:var(--ink-3)">還沒有日期</span>'}</div>
            <div class="add-date"><input type="date" id="ed_new_date"><button type="button" class="btn btn-soft" onclick="addDate()">＋ 加入</button></div>
        </div>
        <div class="card group"><h3>要追哪些航班？</h3>
            <label class="choice ${e.flights.length || e.pickFlights ? '' : 'on'}" onclick="setFlightMode(false)"><b>追當天最低價（推薦）</b><span>不限航班，當天有更便宜的直飛就通知你</span></label>
            <label class="choice ${e.flights.length || e.pickFlights ? 'on' : ''}" onclick="setFlightMode(true)"><b>指定航班</b><span>只追你選的班次，例如 GK50</span></label>
            <div class="flights-box ${e.flights.length || e.pickFlights ? '' : 'hidden'}" id="flightsBox">
                <select id="ed_flights" multiple placeholder="輸入航班號後按 Enter"></select>
                <div class="row"><button type="button" class="btn btn-soft" id="ed_lookup" onclick="lookupFlights()">查詢這條航線的班機</button></div>
            </div>
        </div>`;
    }

    function tripForm(e) {
        return `
        <div class="card group"><h3>行程</h3>
            <div class="field"><label>名稱</label><input class="input" id="ed_name" placeholder="例如 SDCC 2027" value="${esc(e.name)}"></div>
            <div class="field"><label>出發機場</label><select id="ed_origin" placeholder="搜尋機場"></select></div>
            <div class="two">
                <div class="field"><label>去程日期</label><input type="date" id="ed_out" value="${esc(e.out)}" onchange="updateCost()"></div>
                <div class="field"><label>回程日期（單程留空）</label><input type="date" id="ed_ret" value="${esc(e.ret)}"></div>
            </div>
        </div>
        <div class="card group"><h3>要比較哪些飛法？</h3>
            ${e.options.map((o, i) => `<div class="opt-row">
                <select id="ed_opt_${i}" placeholder="目的地機場"></select>
                <div class="mini-seg">
                    <button type="button" class="${o.stops ? '' : 'on'}" onclick="setStops(${i}, 0)">直飛</button>
                    <button type="button" class="${o.stops ? 'on' : ''}" onclick="setStops(${i}, 1)">可轉 1 次</button>
                </div>
                <button type="button" class="del" onclick="removeOption(${i})" aria-label="移除">×</button>
            </div>`).join('')}
            <button type="button" class="btn btn-dashed" style="height:42px" onclick="addOption()">＋ 加一個機場比較</button>
        </div>
        <div class="card group"><h3>轉機條件</h3>
            <div class="field"><label>最長轉機時間</label>
                <select class="native" id="ed_layover">${[[3, '3 小時'], [6, '6 小時'], [9, '9 小時'], [0, '不限']].map(([v, t]) => `<option value="${v}" ${Number(e.maxLayover || 0) === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
            <label class="check"><input type="checkbox" id="ed_overnight" ${e.overnight ? '' : 'checked'}> 排除過夜轉機</label>
        </div>`;
    }

    // 把表單上的值寫回草稿 (重繪前呼叫)
    function syncEditor() {
        const e = editing; if (!e) return;
        const val = id => { const el = document.getElementById(id); return el ? el.value : undefined; };
        if (document.getElementById('ed_origin')) e.origin = val('ed_origin') || e.origin;
        if (e.type === 'oneway') {
            if (document.getElementById('ed_dest')) e.dest = val('ed_dest') || e.dest;
            const fts = tsList.find(ts => ts.input && ts.input.id === 'ed_flights');
            if (fts) e.flights = fts.getValue();
        } else {
            if (document.getElementById('ed_name')) e.name = val('ed_name').trim();
            if (document.getElementById('ed_out')) { e.out = val('ed_out'); e.ret = val('ed_ret'); }
            // 換了機場就清掉舊的備註 (例如「LAX→聖地牙哥」的交通說明)
            e.options.forEach((o, i) => { const v = val(`ed_opt_${i}`); if (v && v !== o.dest) { o.dest = v; o.note = ''; } });
            if (document.getElementById('ed_layover')) {
                e.maxLayover = Number(val('ed_layover'));
                e.overnight = !document.getElementById('ed_overnight').checked;
            }
        }
    }

    function updateCost() {
        if (!editing) return;
        syncEditor();
        const c = itemCost(editing);
        document.getElementById('costHint').textContent = c ? `這項追蹤每月約用 ${c} 次查價額度` : '';
    }

    function swapRoute() { syncEditor(); [editing.origin, editing.dest] = [editing.dest, editing.origin]; renderEditor(); }
    function pickDest(code) { syncEditor(); editing.dest = code; renderEditor(); }
    function addDate() {
        syncEditor();
        const d = document.getElementById('ed_new_date').value;
        if (!d) return;
        if (!editing.dates.includes(d)) editing.dates.push(d);
        editing.dates.sort(); renderEditor();
    }
    function removeDate(d) { syncEditor(); editing.dates = editing.dates.filter(x => x !== d); renderEditor(); }
    function setFlightMode(pick) {
        syncEditor();
        editing.pickFlights = pick;
        if (!pick) editing.flights = [];
        renderEditor();
    }
    function setStops(i, stops) { syncEditor(); editing.options[i].stops = stops; renderEditor(); }
    function addOption() { syncEditor(); editing.options.push({ dest: '', stops: 1 }); renderEditor(); }
    function removeOption(i) { syncEditor(); editing.options.splice(i, 1); renderEditor(); }

    async function lookupFlights() {
        syncEditor();
        const btn = document.getElementById('ed_lookup');
        const date = editing.dates[0] || todayStr();
        btn.disabled = true; btn.textContent = '查詢中…';
        try {
            const res = await fetch(`/api/get_flights?origin=${encodeURIComponent(editing.origin)}&dest=${encodeURIComponent(editing.dest)}&date=${date}`);
            const flights = await res.json();
            const fts = tsList.find(ts => ts.input && ts.input.id === 'ed_flights');
            if (!flights.length) toast('查不到這條航線的直飛班機，可以直接輸入航班號');
            else { fts.addOptions(flights.map(f => ({ value: f.code, text: f.text }))); fts.open(); }
        } catch (err) { toast('⚠️ 查詢失敗'); }
        btn.disabled = false; btn.textContent = '查詢這條航線的班機';
    }

    function validate(e) {
        if (e.type === 'oneway') {
            if (!e.origin || !e.dest) return '請選擇出發和抵達機場';
            if (e.origin === e.dest) return '出發和抵達機場不能一樣';
            if (!e.dates.length) return '請至少加入一個日期（選好日期後按「加入」）';
            if (e.pickFlights && !e.flights.length) return '請輸入要追的航班，或改選「追當天最低價」';
        } else {
            if (!e.name) return '請幫行程取個名字';
            if (!e.out) return '請選擇去程日期';
            if (e.ret && e.ret < e.out) return '回程日期不能早於去程';
            e.options = e.options.filter(o => o.dest);
            if (!e.options.length) return '請至少選一個目的地機場';
        }
        return '';
    }

    function saveEditor() {
        syncEditor();
        const e = editing;
        const err = validate(e);
        if (err) {
            const box = document.getElementById('formErr');
            box.textContent = err; box.classList.remove('hidden');
            document.querySelector('.sheet-body').scrollTop = 0;
            return;
        }
        delete e.pickFlights;
        if (e.id) items = items.map(x => x.id === e.id ? e : x);
        else { e.id = nextId++; items.push(e); }
        closeEditor(); renderList(); persist();
    }

    async function main() {
        try {
            if (liffId) {
                await liff.init({ liffId: liffId });
                if (liff.isLoggedIn()) { userId = (await liff.getProfile()).userId; }
                else { liff.login(); return; }
            }
        } catch (err) { console.log("LIFF Init Error:", err); }

        let saved = { segments: [], trips: [] };
        if (userId) {
            try {
                const res = await fetch('/api/my_setting', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ userId }) });
                saved = await res.json();
            } catch (err) { console.log("讀取設定失敗:", err); }
        }
        items = fromConfig(saved);
        discordWebhook = saved.discord_webhook || '';
        const discordInput = document.getElementById('discordInput');
        if (discordInput) discordInput.value = discordWebhook;
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('main').classList.remove('hidden');
        renderList();
    }
    main();
</script>
</body>
</html>
"""

# --- 2. 單次即時查價專屬網頁 HTML ---
INSTANT_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>即時查價</title>
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    {{ tom_select_assets|safe }}
    <style>
        {{ base_css|safe }}
        .form { padding: 16px; margin-top: 18px; }
        .flight-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }
        .flight-head .label { margin: 0; }
        .result { padding: 18px 16px; margin-top: 14px; }
        .result .kicker { font-size: .78rem; color: var(--ink-3); }
        .result .price { font-size: 2rem; font-weight: 750; letter-spacing: -.01em; margin: 4px 0 2px; }
        .result .price small { font-size: .85rem; color: var(--ink-3); margin-right: 3px; }
        .result .meta { font-size: .85rem; color: var(--ink-2); }
        .result pre { white-space: pre-wrap; font: inherit; font-size: .82rem; line-height: 1.7; color: var(--ink-2);
                      background: var(--chip); border-radius: 10px; padding: 12px; margin: 14px 0; }
        .result .btn-soft { width: 100%; height: 44px; text-decoration: none; }
        .result.error { color: var(--up); font-size: .9rem; }
    </style>
</head>
<body>
{{ page_nav|safe }}
<div class="wrap">
    <header>
        <h1>⚡ 即時查價</h1>
        <p>查一次當下的票價，不會加入背景監控。</p>
    </header>

    <div class="card form">
        <div class="route-row field">
            <div><label class="label">出發</label><select id="inst_origin" placeholder="搜尋機場"></select></div>
            <div class="arrow">→</div>
            <div><label class="label">抵達</label><select id="inst_dest" placeholder="搜尋機場"></select></div>
        </div>
        <div class="field"><label>出發日期</label><input type="date" id="inst_date"></div>
        <div class="field">
            <div class="flight-head">
                <label class="label">指定航班（留空 = 當日最低價）</label>
                <button type="button" class="btn btn-soft" id="inst_search_btn" onclick="searchInstantFlights()">查詢班機</button>
            </div>
            <select id="inst_flight" placeholder="輸入航班號，或按「查詢班機」"></select>
        </div>
        <button type="button" class="btn btn-primary" id="instSubmitBtn" onclick="submitInstantSearch()">立即查價</button>
    </div>

    <div id="instant_result" class="hidden"></div>
</div>
<script>
    let userId = "{{ page_user }}";
    const liffId = "{{ liff_id }}";
    let instFlightTS;
    {{ airport_select_js|safe }}

    async function main() {
        try {
            if (liffId) {
                await liff.init({ liffId: liffId });
                if (liff.isLoggedIn()) { userId = (await liff.getProfile()).userId; }
                else { liff.login(); }
            }
        } catch (err) { console.log("LIFF Init Error:", err); }
        createAirportSelect("#inst_origin", "TPE");
        createAirportSelect("#inst_dest", "KIX");
        const dateInput = document.getElementById("inst_date");
        dateInput.min = todayStr(); dateInput.value = todayStr();
        instFlightTS = new TomSelect("#inst_flight", { valueField: 'value', labelField: 'text', plugins: ['clear_button'], create: true });
    }
    main();

    async function searchInstantFlights() {
        const btn = document.getElementById('inst_search_btn');
        const origin = document.getElementById('inst_origin').value;
        const dest = document.getElementById('inst_dest').value;
        const date = document.getElementById('inst_date').value;
        if (!date) { alert("請先選擇查詢日期！"); return; }
        instFlightTS.clear(); instFlightTS.clearOptions();
        btn.disabled = true; btn.textContent = "查詢中…";
        try {
            const res = await fetch(`/api/get_flights?origin=${origin}&dest=${dest}&date=${date}`);
            const flights = await res.json();
            if (flights.length === 0) alert(`⚠️ ${date} 未查詢到直飛班機資訊`);
            else { instFlightTS.addOptions(flights.map(f => ({ value: f.code, text: f.text }))); instFlightTS.open(); }
        } catch (err) { alert("❌ API 查詢失敗"); }
        btn.disabled = false; btn.textContent = "查詢班機";
    }

    function showResult(html, isError) {
        const box = document.getElementById('instant_result');
        box.className = 'card result' + (isError ? ' error' : '');
        box.innerHTML = html;
        box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async function submitInstantSearch() {
        const btn = document.getElementById('instSubmitBtn');
        const origin = document.getElementById('inst_origin').value;
        const dest = document.getElementById('inst_dest').value;
        const date = document.getElementById('inst_date').value;
        const flight = instFlightTS.getValue() || "";
        if (!date) { alert("請選擇查詢日期"); return; }
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>查價中，約需 5–10 秒…';
        document.getElementById('instant_result').className = 'hidden';
        const searchPayload = { user_id: userId, origin: origin, destination: dest, search_date: date, trip_type: "one_way", mode: "flight", outbound_flight: flight };
        try {
            const response = await fetch('/api/custom-search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(searchPayload) });
            const data = await response.json();
            const r = data.result || {};
            if (data.success && r.min_price) {
                showResult(`
                    <div class="kicker">${esc(origin)} → ${esc(dest)} · ${esc(date)}</div>
                    <div class="price num"><small>NT$</small>${Number(r.min_price).toLocaleString('en-US')}</div>
                    <div class="meta">${esc(r.outbound_flight_no || '')}${r.outbound_time ? '｜' + esc(r.outbound_time) : ''}</div>
                    ${r.outbound_flight ? `<pre>${esc(r.outbound_flight.trim())}</pre>` : ''}
                    <a class="btn btn-soft" href="${esc(r.booking_url)}" target="_blank" rel="noopener">在 Google Flights 開啟</a>`);
            } else {
                showResult(`❌ 查詢失敗：${esc(data.error || '未找到符合的票價')}`, true);
            }
        } catch (err) { showResult("❌ 網路連線異常，請稍後再試。", true); }
        btn.disabled = false; btn.textContent = "重新查價";
    }
</script>
</body>
</html>
"""

# --- 3. 歷史比價戰情室 HTML ---
# 歷史頁面的 LIFF ID 與監控頁不同，未設定環境變數時沿用原本寫死的 ID
HISTORY_LIFF_ID = os.getenv("LIFF_ID_HISTORY", "")

HISTORY_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=0">
    <title>我的票價追蹤</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        {{ base_css|safe }}
        .flight { padding: 16px; margin-bottom: 12px; cursor: pointer; transition: border-color .15s, opacity .15s; position: relative; }
        .flight.selected { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
        .flight.dim { opacity: .45; }
        .f-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
        .f-code { font-weight: 700; font-size: 1.05rem; display: flex; align-items: center; gap: 8px; }
        .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
        .f-sub { color: var(--ink-3); font-size: .8rem; margin-top: 3px; }
        .f-when { text-align: right; font-size: .82rem; color: var(--ink-2); white-space: nowrap; }
        .f-when b { display: block; font-size: .78rem; color: var(--accent); font-weight: 600; margin-top: 2px; }
        .f-mid { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 14px; gap: 12px; }
        .price { font-size: 1.75rem; font-weight: 750; letter-spacing: -.01em; line-height: 1; }
        .price small { font-size: .8rem; font-weight: 600; color: var(--ink-3); margin-right: 3px; }
        .delta { display: inline-block; margin-top: 8px; font-size: .78rem; font-weight: 600; padding: 3px 8px; border-radius: 6px; }
        .delta.down { color: var(--down); background: var(--down-soft); }
        .delta.up { color: var(--up); background: var(--up-soft); }
        .delta.flat { color: var(--ink-3); background: var(--chip); }
        .best { display: inline-block; margin: 8px 0 0 6px; font-size: .75rem; font-weight: 600; padding: 3px 8px; border-radius: 6px;
                color: var(--best); background: var(--best-soft); }
        .spark { width: 46%; max-width: 220px; height: 44px; flex: none; }
        .itin { margin-top: 12px; padding: 10px 12px; border-radius: 10px; background: var(--chip); font-size: .78rem; color: var(--ink-2); line-height: 1.6; }
        .f-stats { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line); }
        .f-stats div { font-size: .75rem; color: var(--ink-3); }
        .f-stats b { display: block; font-size: .9rem; color: var(--ink); margin-top: 2px; font-weight: 600; }
        .chart-card { padding: 16px; }
        .seg { display: inline-flex; background: var(--chip); border-radius: 10px; padding: 3px; }
        .seg button { border: 0; background: none; color: var(--ink-2); font-size: .8rem; padding: 6px 12px; border-radius: 8px; cursor: pointer; }
        .seg button.on { background: var(--card); color: var(--ink); font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
        .chart-box { position: relative; height: 280px; margin-top: 14px; }
        .log { padding: 4px 16px; }
        .log-day { font-size: .75rem; color: var(--ink-3); font-weight: 600; padding: 14px 0 6px; }
        .log-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--line); font-size: .88rem; }
        .log-day + .log-row { border-top: 0; }
        .log-row .t { color: var(--ink-3); width: 40px; flex: none; font-size: .8rem; }
        .log-row .n { flex: 1; min-width: 0; font-weight: 600; }
        .log-row .n small { display: block; color: var(--ink-3); font-size: .75rem; font-weight: 400; margin-top: 2px; }
        .log-row .p { font-weight: 600; text-align: right; flex: none; }
        .log-row .d { display: block; font-size: .75rem; font-weight: 600; margin-top: 2px; }
        .d.down { color: var(--down); } .d.up { color: var(--up); } .d.flat { color: var(--ink-3); }
        details.past { margin-top: 8px; }
        details.past summary { cursor: pointer; color: var(--ink-2); font-size: .9rem; padding: 10px 2px; list-style: none; }
        details.past summary::-webkit-details-marker { display: none; }
        details.past summary::before { content: "▸ "; }
        details.past[open] summary::before { content: "▾ "; }
    </style>
</head>
<body>
{{ page_nav|safe }}
<div class="wrap">
    <header>
        <h1>✈️ 我的票價追蹤</h1>
        <p id="summary">正在載入…</p>
    </header>

    <div class="chips" id="routeChips"></div>

    <div id="loading"><div class="card skeleton"></div><div class="card skeleton"></div></div>
    <div id="stateBox" class="state hidden"></div>

    <div id="content" class="hidden">
        <div class="section-title">
            <h2>追蹤中的航班</h2>
            <button class="link hidden" id="clearSel" onclick="clearSelection()">顯示全部</button>
        </div>
        <div id="activeList"></div>
        <details class="past hidden" id="pastBox">
            <summary id="pastTitle"></summary>
            <div id="pastList"></div>
        </details>

        <div class="section-title">
            <h2>價格走勢</h2>
            <div class="seg" id="rangeSeg">
                <button data-days="3">3 天</button>
                <button data-days="7" class="on">7 天</button>
                <button data-days="30">30 天</button>
                <button data-days="0">全部</button>
            </div>
        </div>
        <div class="card chart-card">
            <div class="chart-box"><canvas id="priceChart"></canvas></div>
        </div>

        <div class="section-title">
            <h2>價格變動紀錄</h2>
            <button class="link" id="logToggle" onclick="toggleLogMode()">顯示每次查價</button>
        </div>
        <div class="card log" id="logList"></div>
    </div>
</div>

<script>
    const LIFF_ID = "{{ liff_id }}";
    const PALETTE = ['#2563eb', '#0d9488', '#d97706', '#db2777', '#7c3aed', '#0891b2', '#65a30d', '#ea580c'];
    const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

    let groups = [];            // 每個 (航線, 出發日, 航班) 一組
    let routeFilter = '';       // '' 代表全部航線
    let rangeDays = 7;
    let selected = new Set();   // 點選的卡片；空集合代表顯示全部
    let logAll = false;         // false = 只列出價格有變動的紀錄
    let chart = null;

    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const money = n => Number(n).toLocaleString('en-US');
    const todayStr = () => { const d = new Date(Date.now() + 8 * 3600e3); return d.toISOString().slice(0, 10); };  // 台灣日期
    const mmdd = s => s ? `${s.slice(5, 7)}/${s.slice(8, 10)}` : '';
    const hhmm = s => s ? s.slice(11, 16) : '';

    function parseFlight(details) {
        // "捷星日本航空 GK 50" → { code: "GK 50", airline: "捷星日本航空" }
        const text = String(details || '').trim();
        const m = text.match(/([A-Z0-9]{2})\\s*(\\d{1,4})\\s*$/i);
        if (!m) return { code: text || '未知航班', airline: '' };
        return { code: `${m[1].toUpperCase()} ${m[2]}`, airline: text.slice(0, m.index).trim() };
    }

    function buildGroups(records) {
        const map = new Map();
        records.forEach(r => {
            const price = Number(String(r.price ?? '').replace(/[^\\d.]/g, ''));
            if (!price || !r.updated_at || !r.origin || !r.destination) return;
            // 轉機 / 來回行程用 track_label 分組 (例如 "SDCC 2027 · SAN 轉機")，每次最便宜的航班組合可能不同
            const parts = r.track_label ? r.track_label.split(' · ') : null;
            const f = parts ? { code: parts.slice(1).join(' · ') || r.track_label, airline: '' } : parseFlight(r.flight_details);
            const key = parts ? ['trip', r.track_label, r.date, r.return_date].join('|') : [r.origin, r.destination, r.date, f.code].join('|');
            if (!map.has(key)) map.set(key, { key, origin: r.origin, dest: r.destination, date: r.date || '', code: f.code, airline: f.airline,
                                              trip: parts ? parts[0] : '', returnDate: r.return_date || '', points: [] });
            const g = map.get(key);
            if (!g.airline && f.airline) g.airline = f.airline;
            if (parts && (!g.itin || r.updated_at >= g.itin.t)) {
                g.itin = { t: r.updated_at, route: r.route, flights: r.flight_details, layovers: r.layovers, duration: r.total_duration };
            }
            g.points.push({ t: r.updated_at, p: price });
        });
        const today = todayStr();
        const list = [...map.values()].map(g => {
            g.points.sort((a, b) => a.t.localeCompare(b.t));
            const prices = g.points.map(x => x.p);
            g.last = g.points[g.points.length - 1];
            g.prev = [...g.points].reverse().find(x => x.p !== g.last.p);  // 上一次不同的價格
            g.min = Math.min(...prices); g.max = Math.max(...prices);
            g.past = g.date && g.date < today;
            return g;
        });
        if (!list.length) return list;  // 還沒有任何紀錄 (新使用者)
        // 最近 3 天內還有被查價的才算「追蹤中」，其餘是已出發或以前的單次查價
        const latest = list.reduce((a, g) => g.last.t > a ? g.last.t : a, '');
        const cutoff = new Date(new Date(latest.replace(' ', 'T') + '+08:00') - 3 * 86400e3 + 8 * 3600e3).toISOString().slice(0, 19).replace('T', ' ');
        list.forEach(g => g.active = !g.past && g.last.t >= cutoff);
        // 依出發日、航線排序，顏色固定跟著航班
        list.sort((a, b) => (a.date + a.origin + a.code).localeCompare(b.date + b.origin + b.code));
        list.forEach((g, i) => g.color = PALETTE[i % PALETTE.length]);
        return list;
    }

    const durText = m => m ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}m` : '';

    function departLabel(date) {
        if (!date) return { day: '', left: '' };
        const d = new Date(date + 'T00:00:00+08:00');
        const diff = Math.round((d - new Date(todayStr() + 'T00:00:00+08:00')) / 86400e3);
        const left = diff > 1 ? `${diff} 天後出發` : diff === 1 ? '明天出發' : diff === 0 ? '今天出發' : '已出發';
        return { day: `${mmdd(date)} (${WEEKDAYS[new Date(date + 'T12:00:00').getDay()]})`, left };
    }

    function deltaHtml(cur, prev, cls, compact) {
        if (prev === undefined || prev === null) return `<span class="${cls} flat">首筆紀錄</span>`;
        const diff = cur - prev;
        if (diff === 0) return `<span class="${cls} flat">持平</span>`;
        const pct = compact ? '' : ` (${Math.abs(diff / prev * 100).toFixed(1)}%)`;
        return diff < 0
            ? `<span class="${cls} down">▼ ${money(-diff)}${pct}</span>`
            : `<span class="${cls} up">▲ ${money(diff)}${pct}</span>`;
    }

    function sparkline(points, color) {
        const pts = points.slice(-30);
        if (pts.length < 2) return '';
        const w = 220, h = 44, pad = 4;
        const ps = pts.map(x => x.p), lo = Math.min(...ps), hi = Math.max(...ps), span = hi - lo || 1;
        const xy = pts.map((x, i) => [pad + i * (w - 2 * pad) / (pts.length - 1), h - pad - (x.p - lo) / span * (h - 2 * pad)]);
        const d = xy.map((c, i) => (i ? 'L' : 'M') + c[0].toFixed(1) + ' ' + c[1].toFixed(1)).join(' ');
        const [ex, ey] = xy[xy.length - 1];
        return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
            <path d="${d} L${ex.toFixed(1)} ${h} L${pad} ${h} Z" fill="${color}" opacity=".08"/>
            <path d="${d}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
            <circle cx="${ex}" cy="${ey}" r="3" fill="${color}"/></svg>`;
    }

    function cardHtml(g) {
        const dep = departLabel(g.date);
        const isBest = g.min < g.max && g.last.p === g.min;
        const delta = g.prev ? deltaHtml(g.last.p, g.prev.p, 'delta')
            : `<span class="delta flat">${g.points.length > 1 ? '價格未變動' : '首筆紀錄'}</span>`;
        const dim = selected.size && !selected.has(g.key) ? ' dim' : '';
        const sel = selected.has(g.key) ? ' selected' : '';
        return `<div class="card flight${sel}${dim}" onclick="toggleSelect('${esc(g.key)}')">
            <div class="f-top">
                <div>
                    <div class="f-code"><span class="dot" style="background:${g.color}"></span>${esc(g.code)}</div>
                    <div class="f-sub">${g.trip
                        ? `${esc(g.trip)} · ${g.returnDate ? '來回，回程 ' + mmdd(g.returnDate) : '單程'}`
                        : `${esc(g.origin)} → ${esc(g.dest)}${g.airline ? ' · ' + esc(g.airline) : ''}`}</div>
                </div>
                <div class="f-when num">${dep.day}<b>${dep.left}</b></div>
            </div>
            <div class="f-mid">
                <div>
                    <div class="price num"><small>NT$</small>${money(g.last.p)}</div>
                    ${delta}${isBest ? '<span class="best">🏆 歷史最低</span>' : ''}
                </div>
                ${sparkline(g.points, g.color)}
            </div>
            ${g.itin ? `<div class="itin">目前最便宜：${esc(g.itin.route)}<br>${esc(g.itin.flights)} · ${durText(g.itin.duration)}${g.itin.layovers ? ' · 轉機 ' + esc(g.itin.layovers) : ' · 直飛'}</div>` : ''}
            <div class="f-stats num">
                <div>最低<b>${money(g.min)}</b></div>
                <div>最高<b>${money(g.max)}</b></div>
                <div>最後查價<b>${mmdd(g.last.t)} ${hhmm(g.last.t)}</b></div>
            </div>
        </div>`;
    }

    const inRoute = g => !routeFilter || `${g.origin}-${g.dest}` === routeFilter;
    const visibleGroups = () => groups.filter(inRoute).filter(g => selected.size ? selected.has(g.key) : g.active);

    function rangeStart() {
        if (!rangeDays) return '';
        const d = new Date(Date.now() + 8 * 3600e3 - rangeDays * 86400e3);
        return d.toISOString().slice(0, 19).replace('T', ' ');
    }

    function renderRoutes() {
        const routes = [...new Set(groups.map(g => `${g.origin}-${g.dest}`))];
        const box = document.getElementById('routeChips');
        box.innerHTML = [['', '全部航線'], ...routes.map(r => [r, r.replace('-', ' → ')])]
            .map(([v, label]) => `<button class="chip${v === routeFilter ? ' on' : ''}" data-route="${esc(v)}">${esc(label)}</button>`).join('');
        box.querySelectorAll('.chip').forEach(b => b.onclick = () => { routeFilter = b.dataset.route; selected.clear(); render(); });
        box.classList.toggle('hidden', routes.length < 2);
    }

    function renderCards() {
        const shown = groups.filter(inRoute);
        const active = shown.filter(g => g.active), past = shown.filter(g => !g.active);
        document.getElementById('activeList').innerHTML = active.length
            ? active.map(cardHtml).join('') : '<div class="card state">目前沒有追蹤中的航班，可以到「監控設定」新增。</div>';
        document.getElementById('pastList').innerHTML = past.map(cardHtml).join('');
        document.getElementById('pastBox').classList.toggle('hidden', !past.length);
        document.getElementById('pastTitle').textContent = `已出發或停止追蹤 (${past.length})`;
        document.getElementById('clearSel').classList.toggle('hidden', !selected.size);
    }

    function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

    function renderChart() {
        const start = rangeStart();
        const gs = visibleGroups();
        const times = [...new Set(gs.flatMap(g => g.points.filter(x => x.t >= start).map(x => x.t)))].sort();
        const datasets = gs.map(g => {
            const byT = new Map(g.points.map(x => [x.t, x.p]));
            return {
                label: `${g.code}  ${mmdd(g.date)}`, data: times.map(t => byT.has(t) ? byT.get(t) : null),
                borderColor: g.color, backgroundColor: g.color, borderWidth: 2, pointRadius: times.length > 40 ? 0 : 2.5,
                pointHoverRadius: 5, tension: 0.25, spanGaps: true
            };
        }).filter(ds => ds.data.some(v => v !== null));

        const grid = cssVar('--line'), tick = cssVar('--ink-3');
        if (chart) chart.destroy();
        chart = new Chart(document.getElementById('priceChart'), {
            type: 'line',
            data: { labels: times, datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'nearest', axis: 'x', intersect: false },
                plugins: {
                    legend: { position: 'bottom', labels: { color: tick, usePointStyle: true, pointStyle: 'circle', boxWidth: 8, padding: 14, font: { size: 11 } } },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,.92)', padding: 10, cornerRadius: 8, usePointStyle: true,
                        callbacks: {
                            title: c => c[0] ? `${mmdd(c[0].label)} ${hhmm(c[0].label)}` : '',
                            label: c => ` ${c.dataset.label.trim()}：NT$ ${money(c.parsed.y)}`
                        }
                    }
                },
                scales: {
                    x: { grid: { display: false }, border: { color: grid },
                         ticks: { color: tick, maxTicksLimit: 6, maxRotation: 0, font: { size: 10 },
                                  callback: function (v) { return mmdd(this.getLabelForValue(v)); } } },
                    y: { grid: { color: grid }, border: { display: false },
                         ticks: { color: tick, font: { size: 10 }, callback: v => money(v) } }
                }
            }
        });
    }

    function renderLog() {
        const start = rangeStart();
        const rows = [];
        visibleGroups().forEach(g => g.points.forEach((x, i) => {
            const prev = i ? g.points[i - 1].p : null;
            if (x.t < start) return;
            if (!logAll && prev !== null && prev === x.p) return;
            rows.push({ g, t: x.t, p: x.p, prev });
        }));
        rows.sort((a, b) => b.t.localeCompare(a.t));
        const box = document.getElementById('logList');
        if (!rows.length) { box.innerHTML = '<div class="state">這段期間沒有價格變動</div>'; return; }
        let html = '', day = '';
        rows.slice(0, 200).forEach(r => {
            const d = r.t.slice(0, 10);
            if (d !== day) { day = d; html += `<div class="log-day">${mmdd(d)} 週${WEEKDAYS[new Date(d + 'T12:00:00').getDay()]}</div>`; }
            html += `<div class="log-row num">
                <span class="t">${hhmm(r.t)}</span>
                <span class="dot" style="background:${r.g.color}"></span>
                <span class="n">${esc(r.g.code)}<small>${esc(r.g.origin)} → ${esc(r.g.dest)} · ${mmdd(r.g.date)} 出發</small></span>
                <span class="p">${money(r.p)}${deltaHtml(r.p, r.prev, 'd', true)}</span>
            </div>`;
        });
        box.innerHTML = html;
    }

    function render() { renderRoutes(); renderCards(); renderChart(); renderLog(); }
    function toggleSelect(key) { selected.has(key) ? selected.delete(key) : selected.add(key); render(); }
    function clearSelection() { selected.clear(); render(); }
    function toggleLogMode() {
        logAll = !logAll;
        document.getElementById('logToggle').textContent = logAll ? '只看價格變動' : '顯示每次查價';
        renderLog();
    }
    document.getElementById('rangeSeg').addEventListener('click', e => {
        const b = e.target.closest('button'); if (!b) return;
        rangeDays = Number(b.dataset.days);
        document.querySelectorAll('#rangeSeg button').forEach(x => x.classList.toggle('on', x === b));
        renderChart(); renderLog();
    });

    function showState(msg) {
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('content').classList.add('hidden');
        const box = document.getElementById('stateBox');
        box.innerHTML = msg; box.classList.remove('hidden');
    }

    async function loadHistory(userId) {
        const res = await fetch('/api/my_history', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ userId })
        });
        const result = await res.json();
        if (result.status !== 'success') throw new Error(result.message || '讀取失敗');
        groups = buildGroups(result.data || []);
        if (!groups.length) return showState('還沒有任何查價紀錄<br>設定監控航班後，系統每天會自動幫你查價三次。');

        const all = groups.flatMap(g => g.points);
        const latest = all.reduce((a, b) => a.t > b.t ? a : b).t;
        document.getElementById('summary').textContent =
            `追蹤 ${groups.filter(g => g.active).length} 個航班 · 共 ${all.length} 筆查價 · 最後更新 ${mmdd(latest)} ${hhmm(latest)}`;
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('content').classList.remove('hidden');
        render();
    }

    async function init() {
        try {
            const pageUser = "{{ page_user }}";  // 密碼登入模式不使用 LIFF
            if (pageUser) return await loadHistory(pageUser);
            await liff.init({ liffId: LIFF_ID });
            if (!liff.isLoggedIn()) return liff.login();
            const profile = await liff.getProfile();
            await loadHistory(profile.userId);
        } catch (err) {
            showState('載入失敗：' + esc(err.message || err) + '<br>請關閉頁面後重新開啟。');
        }
    }
    window.onload = init;
</script>
</body>
</html>
"""

# --- 4. 獨立路由與 API ---
PAGE_NAV = """
<nav class="page-nav">
    <a href="/liff/monitor">監控設定</a><a href="/liff/instant">即時查價</a><a href="/liff/history">歷史紀錄</a><a href="/logout" class="logout">登出</a>
</nav>
<script>document.querySelectorAll('.page-nav a').forEach(a => a.classList.toggle('on', a.getAttribute('href') === location.pathname));</script>
"""

def _render_page(html, liff_id):
    # 密碼登入模式 (Render + Discord 版) 不使用 LIFF，改用登入的使用者並顯示頁面之間的分頁列
    if password_mode():
        return render_template_string(html, liff_id="", page_user=session.get("web_user", ""), page_nav=PAGE_NAV,
                                      base_css=BASE_CSS, tom_select_assets=TOM_SELECT_ASSETS, airport_select_js=AIRPORT_SELECT_JS)
    return render_template_string(html, liff_id=liff_id, page_user="", page_nav="", base_css=BASE_CSS,
                                  tom_select_assets=TOM_SELECT_ASSETS, airport_select_js=AIRPORT_SELECT_JS)

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登入 · 機票價格監控</title>
    <style>
        {{ base_css|safe }}
        .login { max-width: 360px; margin: 18vh auto 0; padding: 28px 22px; }
        .login h1 { font-size: 1.25rem; margin: 0 0 6px; }
        .login p { margin: 0 0 20px; color: var(--ink-3); font-size: .85rem; }
        .login .err { color: var(--up); font-size: .85rem; margin: -6px 0 14px; }
    </style>
</head>
<body>
<div class="wrap">
    <form class="card login" method="post">
        <h1>✈️ 機票價格監控</h1>
        <p>請輸入在 Render 設定的 WEB_PASSWORD</p>
        {% if error %}<div class="err">{{ error }}</div>{% endif %}
        <div class="field"><input class="input" type="password" name="password" placeholder="密碼" autofocus autocomplete="current-password"></div>
        <input type="hidden" name="next" value="{{ next_url }}">
        <button class="btn btn-primary" type="submit">登入</button>
    </form>
</div>
</body>
</html>
"""

@liff_bp.route("/login", methods=['GET', 'POST'])
def login():
    if not password_mode():
        return redirect("/")
    next_url = safe_next(request.values.get("next"))
    error = ""
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), os.environ["WEB_PASSWORD"]):
            session.clear()
            session.permanent = True
            session["web_user"] = web_user_id()
            return redirect(next_url)
        time.sleep(1)  # 拖慢暴力猜密碼
        error = "密碼不正確"
    return render_template_string(LOGIN_HTML, base_css=BASE_CSS, error=error, next_url=next_url)

@liff_bp.route("/logout", methods=['GET'])
def logout():
    session.clear()
    return redirect("/login")

@liff_bp.route("/liff/monitor", methods=['GET'])
def liff_monitor_page():
    return _render_page(MONITOR_HTML, LIFF_ID)

@liff_bp.route("/liff/instant", methods=['GET'])
def liff_instant_page():
    return _render_page(INSTANT_HTML, LIFF_ID)

@liff_bp.route("/liff/history", methods=['GET'])
def liff_history_page():
    return _render_page(HISTORY_HTML, HISTORY_LIFF_ID)

@liff_bp.route("/liff", methods=['GET'])
def liff_page():
    tab = request.args.get('tab')
    if tab == 'instant':
        return _render_page(INSTANT_HTML, LIFF_ID)
    elif tab == 'history':
        return _render_page(HISTORY_HTML, HISTORY_LIFF_ID)
    return _render_page(MONITOR_HTML, LIFF_ID)

@liff_bp.route("/api/airports", methods=['GET'])
def search_airports():
    q = request.args.get('q', '').lower()
    if not q:
        return jsonify([])

    try:
        with open('airports.json', 'r', encoding='utf-8') as f:
            airports = json.load(f)
    except Exception:
        return jsonify([])

    results = []
    for apt in airports:
        search_str = f"{apt.get('code', '')} {apt.get('text', '')} {apt.get('keywords', '')}".lower()
        if q in search_str:
            results.append({"code": apt.get("code"), "text": apt.get("text")})
        if len(results) >= 20:
            break
            
    return jsonify(results)

@liff_bp.route("/api/get_flights", methods=['GET'])
def get_flights():
    origin = request.args.get('origin', 'TPE')
    dest = request.args.get('dest')
    date = request.args.get('date')

    if not dest or not date:
        return jsonify([]), 400

    cache_key = f"{origin}_{dest}_{date}"
    if cache_key in flight_cache:
        return jsonify(flight_cache[cache_key])

    flights = fetch_flights_from_api(origin, dest)
    if flights:
        flight_cache[cache_key] = flights

    return jsonify(flights)

@liff_bp.route("/api/save_setting", methods=['POST'])
def save_setting():
    """儲存監控設定 (設定頁每次修改都會自動呼叫)
    不再另外推播確認訊息：頁面上就看得到結果，也省下 LINE 每月推播額度"""
    data = request.json or {}
    user_id = current_user_id(data.get('user_id'))
    if not user_id:
        return jsonify({"ok": False, "error": "缺少使用者 ID"}), 400

    config = load_config()
    user_entry = config.setdefault("users", {}).setdefault(user_id, {})
    user_entry["monitor_config"] = {"segments": data.get('segments', [])}
    # 舊版頁面不會送 trips，沒送時保留原本的設定
    if "trips" in data:
        user_entry["trips"] = data["trips"]
    if "discord_webhook" in data:
        if data["discord_webhook"]:
            user_entry["discord_webhook"] = data["discord_webhook"]
        else:
            user_entry.pop("discord_webhook", None)
    save_config(config)
    return jsonify({"ok": True})

@liff_bp.route("/api/test_notify", methods=['POST'])
def test_notify():
    """傳一則測試訊息到使用者設定的通知管道 (LINE / Discord)"""
    from notifier import notify, channels_for
    user_id = current_user_id((request.json or {}).get('userId', ''))
    if not user_id:
        return jsonify({"ok": False, "error": "缺少使用者 ID"}), 400
    names = {"line": "LINE", "discord": "Discord"}
    try:
        notify(user_id, "✅ 機票價格監控：測試通知\n收到這則訊息代表通知設定正常！")
        used = "、".join(names[kind] for kind, _ in channels_for(user_id))
        return jsonify({"ok": True, "channels": used})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@liff_bp.route("/api/my_setting", methods=['POST'])
def my_setting():
    """回傳使用者目前的監控設定，讓設定頁打開時帶入原本的內容"""
    user_id = current_user_id((request.json or {}).get('userId', ''))
    user_entry = load_config().get("users", {}).get(user_id, {})
    return jsonify({
        "segments": user_entry.get("monitor_config", {}).get("segments", []),
        "trips": user_entry.get("trips", []),
        "discord_webhook": user_entry.get("discord_webhook", "")
    })

@liff_bp.route("/api/my_history", methods=['POST'])
def my_history():
    data = request.json or {}
    user_id = current_user_id(data.get('userId', ''))
    if not user_id:
        return jsonify({"status": "error", "message": "缺少使用者 ID"}), 400

    try:
        # load_history 會合併 GitHub 上排程寫入的最新紀錄，並把舊格式統一成扁平格式
        return jsonify({"status": "success", "data": load_history().get(user_id, [])})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
