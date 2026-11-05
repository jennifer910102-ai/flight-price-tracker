# 機票價格監控 (Flight Price Tracker)

自動追蹤機票價格，價格變動時透過 **Discord** 或 **LINE** 通知你。支援短程單程航班（指定班次或當天最低價），也支援長程來回比價（例如比較「聖地牙哥轉機」和「洛杉磯直飛」哪個便宜）。

## 選擇你的設定方式

這個專案是「**基本的一定要裝，其他看需要加**」。先看每個服務註冊了可以做什麼，再決定要設定到哪裡。

### 每個服務註冊了可以做什麼

| 服務 | 註冊之後可以做什麼 | 沒註冊的話 | 費用 / 限制 |
|---|---|---|---|
| **GitHub** | 放程式、存設定和查價紀錄；用 GitHub Actions 每天自動查價 3 次，不用開電腦 | **一定要**，整個專案都靠它 | 免費 |
| **SerpApi** | 查 Google 航班的即時票價 | **一定要**，沒有就查不到價格 | 免費每月 250 次查價 |
| **Discord** | 價格變動時在 Discord 頻道收到通知 | 收不到通知（除非有設定 LINE），只能自己去看查價紀錄 | 免費，沒有則數上限 |
| **Render** | 一個 24 小時開著的網頁：<br>・用**網頁點選**設定要追的航班，不用改檔案<br>・**歷史頁**：價格卡片、走勢圖、漲跌紀錄<br>・**即時查價頁**，隨時查一次<br>・設定頁直接顯示每月會用掉多少查價額度<br>網頁用你自己設的密碼登入（有接 LINE 的話改用 LINE 登入） | 只能在 GitHub 上編輯 `config.json` 設定航班，沒有走勢圖，也不能隨時查價 | 免費；閒置約 15 分鐘會休眠，下次打開要等最多 50 秒 |
| **LINE**（要先有 Render） | ・在 LINE 收通知<br>・在 LINE 裡直接打開網頁，不用記網址和密碼<br>・在聊天室輸入「查價」馬上查一次 | 通知只能用 Discord，網頁要用瀏覽器開 | 免費；推播每月 200 則（回覆訊息不算） |
| **Aviationstack**（選填） | 設定頁多一個「查詢班機」按鈕，列出那條航線的航班號 | 航班號要自己去 Google 航班查 | 有免費方案 |
| **PostgreSQL**（選填） | 另外備份一份查價紀錄到資料庫 | 沒影響，紀錄本來就存在 `history.json` | 依服務商而定 |

### 常見的組合

| 你註冊了 | 得到的版本 | 能做的事 | 少了什麼 | 設定時間 |
|---|---|---|---|---|
| GitHub + SerpApi + **Discord** | **基本版**（推薦先從這裡開始） | 每天自動查價、Discord 通知、長程來回比價 | 沒有網頁、走勢圖、即時查價；改設定要編輯 `config.json`；額度要自己算 | 約 20 分鐘，照「一」 |
| GitHub + SerpApi + Discord + **Render** | **網頁版** | 基本版全部功能，加上網頁設定、走勢圖、即時查價（用密碼登入） | LINE 通知和 LINE 聊天室指令 | 約 40 分鐘，照「一」再做「二」 |
| GitHub + SerpApi + **Render + LINE** | **完整版** | 網頁版全部功能，改在 LINE 裡打開網頁、用 LINE 收通知、輸入「查價」 | 沒有（LINE 推播每月 200 則，一般個人使用很夠） | 約 1 小時，照「一」「二」再做「三」 |

每個版本都**不需要自己架資料庫**，而且都是在同一個 repo 往上加，**升級不用重來**：基本版 → 網頁版的設定會直接沿用；改成 LINE 登入時要在設定頁重新加一次航班（見「三」）。

---

## 一、基本版：GitHub + Discord

照著做大約 20 分鐘，全程只需要瀏覽器，不用安裝任何東西。

**開始前先準備好：**
- 一個 [GitHub](https://github.com) 帳號（沒有的話先免費註冊）
- 一個 [Discord](https://discord.com) 帳號
- 想追的航班：出發地、目的地、日期（航班號可有可無，見第 5 步）

---

### 第 1 步：複製一份專案到你的 GitHub

1. 登入 GitHub，打開這個專案的頁面：<https://github.com/jennifer910102-ai/flight-price-tracker>
2. 右上角按綠色的 **Use this template** → **Create a new repository**。
3. 在建立頁面：
   - **Repository name**：隨便取，例如 `my-flight-tracker`
   - 選 **Private**（建議）：你要去哪裡、哪天出發、查價紀錄都不會被別人看到
4. 按 **Create repository**，幾秒後就會進到你自己的 repo 頁面。

> 沒看到 **Use this template** 的話，改按右上角的 **Fork** → **Create fork**。
> 注意 Fork 出來的 repo **一定是公開的**，任何人都看得到你的 `config.json` 和查價紀錄。

✅ **確認**：網址變成 `github.com/你的帳號/my-flight-tracker`，左上角顯示的是你的帳號名稱。

---

### 第 2 步：申請 SerpApi 金鑰（用來查機票價格）

1. 打開 [serpapi.com](https://serpapi.com)，右上角 **Register**。
2. 用 Email、Google 或 GitHub 帳號註冊，方案選 **Free Plan**（每月 250 次查價），照畫面完成驗證（會寄驗證信到你的信箱）。
3. 登入後會進到 **Dashboard**（或左邊選單 **Your Account**），找到 **Your Private API Key**，按旁邊的複製圖示。
   這串金鑰長得像 `7e8ab571...`，大約 64 個英數字。

先把金鑰貼到記事本暫存，第 4 步會用到。

> ⚠️ 這串金鑰等於你的查價額度，不要貼到任何公開的地方（聊天群組、截圖、程式碼裡）。

---

### 第 3 步：建立 Discord Webhook（用來收通知）

Webhook 就是一個專屬網址，程式往這個網址送訊息，訊息就會出現在你指定的頻道。

**還沒有自己的 Discord 伺服器的話，先建一個（只有你自己也可以）：**
1. Discord 左邊欄最下面按 **＋（新增伺服器）** → **親自建立** → **僅供我和我的朋友使用**。
2. 取個名字（例如「機票通知」），按 **建立**。

**建立 Webhook（建議用電腦版 Discord 或網頁版操作）：**
1. 滑鼠移到要收通知的頻道（例如 `#一般`）上，按頻道名稱旁的 **⚙️ 齒輪（編輯頻道）**。
2. 左邊選 **整合** → 右邊按 **Webhook** → **新 Webhook**。
3. 會出現一個新的 Webhook（預設名稱類似「Spidey Bot」），點它展開：
   - 可以把名稱改成「機票價格監控」
   - 確認下面的 **頻道** 是你要收通知的頻道
4. 按 **複製 Webhook 網址**，貼到記事本。網址長得像
   `https://discord.com/api/webhooks/123456789012345678/AbCdEf...`
5. 如果下方出現 **儲存變更**，記得按。

> ⚠️ 拿到這個網址的人都能往你的頻道發訊息，一樣不要公開。

---

### 第 4 步：把兩個金鑰存進 GitHub Secrets

Secrets 是 GitHub 存密碼的地方。存進去後只有程式讀得到，連你自己也看不到內容，也不會出現在 repo 的檔案裡。

1. 回到你的 repo 頁面，上方選單最右邊按 **⚙️ Settings**。
   （視窗太窄時，Settings 會收在 **⋯** 裡面）
2. 左邊選單往下找到 **Secrets and variables**，點開後選 **Actions**。
3. 按綠色的 **New repository secret**，新增第一個：
   - **Name**：`SERPAPI_KEY`
   - **Secret**：貼上第 2 步的 SerpApi 金鑰
   - 按 **Add secret**
4. 再按一次 **New repository secret**，新增第二個：
   - **Name**：`DISCORD_WEBHOOK_URL`
   - **Secret**：貼上第 3 步的 Webhook 網址
   - 按 **Add secret**

✅ **確認**：**Repository secrets** 清單裡有 `SERPAPI_KEY` 和 `DISCORD_WEBHOOK_URL` 兩筆。

> - **Name 要一字不差**，全部大寫、用底線，前後不要有空白。
> - 內容貼錯的話，點那筆旁邊的 ✏️ 重新貼上就好（GitHub 不會顯示舊的內容）。
> - 金鑰**只能**放這裡，不要寫進 `config.json` 或任何檔案。

---

### 第 5 步：設定要追的航班（編輯 `config.json`）

#### 先查好要填的資料
打開 [Google 航班](https://www.google.com/travel/flights) 搜尋你要的航線和日期：
- **機場代碼**：搜尋結果裡的三個英文字母，例如桃園 `TPE`、松山 `TSA`、高雄 `KHH`、大阪關西 `KIX`、東京成田 `NRT`、東京羽田 `HND`、福岡 `FUK`、沖繩 `OKA`、札幌 `CTS`、首爾仁川 `ICN`。
- **航班號**（選填）：點開某一班，會看到像 `GK 50`、`IT 210` 的編號，填的時候空格可以省略。

#### 編輯檔案
1. 回到 repo 首頁（上方選單 **<> Code**），在檔案清單點 **`config.json`**。
2. 檔案內容右上方按 **✏️ 鉛筆圖示（Edit this file）**。
3. 把內容**全部刪掉**，貼上下面的範本，再改成你要的航班：

```json
{
    "users": {
        "me": {
            "monitor_config": {
                "segments": [
                    {
                        "segment_no": 1,
                        "origin": "TPE",
                        "destination": "KIX",
                        "date_schedules": [
                            { "date": "2027-03-20", "flights": [] },
                            { "date": "2027-03-21", "flights": ["GK50"] }
                        ]
                    },
                    {
                        "segment_no": 2,
                        "origin": "KIX",
                        "destination": "TPE",
                        "date_schedules": [
                            { "date": "2027-03-25", "flights": [] }
                        ]
                    }
                ]
            }
        }
    }
}
```

這個範本的意思是：
- 第 1 段：桃園 → 大阪，追 **3/20 當天最便宜的直飛**，以及 **3/21 的 GK50 這一班**
- 第 2 段：大阪 → 桃園（回程），追 **3/25 當天最便宜的直飛**

| 欄位 | 怎麼填 |
|---|---|
| `origin` / `destination` | 出發 / 抵達的機場代碼，要大寫，前後加雙引號，例如 `"TPE"` |
| `date` | 出發日期，格式固定是 `"年-月-日"`，月和日要補 0，例如 `"2027-03-05"` |
| `flights` | `[]`（空的）= 追當天最便宜的**直飛**；`["GK50"]` = 只追這一班；`["GK50", "MM28"]` = 同時追兩班 |
| `segment_no` | 第幾段，照順序寫 1、2、3… |
| `me` | 使用者名稱，隨便取，不用改也可以 |

想再加日期，就在 `date_schedules` 裡多加一行 `{ "date": "...", "flights": [] }`；想追另一條航線，就再加一段 `segments`。長程來回比價（可轉機）的寫法請看 `config.example.json` 裡的 `trips`。

#### 格式一定要正確（最常出錯的地方）
- 所有文字都要用**英文的雙引號** `"`，不能用中文引號 `「」`、`“”` 或單引號 `'`。
- 同一層的項目之間要有**逗號**，**最後一個項目後面不能有逗號**。
- `{ }`、`[ ]` 要成對，打開幾個就要關幾個。

格式錯的話，第 6 步的執行紀錄會顯示
`❌ config.json 格式錯誤：第 X 行第 Y 個字附近`，回來看那一行附近就好。

#### 存檔
4. 右上角按綠色的 **Commit changes...**。
5. 跳出的視窗維持 **Commit directly to the main branch**，再按一次 **Commit changes**。

✅ **確認**：回到 `config.json` 看得到你剛剛改的內容。

---

### 第 6 步：啟用自動查價並測試

1. repo 上方選單按 **▶ Actions**。
   - 如果看到 **I understand my workflows, go ahead and enable them**（通常是 Fork 的才會出現），按下去。
2. 左邊清單點 **Price Monitor Scheduler**。
   - 如果上方出現黃色提示 **This scheduled workflow is disabled…**，按旁邊的 **Enable workflow**。
3. 右邊有個 **Run workflow ▾** 按鈕，點開後直接按綠色的 **Run workflow**。
4. 等幾秒後重新整理頁面，清單最上面會多一筆：🟡 黃色代表執行中，大約 1 分鐘後變成 ✅ 綠色勾勾。

✅ **確認成功：**
- Discord 頻道收到通知，第一次會是 **「✨ 已為您建立首筆基準追蹤價」**，每個日期 / 航班各一則。
- 點進那筆執行紀錄 → 點 **build** → 展開 **Run Price Monitor**，會看到類似：
  ```
  ℹ️ SerpApi 本月剩餘 247 次 (保留 20 次給即時查價)
    ➔ 執行背景抓價：TPE ➔ KIX (2027-03-20), 指定航班: 不限 (當日最低價)
  ✅ 價格有變動或為新追蹤，已推播給 me
  ```

❌ **出現紅色叉叉、或是綠色但沒收到通知**，一樣展開 **Run Price Monitor** 看紀錄：

| 紀錄裡看到 | 原因和解法 |
|---|---|
| `config.json 格式錯誤：第 X 行…` | 回第 5 步檢查那一行的逗號和引號 |
| `沒有可用的通知管道` | `DISCORD_WEBHOOK_URL` 沒設定或名字打錯，回第 4 步（這個情況會是綠燈，但收不到通知） |
| `Discord 回應 401` 或 `404` | Webhook 網址貼錯或已經被刪掉，重新複製後到第 4 步更新 |
| `未設定 SERPAPI_KEY` | `SERPAPI_KEY` 沒設定或名字打錯，回第 4 步 |
| `目前沒有任何使用者設定監控任務` | `config.json` 是空的，回第 5 步 |
| `略過已過期的日期` | 日期已經過了，改成未來的日期 |

測試成功後就不用再管它了。之後每天台灣時間 **08:00、16:00、00:00** 左右會自動查價（GitHub 有時會延遲幾十分鐘）。價格變動超過 NT$200 才會通知（長程來回比價是 NT$500），沒變動就不會吵你。

---

### 之後怎麼用

- **新增 / 修改要追的航班**：照第 5 步編輯 `config.json`。出發日過了會自動略過，不用特地刪。
- **改完想馬上看結果**：照第 6 步按一次 **Run workflow**，不用等下次排程。
- **看查價紀錄**：repo 裡的 `history.json`，每查一次會多幾筆，由程式自動更新，不要手動改。
- **暫停**：**Actions** → **Price Monitor Scheduler** → 右上 **⋯** → **Disable workflow**。要恢復就按 **Enable workflow**。
- **更換金鑰或 Webhook**：照第 4 步，點那筆 Secret 旁的 ✏️ 更新。

### 額度怎麼算

SerpApi 免費方案每月 250 次，每查一個「日期 × 航班」算 1 次。

| 追蹤內容 | 一個月大約用掉 |
|---|---|
| 1 個日期、追最低價（每天查 3 次） | 90 次 |
| 去程 + 回程各 1 個日期、追最低價 | 180 次 |
| 2 個日期 × 各指定 2 班 | 360 次 ⚠️ 超過 |
| 長程來回比價，比較 2 種飛法（每天查 1 次） | 約 60 次 |

建議同時追的總數控制在 2～3 個「日期 × 航班」以內。出發日過了之後就不會再用額度。剩餘額度不到 20 次時排程會自動停止查價，下個月重置後恢復。

### 其他常見問題

- **每次執行都多一筆 `chore: update history.json` 的 commit**：正常，查價紀錄就是這樣存回 repo 的。
- **私人 repo 會不會被收費**：GitHub 免費帳號的私人 repo 每月有 2,000 分鐘的 Actions 時間，這個專案每次大約 1 分鐘、一天 3 次，一個月不到 100 分鐘。
- **很久沒動之後排程停了**：GitHub 會停用長期沒有活動的 repo 排程。到 **Actions** → **Price Monitor Scheduler** 按 **Enable workflow** 就能恢復。

---

## 二、網頁版：加上 Render（密碼登入）

做完「一、基本版」之後再加這一段，就能用網頁設定航班、看價格走勢圖、隨時查價。通知照樣是 Discord，網頁用你自己設的密碼登入。大約多花 20 分鐘。

網頁上看到的就是 `config.json` 裡 `me` 的設定，基本版原本設好的航班會直接出現，不用重新設定。

### 第 1 步：申請 GitHub 存取權杖（讓網頁能把設定存回 repo）

網頁上改的設定和即時查價的紀錄，要存回你的 GitHub repo，GitHub Actions 下次查價才讀得到。

1. GitHub 右上角點你的**頭像** → **Settings**（這是帳號的設定，不是 repo 的）。
2. 左邊選單拉到最下面 → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**。
3. 填寫：
   - **Token name**：例如 `flight-tracker-render`
   - **Expiration**：選 **No expiration**，或選一個日期（到期後要重新申請並更新到 Render）
   - **Repository access**：選 **Only select repositories**，再選你的 repo（例如 `my-flight-tracker`）
   - **Permissions** → **Repository permissions** → 找到 **Contents**，改成 **Read and write**
4. 最下面按 **Generate token**，**馬上複製**那串 `github_pat_...` 開頭的權杖（離開頁面後就看不到了），貼到記事本。

> ⚠️ 這個權杖可以修改你的 repo，跟密碼一樣不要公開。上面只開給一個 repo、只開 Contents 權限，就算外流影響也最小。

### 第 2 步：在 Render 建立網頁服務

1. 到 [render.com](https://render.com) 右上角 **Get Started**，用 **GitHub** 帳號登入最方便。
2. 右上角 **+ New** → **Web Service**。
3. 選 **Git Provider** → **GitHub**，照提示授權 Render 讀取你的 repo（可以只授權這一個 repo），然後在清單裡選你的 repo，按 **Connect**。
4. 填寫設定：

   | 欄位 | 填什麼 |
   |---|---|
   | **Name** | 隨便取，會變成網址的一部分，例如 `my-flight-tracker` → `https://my-flight-tracker.onrender.com` |
   | **Region** | **Singapore**（離台灣最近） |
   | **Branch** | `main` |
   | **Language** | **Python 3** |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `python app.py` |
   | **Instance Type** | **Free** |

5. 往下找到 **Environment Variables**，按 **Add Environment Variable** 逐一加入：

   | Key | Value |
   |---|---|
   | `WEB_PASSWORD` | 自己設一組網頁登入密碼（建議 12 個字以上，不要跟其他地方的密碼一樣） |
   | `SERPAPI_KEY` | 跟基本版第 4 步一樣的 SerpApi 金鑰 |
   | `DISCORD_WEBHOOK_URL` | 跟基本版第 4 步一樣的 Webhook 網址 |
   | `GITHUB_TOKEN` | 第 1 步的 `github_pat_...` 權杖 |
   | `GITHUB_REPO` | `你的帳號/repo名稱`，例如 `your-name/my-flight-tracker` |

6. 按最下面的 **Deploy Web Service**。

### 第 3 步：避免每次查價都重新部署

GitHub Actions 每次查價都會更新 `history.json`，Render 預設只要 repo 有變動就重新部署一次（每次約 1 分鐘，期間網頁打不開）。

1. Render 左邊選單 **Settings** → 找到 **Build Filters**。
2. **Ignored Paths** 按 **Add Ignored Path**，加入這三個：`history.json`、`.github/**`、`*.md`
3. 按 **Save Changes**。

### 第 4 步：打開網頁

1. 回到 Render 服務頁面，等上方狀態變成綠色的 **Live**（第一次大約 2～3 分鐘）。
2. 點服務名稱下面的網址（`https://….onrender.com`）。
3. 輸入第 2 步設定的 `WEB_PASSWORD` 登入。

✅ **確認**：
- 「監控設定」頁看得到你在 `config.json` 設定的航班。
- 頁面下方按 **傳送測試通知**，Discord 收到測試訊息。
- 新增或修改一筆追蹤後，到 GitHub 看 `config.json`，內容有跟著更新。

❌ **有問題的話**：

| 狀況 | 原因和解法 |
|---|---|
| Render 部署失敗（紅色 **Failed**） | 點那次部署看 log 最後幾行；最常見是 Build / Start Command 打錯 |
| 一直跳回登入頁 | 密碼要跟 `WEB_PASSWORD` 完全一樣（大小寫、前後空白） |
| 網頁上改了設定，GitHub 上的 `config.json` 沒變 | `GITHUB_TOKEN` 或 `GITHUB_REPO` 錯誤，或權杖沒開 **Contents: Read and write**；到 Render 的 **Logs** 看有沒有 `GitHub 同步失敗` |
| 打開網頁要等很久 | Render 免費方案閒置約 15 分鐘會休眠，下次打開要等最多 50 秒，正常現象 |
| 想改密碼 | Render → **Environment** 修改 `WEB_PASSWORD` 後存檔，會自動重新部署，所有人要重新登入 |

---

## 三、完整版：再加上 LINE

想在 LINE 裡打開網頁、用 LINE 收通知、在聊天室輸入「查價」，就在「二」的基礎上改成用 LINE 登入。

1. 在 [LINE Developers](https://developers.line.biz) 建立 **Messaging API channel**，以及兩個 **LIFF App**，Endpoint 分別設為 `https://你的網址/liff/monitor`、`https://你的網址/liff/history`。
2. Render → **Environment**：
   - **刪掉 `WEB_PASSWORD`**（有設定密碼時網頁會用密碼登入，不會用 LINE）
   - 加入 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`、`LIFF_ID`（監控設定頁）、`LIFF_ID_HISTORY`（歷史頁）
3. LINE channel 的 **Webhook URL** 設為 `https://你的網址/callback`。
4. GitHub repo 的 Secrets 也加上 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`（自動查價時發 LINE 通知用）。
5. 在 LINE 聊天室輸入「說明」查看可用指令。

注意：
- 改用 LINE 之後，網頁是依 LINE 帳號分開存設定的，原本 `me` 底下的航班不會出現在 LINE 設定頁。請在設定頁重新加一次，確認收得到通知後，再把 `config.json` 裡舊的 `me` 整段刪掉，避免同一個航班通知兩次。
- LINE 免費方案每月 200 則推播。只有價格變動超過門檻才會推播，「查價」指令的回覆也不算，一般個人使用很夠。

### 環境變數一覽

| 名稱 | 用途 | 基本版 (GitHub Secrets) | 網頁版 (Render) | 完整版 (Render) |
|---|---|---|---|---|
| `SERPAPI_KEY` | Google 航班查價 | 必填 | 必填 | 必填 |
| `DISCORD_WEBHOOK_URL` | Discord 通知（網頁版可以在設定頁改成別的 Webhook） | 必填 | 必填 | |
| `WEB_PASSWORD` | 網頁登入密碼；**有設定就用密碼登入，不用 LINE** | | 必填 | 不要設 |
| `WEB_USER_ID` | 密碼登入後使用的使用者名稱，預設 `me` | | 選填 | |
| `GITHUB_TOKEN` / `GITHUB_REPO` | 把設定和查價紀錄存回 GitHub | Actions 自動提供 | 必填（個人存取權杖、`帳號/repo名稱`） | 必填 |
| `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_CHANNEL_SECRET` | LINE Bot | 完整版才需要 | | 必填 |
| `LIFF_ID` / `LIFF_ID_HISTORY` | 監控設定頁 / 歷史頁的 LIFF ID | | | 必填 |
| `DATABASE_URL` | PostgreSQL，另存一份查價紀錄 | 選填 | 選填 | 選填 |
| `AVIATIONSTACK_KEY` | 設定頁「查詢班機」按鈕 | | 選填 | 選填 |

## 檔案結構

| 檔案 | 負責什麼 | 在哪裡執行 |
|---|---|---|
| `config.json` | 要追的航班設定（使用者自己改，或由設定頁寫入） | － |
| `history.json` | 查價紀錄（程式自動更新，不要手動改） | － |
| `config.example.json` | 設定範例，包含長程來回比價 `trips` 的寫法 | － |
| `.github/workflows/monitor.yml` | 告訴 GitHub Actions 什麼時間、用哪些金鑰執行 `scheduler.py` | GitHub Actions |
| `scheduler.py` | 一輪查價的主流程：讀設定 → 查價 → 比價 → 決定要不要通知 → 寫紀錄 | GitHub Actions |
| `server.py` | 呼叫 SerpApi，整理成價格和航班資訊（單程直飛、轉機 / 來回行程） | 兩邊都會用到 |
| `notifier.py` | 判斷每個使用者要發到 LINE 還是 Discord，並實際送出 | 兩邊都會用到 |
| `utils.py` | 讀寫 `config.json` / `history.json`，同步回 GitHub、寫入資料庫 | 兩邊都會用到 |
| `app.py` | 伺服器入口：LINE Webhook、即時查價 API | Render |
| `web_auth.py` | 網頁版的密碼登入：沒登入就擋下網頁和 API | Render |
| `liff_views.py` | 三個網頁（監控設定、即時查價、歷史）、登入頁和設定用的 API | Render |
| `bot_handlers.py` | LINE 聊天室指令（「查價」「設定」「歷史」…） | Render（完整版才會用到） |
| `airports.json` / `airlines.json` | 機場、航空公司的中文名稱對照 | Render |
| `requirements.txt` | 需要安裝的 Python 套件 | 兩邊都會用到 |
