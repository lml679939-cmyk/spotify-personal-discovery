# Spotify Personal Discovery

個人化音樂發現 App，結合 Spotify 聆聽資料、Gemini 多模態 LLM 與環境情境（時間、天氣、地理位置、圖片、文字）生成推薦歌單。

## 為什麼做這個

使用者平常使用 Spotify 時間碎片化，自家演算法容易陷入循環推薦舊歌。本專案用 LLM 的廣度知識打破 collaborative filtering 的回音壁，並讓「當下情境」主導推薦風格。

---

## 使用方式

本 App 提供兩種使用方式：

### 方式一：Spotify 登入（個人化推薦）
讀取你的 Spotify 聆聽紀錄，AI 會根據你的口味 + 當下情境推薦「你沒聽過、但會喜歡」的歌。

### 方式二：訪客模式（不需登入）
不需要 Spotify 帳號，純靠情境（心情、活動、文字描述、圖片）推薦音樂。推薦不會個人化，也無法建立 Spotify 歌單。

---

## 目前完成狀態

| 階段 | 狀態 | 對應檔案 |
|---|---|---|
| M1：Spotify OAuth + 讀取 Top Tracks | ✅ 完成 | `m1_top_tracks.py` |
| M2：自動寫入歌單到 Spotify | ⏸ **被 Spotify 平台限制** | `m2_create_playlist.py` |
| M3：LLM 推薦引擎 | ✅ 完成 | `m3_recommend.py` |
| M4：多模態情境輸入（文字/圖片/自動偵測） | ✅ 完成 | `m4_contextual_recommend.py` |
| Web UI（Streamlit） | ✅ 完成 | `app.py` |
| IG Story 分享圖卡 | ✅ 完成 | `share_card.py` |
| BYOK（自訂 API Keys）+ 訪客模式 | ✅ 完成 | `app.py` |

主要使用方式是 **`app.py` Streamlit Web UI**，CLI 檔案保留作為單元測試與功能驗證用。

---

## 快速開始

### 1. 安裝依賴
```powershell
pip install -r requirements.txt
```

### 2. 設定環境變數（複製 `.env.example` → `.env`）
```
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8501/
GEMINI_API_KEY=...
```

⚠️ **`SPOTIFY_REDIRECT_URI` 必須跟 Developer Dashboard 的 Redirect URIs 設定一字不差。**
本機跑用 `http://127.0.0.1:8501/`，雲端部署改成 `https://你的app.streamlit.app/`。

> 如果不設 `.env`，使用者也可以在 App 內的「自訂 API Keys」區自行填入 credentials。

### 3. 啟動 Web UI
```powershell
streamlit run app.py
```

瀏覽器會自動開啟 `http://localhost:8501`。首次會看到登入頁，可選擇 Spotify 登入或訪客模式。

---

## 讓更多人使用（突破 Spotify 25 人限制）

Spotify Development Mode 限制最多 25 位授權用戶。有三種解法：

### 方法一：BYOK — 使用者自帶 API Keys（推薦，立即生效）
每位使用者建立自己的 Spotify Developer App，就不受共用額度限制：

1. 到 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) → Create App
2. 填寫 App Name、Description（隨意）
3. Redirect URI 填入 App 的網址（如 `http://127.0.0.1:8501/` 或 `https://xxx.streamlit.app/`）
4. 勾選 Web API
5. 複製 Client ID 和 Client Secret
6. 在 App 頁面下方「自訂 API Keys」區貼上

同理，Gemini API Key 也可以到 [Google AI Studio](https://aistudio.google.com/apikey) 免費申請後自行填入。

### 方法二：申請 Extended Quota Mode
到 Developer Dashboard → 你的 App → 申請 Extended Quota Mode，等 Spotify 審核（幾天到幾週）。

### 方法三：訪客模式
不需要任何 Spotify 帳號，選擇「不登入，直接推薦」即可使用（仍需要 Gemini API Key）。

---

## 部署到 Streamlit Community Cloud（分享給朋友）

### 前置
- GitHub 帳號（要把專案推到一個 repo）
- Spotify Developer Dashboard 已建好 App

### 步驟

1. **推 code 到 GitHub**（**確認 `.env` 跟 `.cache` 不在 commit 內！**）
   ```powershell
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/<你的帳號>/<repo>.git
   git push -u origin main
   ```

2. **部署到 Streamlit Cloud**
   - 開 [share.streamlit.io](https://share.streamlit.io) → New app → 選你的 repo
   - Main file path：`app.py`
   - 部署後會拿到網址，例如 `https://xxx.streamlit.app/`

3. **在 Streamlit App 設定 Secrets**
   - App 設定 → Settings → Secrets，貼上：
   ```toml
   SPOTIFY_CLIENT_ID = "..."
   SPOTIFY_CLIENT_SECRET = "..."
   SPOTIFY_REDIRECT_URI = "https://xxx.streamlit.app/"
   GEMINI_API_KEY = "..."
   ```
   > 這些是作為「預設 credentials」供不自帶 Keys 的用戶使用。自帶 Keys 的用戶會在瀏覽器內自行填入，覆蓋這些預設值。

4. **Spotify Developer Dashboard 設定**
   - Settings → Redirect URIs → 加上 `https://xxx.streamlit.app/`
   - User Management → 加上要授權的用戶 Email（不自帶 Keys 的人才需要）

5. **分享網址給朋友**
   - 自帶 Keys 的朋友：直接開網頁 → 填入自己的 Keys → 用 Spotify 登入
   - 不帶 Keys 的朋友：需要你先在 User Management 加入他們的 Email
   - 只想試試的人：選訪客模式即可

### 同 WiFi 手機存取
```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```
手機瀏覽器連 `http://<電腦本機IP>:8501`。

---

## 架構與檔案說明

```
├── app.py                       ← 主程式（Streamlit UI），日常使用就跑這個
├── share_card.py                ← IG Story 分享圖卡生成
├── m1_top_tracks.py             ← CLI：驗證 OAuth + 讀取 Top Tracks
├── m2_create_playlist.py        ← CLI：建立歌單（會 403，留作備案）
├── m3_recommend.py              ← CLI：LLM 推薦（純口味，無情境）
├── m4_contextual_recommend.py   ← CLI：情境化推薦（文字/圖片/auto-context）
├── debug_api.py                 ← 診斷工具：測試 Spotify 寫入 API
├── check_models.py              ← 列出可用的 Gemini 模型
├── fonts/                       ← NotoSansTC 字型（中文渲染用）
├── requirements.txt             ← 依賴清單
├── .env                         ← API Keys（不要進版控）
├── .env.example                 ← 範例
└── .streamlit/secrets.toml.example ← 雲端部署用 Secrets 範例
```

### 核心流程（`app.py`）
1. **登入閘門**：Spotify OAuth 登入 / 訪客模式 / BYOK 自訂 Keys
2. **聆聽資料**（登入模式）：抓 Top Tracks（短期+中期）、Top Artists、Recently Played(50)、Saved Tracks(100)
3. **情境合成**：自動偵測（IP→城市→天氣+時間）+ 文字描述 + 圖片（Gemini Vision 分析氛圍）+ 個人特質（MBTI/血型/星座）+ 心情滑桿 + 活動/語言/曲風 pills + 投射問題
4. **LLM 推薦**：Gemini 2.5 Flash 根據口味+情境+已聽清單+歷史，生成 JSON 候選歌單
5. **Spotify 搜尋**：Search API 將候選歌轉為 Track URI + 專輯封面（訪客模式用 Client Credentials Flow）
6. **後處理**：去重 + 同藝人最多 2 首 + 排除已聽/已推薦歷史
7. **顯示**：條列式或網格卡片，含 Spotify 連結
8. **分享**：純文字複製 + IG Story 分享圖卡（7 色系，單張/多張模式）

### Credential 優先順序
```
使用者在 App 內填入的自訂 Key（session_state）
  ↓ fallback
.env 或 Streamlit Secrets 中的預設值
```
由 `_get_credential()` 函式統一管理。

---

## 重要外部限制

### Spotify Web API（2024-11 後政策變更）
新建立的 Spotify App 在 Development Mode 下：

**已被停用的讀取 API**（無法使用）：
- `Get Recommendations`
- `Audio Features`、`Audio Analysis`
- `Related Artists`、30 秒試聽片段

**寫入 API 被擋（403 Forbidden）**：
- `POST /v1/me/playlists`（建立歌單）
- **唯一解法**：申請 Extended Quota Mode 等待審核

UI 在 403 時會顯示解決方向，並建議使用「在 Spotify 開啟」手動加入歌單。

### Gemini API
- 預設模型 `gemini-2.5-flash`（免費 tier 可用）
- `gemini-2.0-flash` 免費 tier 配額為 0，不要用
- Vision 多模態用同個模型，傳 `types.Part.from_bytes()`

---

## Web UI 功能總覽

### 情境設定
- **自動偵測位置與天氣**（toggle）：抓 IP 城市 + Open-Meteo 天氣 + 當下時間
- **文字描述**：自由輸入當下心情或情境
- **圖片上傳**：JPG/PNG/WEBP，Gemini Vision 萃取情緒/氛圍/節奏/能量
- **個人特質**：MBTI、血型、星座
- **心情雙軸 slider**：活力 + 情緒
- **活動 pills**（單選）：讀書、工作、通勤等
- **語言 pills**（多選）：華語、英語、日語等
- **曲風 pills**（多選）：Pop、Rock、Indie 等 20 種
- **投射問題**：15 題隨機輪換

### 推薦控制
- **歌曲數量 slider**：5-30 首
- **新藝人佔比 slider**：0-100%（僅 Spotify 登入模式）
- **推薦歷史**：session 內 + 跨 session（Spotify 私人歌單持久化），自動去重

### 分享
- **複製歌單**：純文字含 Spotify 連結
- **IG Story 分享圖**：7 色系 × 2 模式（單張/4 張），1080×1920 PNG

---

## 開發/維護指引

### 想擴充功能
- 修改 prompt 比改架構有效，推薦品質的瓶頸在 prompt 設計
- `app.py` 是主要入口，CLI 檔案（m1-m4）已不常更新

### Spotify Token 刷新
如果加新 scope 或寫入失敗：
```powershell
Remove-Item ".cache" -ErrorAction SilentlyContinue
```
然後重新執行會跳新的授權頁。

### Gemini 模型切換
`check_models.py` 可列出當前 API Key 可用的所有模型。

---

## 已知未實作的方向

- 申請 Spotify Extended Quota Mode 解鎖寫入 API
- 定時自動推薦（Windows Task Scheduler 或 GitHub Actions）
- 推薦結果評分回饋機制（讓 LLM 學習使用者喜好）
