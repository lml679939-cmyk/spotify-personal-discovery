# CLAUDE.md — AI 開發者交接文件

本文件供 AI 助手（Claude / 其他 LLM）在接手本專案時快速理解架構與注意事項。

## 專案概覽

**Spotify Personal Discovery** — 個人化音樂推薦 Streamlit Web App。

- **主要入口**：`app.py`（Streamlit UI 層）
- **模組拆分**：`recommend.py`（prompt/Gemini/去重，無 Streamlit 依賴、可單元測試）、`spotify_api.py`（OAuth/搜尋/歌單/歷史）
- **樣式集中管理**：`styles.py`（Y2K/Retro Pop 主題）
- **測試**：`test_recommend.py`（pytest，28 tests）
- **語言**：Python 3.12+
- **框架**：Streamlit >= 1.37
- **外部 API**：Spotify Web API（via Spotipy）、Google Gemini 2.5 Flash
- **部署**：Streamlit Community Cloud — `https://spotify-lml.streamlit.app`
- **GitHub**：`https://github.com/lml679939-cmyk/spotify-personal-discovery`
- **使用者偏好語言**：繁體中文

## 關鍵架構

### 雙模式運行
1. **訪客模式**（`is_guest_mode()`，登入頁「方式一」）：不需 Spotify 帳號、零設定，純情境推薦。
   **人數不限**——搜尋走 Client Credentials（app 層級），AI 用本站自備的 Gemini Key。
2. **Spotify 登入模式**（「方式二」）：讀取使用者聆聽資料，個人化推薦 + 寫入歌單。
   **受 Spotify Development Mode 授權名單人數限制**，需在 Dashboard → User Management 逐一加 email。

### Credential 管理（重要）
```
_get_credential(key)   # 只用於 Spotify
  → 先查 st.session_state["custom_{key}"]（使用者自訂 BYOK）
  → 再查 _get_env(key)（.env / Streamlit Secrets）

_gemini_key()          # Gemini 專用，app.py
  → 只查 _get_env("GEMINI_API_KEY")
```
> ⚠️ **Gemini 是本站自備的共用 Key**，使用者不能也不需要填（2026-08 改）。
> UI 上已無 Gemini 輸入欄，`custom_GEMINI_API_KEY` 這個 session key 已完全移除。
> 雲端部署必須在 Streamlit Cloud → Settings → Secrets 設定 `GEMINI_API_KEY`，否則登入頁會顯示紅色錯誤、訪客按鈕變灰。
> 共用 Key 代表**所有使用者共用同一份免費配額**，人多時會撞 429（已有中文友善訊息，不會 crash）。

Spotify BYOK 仍保留為「進階（選填）」，供不在授權名單內、又想要個人化推薦的使用者自建 App。

### Spotify 認證
- **登入模式**：Authorization Code Flow（`SpotifyOAuth` + `MemoryCacheHandler`）
- **訪客模式搜尋**：Client Credentials Flow（`SpotifyClientCredentials`，`_get_guest_spotify_client()`）
- Token 只存 session_state，不寫 `.cache` 檔

### 模組分層（2026-08 拆分）
```
app.py         → UI、登入/訪客流程、context helpers（定位/天氣）
recommend.py   → prompt 組裝、Gemini 呼叫（api_key 用參數傳入）、JSON 解析、去重
                 ⚠️ 不 import streamlit——pytest 可直接 import
spotify_api.py → OAuth、Spotify clients、並行搜尋、歌單寫入、跨 session 歷史
                 import streamlit 但無 module-level UI 碼，import 安全
```

### 推薦流程
1. `fetch_user_profile()`（spotify_api）— 讀 Spotify 資料（訪客模式跳過）
2. `fetch_auto_context()`（app）— IP 定位 + 天氣（`_fetch_geo_weather()` 快取 `AUTO_CONTEXT_TTL=600` 秒；時刻每次即時算）
3. `analyze_image(api_key, ...)`（recommend）— Gemini Vision 圖片分析（選用）
4. `build_prompt()` / `build_guest_prompt()`（recommend）— 組裝 LLM prompt
5. `get_recommendations(api_key, ...)`（recommend）— 呼叫 Gemini，解析 JSON
6. `_search_tracks_parallel()`（spotify_api）— ThreadPoolExecutor 8 workers 並行呼叫 `search_track()`；token 需在主執行緒先用 `_get_search_token()` 取得（worker thread 不能碰 session_state），單首失敗以 fallback 搜尋卡呈現、不中斷整批
7. `dedupe_tracks()`（recommend）— 後處理去重

### 推薦 Prompt 參數（兩個函式都有）
| 參數 | 說明 |
|---|---|
| `context` | 情境文字（地點天氣 + 使用者描述 + 圖片分析） |
| `num_songs` | 推薦歌曲數量（5–30） |
| `user_traits` | MBTI/星座/心情/活動/投射問題 |
| `languages` | 語言過濾清單（None = 不限） |
| `genres` | 曲風過濾清單（None = 不限） |
| `history` | 已推薦歌曲清單（避免重複） |
| `fav_artists` | **使用者指定歌手**（None = 不限；填入時 AI 優先從這些歌手推薦） |

### 歷史去重
- **Session 內**：`st.session_state["recommend_history"]`
- **跨 Session**（僅登入模式）：寫入 Spotify 私人歌單 `🤖 AI Discovery History`
- 訪客模式只有 session 內歷史
- 歷史歌單上限 `PERSISTENT_HISTORY_MAX=500` 首，超過時 `_trim_persistent_history()` 自動修剪最舊的
- 清空/修剪都用 `_playlist_replace_items()`：`PUT /playlists/{id}/items` 整批取代（失敗 fallback 舊 `/tracks` 路徑）

## UI 主題系統（Y2K / Retro Pop）

### styles.py 結構
- **CSS**：`_build_global_css()` — 在 f-string 內，所有 CSS `{}` 須寫成 `{{}}` 否則 Python SyntaxError
- **SVG 常數**：`SVG_CASSETTE`, `SVG_VINYL`, `SVG_NOTES`, `SVG_BOOMBOX`, `SVG_SPARKLE`
- **HTML helpers**：
  - `inject_global_css()` — app.py 頂部呼叫，注入全域 CSS
  - `login_hero_html()` — 登入頁頂部 Hero 區（圖示 + 標題 + 副標題）
  - `login_spotify_card()` / `login_guest_card()` — 登入方式卡片
  - `byok_spotify_steps_html()` — 自建 Spotify App 的視覺引導步驟卡（Gemini 版已移除）
  - `track_card_html()` / `track_list_html()` — 推薦結果卡片
  - `results_header_html()` / `context_interpretation_html()` / `section_header_html()` / `divider_html()`

### CSS 變數（:root）
```css
--y2k-cyan: #00D4AA
--y2k-pink: #FF69B4
--y2k-yellow: #FFD700
--y2k-purple: #9B59B6
--y2k-deep-purple: #2D1B4E
--y2k-cream: #FFFDF7
--y2k-lavender: #FFF0F5
```

### .streamlit/config.toml
```toml
[theme]
primaryColor = "#FF69B4"
backgroundColor = "#FFFDF7"
secondaryBackgroundColor = "#FFF0F5"
textColor = "#2D1B4E"

[client]
toolbarMode = "minimal"   # 縮小頂部工具列，移除裝飾線
```
> ⚠️ 這個檔案已加入 git，會被 Streamlit Cloud 讀取。

### Streamlit 頂部裝飾線隱藏
在 `_build_global_css()` 中以 CSS 隱藏，涵蓋多版本 selector：
```css
[data-testid="stDecoration"], [data-testid="stDecorationLine"], ...
[data-testid="stHeader"], header { display: none !important; ... }
```
若 Streamlit 升版後裝飾線復現，需檢查新版的 `data-testid` 屬性名稱。

### 重要限制
- **強制亮色模式**，不支援暗色主題
- 修改樣式只改 `styles.py` + `config.toml`，不要在 `app.py` 混入 CSS
- `_method_card_html()` 使用 `min-height:130px`（非 `height`），讓手機上文字換行後能撐高，不截字

## 修改注意事項

### Spotify API 限制（重要）
- **Development Mode 最多 25 位授權用戶**（BYOK 可繞過此限制）
- Extended Quota Mode（申請更多用戶）對個人開發者實際上已無法申請（截至 2025/2026 Spotify 政策）
- **已停用的 API**：`Get Recommendations`、`Audio Features`、`Audio Analysis`、`Related Artists`
- 歌單寫入需申請 Quota Extension（`POST /playlists/{id}/items` 會 403）

### Gemini
- 模型：`gemini-2.5-flash`（`GEMINI_MODEL` 常數，在 `recommend.py`）
- `gemini-2.0-flash` 免費 tier 配額為 0，不要用
- 有 503 重試邏輯（3 次，8s/16s 間隔）
- 429/RESOURCE_EXHAUSTED 與 API Key 無效不重試，`_friendly_gemini_error()` 直接轉成中文友善訊息
- JSON 解析有 regex fallback（`_parse_json_robust()`）；code fence 統一由 `_strip_code_fence()` 處理

### Widget Key 衝突
- `_render_api_key_settings()` 在登入頁和 sidebar 共用，因 `st.stop()` 機制兩者不同時渲染
- Streamlit widget key 以 `custom_` 前綴存在 session_state：`custom_SPOTIFY_CLIENT_ID` 等

### f-string 中的 CSS
`styles.py` 的 `_build_global_css()` 是一個 f-string。所有 CSS 花括號必須寫成雙括號：
```python
# ✅ 正確
.selector {{
    color: red;
}}

# ❌ 錯誤（會造成 Python SyntaxError）
.selector {
    color: red;
}
```

## 輸入欄位說明（登入頁）

### 進階（選填）：自備 Spotify App
| 欄位 | session_state key | 說明 |
|---|---|---|
| Spotify Client ID | `custom_SPOTIFY_CLIENT_ID` | 自動填入 Redirect URI |
| Spotify Client Secret | `custom_SPOTIFY_CLIENT_SECRET` | |
| Redirect URI | `custom_SPOTIFY_REDIRECT_URI` | 自動從 URL 組合 |

> Gemini 欄位已於 2026-08 移除——AI 由本站提供，見上方 Credential 管理。

### 推薦偏好輸入
| 欄位 | 變數 | 說明 |
|---|---|---|
| 情境文字 | `text_ctx` | 自由描述當下情境 |
| 自動偵測 | `auto_ctx` | 開啟後讀取 IP/天氣 |
| 圖片上傳 | `uploaded` | Gemini Vision 分析氛圍 |
| 活動情境 | `activity` | Pills 單選 |
| 語言 | `languages` | Pills 多選 |
| 曲風 | `genres` | Pills 多選 |
| **指定歌手** | `fav_artists` | 文字輸入，逗號分隔，傳入 prompt 讓 AI 優先推薦 |
| 推薦數量 | `num_songs` | 5–30 首 |
| 新藝人佔比 | `new_artist_ratio` | 0–100%（僅登入模式） |

## 常見操作

### 啟動開發伺服器
```powershell
streamlit run app.py
```

### 語法檢查
```powershell
python -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ('app.py','recommend.py','spotify_api.py','styles.py')]; print('OK')"
```

### 跑單元測試（改 recommend.py 後必跑）
```powershell
python -m pytest test_recommend.py -q
```

### 推到 Streamlit Cloud
```powershell
git add app.py recommend.py spotify_api.py styles.py .streamlit/config.toml
git commit -m "feat: ..."
git push origin main
```
Streamlit Cloud 會自動偵測 push 並重新部署（約 1–2 分鐘）。

## 檔案結構

| 檔案 | 用途 | 常改？ |
|---|---|---|
| `app.py` | Streamlit UI 層 + 登入/訪客流程 | 是 |
| `recommend.py` | prompt / Gemini / JSON 解析 / 去重（純邏輯，無 Streamlit） | 是 |
| `spotify_api.py` | OAuth / 搜尋 / 歌單 / 跨 session 歷史 | 偶爾 |
| `test_recommend.py` | recommend.py 單元測試（pytest） | 改 recommend.py 時同步 |
| `styles.py` | Y2K 主題 CSS / SVG / HTML helpers | 偶爾 |
| `share_card.py` | IG Story 圖卡生成（Pillow） | 偶爾 |
| `.streamlit/config.toml` | Streamlit 主題 + toolbarMode | 偶爾 |
| `requirements.txt` | pip 依賴 | 偶爾 |
| `.env` / `.env.example` | 本地 credentials（不加入 git） | 否 |
| `m1~m4_*.py` | CLI 測試腳本（非主程式） | 否 |

## 近期修改紀錄（最新在上）

| Commit | 說明 |
|---|---|
| `c19033a` | feat: Gemini 改為本站自備（移除 BYOK 欄位），訪客模式提升為方式一、Spotify 登入降為方式二並說明人數限制 |
| `2c25727` | fix: hero 上下間距對齊（container padding-top 0.8rem） |
| `0823714` | fix: 改用 stMainBlockContainer testid 收窄頂部留白 |
| `7f1df04` | refactor: Spotify 層拆到 spotify_api.py，app.py 只剩 UI（~870 行） |
| `e5f5202` | test: 純邏輯拆到 recommend.py（Gemini api_key 改參數傳入），新增 test_recommend.py 28 個單元測試 |
| `c64c4e8` | refactor: 清理 imports、Gemini 429/Key 無效友善錯誤訊息、403 文案改寫（移除 Extended Quota 死路建議，改指向 BYOK） |
| `cd90b79` | fix: 移除 not_found 死代碼、fallback 連結 URL encoding；perf: 天氣/定位快取 10 分鐘、歷史歌單上限 500 首自動修剪 |
| `749d847` | fix: 清除歷史改用 PUT /items（舊 DELETE /tracks 已失效）、專輯無封面防呆；perf: Spotify 搜尋並行化（ThreadPoolExecutor 8 workers） |
| `c8dd345` | fix: restore env/secrets fallback in _get_credential — BYOK optional |
| `e9261e3` | fix: remove double border on privacy badge inside BYOK expander |
| `9c504a1` | fix: remove env/secrets fallback in _get_credential — BYOK only |
| `30f29eb` | feat: require BYOK — remove shared key fallback messaging |
| `7c12fe6` | fix: f-string brace escaping in styles.py |
| `f750931` | fix: push config.toml to git; use `header` tag selector |
| `562a97d` | feat: 新增「指定歌手」輸入欄位 + prompt 注入 |
| `74098cd` | fix: 多版本 selector 隱藏裝飾線 |
| `82ef1b6` | fix: 隱藏 stHeader，清零頂部 padding |
| `9ad5880` | feat: BYOK 視覺引導 UI 大改版（styles.py 新增） |
| `0998747` | feat: BYOK credentials、訪客模式、Redirect URI 自動填入 |
