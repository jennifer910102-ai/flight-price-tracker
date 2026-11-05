import os
import json
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, abort, jsonify, render_template_string
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, PushMessageRequest, FlexMessage, FlexContainer, TextMessage

from utils import load_config, save_config, save_price_history
import web_auth
from server import scrape_flight_price

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

AIRLINES_FILE = "airlines.json"
HISTORY_FILE = "history.json"

def get_line_configuration():
    return configuration

def send_line_push(user_id, text_msg):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=text_msg)]
            ))
    except Exception as e:
        print(f"❌ 推播失敗 ({user_id}): {e}")

def send_line_push_flex(user_id, flex_json, alt_text="訊息"):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(PushMessageRequest(
                to=user_id,
                messages=[FlexMessage(alt_text=alt_text, contents=FlexContainer.from_json(json.dumps(flex_json)))]
            ))
    except Exception as e:
        print(f"❌ 推播 Flex 失敗 ({user_id}): {e}")

def get_airline_name(flight_no, default_name="捷星日本航空"):
    if not flight_no:
        return default_name
    prefix = flight_no.strip()[:2].upper()
    if os.path.exists(AIRLINES_FILE):
        try:
            with open(AIRLINES_FILE, "r", encoding="utf-8") as f:
                airline_map = json.load(f)
                return airline_map.get(prefix, default_name)
        except Exception:
            pass
    return default_name

def append_to_history(user_id, search_config, price_result):
    # 沒帶 user_id 的請求 (例如直接打 API 測試) 不寫入歷史，避免產生無主的 DEFAULT 紀錄
    if not user_id or user_id == "DEFAULT":
        return

    # 與背景排程使用同一個扁平格式，並同步到 GitHub，歷史戰情室才看得到
    origin = search_config.get("origin", "TPE")
    destination = search_config.get("destination", "KIX")
    search_date = search_config.get("search_date") or search_config.get("去程日期")
    return_date = search_config.get("return_date") or search_config.get("回程日期")

    legs = [(origin, destination, search_date,
             price_result.get("outbound_flight_no") or search_config.get("outbound_flight", ""),
             price_result.get("outbound_price"))]
    if search_config.get("trip_type", "round") != "one_way" and return_date:
        legs.append((destination, origin, return_date,
                     price_result.get("inbound_flight_no") or search_config.get("inbound_flight_a", ""),
                     price_result.get("inbound_price")))

    for leg_origin, leg_dest, leg_date, flight_no, price in legs:
        if not price:
            continue
        try:
            save_price_history(flight_data=flight_no, current_price=price, user_id=user_id,
                               origin=leg_origin, dest=leg_dest, date=leg_date)
        except Exception as e:
            print(f"❌ 寫入歷史紀錄失敗: {e}", flush=True)

def _save_history_in_background(user_id, search_config, price_result):
    """寫歷史紀錄要同步 GitHub (幾秒鐘)，放到背景執行，查價結果先回給使用者"""
    threading.Thread(target=append_to_history, args=(user_id, search_config, price_result), daemon=True).start()

app = Flask(__name__)
# 有設定 WEB_PASSWORD 時，網頁改用密碼登入 (Render + Discord 版)
web_auth.init_app(app)

from liff_views import liff_bp
app.register_blueprint(liff_bp)

if handler:
    from bot_handlers import register_bot_handlers
    register_bot_handlers(handler, configuration)

@app.route("/", methods=['GET'])
def home():
    if web_auth.password_mode():
        from flask import redirect
        return redirect("/liff/monitor")
    return "Flight Monitor Webhook Server is running!"

@app.route("/callback", methods=['POST'])
def callback():
    if not handler:
        return "LINE Webhook Handler not configured", 500
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        app.logger.error(f"Error: {e}")
        abort(500)
    return 'OK'

@app.route("/api/monitor-quick-search", methods=["POST"])
def monitor_quick_search():
    data = request.json or {}
    user_id = web_auth.current_user_id(data.get("user_id", "DEFAULT"))
    config = load_config()
    users = config.get("users", {})
    user_entry = users.get(user_id) or users.get("DEFAULT")
    
    if not user_entry:
        return jsonify({"success": False, "error": "找不到對應的使用者監控設定"}), 404

    monitor_configs = user_entry.get("monitor_configs", user_entry.get("monitor_config", user_entry.get("search_config", [user_entry])))
    if not isinstance(monitor_configs, list):
        monitor_configs = [monitor_configs]

    if not monitor_configs:
        return jsonify({"success": False, "error": "config.json 中無任何監控航段"}), 400

    results = []
    try:
        for monitor_data in monitor_configs:
            origin = monitor_data.get("origin", "TPE")
            destination = monitor_data.get("destination", "KIX")
            search_date = monitor_data.get("search_date") or monitor_data.get("去程日期")
            return_date = monitor_data.get("return_date") or monitor_data.get("回程日期")
            trip_type = monitor_data.get("trip_type", "round")
            mode = monitor_data.get("mode", "flight")

            if not search_date:
                continue

            search_config = {
                "origin": origin,
                "destination": destination,
                "search_date": search_date,
                "return_date": return_date,
                "trip_type": trip_type,
                "mode": mode,
                "outbound_flight": monitor_data.get("outbound_flight") or monitor_data.get("去程航班") or "",
                "inbound_flight_a": monitor_data.get("inbound_flight_a") or monitor_data.get("回程航班") or "",
                "outbound_time": monitor_data.get("outbound_time", "")
            }

            price_result = scrape_flight_price(search_config, mode=mode)
            _save_history_in_background(user_id, search_config, price_result)
            results.append(price_result)

        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/custom-search", methods=["POST"])
def custom_search_flight():
    data = request.json or {}
    user_id = web_auth.current_user_id(data.get("user_id", "DEFAULT"))
    search_config = {
        "origin": data.get("origin", "TPE"),
        "destination": data.get("destination", "KIX"),
        "search_date": data.get("search_date"),
        "return_date": data.get("return_date"),
        "trip_type": data.get("trip_type", "round"),
        "mode": data.get("mode", "flight"),
        "outbound_flight": data.get("outbound_flight", ""),
        "inbound_flight_a": data.get("inbound_flight_a", ""),
        "outbound_time": data.get("outbound_time", "")
    }

    if not search_config["search_date"]:
        return jsonify({"success": False, "error": "缺少去程日期設定"}), 400

    try:
        price_result = scrape_flight_price(search_config, mode=search_config["mode"])
        _save_history_in_background(user_id, search_config, price_result)
        return jsonify({"success": True, "result": price_result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==========================================
# 旗艦版：多航線比價戰情室 (支援多條折線 + 使用者隔離)
# ==========================================

HISTORY_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=0">
    <title>歷史票價走勢</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <style>
        body { background-color: #f4f6f9; font-family: '微軟正黑體', sans-serif; }
        .filter-card { background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); padding: 20px; margin-bottom: 20px; }
        .chart-card { background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); padding: 20px; margin-bottom: 20px; }
        .chart-container { position: relative; height: 350px; width: 100%; display: none; }
        .price-text { color: #20c997; font-weight: 700; font-size: 1.1em; }
        .flight-text { font-size: 0.85em; color: #8a98ac; }
        .btn-custom { background-color: #4361ee; border: none; font-weight: 600; letter-spacing: 1px; }
        .btn-custom:hover { background-color: #3a53d0; }
    </style>
</head>
<body>
    <div class="container py-4">
        
        <div class="filter-card">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="mb-0" style="color: #2b3452; font-weight: bold;">🎛️ 多航線比價戰情室</h5>
                <select id="viewMode" class="form-select form-select-sm w-auto" style="border-radius: 20px; font-weight: bold; color: #4361ee; border-color: #4361ee;">
                    <option value="all">🌐 共享數據</option>
                    <option value="me">👤 只看我的</option>
                </select>
            </div>
            <div class="row g-2 mb-3">
                <div class="col-6">
                    <label class="form-label text-muted small mb-1">起始日期</label>
                    <input type="date" id="startDate" class="form-control form-control-sm">
                </div>
                <div class="col-6">
                    <label class="form-label text-muted small mb-1">結束日期</label>
                    <input type="date" id="endDate" class="form-control form-control-sm">
                </div>
            </div>
            <div class="input-group">
                <input type="text" id="searchInput" class="form-control" placeholder="例: GK50, MM28, IT213">
                <button class="btn btn-primary btn-custom text-white" type="button" onclick="searchHistory()">套用比價</button>
            </div>
        </div>

        <div id="statusMessage" class="text-center text-muted mb-3" style="font-size: 0.9em;">請輸入航班並點擊套用比價...</div>
        
        <div class="chart-card" id="chartWrapper" style="display: none;">
            <canvas id="priceChart"></canvas>
        </div>

        <div class="accordion" id="dataAccordion" style="display: none;">
            <div class="accordion-item" style="border-radius: 12px; overflow: hidden; border: none; box-shadow: 0 2px 10px rgba(0,0,0,0.05);">
                <h2 class="accordion-header" id="headingOne">
                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapseList" style="background-color: white; font-weight: 600; color: #4361ee;">
                        📋 展開原始數據明細
                    </button>
                </h2>
                <div id="collapseList" class="accordion-collapse collapse" data-bs-parent="#dataAccordion">
                    <div class="accordion-body p-0">
                        <div class="list-group list-group-flush" id="resultsList"></div>
                    </div>
                </div>
            </div>
        </div>

    </div>

    <script>
        let currentUserId = "";
        let priceChart = null;

        const colorPalette = ['#4361ee', '#f72585', '#4cc9f0', '#ff9f1c', '#2a9d8f', '#7209b7'];

        async function initializeLiff() {
            try {
                await liff.init({ liffId: "{{ liff_id }}" });
                if (!liff.isLoggedIn()) {
                    liff.login();
                    return;
                }
                const profile = await liff.getProfile();
                currentUserId = profile.userId;
                
                const today = new Date();
                const lastWeek = new Date(today);
                lastWeek.setDate(lastWeek.getDate() - 7);
                document.getElementById('endDate').value = today.toISOString().split('T')[0];
                document.getElementById('startDate').value = lastWeek.toISOString().split('T')[0];
                
                // 監聽下拉選單改變，自動重新搜尋
                document.getElementById('viewMode').addEventListener('change', searchHistory);
                
                searchHistory();
            } catch (err) {
                document.getElementById('statusMessage').innerText = "LIFF 初始化失敗";
            }
        }

        function renderMultiChart(data) {
            const chartWrapper = document.getElementById('chartWrapper');
            const dataAccordion = document.getElementById('dataAccordion');
            const ctx = document.getElementById('priceChart').getContext('2d');
            
            if (data.length === 0) {
                chartWrapper.style.display = 'none';
                return;
            }
            
            chartWrapper.style.display = 'block';
            dataAccordion.style.display = 'block';

            if (priceChart) {
                priceChart.destroy();
            }

            const chartData = [...data].reverse();
            
            chartData.forEach(item => {
                item.timeKey = item.check_time.substring(0, 16);
            });
            const uniqueTimes = [...new Set(chartData.map(item => item.timeKey))].sort();
            
            const labels = uniqueTimes.map(t => t.substring(5));

            const uniqueFlights = [...new Set(chartData.map(item => item.flight_data))];
            
            const datasets = uniqueFlights.map((flight, index) => {
                const color = colorPalette[index % colorPalette.length];
                
                const prices = uniqueTimes.map(time => {
                    const record = chartData.find(d => d.flight_data === flight && d.timeKey === time);
                    return record ? record.price : null;
                });

                return {
                    label: flight,
                    data: prices,
                    borderColor: color,
                    backgroundColor: color + '22',
                    borderWidth: 3,
                    pointBackgroundColor: '#ffffff',
                    pointBorderColor: color,
                    pointBorderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    tension: 0.4,
                    spanGaps: true
                };
            });

            priceChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        intersect: false,
                        mode: 'index',
                    },
                    plugins: {
                        legend: { 
                            display: true, 
                            position: 'bottom',
                            labels: {
                                usePointStyle: true,
                                boxWidth: 8
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(43, 52, 82, 0.9)',
                            titleFont: { size: 13 },
                            bodyFont: { size: 14, weight: 'bold' },
                            padding: 12,
                            callbacks: {
                                label: function(context) {
                                    return context.dataset.label + ': NT$ ' + context.parsed.y.toLocaleString();
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { display: false, drawBorder: false },
                            ticks: { font: { size: 10 }, color: '#8a98ac', maxRotation: 45, minRotation: 45 }
                        },
                        y: {
                            grid: { color: '#f0f2f5', drawBorder: false, borderDash: [5, 5] },
                            ticks: { 
                                font: { size: 11 }, 
                                color: '#8a98ac',
                                callback: function(value) { return 'NT$ ' + value; }
                            }
                        }
                    }
                }
            });
        }

        async function searchHistory() {
            if (!currentUserId) return;
            
            const keyword = document.getElementById('searchInput').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            const viewMode = document.getElementById('viewMode').value;
            
            const resultsList = document.getElementById('resultsList');
            const statusMessage = document.getElementById('statusMessage');
            const chartWrapper = document.getElementById('chartWrapper');
            const dataAccordion = document.getElementById('dataAccordion');
            
            statusMessage.innerText = "⏳ 擷取與過濾資料中...";
            resultsList.innerHTML = "";
            chartWrapper.style.display = 'none';
            dataAccordion.style.display = 'none';
            if (priceChart) priceChart.destroy();

            try {
                const response = await fetch('/api/query_history', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        userId: currentUserId, 
                        keyword: keyword,
                        startDate: startDate,
                        endDate: endDate,
                        viewMode: viewMode
                    })
                });
                
                const result = await response.json();
                
                if (result.status === 'success') {
                    const data = result.data;
                    if (data.length === 0) {
                        statusMessage.innerText = "👀 該區間與條件內沒有找到紀錄。";
                        return;
                    }
                    
                    statusMessage.innerText = `✨ 成功彙整 ${data.length} 筆比價資料`;
                    
                    renderMultiChart(data);
                    
                    data.forEach(item => {
                        const listItem = document.createElement('div');
                        listItem.className = "list-group-item flex-column align-items-start border-0 border-bottom";
                        listItem.innerHTML = `
                            <div class="d-flex w-100 justify-content-between mb-1">
                                <span style="font-weight: 600; color: #2b3452;">${item.flight_data}</span>
                                <small class="text-muted">${item.check_time}</small>
                            </div>
                            <div class="d-flex justify-content-between align-items-center">
                                <span class="price-text">NT$ ${item.price.toLocaleString()}</span>
                                <small class="flight-text px-2 py-1 bg-light rounded">來源: ${item.source}</small>
                            </div>
                        `;
                        resultsList.appendChild(listItem);
                    });
                } else {
                    statusMessage.innerText = "查詢失敗：" + result.message;
                }
            } catch (error) {
                statusMessage.innerText = "伺服器連線錯誤。";
            }
        }

        window.onload = initializeLiff;
    </script>
</body>
</html>
"""

@app.route('/liff/history')
def liff_history_page():
    liff_id = os.getenv("LIFF_ID_HISTORY", "") 
    return render_template_string(HISTORY_HTML, liff_id=liff_id)

@app.route('/api/query_history', methods=['POST'])
def query_history_api():
    data = request.json or {}
    keyword = data.get("keyword", "").strip()
    start_date = data.get("startDate", "")
    end_date = data.get("endDate", "")
    view_mode = data.get("viewMode", "all")
    user_id = web_auth.current_user_id(data.get("userId", ""))

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return jsonify({"status": "error", "message": "資料庫尚未連線"})

    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = "SELECT check_time, flight_data, price, source, user_id, origin, destination, flight_date FROM price_history WHERE 1=1"
        params = []

        # 根據下拉選單決定是否只看自己的資料
        if view_mode == "me" and user_id:
            query += " AND user_id = %s"
            params.append(user_id)

        # 支援逗號分隔多筆查詢 (例如 "GK50, MM28")
        if keyword:
            keywords = [k.strip() for k in keyword.split(',') if k.strip()]
            if keywords:
                conditions = []
                for k in keywords:
                    k_clean = k.replace(" ", "").upper()
                    conditions.append("UPPER(REPLACE(flight_data, ' ', '')) LIKE %s")
                    params.append(f"%{k_clean}%")
                
                # 將多個 LIKE 條件用 OR 串接起來
                query += " AND (" + " OR ".join(conditions) + ")"
            
        if start_date:
            query += " AND check_time >= %s"
            params.append(f"{start_date} 00:00:00")
        if end_date:
            query += " AND check_time <= %s"
            params.append(f"{end_date} 23:59:59")

        # 放大查詢上限以容納多航線的數據點
        query += " ORDER BY check_time DESC LIMIT 300" 

        cursor.execute(query, params)
        records = cursor.fetchall()
        
        cursor.close()
        conn.close()

        for r in records:
            if r['check_time']:
                r['check_time'] = r['check_time'].strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({"status": "success", "data": records})

    except Exception as e:
        print(f"資料庫查詢錯誤: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
