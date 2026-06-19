# CLAUDE.md — AI 開發者交接文件

本文件供 AI 助手（Claude / 其他 LLM）在接手本專案時快速理解架構與注意事項。

## 專案概覽

Spotify Personal Discovery — 個人化音樂推薦 Streamlit Web App。

- **主要入口**：`app.py`（Streamlit Web UI）
- **語言**：Python 3.12+
- **框架**：Streamlit >= 1.37
- **外部 API**：Spotify Web API（via Spotipy）、Google Gemini 2.5 Flash
- **使用者偏好語言**：繁體中文

## 關鍵架構

### 雙模式運行
1. **Spotify 登入模式**：讀取使用者聆聽資料，個人化推薦
2. **訪客模式**（`is_guest_mode()`）：不需 Spotify 帳號，純情境推薦

### Credential 管理（重要）
```
_get_credential(key)
  → 先查 st.session_state["custom_{key}"]（使用者自訂 BYOK）
  → 再查 _get_env(key)（.env / Streamlit Secrets）
```
所有用到 API Key 的地方都用 `_get_credential()` 而非直接讀 env。

### Spotify 認證
- **登入模式**：Authorization Code Flow（`SpotifyOAuth` + `MemoryCacheHandler`）
- **訪客模式搜尋**：Client Credentials Flow（`SpotifyClientCredentials`，`_get_guest_spotify_client()`）
- Token 只存 session_state，不寫 `.cache` 檔

### 推薦流程
1. `fetch_user_profile()` — 讀 Spotify 資料（訪客模式跳過）
2. `fetch_auto_context()` — IP 定位 + 天氣
3. `analyze_image()` — Gemini Vision 圖片分析（選用）
4. `build_prompt()` / `build_guest_prompt()` — 組裝 LLM prompt
5. `get_recommendations()` — 呼叫 Gemini，解析 JSON
6. `search_track()` — Spotify Search API 解析曲目
7. `dedupe_tracks()` — 後處理去重

### 歷史去重
- **Session 內**：`st.session_state["recommend_history"]`
- **跨 Session**（僅登入模式）：寫入 Spotify 私人歌單 `🤖 AI Discovery History`
- 訪客模式只有 session 內歷史

## 修改注意事項

### Spotify API 限制
- Development Mode 最多 25 位授權用戶（BYOK 可繞過）
- 2024-11 政策：新 endpoint `POST /me/playlists`、`POST /playlists/{id}/items`
- 寫入 API 會 403 — 需申請 Extended Quota Mode
- 被停用的 API：`Get Recommendations`、`Audio Features`、`Audio Analysis`、`Related Artists`

### Gemini
- 模型：`gemini-2.5-flash`（`GEMINI_MODEL` 常數）
- `gemini-2.0-flash` 免費 tier 配額為 0，不要用
- 有 503 重試邏輯（3 次，8s/16s 間隔）
- JSON 解析有 regex fallback（`_parse_json_robust()`）

### UI 元件 Key 衝突
- `_render_api_key_settings()` 在登入頁和 sidebar 共用，但因 `st.stop()` 機制，兩者不會同時渲染
- Streamlit widget key 以 `custom_` 前綴存在 session_state，例如 `custom_SPOTIFY_CLIENT_ID`

### UI 主題系統（Y2K / Retro Pop）
- **`styles.py`**：集中管理所有 CSS、SVG 素材、HTML 輔助函數
  - `inject_global_css()` — 在 `app.py` 頂部呼叫，注入全域 CSS
  - CSS 變數定義在 `:root`（`--y2k-cyan`, `--y2k-pink`, `--y2k-yellow`, `--y2k-purple` 等）
  - 5 個內嵌 SVG 常數：`SVG_CASSETTE`, `SVG_VINYL`, `SVG_NOTES`, `SVG_BOOMBOX`, `SVG_SPARKLE`
  - HTML helpers：`login_hero_html()`, `login_spotify_card()`, `login_guest_card()`, `track_card_html()`, `track_list_html()`, `results_header_html()`, `context_interpretation_html()`, `section_header_html()`, `divider_html()`
- **`.streamlit/config.toml`**：Streamlit 原生主題設定（primaryColor, backgroundColor 等）
- **強制亮色模式**，不支援暗色主題
- 修改樣式時只改 `styles.py` + `config.toml`，不要在 `app.py` 中混入 CSS
- CSS 選擇器依賴 Streamlit 的 `data-testid` 屬性，升級 Streamlit 版本時需驗證
- `span` 的 font-family 排除了 Material Symbols icon（`:not(.material-symbols-rounded)` 等），避免破壞圖示渲染

### 分享圖卡
- `share_card.py`：9 色系（原 7 + Neon Pop + Cyber Y2K）
- 兩種模式：單張總合卡（`generate_single`）/ 4 張分頁（`generate_deck`）
- 需要 `fonts/NotoSansTC-*.ttf` 字型檔

## 常見操作

### 啟動開發伺服器
```powershell
streamlit run app.py
```

### 語法檢查
```powershell
python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"
```

### 推到 Streamlit Cloud
```powershell
git add app.py README.md CLAUDE.md
git commit -m "feat: ..."
git push origin main
```
Streamlit Cloud 會自動偵測 push 並重新部署。

## 檔案結構

| 檔案 | 用途 | 常改？ |
|---|---|---|
| `app.py` | 主程式 Streamlit UI | 是 |
| `styles.py` | Y2K 主題 CSS/SVG/HTML helpers | 偶爾 |
| `share_card.py` | IG Story 圖卡生成 | 偶爾 |
| `m1_top_tracks.py` | CLI：OAuth 測試 | 否 |
| `m2_create_playlist.py` | CLI：歌單寫入測試 | 否 |
| `m3_recommend.py` | CLI：LLM 推薦測試 | 否 |
| `m4_contextual_recommend.py` | CLI：情境推薦測試 | 否 |
| `requirements.txt` | pip 依賴 | 偶爾 |
| `.env` / `.env.example` | 本地 credentials | 否 |
| `.streamlit/config.toml` | Streamlit 主題設定（Y2K 色彩） | 偶爾 |
| `.streamlit/secrets.toml.example` | 雲端 credentials 範例 | 否 |
