# Spotify Personal Discovery

個人化音樂發現 App，結合 Spotify 聆聽資料、Gemini 多模態 LLM 與環境情境（時間、天氣、地理位置、圖片、文字）生成推薦歌單。

## 為什麼做這個

使用者平常使用 Spotify 時間碎片化，自家演算法容易陷入循環推薦舊歌。本專案用 LLM 的廣度知識打破 collaborative filtering 的回音壁，並讓「當下情境」主導推薦風格。

---

## 使用方式

**線上版**：<https://spotify-lml.streamlit.app>

### 方式一：直接開始
不需要 Spotify 帳號、不用申請任何 API Key，描述當下情境就能拿到推薦歌單。
**人數不限**——AI 由本站提供，歌曲搜尋走 Spotify 的 app 層級授權。
推薦不會個人化，也無法直接寫進你的 Spotify 歌單。

### 方式二：連結 Spotify（個人化推薦）
讀取你的聆聽紀錄，AI 根據你的口味 + 當下情境推薦「你沒聽過、但會喜歡」的歌。
⚠️ 受 Spotify Development Mode 限制，登入名單最多 25 人，需由專案擁有者在
Developer Dashboard → User Management 逐一加入 email。不在名單內但想要個人化推薦的人，
可以展開頁面下方的「進階（選填）」自備 Spotify App。

> Gemini API Key 由本站提供，使用者不需要也無法填入。

---

## 目前完成狀態

| 階段 | 狀態 | 對應檔案 |
|---|---|---|
| M1：Spotify OAuth + 讀取 Top Tracks | ✅ 完成 | `m1_top_tracks.py` |
| M2：自動寫入歌單到 Spotify | ⏸ **被 Spotify 平台限制** | `m2_create_playlist.py` |
| M3：LLM 推薦引擎 | ✅ 完成 | `m3_recommend.py` |
| M4：多模態情境輸入（文字/圖片/自動偵測） | ✅ 完成 | `m4_contextual_recommend.py` |
| Web UI（Streamlit） | ✅ 完成 | `app.py` |
| BYOK（自備 Spotify App）+ 訪客模式 | ✅ 完成 | `app.py` |
| 出圈演算法（避免推到已經聽過的歌） | ✅ 完成 | `recommend.py` |
| Spotify / YouTube / Apple Music 播放平台切換 | ✅ 完成 | `recommend.play_link()` |
| 曲目回饋 👍/👎/🎧（餵回推薦演算法） | ✅ 完成 | `app.py` + `recommend._feedback_block()` |
| 幻覺補救（搜不到的歌換成同歌手真實曲目） | ✅ 完成 | `spotify_api.repair_hallucinated_track()` |
| Y2K 圖示系統（自繪貼紙 SVG + Material 兩層制） | ✅ 完成 | `styles.py` + `app.py` |
| 生成節流（冷卻 20s + 每日 40 次） | ✅ 完成 | `ratelimit.py` |
| 演算法驗收跑分（S1–S5 自動化 + S6 手動） | 🔧 工具就緒，第 1 輪待跑 | `eval_bench.py` + `EVAL.md` |
| 當地時間偵測 | ✅ 完成（改由瀏覽器提供時區，不靠 IP） | `app.py` |
| 位置與天氣自動偵測 | ⚠️ 雲端的代理鏈拿不到使用者 IP，暫不顯示 | `app.py` |
| 單元測試（199 tests） | ✅ 完成 | `test_*.py` 共 5 個檔案 |

主要使用方式是 **`app.py` Streamlit Web UI**，CLI 檔案保留作為單元測試與功能驗證用。

> 接手開發前請先讀 [`CLAUDE.md`](CLAUDE.md)——架構、踩過的坑與量測數據都在那裡。

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

> `GEMINI_API_KEY` 是**站方必填**（本站共用），使用者端不會出現 Gemini 輸入欄。
> Spotify 的三個值使用者可以在登入頁「進階（選填）」自行覆蓋。

### 3. 啟動 Web UI
```powershell
streamlit run app.py
```

瀏覽器會自動開啟 `http://localhost:8501`。首次會看到登入頁，可選擇 Spotify 登入或訪客模式。

---

## 讓更多人使用（Spotify 25 人限制）

Spotify Development Mode 最多 25 位授權用戶，而 Extended Quota Mode 對個人開發者
實際上已經申請不到（2025/2026 政策）。目前的解法：

### 方法一：訪客模式（預設，人數不限）
不需要 Spotify 帳號也不需要進授權名單，直接開網頁按「直接開始推薦」。
搜尋走 Client Credentials（app 層級），不佔用授權名單。

### 方法二：使用者自備 Spotify App（想要個人化推薦時）
每位使用者建立自己的 Spotify Developer App，就不受本站授權名單限制：

1. 到 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) → Create App
2. 填寫 App Name、Description（隨意）
3. Redirect URI 填入 App 的網址（如 `http://127.0.0.1:8501/` 或 `https://xxx.streamlit.app/`）
4. 勾選 Web API
5. 複製 Client ID 和 Client Secret
6. 在登入頁「進階（選填）：用自己的 Spotify 登入」貼上

> Gemini 不需要自備——AI 由本站的共用 Key 提供。代價是所有使用者共用同一份免費配額，
> 人多時可能撞到 429（會顯示中文提示，不會 crash）。

## 部署到 Streamlit Community Cloud（分享給朋友）

### 前置
- GitHub 帳號（要把專案推到一個 repo）
- Spotify Developer Dashboard 已建好 App

### 步驟

1. **推 code 到 GitHub**（確認 `.env` 跟 `.cache` **不在** commit 內；`.streamlit/config.toml` **要**進版控）
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
   > `GEMINI_API_KEY` 沒設的話，登入頁會顯示紅色錯誤、訪客按鈕變灰（整個 App 不能用）。
   > Spotify 三個值是預設 credentials；自備 App 的使用者會在瀏覽器內填入並覆蓋它們。

4. **Spotify Developer Dashboard 設定**
   - Settings → Redirect URIs → 加上 `https://xxx.streamlit.app/`
   - User Management → 加上要授權的用戶 Email（要用 Spotify 登入的人才需要，上限 25 人）

5. **分享網址給朋友**
   - 一般朋友：直接開網頁 →「直接開始推薦」即可，不用登入也不用申請任何東西
   - 想要個人化推薦的朋友：需要你先在 User Management 加入他們的 Email（上限 25 人）
   - 名單滿了：請對方在「進階（選填）」自備 Spotify App

### 同 WiFi 手機存取
```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```
手機瀏覽器連 `http://<電腦本機IP>:8501`。

---

## 架構與檔案說明

```
├── app.py                       ← 主程式（Streamlit UI 層），日常使用就跑這個
├── recommend.py                 ← prompt 組裝 / Gemini 呼叫 / 驗證鏈（純邏輯，可單獨測試）
├── spotify_api.py               ← OAuth / 搜尋 / 歌單 / 跨 session 歷史
├── styles.py                    ← Y2K 主題 CSS、SVG 圖示、HTML helpers
├── ratelimit.py                 ← 生成節流（純邏輯，時間由參數傳入）
├── eval_bench.py                ← 演算法驗收跑分 CLI（訪客 S1–S5 固定情境）
├── EVAL.md                      ← 驗收紀錄（每輪一節，含人工三題）
├── eval_runs/                   ← 驗收的 JSON 明細（進版控，是歷史資料）
├── test_recommend.py            ← recommend.py 的 pytest（105 tests，不依賴 streamlit）
├── test_spotify_api.py          ← spotify_api.py 的 pytest（27：搜尋快取、重試、OAuth state、幻覺補救）
├── test_styles.py               ← styles.py 的 pytest（14：HTML 產出、注入防護、圖示字型）
├── test_app.py                  ← app.py 的 pytest（40：時區換算、client IP、錯誤白名單、投射輪替）
├── test_ratelimit.py            ← ratelimit.py 的 pytest（13）
├── CLAUDE.md                    ← 交接文件：架構、踩過的坑、量測數據
├── m1_top_tracks.py             ← CLI：驗證 OAuth + 讀取 Top Tracks
├── m2_create_playlist.py        ← CLI：建立歌單（會 403，留作備案）
├── m3_recommend.py              ← CLI：LLM 推薦（純口味，無情境）
├── m4_contextual_recommend.py   ← CLI：情境化推薦（文字/圖片/auto-context）
├── debug_api.py                 ← 診斷工具：測試 Spotify 寫入 API
├── check_models.py              ← 列出可用的 Gemini 模型
├── fonts/                       ← ⚠️ 已無程式使用（13.6 MB，原為 IG 分享圖卡渲染中文用，
│                                   該功能 2026-08-21 移除）——確認不需要就可以刪
├── requirements.txt             ← 依賴清單
├── .streamlit/config.toml       ← 主題色 + toolbarMode + maxUploadSize（要進版控）
├── .env                         ← API Keys（不要進版控）
├── .env.example                 ← 範例
└── .streamlit/secrets.toml.example ← 雲端部署用 Secrets 範例
```

### 核心流程
1. **登入閘門**（`app.py`）：訪客模式 / Spotify OAuth 登入 / 自備 Spotify App
2. **聆聽資料**（登入模式，`spotify_api.py`）：頁面載入就在背景並行抓——
   3 個時間範圍的 Top Tracks/Artists、最近播放、收藏（依 total 決定頁數，上限 500）、追蹤歌手
3. **情境合成**（`app.py`）：**當地時間**（取自瀏覽器時區）+ 文字描述 + 圖片（Gemini Vision）
   + 個人特質（MBTI/血型/星座）+ 心情雙軸 + 語言/曲風 + 投射問題
   + 使用者對過往推薦的 👍/👎/🎧 回饋（城市與天氣在雲端拿不到，會靜默略過）
4. **LLM 推薦**（`recommend.py`）：Gemini 2.5 Flash 產生 JSON 候選（登入超額 1.6 倍、
   訪客 1.25 倍），登入版走 discovery / familiar 雙通道 prompt，兩種模式都請 LLM
   自評每首的知名度 `fame` 1-5
5. **Spotify 搜尋**（`spotify_api.py`）：8 workers 並行把候選轉成 Track URI + 封面；
   模糊搜尋的結果會驗證是否真的對得上，避免拿到「同歌手的另一首熱門歌」
6. **幻覺補救**（`repair_hallucinated_track()`）：搜不到的候選（LLM 編出來的歌名）
   換成**同一位歌手真實存在的深軌**，而不是丟掉——歌手是真的、只有歌名是編的
7. **驗證鏈**（`curate_tracks()`）：去重 → 排除聽過的曲目/歌手 → 知名度天花板 →
   新穎度重排 → 湊不滿時補生成一輪（詳見 `CLAUDE.md`「出圈演算法」）
8. **顯示**：條列式或網格卡片（同列等高），含播放連結與 👍/👎/🎧 回饋鈕；
   回饋會進下一次生成的 prompt，並在程式端保證不再推薦同一首
9. **分享**：純文字複製（含所選平台的播放連結）

推薦品質的核心問題是「使用者選 100% 新藝人，卻還是拿到聽過的歌」——
解法與量測結果都寫在 `CLAUDE.md`。

### Credential 優先順序
```
Spotify：使用者在「進階（選填）」填入的值（session_state）
          ↓ fallback
        .env 或 Streamlit Secrets

Gemini：只讀 .env / Streamlit Secrets（本站自備，使用者不能填）
```
由 `_get_credential()`（Spotify）與 `_gemini_key()`（Gemini）分別管理。

---

## 重要外部限制

### Spotify Web API（2024-11 後政策變更）
新建立的 Spotify App 在 Development Mode 下：

**已被停用的讀取 API**（無法使用）：
- `Get Recommendations`
- `Audio Features`、`Audio Analysis`
- `Related Artists`、`Artist Top Tracks`（實測 403）、30 秒試聽片段

**熱門度訊號也整批消失（2026-08 實測）**：
- track 物件連 `popularity` 這個鍵都沒有，artist 物件沒有 `popularity` / `followers` / `genres`
- 本專案改請 LLM 自評知名度（`fame` 1-5）當替代指標

**還能用的**：`search`、`artist_albums`、`album_tracks`、`current_user_*`、歌單讀寫（部分）
⚠️ `artist_albums` 的 `limit` 上限實測只剩 **10**（2026-08：給 20 或 50 都回 400
「Invalid limit」，官方文件沒跟上）

**寫入 API 被擋（403 Forbidden）**：
- `POST /v1/me/playlists`（建立歌單）
- 解法是申請 Extended Quota Mode，但個人開發者實際上已經申請不到（2025/2026 政策），
  UI 在 403 時會改建議「在 Spotify 開啟」手動加入

**速率限制**：所有訪客共用同一組 Client ID 的配額。撞到 429 時 `Retry-After` 實測是
約 6 小時，spotipy/urllib3 預設會真的睡下去——本專案已改成不遵守該標頭（見 `CLAUDE.md`）。

UI 在 403 時會顯示解決方向，並建議使用「在 Spotify 開啟」手動加入歌單。

### Gemini API
- 預設模型 `gemini-2.5-flash`（免費 tier 可用）
- `gemini-2.0-flash` 免費 tier 配額為 0，不要用
- Vision 多模態用同個模型，傳 `types.Part.from_bytes()`
- **`thinking_budget=0` 一定要留著**：2.5-flash 預設會先思考再回答，
  同一個 prompt 實測 18.2s → 5.0s。整體生成時間約 8–10 秒（訪客模式 15 首）。

---

## Web UI 功能總覽

### 情境設定
- **自動偵測位置與天氣**（toggle）：抓 IP 城市 + Open-Meteo 天氣 + 當下時間
- **文字描述**：自由輸入當下心情或情境
- **圖片上傳**：JPG/PNG/WEBP，Gemini Vision 萃取情緒/氛圍/節奏/能量
- **個人特質**：MBTI、血型、星座
- **心情雙軸 slider**：活力 + 情緒
- **語言 pills**（多選）：華語、英語、日語等
- **曲風 pills**（多選）：Pop、Rock、Indie 等 20 種
- **投射問題**：30 題洗牌輪替（「你手機現在的桌布是什麼？」這類，用回答推測當下狀態；
  一輪出完才重洗，不會連續看到同一題）
- **指定歌手**：逗號分隔，AI 會優先從這些歌手挑

> 版面採漸進式揭露：情境輸入 + 投射問題 + 生成按鈕在最上層，其餘四區收在帶即時摘要的摺疊區。

### 推薦控制
- **歌曲數量 slider**：5-30 首
- **新藝人佔比 slider**：0-100%（僅 Spotify 登入模式）
- **推薦歷史**：session 內 + 跨 session（Spotify 私人歌單持久化），自動去重

### 分享
- **複製歌單**：純文字，含所選播放平台（Spotify / YouTube / Apple Music）的連結

---

## 開發/維護指引

### 想擴充功能
- **先讀 [`CLAUDE.md`](CLAUDE.md)**，裡面有踩過的坑與量測方法（版面、速度、SVG、rate limit）
- 推薦品質的瓶頸在 prompt 與驗證鏈；`recommend.py` 是純邏輯，改完跑 `pytest`
- `app.py` 是主要入口，CLI 檔案（m1-m4）已不常更新

### 改完要跑的檢查
```powershell
python -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ('app.py','recommend.py','spotify_api.py','styles.py')]; print('OK')"
python -m pytest -q
```

### Spotify Token 刷新
Web UI 的 token 只存在瀏覽器分頁的 session（`MemoryCacheHandler`），**不會寫 `.cache` 檔**——
換 scope 只要在 sidebar 登出再登入即可。CLI 腳本（`m1`~`m4`）仍會寫 `.cache`，
那邊要重新授權才需要刪檔：
```powershell
Remove-Item ".cache" -ErrorAction SilentlyContinue
```

### Gemini 模型切換
`check_models.py` 可列出當前 API Key 可用的所有模型。

---

## 已知未實作的方向

- **回饋的跨 session 持久化**：👍/👎/🎧 已經會餵回演算法，但只存在瀏覽器分頁記憶體，
  關掉分頁就歸零。登入版可寫進 Spotify 歌單，訪客版要 localStorage（需自訂前端元件）
- **演算法驗收第 1 輪**：`eval_bench.py` 已就緒但基準還沒跑，見 [`EVAL.md`](EVAL.md)
- 定時自動推薦（Windows Task Scheduler 或 GitHub Actions）
- Spotify 歌單寫入（卡在 Extended Quota Mode，個人開發者申請不到）
- 雲端的位置與天氣（代理鏈拿不到 client IP，見 `CLAUDE.md`「位置偵測」）

> **已經調查過、結論是「不要做」的方向**（別重複踩坑，理由都在 `CLAUDE.md`）：
> 播放點擊中繼計數（雲端 iframe sandbox 擋死）、Apple Music 曲目直連（iTunes Search API
> 中文召回率極差）、YouTube Data API（配額不夠）、讓 LLM 只提名歌手而曲目全由 Spotify
> 提供（成本 +70 請求／批——已改用只修失敗案例的 repair-on-miss，用一成成本拿九成效益）。
