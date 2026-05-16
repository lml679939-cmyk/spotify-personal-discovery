# Spotify Personal Discovery

個人化音樂發現 App，結合 Spotify 聆聽資料、Gemini 多模態 LLM 與環境情境（時間、天氣、地理位置、圖片、文字）生成推薦歌單。

## 為什麼做這個

使用者平常使用 Spotify 時間碎片化，自家演算法容易陷入循環推薦舊歌。本專案用 LLM 的廣度知識打破 collaborative filtering 的回音壁，並讓「當下情境」主導推薦風格。

---

## 目前完成狀態

| 階段 | 狀態 | 對應檔案 |
|---|---|---|
| M1：Spotify OAuth + 讀取 Top Tracks | ✅ 完成 | `m1_top_tracks.py` |
| M2：自動寫入歌單到 Spotify | ⏸ **被 Spotify 平台限制** | `m2_create_playlist.py` |
| M3：LLM 推薦引擎 | ✅ 完成 | `m3_recommend.py` |
| M4：多模態情境輸入（文字/圖片/自動偵測） | ✅ 完成 | `m4_contextual_recommend.py` |
| Web UI（Streamlit） | ✅ 完成 | `app.py` |

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
本機跑用 `http://localhost:8501/`，雲端部署改成 `https://你的app.streamlit.app/`。

### 3. 啟動 Web UI
```powershell
streamlit run app.py
```

瀏覽器會自動開啟 `http://localhost:8501`。首次會看到登入頁，點「用 Spotify 登入」後跳轉授權，回來就能使用。

---

## 部署到 Streamlit Community Cloud（分享給朋友）

### 前置
- GitHub 帳號（要把專案推到一個 repo）
- Spotify Developer Dashboard 已建好 App
- 朋友的 Spotify Email 清單（Premium 帳號，最多 5 人）

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

4. **Spotify Developer Dashboard 設定**
   - Settings → Redirect URIs → 加上 `https://xxx.streamlit.app/`
   - User Management → 加上所有要授權的朋友 Email（最多 5 人）

5. **分享網址給朋友**
   - 朋友點連結 → 看到登入頁 → 用 Spotify 授權 → 就能用自己的資料生成推薦

### 朋友超過 5 人怎麼辦？
到 Developer Dashboard → 你的 App → 申請 **Extended Quota Mode**，等 Spotify 審核（幾天到幾週）。

### 同 WiFi 手機存取
```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```
手機瀏覽器連 `http://<電腦本機IP>:8501`。

---

## 架構與檔案說明

```
├── app.py                       ← 主程式（Streamlit UI），日常使用就跑這個
├── m1_top_tracks.py             ← CLI：驗證 OAuth + 讀取 Top Tracks
├── m2_create_playlist.py        ← CLI：建立歌單（會 403，留作備案）
├── m3_recommend.py              ← CLI：LLM 推薦（純口味，無情境）
├── m4_contextual_recommend.py   ← CLI：情境化推薦（文字/圖片/auto-context）
├── debug_api.py                 ← 診斷工具：測試 Spotify 寫入 API
├── check_models.py              ← 列出可用的 Gemini 模型
├── requirements.txt             ← 依賴清單
├── .env                         ← API Keys（不要進版控）
├── .env.example                 ← 範例
└── .cache                       ← Spotipy OAuth Token Cache（自動產生）
```

### 核心流程（`app.py`）
1. **聆聽資料**：抓 Top Tracks（短期+中期）、Top Artists、Recently Played(50)、Saved Tracks(100)
2. **情境合成**：自動偵測（IP→城市→天氣+時間）+ 文字描述 + 圖片（Gemini Vision 分析氛圍）
3. **LLM 推薦**：Gemini 2.5 Flash 根據口味、情境、已聽清單、新藝人佔比，生成 JSON 候選歌單
4. **Spotify 解析**：用 Search API 將每首候選歌轉換為 Track URI 與專輯封面
5. **顯示**：條列式或網格（3-10 欄）卡片，每首歌附 Spotify 開啟連結
6. **加入歌單**：嘗試呼叫 `playlist-modify` API（目前會 403，見下方）

---

## 重要外部限制

### Spotify Web API（2024-11 後政策變更）
新建立的 Spotify App 在 Development Mode 下：

**已被停用的讀取 API**（無法使用）：
- `Get Recommendations`
- `Audio Features`、`Audio Analysis`
- `Related Artists`、30 秒試聽片段
- `Featured Playlists`、`Category Playlists`

**寫入 API 被擋（403 Forbidden）**：
- `POST /v1/users/{id}/playlists`（建立歌單）
- `PUT /v1/me/tracks`（加入 Liked Songs）
- 已嘗試以下解法皆無效：
  - 加入 User Management（confirmed email 匹配）
  - 加上 `show_dialog=True` 強制重新授權
  - 撤銷 App 授權後重新登入
- **唯一解法**：到 Developer Dashboard 申請 **Extended Quota Mode** 等待審核

目前 UI 在 403 時會顯示三個解決方向給使用者，並建議使用卡片上的「在 Spotify 開啟」手動加入歌單。

### Gemini API
- 使用者 Anthropic Console 沒有額度，已改用 Gemini 免費 API
- 預設模型 `gemini-2.5-flash`（早期試過 `gemini-2.0-flash` 但免費額度為 0）
- Vision 多模態用同個模型，傳 `types.Part.from_bytes()`

---

## Web UI 功能總覽

### 情境設定
- **自動偵測位置與天氣**（toggle）：抓 IP 城市 + Open-Meteo 天氣 + 當下時間
- **文字描述**：自由輸入當下心情或情境
- **圖片上傳**：JPG/PNG/WEBP，Gemini Vision 會萃取情緒/氛圍/節奏/能量等結構化標籤
- 三者可疊加使用

### 推薦控制
- **歌曲數量 slider**：5-30 首
- **新藝人佔比 slider**：0-100%（以 10% 為單位）
  - 0% = 全部從已接觸藝人推
  - 70% = 平衡（預設）
  - 100% = 完全沒接觸過的小眾新藝人

### 顯示控制
- **顯示方式**：條列式 / 網格
- **網格**：可調每列 3-10 首（超過 5 首會自動隱藏專輯名與推薦理由節省空間）

### 加入 Spotify 歌單
- 自訂歌單名稱 + 一鍵加入（受 Spotify 403 限制）

---

## 開發/維護指引

### 想擴充功能
- 修改 prompt 比改架構有效，推薦品質的瓶頸在 prompt 設計
- 三個檔案（`m3`、`m4`、`app.py`）都有自己的 `build_prompt` 與 `fetch_user_profile`，改一個記得對齊其他兩個
- 或考慮抽出共用的 `spotify_utils.py`（目前刻意不抽，避免過早抽象）

### Spotify Token 刷新
如果加新 scope 或寫入失敗：
```powershell
Remove-Item ".cache" -ErrorAction SilentlyContinue
```
然後重新執行會跳新的授權頁。

### Gemini 模型切換
`check_models.py` 可列出當前 API Key 可用的所有模型。注意 `gemini-2.0-flash` 雖然在清單裡，但免費 tier 配額為 0；目前可用的免費模型是 `gemini-2.5-flash`。

### 雲端部署
- 本機 WiFi 已驗證可手機存取
- 下一步：Streamlit Community Cloud（GitHub private repo + Secrets 管理 API Keys）

---

## 已知未實作的方向

- 申請 Spotify Extended Quota Mode 解鎖寫入 API + 突破 5 人上限
- 定時自動推薦（Windows Task Scheduler 或 GitHub Actions）
- 推薦結果評分回饋機制（讓 LLM 學習使用者喜好）
