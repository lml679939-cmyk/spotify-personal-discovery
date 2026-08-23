# CLAUDE.md — AI 開發者交接文件

本文件供 AI 助手（Claude / 其他 LLM）在接手本專案時快速理解架構與注意事項。

## 專案概覽

**SoundCurator** — 個人化音樂推薦 Streamlit Web App。
> 2026-08-22 顯示名稱由「Spotify Personal Discovery」改為「SoundCurator」。
> ⚠️ GitHub repo 仍是 `spotify-personal-discovery`（未改）；部署網址已由 `spotify-lml` 改成 `soundcurator.streamlit.app`。
> 換子網域要同步三處、否則方式二登入會 redirect mismatch：① Streamlit App URL ② Spotify Dashboard 的 Redirect URI ③ Streamlit Secrets 的 `SPOTIFY_REDIRECT_URI`。
> UI 顯示名稱／分享文字／歌單敘述已改；`HISTORY_PLAYLIST_NAME`（靠名稱找回歷史）刻意未動。

- **主要入口**：`app.py`（Streamlit UI 層）
- **模組拆分**：`recommend.py`（prompt/Gemini/去重，無 Streamlit 依賴、可單元測試）、`spotify_api.py`（OAuth/搜尋/歌單/歷史）
- **樣式集中管理**：`styles.py`（Y2K/Retro Pop 主題）
- **測試**：`test_recommend.py`（125）+ `test_spotify_api.py`（32）+ `test_styles.py`（14）+ `test_app.py`（40）+ `test_ratelimit.py`（13）+ `test_db.py`（21，純邏輯＋假 conn，不需 DB），共 245 tests
  ⚠️ `test_app.py` 會 import `app.py`＝把登入頁渲染一遍（約 5s，不發網路請求）。純邏輯請放 `recommend.py`。
- **語言**：Python 3.12+
- **框架**：Streamlit >= 1.57（`st.expander(key=...)` 需要）
- **外部 API**：Spotify Web API（via Spotipy）、Google Gemini 2.5 Flash
- **部署**：Streamlit Community Cloud — `https://soundcurator.streamlit.app`
- **GitHub**：`https://github.com/lml679939-cmyk/spotify-personal-discovery`
- **使用者偏好語言**：繁體中文

## 交接：先讀這 5 分鐘

**跑起來**
```powershell
streamlit run app.py                    # 本機開發（.env 要有 GEMINI_API_KEY / SPOTIFY_*）
python -m pytest -q                     # 245 tests，改任何 .py 都要跑
```
⚠️ 改了 `styles.py` / `recommend.py` / `spotify_api.py` **要重啟 streamlit**，
只存檔重整瀏覽器沒用（見「啟動開發伺服器」）。

**照任務找地方**

| 你要做的事 | 先看 | 一定要先讀的段落 |
|---|---|---|
| 改推薦品質／出圈程度 | `recommend.py` 的 `build_prompt()` / `curate_tracks()` | 「出圈演算法」整段＋**「驗收流程」（改演算法前後都要跑分）** |
| 改版面、間距、顏色 | `styles.py`（CSS 全在 `_build_global_css()`） | 「版面幾何」「視覺層級」（含垂直間距三級制） |
| 加／改圖示 | `styles.py` 的 SVG 常數；原生元件用 `icon=":material/xxx:"` | 「圖示系統」（兩層制、三種 testid 的字型地雷） |
| 改 Spotify 相關 | `spotify_api.py` | 「Spotify API 限制」「速率限制與 spotipy 重試」 |
| 查為什麼很慢 | 「生成速度」表 | 同段的量法（`_mark()` 印 stderr） |
| 時間顯示不對 | `_local_now()` | 「時區」 |

**這個專案的三條工作紀律**（前人踩過才立的規矩，請沿用）
1. **版面問題一律先量再改**——起 `streamlit run app.py --server.headless true --server.port 8599`
   用瀏覽器跑 `getBoundingClientRect()` / `getComputedStyle()`，改完再量一次。
   目測分不出 1px 和 12px，這個專案的版面 bug 幾乎都是「量了才知道真正原因」。
2. **演算法改動前後各跑一輪 `eval_bench.py`，數字進 `EVAL.md`**——沒有對照數字的
   演算法改動不要上線（使用者定的）。
3. **改了行為就順手更新這份文件**，尤其是踩到新坑時：寫下「症狀 → 真正原因 → 量法」，
   不要只寫結論。這份文件的價值全在那些細節上。

**最容易重蹈的覆轍**（每一條都真的發生過，細節在對應段落）
1. `datetime.now()` — 雲端是 UTC，台灣少 8 小時。一律 `_local_now()`。
2. Gemini 的 `thinking_budget=0` 被拿掉 — 生成時間會從 5s 變回 18s。
3. spotipy 預設重試 — 429 的 `Retry-After` 是 6 小時，urllib3 會真的睡下去，整頁凍住。
4. 注入的 HTML 有縮排 — Streamlit markdown 會當成程式碼區塊印出原始碼。
5. Material 圖示顯示成文字（「music_note」而不是圖示）— 全域 span 的 Nunito
   `!important` 把圖示字型蓋掉、連字失效。圖示 span 有**三種**變體，`:not()` 排除清單
   缺一不可（這次踩了三次才收齊），見「圖示系統」。
6. prompt 裡塞長排除清單 — 遵守率會掉，保證要寫在程式端（`curate_tracks()`）。
7. 以為 `st.session_state` 撐得過 OAuth 來回 — **不會**，跳去 Spotify 再導回是整頁重載，
   session_state 整個重生。OAuth state 因此做成無狀態簽章，見「OAuth state」。
8. 把網址參數（`?error=`）原樣回顯到 `st.warning()` — alert 會渲染 Markdown，
   反引號可跳脫 code span，等於讓人在登入頁插釣魚連結。一律走白名單。
9. push 後看到 `ImportError: cannot import name 'X' from 'recommend'`，
   但 GitHub 上明明有 X — **不是程式的錯，是 Streamlit Cloud 沒重啟行程**。
   見下方「部署：跨模組改動要 Reboot」。本機改被 import 的模組也一樣要重啟。
10. 拿不到使用者 IP 還照樣打 ipwho.is — 那會定位到**伺服器自己**（顯示 The Dalles），
    時刻判斷全錯。見「位置偵測」。
11. 用 IP 推時區 — 雲端拿不到 client IP、使用者掛 VPN 也會錯。
    一律用 `st.context.timezone_offset`（注意單位是分鐘、正負號相反），見「時區」。
12. **在 GitHub Codespaces／dev container 裡開發時，測試會紅、安全機制會失效**——
    但那不是你改壞的，是 `.devcontainer/devcontainer.json` 的設定，見下方「dev container 的兩個陷阱」。

**⚠️ dev container 的兩個陷阱**（`.devcontainer/devcontainer.json`，GitHub Codespaces 會吃）

這個檔案是 GitHub 自動產生的樣板、**沒有跟著本專案調整過**，裡面兩個設定與專案的
前提衝突。本機 Windows 開發不受影響，只有在 Codespaces／dev container 裡才會中招：

| 設定 | 衝突 | 症狀 |
|---|---|---|
| `image: …python:1-3.11-bookworm` | 專案要求 **Python 3.12+** | `test_app.py` 有幾條測試依賴 3.12 才把 `203.0.113.x` / `2001:db8::` 算成 private，在 3.11 上會失敗——乾淨的 checkout 卻看到紅色測試 |
| `postAttachCommand` 帶 `--server.enableXsrfProtection false` | 關掉 XSRF＝拿不到 `_streamlit_xsrf` cookie | `_browser_secret()` 回空字串 → **OAuth state 綁定失效**（見「OAuth state」的限制段）＋**節流桶退回 per-session 隨機 id**（重整就能洗掉額度）。兩道防線都靜默降級，不會報錯 |

要在容器裡認真開發就先把 image 換成 3.12、拿掉那個 XSRF flag；只是隨手跑一下就
知道上面兩件事即可。**別因為容器裡測試紅就去改測試或改 `_client_ip()` 的邏輯。**

**接手後的第一件事**（2026-08-23 交接狀態，第 4 版）

> ⚠️ **第 2 輪第 2 項尚未 push**（第 1 項「指定歌手保底」已 push＝commit `00afdaf`；工作區有
> 第 2 項的改動、222 tests 全過）。顯示名稱 **SoundCurator**、網址 `soundcurator.streamlit.app`
> （repo 仍 spotify-personal-discovery）。**第 2 輪兩項演算法都已做完並驗收**（數字進 `EVAL.md`
> 第 2 輪兩節）。細節見「指定歌手保底」「訪客探索度」兩段。

1. ✅ **①指定歌手保底佔比（已完成＋已 push `00afdaf`，2026-08-23）**——`recommend._apply_fav_floor`
   用 `spotify_api.fav_artist_pool()` 從點名歌手真實目錄補深軌到 `FAV_MIN_SHARE=0.5`，零幻覺。
   S4：3/15→8/15、fav_share 0.20→0.53。見「指定歌手保底」段。
2. ✅ **②訪客「熟悉/均衡/探索」fame 選項（已完成，2026-08-23，未 push）**——訪客新增「探索度」三檔。
   均衡＝改版前行為（預設）；探索才帶「至少一半 fame1-2」配額＋較嚴天花板（65）。**兩件綁一起做**
   （疑點1：只調天花板 LLM 仍不自產 fame≤2）。探索的挖法綁「知名歌手的專輯深軌」才不會幻覺暴增。
   S1 fame≤2 0.07→0.33、S3 0→0.27。見「訪客探索度」段。**下一步先 push**（跨模組、沒動
   requirements.txt→雲端記得 Reboot）。
3. **驗證幻覺補救真的在線上生效**（還沒做）：在 `soundcurator.streamlit.app` 生成一份，再到
   Manage app 日誌撈 `[NOVELTY]`，看 `repaired` 有沒有上升、`spare_used`（死連結卡）有沒有下降。
   這是 `5c70d25` 的驗收指標。（部署日誌已確認 `[GEO] 找不到 client IP`＝雲端拿不到位置，非 bug。）

**還沒做的**（依價值排序，都不急）
- **回饋持久化（登入版）**：回饋目前是 session 級，關分頁歸零；使用者已定案
  「登入版之後再做」（寫進 Spotify 歌單那招）。訪客要 localStorage（自訂元件）成本高，緩。
  ⚠️ 目前**站方端沒有任何使用者資料留存**（歌單只寫進使用者自己的 Spotify、
  回饋只在分頁記憶體、日誌是暫時性的）——要做持久化就得接資料庫，
  屆時登入頁那句「不儲存任何資料」要同步改，並補告知同意。
- **雲端的位置與天氣**：已確認 Streamlit Cloud 的代理鏈拿不到 client IP（見「位置偵測」），
  時區已改由瀏覽器提供、時間正確，但位置與天氣在雲端一律不顯示。
  要恢復得走前端（Geolocation API 或前端打 IP API），成本不低，目前判斷可以不做。
- **導流分潤**：Apple Music 已是第三播放平台，聯盟 token（`&at=`）掛在
  `apple_music_search_url()` 即可；但申請要有流量數字與自有網域，等有再說。
  ⚠️ 自家點擊追蹤**做過且證實在雲端不可行**（iframe sandbox），別再重做——
  見「播放點擊計數」段的驗屍報告。
- 歌單寫入仍是 403（需要 Spotify Quota Extension，個人開發者實際上申請不到）

**已經調查過、結論是「不要做」的**（省下重複踩坑的時間）
| 想法 | 為什麼不做 | 細節在 |
|---|---|---|
| 播放點擊中繼計數 | Streamlit Cloud 的 app iframe sandbox 沒有 `allow-top-navigation`，轉導必被平台擋成「拒絕連線」 | 「播放點擊計數」 |
| Apple Music 曲目直連 | iTunes Search API 對中文召回率極差（實測四種搜法全找不到），且 ~20 req/min 共用 IP | 「播放平台選擇」 |
| YouTube Data API | `search.list` 一次 100 units／日配額 10000，全站一天約 100 次搜尋 | 「播放平台選擇」 |
| LLM 只提歌手、曲目全由 Spotify 給 | 成本 +70 請求／批；改成「只修失敗案例」的 repair-on-miss 用一成成本拿九成效益 | 「出圈演算法」 |
| 回饋加「無感」中間選項 | 對演算法沒有可執行的指令、稀釋訊號；業界（Netflix）也已從五星收斂到二元 | — |

## 關鍵架構

### 雙模式運行
1. **訪客模式**（`is_guest_mode()`，登入頁「方式一」）：不需 Spotify 帳號、零設定，純情境推薦。
   **人數不限**——搜尋走 Client Credentials（app 層級），AI 用本站自備的 Gemini Key。
2. **Spotify 登入模式**（「方式二」）：讀取使用者聆聽資料做個人化推薦，並寫入跨 session 歷史歌單。
   （另存成新歌單的按鈕仍可能 403——見「Spotify API 限制」。）
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
- 2026-08 新增 `user-follow-read` scope（追蹤中的歌手也算「已知」）。scope 不需要在
  Dashboard 註冊，但使用者會看到新的同意項目；舊 token 缺這個 scope 時該筆抓取
  回空陣列、不影響其他資料（`_call()` 每個 job 各自 try/except）
- **訪客模式搜尋**：Client Credentials Flow（`SpotifyClientCredentials`，`_get_guest_spotify_client()`）
- **所有 token 都只存記憶體，不寫 `.cache` 檔**（2026-08 補上）
  - 使用者 token：`_get_auth_manager()` 用 `MemoryCacheHandler()`，只存 session_state
  - app 層級（client-credentials）token：一律走 `_client_credentials()`。
    ⚠️ `SpotifyClientCredentials()` **沒帶 `cache_handler` 時預設是 `CacheFileHandler()`**，
    會把 token 寫進 CWD 的 `.cache`（實測確認會產生該檔）。新增 client-credentials
    的呼叫點時務必走這個 helper，不要自己 new。
    ⚠️ 快取還要**依 client id 分開**（`_CC_CACHES`）——BYOK 使用者填的是自己的
    Client ID，共用一份快取會讓不同 app 的 token 互相污染。三條測試釘住這些行為。

#### OAuth state（防授權碼注入 / login CSRF）
沒有 `state` 時，攻擊者可以用自己的帳號授權、拿到 `?code=` 之後不讓自己的分頁載入，
再把 `https://本站/?code=攻擊者的code` 傳給受害者——受害者一點開就被靜默綁到攻擊者的
Spotify 帳號，之後生成的歌單與推薦歷史全寫進攻擊者帳號（可回頭讀取）。

⚠️ **教科書寫法「nonce 存 session_state、回來比對」在 Streamlit 上行不通**：
授權來回是整頁重新載入，session_state 會重生（實測 nonce `e2b32d96` → `909f0aa6`），
比對永遠失敗＝登入直接壞掉。

所以做成**無狀態簽章**（`spotify_api.py`）：

```
state = 時間戳.nonce.HMAC-SHA256(瀏覽器祕密, "時間戳.nonce")
```

- 「瀏覽器祕密」＝ `_browser_secret()`，取自 Streamlit 的 `_streamlit_xsrf` cookie。
  ⚠️ 這個 cookie 是 Tornado 的 `2|<mask>|<masked token>|<ts>` 格式，**每次送出都換一組
  mask**，不能直接拿字串當祕密（值會變、比對必失敗）；要解遮罩還原成底層 raw token，
  那個才穩定（實測兩次載入都是 `682ffabc…`）。有測試釘住這條。
- 驗證在 `consume_oauth_callback()` 換 token **之前**，驗不過就不換、寫入 `state_mismatch`。
- 攻擊者的 state 是用**攻擊者的**瀏覽器祕密簽的，到受害者瀏覽器就驗不過，攻擊失效。
- 產生授權網址一律走 `get_login_url()`，不要自己 `_get_auth_manager().get_authorize_url()`
  ——那樣就不會帶 state。
- 限制：cookie 取不到時 `_browser_secret()` 回空字串，兩端都空則簽章仍相符＝沒有綁定效果
  （Streamlit Cloud 預設 `enableXsrfProtection=true`，實務上都拿得到）。

#### `?error=` 一律走白名單
`?error=` 是網址參數＝完全由攻擊者控制。登入頁用 `st.warning()` 呈現，而 Streamlit 的
alert **會渲染 Markdown**（雖然不允許 HTML）——payload 裡放一個反引號就跳出 code span，
之後可插入任意 Markdown。實測確認可在官方警告框內產生 `target="_blank"` 的釣魚連結，
以及會被瀏覽器實際抓取的 `<img>`（靜默外洩受害者 IP／UA）。

因此 `_set_auth_error()` 只接受 `_ALLOWED_OAUTH_ERRORS` 內的代碼，其餘一律收斂成
`unknown_error`；`app.py` 的 `AUTH_ERROR_MESSAGES` 再把代碼查表換成**寫死的句子**。
⚠️ **不要把代碼本身插回訊息裡**，也不要把 `str(e)` 存進 `spotify_auth_error`
（例外訊息含 Spotify 回傳的內容，同樣會被回顯）。

### 濫用防護（生成節流）

本站是**公開網址**，用的是站方自備的 Gemini Key（所有人共用同一份免費配額）與同一組
Spotify Client ID（所有人共用同一份速率限制）。一次 15 首的生成 ≈ 1–2 個 Gemini 請求
+ 上百個 Spotify 請求——沒有節流的話，一個人按住生成鍵連點就能把當日配額耗光、
並讓 Spotify 回 429（`Retry-After` 實測 6 小時），**對所有使用者**。

`ratelimit.py`（純邏輯、時間由參數傳入、可直接 pytest）：
`COOLDOWN_SEC=20` 冷卻 + `DAILY_MAX=40` 滾動 24 小時窗上限。

- **桶子鍵走 `_rate_key()`**：優先用 `_browser_secret()`（XSRF cookie 的 raw token），
  它撐得過整頁重載，所以重新整理洗不掉額度（實測：重載後仍顯示「請稍候 6 秒」）。
  ⚠️ 取不到 cookie 時**不能**退回固定字串——那會把所有這類使用者算成同一個人、
  互相鎖死。改用 per-session 隨機 id（撐不過重載，但不誤傷別人）。
- ⚠️ **冷卻中不要把按鈕 `disabled`**：按鈕的文字與 disabled 都是「渲染當下」的快照，
  Streamlit 沒重跑就不會更新。實測 20 秒早就過了、畫面還停在「請稍候 6 秒」且點不動，
  使用者會以為壞掉。改成讓他點得下去，由 `consume()` 用當下時間回準確秒數——
  點擊本身就會觸發重跑。**每日上限相反**：持續 24 小時，disable 不會卡住，擋住比較清楚。
- ⚠️ **`consume()` 要在「驗完輸入之後」呼叫**：順序反過來的話，什麼都沒填就按下去
  也會被扣一次，等於用填錯把自己的額度耗光。
- ⚠️ **清空舊結果（`found` / `context_interp`）要放在確定要生成之後**，不能放在
  `if _clicked:` 開頭——否則被冷卻擋下時會順手把使用者上一份歌單清掉（實測過這個症狀）。
- **額度是逐格恢復不是到點清零**：每一次呼叫各自滿 24 小時才回來，所以釋放速率
  ＝當初的消耗速率。有測試釘住這條，很容易誤以為是「過 24 小時全部恢復」。
- **這道防線擋的是意外與隨手亂點，不是有決心的攻擊者**：清 cookie／無痕／寫腳本都能繞。
  真正擋得住的（登入驗證、WAF、IP 信譽）Streamlit Cloud 免費方案都沒有。

### 模組分層（2026-08 拆分）
```
app.py         → UI、登入/訪客流程、context helpers（定位/天氣）
recommend.py   → prompt 組裝、Gemini 呼叫（api_key 用參數傳入）、JSON 解析、去重
                 ⚠️ 不 import streamlit——pytest 可直接 import
spotify_api.py → OAuth、Spotify clients、並行搜尋、歌單寫入、跨 session 歷史
                 import streamlit 但無 module-level UI 碼，import 安全
```

### 推薦流程
1. `fetch_user_profile()`（spotify_api）— 讀 Spotify 資料（訪客模式跳過）；
   頁面載入時 `start_profile_prefetch()` 已在背景抓好——`_fetch_profile_blocking()`
   起手並行送 9 個請求（3 個 time_range × top tracks/artists、最近播放、收藏第一頁、
   追蹤歌手，`PROFILE_WORKERS=10`），再依收藏的 `total` 決定補幾頁（上限 500 首）
2. `fetch_auto_context()`（app）— IP 定位 + 天氣（`_fetch_geo_weather()` 快取 `AUTO_CONTEXT_TTL=600` 秒；時刻每次即時算）
   - 頁面載入時 `start_geo_prefetch()` 就把查詢丟到背景執行緒（`_GEO_POOL`），按下生成時通常已經好了
   - 時間一律走 `_local_now()`——**不能用 `datetime.now()`**，見下方「時區」
3. `analyze_image(api_key, ...)`（recommend）— Gemini Vision 圖片分析（選用）
4. `build_prompt()` / `build_guest_prompt()`（recommend）— 組裝 LLM prompt
5. `get_recommendations(api_key, ...)`（recommend）— 呼叫 Gemini，解析 JSON
6. `_search_tracks_parallel()`（spotify_api）— ThreadPoolExecutor 8 workers 並行呼叫 `search_track()`；token 需在主執行緒先用 `_get_search_token()` 取得（worker thread 不能碰 session_state），單首失敗以 fallback 搜尋卡呈現、不中斷整批
7. `curate_tracks()`（recommend）— 驗證鏈：去重 → 排除聽過的曲目 → 分探索/熟悉兩桶
   → 探索桶套流行度天花板 → 依「LLM 順位 + 新穎度」重排取額（見下方「出圈演算法」）
   → **指定歌手保底**：不足時用 `fav_pool` 的真實深軌補到至少一半（見「指定歌手保底」段）

### 推薦 Prompt 參數（兩個函式都有）
| 參數 | 說明 |
|---|---|
| `context` | 情境文字（地點天氣 + 使用者描述 + 圖片分析） |
| `num_songs` | 推薦歌曲數量（5–30） |
| `user_traits` | MBTI/星座/心情/活動/投射問題 |
| `languages` | 語言過濾清單（None = 不限） |
| `genres` | 曲風過濾清單（None = 不限） |
| `history` | 已推薦歌曲清單（避免重複） |
| `fav_artists` | **使用者指定歌手**（None = 不限）。prompt 讓 AI 優先推薦，但**保證在程式端**：`curate_tracks` 的 `fav_pool` 會用真實深軌補到至少一半（見「指定歌手保底」段）。`curate_tracks(fav_artists=, fav_pool=)` 兩參數配套 |
| `refill_exclude` | 補生成那一輪才有：把第一輪已經產出的 (曲名, 歌手) 傳回去，避免重複提名（兩個函式都支援，2026-08 起） |
| `feedback` | 使用者回饋 `{"liked": [...], "disliked": [...], "heard": [...]}`——讚＝相鄰探索錨點、倒讚＝避開方向、聽過＝出圈校準（`_feedback_block()`，每類最多 20 筆；排除保證在程式端，見「使用者回饋」段） |

### 出圈演算法（novelty，2026-08 Phase 1）

> ✅ **2026-08-20 線上實測有效**：重度聽眾、新藝人 100%，12 首推薦裡使用者只聽過 1 首
> （Motion Sickness — Phoebe Bridgers）。同一批有 3 首是 LLM 幻覺（曲名與歌手配錯，
> 例如把 Wolf Alice 的《Don't Delete The Kisses》掛到 Lianne La Havas），
> 已被搜尋端擋下、改附 YouTube 連結並排到清單最後。
> 這是整套演算法唯一的真實驗收數據，改動前後都該用同樣方式對照。

**要解決的問題**：登入使用者把「新藝人佔比」拉到 100%，推出來的還是自己聽過的歌。
根因是雙重流行度偏差——① 舊版「已聽過清單」只抓約 180 首，是使用者真實聽覺記憶的極小
取樣；② Gemini 本身偏向推每個曲風最有名的歌，那正是重度聽眾最可能聽過的。

**核心原則：prompt 只做機率優化，保證一律寫在程式端。**
（文獻：否定式指令有 inverse scaling、清單超過 ~50 條遵守率明顯衰退、長 context 中段
利用率最低。所以 prompt 裡只放 top 50 歌手的短清單，真正的排除靠 `curate_tracks()`。）

| 層 | 做法 |
|---|---|
| 資料 | `_fetch_profile_blocking()` 抓 3 個 time_range × top tracks/artists 各 50、收藏（先看 `total` 再決定頁數，上限 500）、追蹤歌手、最近播放 50 → 產出 `known_artist_ids` / `known_artist_names` / `known_track_keys` |
| 生成 | 雙通道 prompt（discovery / familiar 各自不同指令）+ 去錨定 + 超額 `OVERGEN_FACTOR`（1.6，上限 40）倍候選 |
| 驗證 | `curate_tracks()`：幻覺檢查 → 曲目層排除 → 歌手層排除（**所有比例**下對探索額度生效）→ 知名度天花板 → EPC 重排 → 不足時補生成一輪 |

**Prompt 設計（Phase 2）**——`build_prompt()` 的順序刻意如此，改動前先看這段：
1. **先歸納 `taste_profile` 再推薦**（de-anchoring）：不讓模型從「喜愛藝人」直接聯想同溫層大牌
2. **discovery 通道**：只從「相鄰但不同」的音樂人挑（合作者／同廠牌／影響鏈／同曲風不同國家年代），
   優先專輯曲目與 B-side、避開代表作
3. **familiar 通道**：只從喜愛藝人挑深軌、避開熱門主打
4. **`fame` 自評 1-5**＋配額「至少一半是 1 或 2」（見下）
5. **排除清單放在最後、緊鄰輸出格式**，只放 top 50 歌手
   （文獻：否定清單有 inverse scaling、清單愈長遵守率愈差、長 context 中段最容易被忽略）
6. **JSON 範本只列有配額的通道**——⚠️ 範本裡出現的鍵，LLM 就算配額是 0 也會硬生一些填進去。
   實測 `new_ratio=100` 時模型照樣填滿 `familiar`，那些候選全部白費。

**知名度 `fame`（popularity 的替代品）**
- Spotify 拿掉 popularity 後天花板沒資料可用，改請 LLM 自評 `fame` 1-5，
  用 `FAME_TO_POP = {1:10, 2:35, 3:60, 4:80, 5:95}` 換算成 0-100 餵給原本的天花板邏輯。
  `popularity` 若哪天回來會優先採用，不必改程式。
- ⚠️ **LLM 會系統性低估自己選的歌**：初版只給「5=國民金曲…1=死忠樂迷」的定義，
  實測 24 首裡 3 分×12、4 分×7、5 分×3，**從不給 1-2 分**。
  加上**可操作的錨點**（「這首在該音樂人的 Spotify 熱門排第幾」＋ Pink Moon／
  On Melancholy Hill 這種具體例子屬於 4 分）後變成 1分×2、2分×9、3分×7、4分×6。
- `stats` 的 `pop_from_spotify` / `pop_from_fame` / `pop_unknown` 三個計數要看——
  三個都是 0 代表天花板其實沒在跑。

**⚠️ 推向冷門會讓幻覺暴增（實測）**
- 加強冷門指令後，24 個候選有 15 個在 Spotify 找不到。診斷結果**不是搜尋壞掉**：
  人工確認存在的冷門曲（The Lazy Eyes《Fuzz Jam》、Priests）都搜得到；
  LLM 那些的**歌手全部真實存在，歌名是編的**（Bathe Alone《Your Dog》其實是 Soccer Mommy 的歌）。
  `resolution_matches()` 全數擋下（模糊搜尋撈回 6ix9ine《KEKE》這種東西也擋掉了）。
- 因此：① prompt 加「只推你確定存在的曲目，想不起來就換一位音樂人」
  ② `SPARE_MAX_RATIO = 0.2` 限制搜不到的補位卡比例
  ③ **補生成的觸發條件看「可播放」首數**（`len(found) - spare_used`）——
  用總數判斷的話清單看起來是滿的、補生成永遠不觸發，使用者卻拿到一堆死連結。
- ⚠️ **`resolution_matches()` 只套用在模糊 fallback，不要也套到嚴格搜尋**（有實測依據）。
  嚴格搜尋（`track:` + `artist:` 欄位限定）的結果品質夠好；套上驗證反而會誤刪正確結果——
  實測 15 首裡唯一「通不過驗證」的是「風になる / つじあやの」被解析成
  「風になる / Tsuji Ayano」，**同一首歌同一位歌手**，只是日文名 vs 羅馬拼音。
  `_loose_match()` 以詞為單位比對，跨文字系統（日文/韓文 vs 羅馬拼音）本來就沒有共同詞。
  這個盲點在 fallback 路徑會讓正確曲目被丟掉變成搜尋連結卡——代價是少一首可播的歌，
  不是推錯歌，目前接受。要修的話得做音譯，成本高。
- **解析率實測**（配額正常時，訪客模式一般推薦）：15 首中 14–15 首解析成功、耗時 5 秒。
  對照組：登入模式加強冷門指令後只有約 40%——差距全部來自幻覺，不是搜尋能力。
- **✅ 幻覺補救（repair-on-miss，2026-08-21）**：幻覺的模式是「歌手真實、歌名是編的」
  ＝方向對、細節錯，所以**只修失敗案例**就夠，不必整條管線改成「LLM 只提歌手」。
  搜不到的候選走 `spotify_api.repair_hallucinated_track()`：搜歌手（驗證名稱對得上
  才收，補到別的歌手比不補糟糕得多）→ `artist_albums`（跳過合輯，全空才退收單曲）
  → 一張專輯的曲目 → 避開第 1 軌、從中段挑一首沒出現過的深軌替換，
  `reason` 沿用（橋接句本來就是歌手層級）、標 `_repaired`。
  成本每位歌手 3–4 個請求、每批上限 `REPAIR_MAX_PER_BATCH=5`；
  目錄跨使用者快取（`_REPAIR_CACHE`，不設 TTL，「找不到」也快取），
  撞 429 立即停止整批補救。`[NOVELTY]` log 的 `repaired`/`repair_cache` 是驗收指標
  （repaired 上升＋spare_used 下降＝在生效）。
  ⚠️ **`artist_albums` 的 limit 上限實測只剩 10**（2026-08：20 與 50 都回 400
  「Invalid limit」，文件沒跟上）；`album_tracks` 給 20 沒問題。

- **歌手比對以 Spotify artist ID 為主**、名稱為輔——名稱變體（IU / 아이유）用 ID 才不會漏。
- **曲目比對用 `_track_key()` =（正規化歌名, 正規化主要藝人）配對**。舊版只比歌名，
  害得「別人的同名歌」被誤殺、而 `Song (Remastered 2011)` 這種變體又漏掉。
  `_norm_title()` 去掉括號、`- Live`／`- Remastered` 等版本後綴與 `feat.`；
  ⚠️ dash 後綴只有含版本關鍵字才砍，否則 `Song - Part 2` 會被誤當成 `Song`。
- ⚠️ **有 Spotify 的 artists 陣列時一律用 `_track_key_from()`**（取 `artist_names[0]`）；
  `_track_key()` 切逗號，對「Earth, Wind & Fire」「Tyler, The Creator」這種團名會切錯。
  歷史紀錄存的是逗號串接字串，所以歷史比對走 `_history_keys()`——**兩種切法都放進 set**，
  否則這些歌手的歷史去重會完全失效（已推薦過的歌照樣再推一次）。
- **流行度天花板**是「熟悉度暈輪」的程式化：沒紀錄不代表沒聽過，太紅的歌就當作聽過。
  `POP_CEILING_DISCOVERY=65`、`POP_CEILING_STRICT=55`（ratio 100 時）。
  ⚠️ **放寬必須有絕對上限**（`POP_CEILING_MAX_RELAX=80`，100% 模式只放寬到 65）——
  沒有上限的話，湊不滿時會一路放寬到 85，把天花板剛擋掉的大熱門整批放回來＝等於沒有天花板。
  湊不滿寧可少幾首，並在結果頁用 `novelty_notice` 誠實說明，不要默默縮水。
- **`new_ratio == 100` 不向熟悉桶借額**：使用者明確要「完全沒聽過的藝人」，
  少幾首也不能塞熟悉藝人——那正是這次改版要解決的問題。
- 搜不到的候選（`_no_spotify`）降級為補位，只有湊不滿時才用。
- `search_track()` 的模糊 fallback 會用 `resolution_matches()` 驗證，
  搜到「同一位藝人的另一首熱門歌」直接視為找不到——照收就等於推了一首八成聽過的歌。
- 量測：每次生成印一行 `[NOVELTY] {...} known={...}` 到 stderr
  （新歌手數、平均知名度、各關卡刷掉幾首、訊號來源、profile 抓取失敗次數）。
- ⚠️ **提示訊息一律寫進 `st.session_state["novelty_notice"]`（list[str]）**：
  生成流程跑在 `st.status` 容器裡，結尾的 `st.rerun()` 會把容器內容清掉，
  直接 `st.warning()` 使用者根本看不到。而且訊息要在**補生成迴圈之後**才組裝——
  限流可能是補生成那一輪才撞到的，在迴圈前組的話那種情況會一則都不出現。
- ⚠️ **提示的渲染要放在 `if st.session_state.found:` 之外**：過濾太嚴導致一首都不剩時，
  原因說明剛好也跟著消失，畫面變成什麼都沒發生——那正是最需要解釋的情況。
  `found` 為空時另外出一則 `st.warning`。
- 湊不滿時的訊息要列**五個**原因（推薦過的／聽過的曲目／熟悉歌手用不上／太熱門被擋／
  搜不到），少列任何一個都可能出現「擋掉了 0 首…0 首」這種自相矛盾的訊息。
  建議文案也要對得上主因——歷史佔比高時要說「清除推薦歷史」，不是「調低新藝人佔比」。

**呈現層（Phase 3）**
- `curate_tracks()` 會在每首歌上標 `_discovery`（來自沒接觸過的音樂人）。
  `styles._discovery_badge_html()` 據此畫「🧭 出圈」標籤：卡片版**浮貼在封面左上角**
  （`position:absolute`，不佔垂直空間——多一列會讓等高卡片的 ▶ Spotify 按鈕跑掉），
  列表版是行內 pill。標籤色固定 `#00D4AA`／`#2D1B4E`（9.6:1），
  **不跟著 `_ACCENT_COLORS` 輪替**——它是語意標記，顏色一變就沒有辨識度。
  ⚠️ **標籤寬度固定但卡片會隨每列首數變窄**：每列 10 首時封面只有 58px、完整標籤 54px，
  量到會超出封面邊界並蓋掉 35% 專輯圖。所以 `compact_badge=not show_album`
  （沿用密集網格拿掉專輯名/理由的同一條界線）縮成只有圖示，意思靠 `title` 補回來。
  量測值：卡片 84/154/190px → 標籤佔專輯圖 17%/7%/4%，三者都在封面內。
  列表模式的行內標籤在手機（375px）量過：理由那行本來就會換成兩行，加標籤只多 2px
  （列高 89 → 91），不會多擠出一行，所以不需要 compact 版本。
  控制列的三欄在手機會各自堆疊成整寬（343px），無水平溢出。
- 結果頁的 `st.caption` 顯示「幾首出圈／平均知名度／擋掉幾首」，資料來自
  `st.session_state["novelty_stats"]`（要撐過結尾的 `st.rerun()` 才存進 session_state）。
  這行同時是給使用者的透明度與開發者的驗收儀表板。
- discovery 的 `reason` 在 prompt 裡要求寫成「橋接句」（點出與使用者已聽音樂的關聯）。

**訪客模式**（`profile is None` → `_basic_dedupe()`）不走登入版驗證鏈，
但 2026-08 已把四件事對齊到同一套設計原則：
① prompt 歷史同樣只放最近 `PROMPT_HISTORY_MAX=40` 筆（原本塞到 200，違反自家
「清單超過 ~50 條遵守率衰退」原則；完整排除照舊靠程式端拿**整份**歷史比對）；
② 超額生成 `GUEST_OVERGEN_FACTOR=1.25`（下限 num_songs+2、上限 40）；
③ `_basic_dedupe` 把搜不到的（`_no_spotify`）穩定排序到最後，且排序在截斷**之前**
——超額餘裕優先留給可播放的曲目；刷掉的首數計進 stats
（`dup_history` / `dup_batch` / `artist_capped`），湊不滿時 app.py 拿它組說明訊息
（訪客分支，建議固定指向「清除推薦歷史」）；
④ 補生成對訪客也生效（`build_guest_prompt` 支援 `refill_exclude`，指令是「換別的」
而非登入版的「往更冷門挑」）；
⑤ **訪客 fame 天花板（2026-08-21 起，2026-08-23 改成三檔可調）**：guest prompt 要求 fame 自評，
天花板與「是否套配額」現在由使用者選的**探索度**決定（見「訪客探索度」段）——**均衡＝
`GUEST_POP_CEILING=80`＋不套配額，就是這裡描述的改版前行為**（預設）；熟悉不擋；探索降到 65
＋套「至少一半 1-2」配額。以下描述的是均衡檔：`_basic_dedupe(fame_ceiling=80)` 兩段式，
只擋 fame 5（≈95）的國民金曲層級、fame 4（=80）貼線通過；**超標只降權不刪除**——排序優先序是
「不超標 → 太紅 → 搜不到」，湊不滿時超標的照樣回補，數量永不縮水
（均衡檔沒有「想探索」的意圖訊號，硬擋會毀掉「想聽經典金曲」那種請求；探索檔才是意圖訊號）。
被截掉的超標首數計進 `stats["pop_blocked"]`。
去重鍵沿用括號剝除的正規化，同藝人的 `Interlude (I)` / `Interlude (II)` 視為同一首。

### 指定歌手保底（fav floor，2026-08-23，第 2 輪第 1 項）

> ✅ **S4 實測有效**：指定歌手佔比 **3/15 → 8/15**、`fav_share` **0.20 → 0.53**，達到承諾線
> 且 15/15 全可播、零死連結卡。前後數字在 `EVAL.md` 第 2 輪節。

**要解決的問題**：使用者在「指定歌手」欄點名歌手，prompt 承諾「至少一半來自這裡」，但 LLM
實測只遵守 0.2；更糟的是同藝人上限 `MAX_TRACKS_PER_ARTIST=2` 把兩位歌手硬卡在 4 首。
＝使用者最想點開的就是指定歌手，供給卻嚴重不足（S4 想點開 4 首全是指定歌手、供給只有 3）。

**核心原則同「出圈演算法」：prompt 只做機率優化，保證寫在程式端。**
`recommend._apply_fav_floor()`（純函式、兩種模式共用，在 `curate_tracks` 最後一關）：
- 目標＝清單至少 `FAV_MIN_SHARE=0.5` 來自點名歌手（刻意對齊 prompt 的「至少一半」）。
- 不夠時用 `spotify_api.fav_artist_pool()`（重用幻覺補救的 `_artist_catalog`，跨使用者快取）
  從點名歌手的**真實專輯目錄**拉深軌補上——**零幻覺**（曲目來自 Spotify 目錄，不是 LLM 生的）。
- **對點名歌手放寬同藝人上限**（`per_cap = max(2, ⌈floor/人數⌉)`）——使用者明確點名＝想多聽幾首。
- **各點名歌手之間平均分配**（round-robin，先補目前較少的那位），不讓其中一位吃掉整個保底額。
- 有空位時（清單湊不滿）順便用真實深軌把清單補長，解一部分「湊不滿」；會超過 target 才置換，
  且**優先砍搜不到的墊底卡與非指定歌手的低順位曲目**，不砍可播的指定歌手曲目。
- 補進來的卡標 `_fav_pick=True`（UI／出圈計數用）＋沿用 pool 的 `_fav_artist` 標籤；`_discovery`
  一律 False（明確點名 ≠ 出圈）。stats 記 `fav_floor` / `fav_have` / `fav_added`。

**app.py 的接法（兩段式，省 API）**：先照常 `_curate`（`fav_pool=None`，只算出 `fav_have`/`fav_floor`），
只有 `fav_have < fav_floor` 時才去 `fav_artist_pool()` 抓 pool、再 `_curate` 一次帶 pool。撞 429 跳過。

**⚠️ CJK 藝名解析（zh-TW app 的常見坑，不是邊緣案例）**：`陳綺貞` 在 Spotify 存成 "Cheer Chen"，
`_artist_catalog` 的嚴格名稱比對跨文字系統對不上 → 那位歌手一首都補不到。修法：`fav_artist_pool`
走 `_artist_catalog(..., allow_top_result=True)`——**使用者親手打的藝名，搜尋第一筆幾乎必然是本尊**。
⚠️ **只給保底用**：幻覺補救維持嚴格比對（`allow_top_result=False`），LLM 給的歌手名不可信，
退而取第一筆會補到別人、比不補更糟。兩種模式的目錄結果**分開快取**（cache key 加 `\x00top`）避免互相污染。

**CJK id 比對（① 最小版，2026-08-23 已做）**：被搜尋端解析成羅馬拼音的 LLM 指定歌手卡
（Cheer Chen，沒有 `_fav_artist` 標籤）名字比不出 → 舊版 `fav_have` 會低估、可能 overshoot。
`_apply_fav_floor` 現在**從 pool 卡免費收集每位指定歌手的 Spotify artist id**（pool 卡主藝人
id[0] ＝ 該歌手 id），`_track_matches_fav` 多一條 id 比對（優先於名字）→ **帶 pool 的第二輪
`fav_have` 準確、不再 overshoot**，零額外 API。**殘留**：第一輪（`fav_pool=None`）沒有 id、
仍靠名字比對，所以 app 端「要不要抓 pool」的判斷偶爾仍被低估觸發、多抓一次——但 pool 跨使用者
快取、成本近零，接受。要連第一輪也修得多一個 `resolve_fav_artist_ids` 輕量搜尋（②完整版，未做）。

**測試**：`test_recommend.py` 的「指定歌手保底」段（10 條）＋ `test_spotify_api.py` 的 `fav_artist_pool`
段（含 CJK top-result、嚴格補救不 fallback）。無 fav_artists 時 `_apply_fav_floor` 原樣返回，
其他情境零行為變動（有測試釘住），所以第 2 輪只需重跑 S4。

### 訪客探索度（fame_mode：熟悉/均衡/探索，2026-08-23，第 2 輪第 2 項）

> ✅ **驗收有效**：探索模式讓 LLM 自產 fame≤2 大增（S1 華語 0.07→0.33、S3 健身 0→0.27），
> 均衡＝改版前行為零變動。前後數字在 `EVAL.md` 第 2 輪第 2 節。

**要解決的問題（EVAL 第 1 輪疑點 1）**：訪客的 fame 天花板（`GUEST_POP_CEILING=80`）形同虛設——
LLM 幾乎不自產 fame≤2，`fame_low_share` 普遍是 0，S1 華語甚至五首 fame5 國民金曲全數入列。
訪客沒有聆聽紀錄可比對，「太紅」是唯一的驚喜度訊號，但沒有工具讓使用者調、LLM 也不配合。

**做法**：訪客表單新增「探索度」三檔（`app.py` 的 `_GUEST_FAME_LABELS`，radio）→ `fame_mode`：

| 模式 | 天花板（`GUEST_CEILING_BY_MODE`） | guest prompt fame 錨點（`_GUEST_FAME_PUSH`） |
|---|---|---|
| 熟悉 familiar | None（不擋，要「聽得出來」的歌） | 以樂迷熟悉曲目（fame 3-4）為主體 |
| **均衡 balanced（預設）** | 80（只壓 fame 5，＝改版前） | 混一部分 2-3 分（＝改版前，逐字不動保跨輪可比）|
| 探索 discovery | 65（擋 fame 4-5，＝登入版 discovery） | **「至少一半 fame 1-2」配額＋具體挖法** |

**⚠️ 兩件必須綁一起做（疑點 1 的核心）**：只調天花板、prompt 不改的話，LLM 不自產 fame≤2 →
探索模式湊不滿 → 天花板兩段式不縮量 → 大熱門回補 → 空轉。所以探索同時降天花板**且**在
prompt 下配額。`fame_mode` 一路從 `app.py`→`get_recommendations`→`build_guest_prompt`（錨點）
＋`curate_tracks`（天花板）；登入模式走 new_ratio，傳了也不生效。

**⚠️ 探索 prompt 的「挖法」教訓（三版迭代，都有 eval 數字）**：
- 只給抽象「往深挖」→ fame≤2 幾乎不動（LLM 挑「稍微不那麼紅」的 fame 3 安全牌）。
- 加「換不同國家/年代/廠牌、較小眾的名字」→ fame≤2 衝高，但**華語死卡暴增**（推向小眾→
  幻覺/搜不到暴增，CLAUDE 早有此警告）。**小眾藝人是危險槓桿。**
- **採用版＝把挖法綁在「你確定有名氣的音樂人的專輯曲/B-side」**（＝登入版 familiar channel 的
  安全版，不是 discovery channel 的小眾版）：fame≤2 大幅上升、非華語情境零死卡。
  **安全槓桿是「知名歌手的深軌」，不是「小眾歌手」。**

**已知限制**：華語專輯深軌的 Spotify 搜尋召回本來就差，探索疊加後死卡會多幾張（eval S1 探索
4 死卡）——**既有限制、非本項引入**，且 eval 不做補生成＝最壞情況；app 端有補生成＋幻覺補救＋
墊底卡上限＋「湊不滿」說明吸收。使用者主動選探索，「更冷門、偶爾附搜尋連結」在預期內。

**測試**：`test_recommend.py` 的「訪客探索度」段（8 條）——三模式的天花板差異、探索有配額/
熟悉沒有、**預設＝balanced 且逐字不變**、未知模式退回 balanced。改任何一檔的文案先跑
`eval_bench.py --mode <檔> --only S1 S3` 對照（S1 華語是最容易踩幻覺的照妖鏡）。

### 歷史去重
- 三個上限別搞混：`HISTORY_KEEP=200`（session 內保留幾筆）、
  `PROMPT_HISTORY_MAX=40`（其中真正寫進 prompt 的筆數，清單愈長 LLM 遵守率愈差）、
  `PERSISTENT_HISTORY_MAX=500`（Spotify 歷史歌單保留上限）。
  **完整的排除靠程式端 `curate_tracks()`，prompt 只是機率優化。**
- **Session 內**：`st.session_state["recommend_history"]`
- **跨 Session**（僅登入模式）：寫入 Spotify 私人歌單
  `🤖 AI Discovery History (請勿手動刪除)`（完整字串在 `HISTORY_PLAYLIST_NAME`，
  歌單是靠**名稱**找回來的，改字串等於讓所有現存使用者的歷史失聯）
- 訪客模式只有 session 內歷史
- 歷史歌單上限 `PERSISTENT_HISTORY_MAX=500` 首，超過時 `_trim_persistent_history()` 自動修剪最舊的
- 清空/修剪都用 `_playlist_replace_items()`：`PUT /playlists/{id}/items` 整批取代（失敗 fallback 舊 `/tracks` 路徑）

## UI 主題系統（Y2K / Retro Pop）

### styles.py 結構
- **CSS**：`_build_global_css()` — 在 f-string 內，所有 CSS `{}` 須寫成 `{{}}` 否則 Python SyntaxError
- **SVG 常數**（9 個）：裝飾用 `SVG_CASSETTE`, `SVG_VINYL`, `SVG_NOTES`, `SVG_BOOMBOX`,
  `SVG_SPARKLE`；圖示系統用 `SVG_CLIPBOARD`（複製歌單）、`SVG_QUESTION`（投射問題）、
  `SVG_CHAT`（情境輸入標題）、`SVG_LOCK`（隱私徽章）——後四個見「圖示系統」段
  - 改 SVG 後要驗證「同色的形狀是不是連在一起」：把 SVG 序列化成 data URL → 畫進 canvas →
    `getImageData()` 後對每個顏色做連通分量分析。舊版 `SVG_NOTES` 的綠色是**兩塊**
    （符桁 rect 的下緣 y=9.5、左符桿頂端 y=10，差 0.5px 就斷開），修好後是一塊。
  - 兩根符桿頂端高度不同時，符桁不能用 `<rect>`，要用斜的平行四邊形 `<path>` 才蓋得住。
  - 符桿要「收進」符頭裡：桿底兩角必須落在旋轉橢圓內，否則會從符頭右下角凸出來。
    檢查法（旋轉 −20°、rx 7.5 / ry 5.5）：把點反旋轉回未旋轉座標算 `(x/rx)²+(y/ry)²`，
    <1 才算在裡面。右緣距圓心 8.4 時算出 1.64（凸出），移到 6.0 後是 0.70。
  - 尖角（符尾尖端）兩條曲線收在同一點時，抗鋸齒會留下孤立像素——連通分量檢查會顯示
    「1 大塊 + 2px」。把尖端改成小圓頭即可，480px 與 80px 兩種尺寸都要測。
- **HTML helpers**：
  - `inject_global_css()` — app.py 頂部呼叫，注入全域 CSS
  - `login_hero_html()` — 登入頁頂部 Hero 區（圖示 + 漸層標題）
  - `form_hero_html()` — 主表單頁 Hero（放大漸層標題「想成為你專屬的歌單」左對齊＋小圖示漂浮裝飾）
    ⚠️ Streamlit 自己的 `.stMarkdown h2` 是 2.25rem，單一 class 選擇器蓋不過去——
    字級規則要寫成 `h2.y2k-form-title { font-size: … !important }`
  - `login_spotify_card()` / `login_guest_card()` — 登入方式卡片
  - `byok_spotify_steps_head_html()` / `byok_spotify_steps_tail_html()` —
    自建 Spotify App 的視覺引導步驟卡，**刻意拆成上下兩半**（Gemini 版已移除）。
    `app.py` 在兩半中間夾一個原生的 `st.code(redirect_uri)`。
    - **為什麼拆**：原本卡片裡那顆自製的「📋 複製」按鈕**根本是死的**——Streamlit 的
      markdown（rehype-raw → React）會把 `onclick` 這類事件處理器整個濾掉
      （實測整頁 0 個元素帶 onclick），按鈕有 `cursor:pointer`、看起來可點卻毫無反應。
      `st.code()` 的複製鈕是真的 React handler。
    - **順帶消滅注入面**：`redirect_uri` 從此**完全不經過 `unsafe_allow_html`**，
      兩個 helper 都不收參數。⚠️ 別為了方便又把網址塞回 HTML——
      `html.escape()` 只擋得住 HTML 屬性情境，JS 字串情境（`onclick` 內）下
      `&#x27;` 會被實體解碼還原成單引號、照樣跳脫。五條測試釘住這些。
    - **接縫**（`.st-key-byok_steps` / `.st-key-byok_uri`，CSS 在 `_build_global_css()`）：
      上半無下框線＋只有上圓角、中段補左右框線、下半無上框線＋只有下圓角；
      陰影也要拆（上半與中段 `4px 0`、下半 `4px 4px`），否則接縫處會有兩道重疊投影。
      ⚠️ **兩條 CSS 要成對出現**：① `gap:0` 必須下在 `.st-key-byok_steps` **自己**身上
      （它本身就是那個 `stVerticalBlock`，寫成後代選擇器選不到自己）
      ② 同時歸零 `stMarkdownContainer` 的 `-16px` 負邊界，否則 `gap:0` 會讓它變成重疊。
      修好前量到 head→mid 0（**碰巧**被負邊界抵銷）/ mid→tail 16；
      修好後桌機 1280px 與手機 375px 兩處都是 0，左右邊緣完全對齊。
      長網址（69 字元也試過）在 `pre` 內部橫向捲動，頁面本身不會橫向溢出。
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

### 圖示系統：兩層制（2026-08-21，取代全站 emoji）
設計稿（Claude Design 畫布）：https://claude.ai/code/artifact/d2fc1112-59da-4c0b-8fd7-e63461e53725
- **A 層＝自繪貼紙 SVG**（我們自己輸出 HTML 的區塊）：糖果填色＋深紫描邊，與卡帶／
  黑膠同一家。`SVG_CLIPBOARD`（複製歌單標題，走 `section_header_html(icon="clipboard")`）、
  `SVG_QUESTION`（投射問題統一圖示，`projective_question_html()`；**30 題的題目
  文字已不帶 emoji**）。新增 SVG 照「SVG 常數」那節的連通分量品管；
  **描邊要用「輪廓層＋填色層」的聯集畫法**——兩個形狀各自描邊，銜接處會露出
  互相穿過的接縫（音符的符頭×符桿實測踩過，修法見設計稿）。
- **B 層＝Material Symbols Rounded**（原生元件塞不進 SVG，只吃 `:material/xxx:`）：
  回饋 pills（thumb_up／thumb_down／headphones，對照表在 app.py 的
  `_FB_STATE_BY_LABEL`）、生成按鈕（auto_awesome；額度用完 hourglass_top）、
  四個 expander（tune／music_note／mood／psychology，`icon=` 參數）、換一題（refresh）。
- ⚠️ **Material 圖示 span 有三種變體，排除清單缺一不可**（三種都實測踩過，
  有測試釘住）：① pills／按鈕＝`stIconMaterial` ② expander＝`stExpanderIcon`
  ③ **markdown 行內**（caption／widget 標籤／`###` 標題裡的 `:material/xxx:`）＝
  無 class、無 testid，只有 `translate="no"` 屬性可以認。全域 span 的 Nunito
  `!important` 規則靠 `:not()` 清單排除它們——漏掉哪種，那種圖示就連字失效、
  顯示成文字「music_note」。圖示另設 `line-height:1`（繼承 1.6 會把字圖抬離盒中心）。
- **2026-08-21 全站清掃**：登入頁（直接開始 play_arrow／Spotify 登入 headphones／
  🔒→lock／🔧→build×2／✅→check_circle）、sidebar（music_note／account_circle／
  swap_horiz／logout）、歷史提示 🧠→history、額度 🚦→traffic、清除×2 delete、
  指定歌手 🎤→mic、加入 Spotify playlist_add、📖→menu_book、提示框 icon 🔭→explore、
  🫥→search_off。styles 端：💭→紫色火花、封面佔位 🎵→`SVG_NOTES`、💿→迷你黑膠
  `_mini_vinyl()`、理由標籤的 💡 移除、BYOK 步驟去 emoji（數字圈就是視覺錨）、
  隱私徽章 🔒→新資產 `SVG_LOCK`（鎖環用線條版聯集畫法）。
  **刻意保留的 emoji**：🧭 出圈標籤（語意標記，見「呈現層」）、警示訊息的 ⚠️ 前綴與 toast、
  複製歌單分享文字開頭的 🎵（那是複製進剪貼簿的**純文字**，`:material/` 不會被解析成圖示）、
  `page_icon` 的 🎵（瀏覽器分頁圖示，只吃 emoji／圖檔）。
  ⚠️ **生成過程的 st.status 敘事行原本也刻意留 emoji，2026-08-22 已全部改成 Material 行內圖示**
  （🔗→sync／✅→check_circle／🌍→my_location／📍→location_on／🖼️→image／🎨→palette／
  💬→chat_bubble／🤖→auto_awesome／🔍→search／🔁→refresh／🎶→person_off／⏳→hourglass_top，
  在 `app.py` 生成 handler 的 `st.status` 容器內）——使用者要求全站一致。**別再改回 emoji。**
  只有那三行 ⚠️ 警示（連線重試／未設 Spotify API／補生成失敗）照全站警示慣例留著。
- **行內圖示（markdown 的 `:material/xxx:`）與後面文字間距**：Streamlit 不給間距
  （實測 gap=0、緊貼），用 `span[translate="no"]:not([data-testid="stIconMaterial"]):not([data-testid="stExpanderIcon"])`
  補 `margin-right:0.4em`（生成敘事行／隱私／歷史／額度 caption 都受惠；那兩個 `:not()`
  一定要在，否則會誤加到按鈕與 expander 圖示、多推一截）。上下置中實測本來就 OK（偏差 0.7px→補 margin 後量到 0）。
- expander 圖示的染色 CSS 綁 key（`.st-key-exp_music …`），改 key 名要同步改。
- 量測：Material 版 pills 寬 133px（emoji 版 134）、等高網格、手機 375px 皆不受影響。

### .streamlit/config.toml
```toml
[theme]
primaryColor = "#FF69B4"
backgroundColor = "#FFFDF7"
secondaryBackgroundColor = "#FFF0F5"
textColor = "#2D1B4E"

[client]
toolbarMode = "minimal"   # 縮小頂部工具列，移除裝飾線

[server]
maxUploadSize = 10        # 不設的話上傳區會顯示預設「200MB per file」，與程式碼實際擋的 10 MB 不符
```
> ⚠️ 這個檔案已加入 git，會被 Streamlit Cloud 讀取。

### Streamlit 頂部裝飾線隱藏
在 `_build_global_css()` 中以 CSS 隱藏，涵蓋多版本 selector：
```css
[data-testid="stDecoration"], [data-testid="stDecorationLine"], ...
[data-testid="stHeader"], header { display: none !important; ... }
```
若 Streamlit 升版後裝飾線復現，需檢查新版的 `data-testid` 屬性名稱。

### 版面幾何：改動前務必先量，不要憑感覺調

這個專案的 UI 微調幾乎都是「看起來怪 → 量出真正原因 → 改一個數字」。歷史上踩過的坑：

| 症狀 | 真正原因 | 量法 |
|---|---|---|
| 置中標題換行後偏左 12px | Streamlit 在標題尾端插 `stHeaderActionElements` 錨點（inline-flex 佔行內寬） | `range.getClientRects()` 逐行比對 center |
| 摺疊區內容貼住下框線 | `stMarkdownContainer` 帶 `-16px` 負邊界抵銷了 padding | 往上追祖先的 `marginBottom` |
| 拖滑桿面板自己關起來 | expander 沒有 `key`，標題文字一變就被當新元件重建 | 改值後看 `details.open` |
| 兩欄輸入框沒對齊 | 上傳區有自己的 `padding` + 邊框把右欄推低 | 比對兩個 box 的 `top`/`bottom` |
| 黃底標籤看不到字 | 白字壓 `#FFD700` 對比只有 1.4:1 | 用 WCAG 公式算 relative luminance |
| 投射列題目與按鈕差 8px | 題目從 `<p>` 改成 `<div>` 後，沒有 p 的 16px 下邊距去抵銷 `stMarkdownContainer` 的 -16px 負邊界 | 量氣泡/文字/按鈕三者 centerY（修後 149/149/149） |
| 氣泡圖示浮在兩行中間 | 文字折行後 flex 的 `align-items:center` 對齊的是整個兩行文字塊，不是第一行 | 改 `flex-start`（26px 圖示天然對齊 25.6px 行框），量 icon vs 第一行墨水 centerY（13px → 1.1px） |
| 「AI 情境解讀」火花圖示浮在文字上方 ~1.5px | flex `align-items:center` 對齊的是盒子；SVG 在 24px 盒內置中，但文字 `line-height:1` 的墨水中心與盒中心不同，淨值火花中心低 1.53px | 探針量 SVG `path` vs 文字 `range` 的 centerY；wrapper 加 `transform:translateY(-1.5px)`，殘差 0.03px |
| 「AI 情境解讀」框下方（→🧭 caption）間距比別處小 | 框內 `margin:0.8rem 0`(12.8px) 少於 `stMarkdownContainer` -16px 要抵銷的段落 16px，淨間距被壓成 12.8 而非全站的 16 | 量主區塊各相鄰元素 gap 全是 16px（連 caption 兩側）；框下邊距補成 `1rem` 即回 16 |
| 黑膠當「Sound 的 o」偏高 ~1.9px | inline-block 預設 baseline 對齊，黑膠盒中心比小寫 o 的墨水中心高 | 量 svg vs「und」range 的 centerY，`translateY(0.075em)` 後殘差 0.5px（改字級要重量） |
| 登入 hero（Option C）比表單 hero 矮 41px | Option C 拿掉圖示列只剩 wordmark＋tagline；且登入 hero 的 `stMarkdownContainer` -16px 沒歸零，block 被縮成 101 | 量兩邊 stMarkdown block（登入 75.5 vs 表單 116.8）；`min-height:117`＋flex 置中＋`:has(.y2k-login-hero)` 歸零 -16 → block 117≈116.8 |

**做法**：`streamlit run app.py --server.headless true --server.port 8599`
起服務後用瀏覽器工具跑 `getBoundingClientRect()` / `getComputedStyle()` 量，
改完再量一次確認數字真的變了——目測分不出 1px 和 12px 的差別。

### 視覺層級（2026-08 手機版改版）
- **粗框（3px）+ 彩色陰影只留給主要 CTA**（`stBaseButton-primary`、`stLinkButton`）。
  其餘元件（expander / 輸入框 / 上傳區 / secondary 按鈕 / status）一律 `2px rgba(45,27,78,0.28)`、無陰影。
- ⚠️ 按鈕的 `border-radius/font/border` 是 `.stButton > button, stBaseButton-primary, stBaseButton-secondary`
  **三個 selector 共用**的規則——只想改次要按鈕時要改後面的 secondary 專屬區塊，別動共用規則。
- **所有彩色左邊框已移除**（登入卡片、AI 情境解讀、BYOK 步驟卡、stAlert、expander）。
- **手機覆寫放在 `_build_global_css()` 最後**：同特異性下後定義者勝，放前面會被桌機規則蓋掉。
- 曲目卡的理由標籤文字色走 `_ACCENT_TEXT_COLORS`（亮底配深紫、深底配白）——
  白字壓黃底只有 1.4:1，改後最差 4.67:1，四色全數通過 WCAG AA。
- 登入卡片 `_method_card_html()`：`display:flex;flex-direction:column;justify-content:center`
  讓內容在 `min-height:130px` 內垂直置中。標題單行——舊的 `y2k-mbr` 手機強制斷行
  機制已移除（2026-08-22）：那是標題還帶「（推薦，免登入）」時防硬斷用的，
  縮短後手機 375px 實測單行 29px 放得下。
- **登入 hero 與表單 hero 的「圖示→標題」間距一致**（使用者指定以表單版為準）：
  對齊的是「圖示墨水底 → 文字頂」的視覺間距（兩邊皆 13px），不是 CSS 數字——
  兩組 SVG 在 viewBox 裡的留白不同，登入版 margin-bottom=17px 是量測校準值。
  ⚠️ 自繪 HTML 的標題**一定要寫 `padding:0`**：Streamlit 的 `.stMarkdown h1/h2`
  預設帶 padding，不歸零標題上方會多墊一截。
- **垂直間距走三級制（8 / 16 / 32）**，`.y2k-gap` 空 div 已移除。
  過去混用三套機制（Streamlit 垂直區塊的 flex `gap:1rem`、`.y2k-gap` 空 div、
  `stMarkdownContainer` 的 -16px 負邊界），相加後手機上量到 16/20/26/32/41/49 六種間距。
  現在只留 flex gap 16px 當基準（＝並列欄位），另外兩級用 widget 的 **key class** 加減：

  | 級距 | 用途 | 作法 |
  |---|---|---|
  | 8px | 組內（標題 → 輸入框、題目 → 回答框） | `.st-key-text_ctx` 等 `margin-top:-8px` |
  | 16px | 並列欄位、expander 之間 | 不動，就是 flex gap |
  | 32px（手機）/ 24px（桌機） | 區塊之間 | `.st-key-auto_ctx`/`proj_row`/`exp_songs`/`btn_generate` 加 `margin-top` |

  ⚠️ **CSS 裡的數字是「在 16px 之上再加減多少」，不是最終間距**（手機寫 16 → 實際 32）。
  ⚠️ 這些選擇器都綁在 `app.py` 的 `key=` 上，改 key 名要一起改 CSS。
  ⚠️ hero 的 `stMarkdownContainer` 帶 -16px 負邊界，會把下面第一個元件吸上來，
  已用 `[data-testid="stMarkdownContainer"]:has(.y2k-form-title)` 歸零。
  手機量到：32 / 8 / 8 / 16 / 32 / 8 / 24 / 32 / 16 / 16；桌機：24 / 8 / 8 / 24 / 8 / 24 / 24 / 16。

### 重要限制
- **強制亮色模式**，不支援暗色主題
- 標題內的文字必須緊貼標籤（`<h1 ...>文字</h1>`），換行縮排會產生尾隨空白讓置中偏移
- 注入自訂 HTML 的 `stMarkdownContainer` 帶 `-16px` 負邊界（Streamlit 用來抵銷段落 margin），
  若它是 expander 的最後一個元素，內容會被拉去貼住下框線——已用 `:last-of-type` 規則歸零
- `[data-testid="stHeaderActionElements"]`（Streamlit 標題錨點圖示）已用 CSS 隱藏——它是 inline-flex，
  會佔行內寬度、把置中標題推偏（手機上 h1 換行時特別明顯）
- **注入的 HTML 不能有縮排**：Streamlit 的 markdown 會把「縮排 4 個空白」的行當成程式碼區塊。
  條件式片段（如沒有專輯時的 `album_html`）算出來是空字串時那一行只剩空白＝空行，
  後面縮排的 `<div>` 就會被當 code block 印出原始碼（症狀：曲目卡的理由標籤變成一段程式碼）。
  `track_card_html()` 的輸出走 `_tidy()` 去掉行首縮排與空行；新增有條件式插值的 HTML helper 時照做。
- 修改樣式只改 `styles.py` + `config.toml`，不要在 `app.py` 混入 CSS
- `_method_card_html()` 使用 `min-height:130px`（非 `height`），讓手機上文字換行後能撐高，不截字

## 驗收流程（2026-08 起）

> 演算法改動**前後各跑一輪、數字進 `EVAL.md`**，commit message 引用輪次。
> 沒有對照數字的演算法改動不要上線——優化不能憑感覺（這句是使用者定的）。

- **機器指標**：`python eval_bench.py`（訪客 S1–S5，情境輸入逐字固定在腳本裡，
  **改一個字就開新情境 ID**，否則跨輪不可比）。需要本機 `.env` 金鑰；
  結果進 `eval_runs/*.json`（要進版控，是歷史資料）。
  `--no-repair` 關閉幻覺補救（量對照組）、`--only S1 S4` 只跑部分、`--tag` 標記輪次。
- **與 app 的刻意差異**：不做補生成（湊不滿本身是要量的訊號）、搜尋循序非並行
  （省共用配額，時間數字比線上慢）。
- **人工三題**（每情境一分鐘）：認得幾首／契合 1–5／想點開幾首。
  S6（登入 100% 探索）CLI 做不了 OAuth，照 `EVAL.md` 的固定輸入在 app 手動跑，
  出圈指標抄結果頁 caption。
- **判定指引**（不是硬性 CI）：可播 < 13/15 要查；70% 模式認得 > 3 首＝出圈退步；
  任一指標比上一輪差 15% 以上不上線，除非理由寫進 EVAL.md。
  LLM 有隨機性——單輪幾個百分點是雜訊，看趨勢與大幅退步。
- 真實使用者端的品質訊號：`[FEEDBACK]`（見「使用者回饋」）與 `[NOVELTY]` 在
  Manage app 日誌可撈。

## 修改注意事項

### Spotify API 限制（重要）
- **Development Mode 最多 25 位授權用戶**（BYOK 可繞過此限制）
- Extended Quota Mode（申請更多用戶）對個人開發者實際上已無法申請（截至 2025/2026 Spotify 政策）
- **已停用的 API**：`Get Recommendations`、`Audio Features`、`Audio Analysis`、
  `Related Artists`、`Artist Top Tracks`（後兩者實測 403）
- **熱門度訊號全部消失（2026-08 實測）**：track 物件連 `popularity` 這個鍵都沒有
  （搜尋與 `/tracks/{id}` 皆然、加 `market` 也一樣），artist 物件只剩
  `['external_urls','href','id','images','name','type','uri']`——
  沒有 `popularity`、`followers`，**連 `genres` 都沒了**。
  → 影響：流行度天花板改吃 LLM 自評的 `fame`（見「出圈演算法」）；
  `profile["top_genres"]` 可能是空的（prompt 會退回 "pop, indie pop"），
  用登入 token 測試時要順便確認這件事。
- **還能用的**：`search`、`artist_albums`、`album_tracks`、`current_user_*`、歌單讀寫
- 歌單寫入需申請 Quota Extension（`POST /playlists/{id}/items` 會 403）

### 播放平台選擇（Spotify / YouTube / Apple Music）
- 結果區有「用什麼聽」的 radio（`key="play_platform"`），影響曲目卡的按鈕與分享文字。
  `recommend.play_link(track, platform)` 回傳 `(按鈕文字, 連結)`。
- **Apple Music 走搜尋頁**（`music.apple.com/tw/search?term=…`，storefront 固定 tw）——
  同 YouTube 模式：不需要 API、不吃配額，跟 Spotify 搜不搜得到無關（不必 fallback）。
  未來要掛聯盟分潤（Apple Performance Partners 的 `&at=` token）就加在
  `apple_music_search_url()`。
- ⚠️ **曲目直連（`/song/{id}`）已調查、定案先不做（2026-08-21）**：免費的
  iTunes Search API 對中文內容召回率極差——實測「史詩／蛋堡」在 TW 目錄裡
  確實存在（`lookup?id=` 查得到、`/song/1448339528` 回 200），但組合詞、
  `songTerm`、`artistTerm`（中英文藝名各取 200 筆）**四種搜法全部找不到**；
  對照組英文歌（Motion Sickness / Phoebe Bridgers）第一筆完美命中。
  另兩個致命點：① 限制約 20 req/min/IP，而 Streamlit Cloud 全站共用出口 IP，
  一次生成 15 首就逼近上限；② 第一筆常是「別人 feat. 該歌手」的錯歌，
  真要做必須套 `resolution_matches()` 驗證、驗不過退回搜尋頁。
  正規解是 MusicKit（要 Apple Developer Program，99 美元/年）——
  哪天為了分潤辦了開發者帳號再回來做。

#### 播放點擊計數：做過中繼、雲端證實做不到、已撤除（2026-08-21）
- 動機：「每次生成有幾人點播放、點哪個平台」是導流分潤的決策數據。純 Streamlit
  唯一可行做法是中繼——link_button 指回本站 `?goto=…` 記一筆再 `<meta refresh>` 轉出。
  **本機實測整條鏈可行；部署後三個平台一律「拒絕連線」，已回退成直連。**
- **根因（在線上 DOM 實證）**：Streamlit Cloud 把 app 包在 iframe 裡跑
  （`soundcurator.streamlit.app/~/+/`），sandbox 是 `allow-forms allow-modals
  allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts
  allow-downloads`——**沒有 `allow-top-navigation`**。meta refresh 只會導航 iframe
  自己，而 Spotify/YouTube/Apple 都拒絕被嵌入（X-Frame-Options/CSP）
  → iframe 顯示「拒絕連線」，網址列還停在本站。本機沒有外層 iframe 所以測不出來。
- **為什麼判定不可修**：sandbox 沒開 top navigation，連改成 `<a target="_top">`
  讓使用者第二次點擊也會被擋；唯一放行的是 allow-popups（再開新分頁）＝
  點兩次、還多留一個廢分頁。JS beacon 也不通（markdown 濾掉 script/onclick，
  且沒有自訂 endpoint 可收）。要點擊數據只剩自架（不被 iframe 包）或自訂前端元件。
- **對分潤沒有影響**：聯盟追蹤（如 Apple 的 `&at=`）掛在**直連連結**上就行，
  轉換計數是平台端做的，不需要我們的中繼。死掉的只是自家 analytics。
- ⚠️ 若未來重做，白名單防 open redirect 的教訓要帶上（`?goto=` 是攻擊者可控參數）；
  當時的實作（含網域字尾偽裝測試）在 git 歷史 `5f2db78`。

### 使用者回饋（👍/👎/🎧，2026-08，兩種模式都有）
- 曲目卡下方三顆 `st.pills` 單選（再點一次取消）：喜歡／不合／早就聽過
  （標籤是 `:material/thumb_up:` 等，對照表 `_FB_STATE_BY_LABEL`，見「圖示系統」）。
  **真相來源是 `st.session_state["track_feedback"]`**（dict，key=`fb::`+`_track_key`）——
  它撐得過重新生成與檢視切換；widget state 只是 UI 快照，**Streamlit 會回收
  「這一輪沒渲染的 widget」的 state**（生成中結果區整段不渲染就會發生），
  所以 `_render_feedback()` 每次渲染前先從 dict seed 回 widget key（`w_fb::…`）。
  清除回饋時兩邊都要清，只清 dict 的話下次渲染 pills 會把舊選取寫回來。
- **回饋如何影響演算法**：① 回饋過的曲目一律併進 `history` 尾端＝程式端保證不再推薦
  （清除推薦歷史也不影響），且必落在 prompt 的最近 40 筆窗內；
  ② `recommend._feedback_block()` 進兩個 prompt builder（`feedback` 參數）——
  讚＝往相鄰方向探索的正向錨點（**訪客模式第一個真正的品味訊號**）、
  倒讚＝避開方向、聽過＝出圈校準；每類最多 `FEEDBACK_PROMPT_MAX=20` 筆（短清單原則）。
- **密集網格（>5/列）不顯示 pills**——欄寬塞不下，跟專輯名/理由走同一條
  「密集就省略」界線（`show_album`）。條列式一律顯示。
- 每次生成若帶有回饋，印一行 `[FEEDBACK] liked=N disliked=N heard=N guest=…` 到
  stderr——真實使用者的 👍 率是 EVAL.md 之外的第二個品質訊號源（Manage app 日誌可撈）。
- 版面量測（probe 頁，2026-08）：桌機 5/列與 3/列兩列——卡片等高（580/561）、
  按鈕齊（604）、pills 齊、列距 16px、pills 收在 column 盒內（bottom 對齊）；
  手機 375px 欄堆疊 343px、pills 單列 134×32 不換行；兩種尺寸皆零水平溢出。
  pills 是單一 widget 所以手機不會像巢狀 columns 那樣直向堆疊——這是選它不選
  三顆 `st.button` 的主因。
- **YouTube 走純搜尋網址**（`youtube.com/results?search_query=…`），不需要任何 API、
  不吃配額、不用 OAuth。⚠️ **不要改用 YouTube Data API**：`search.list` 一次 100 units、
  每天總共才 10,000 units，等於全站一天約 100 次搜尋——解析一份歌單就要 24 次。
  建立歌單（`playlists.insert` 50 + `playlistItems.insert` 50/首）約 800 units/份，
  全站一天 12 份。而且未通過 Google 驗證的 app 同樣有 100 人上限，沒有繞過授權問題。
- ⚠️ **選 Spotify 但那首歌在 Spotify 找不到時，一律退回 YouTube 連結**（`_no_spotify`）。
  以前給的是 Spotify 站內搜尋網址，但那首歌本來就不在 Spotify 上，點過去必然落空。
  按鈕文字跟著變「▶ YouTube」，順便讓使用者一眼看出哪幾首不在 Spotify。
  → 所以 `🔍 搜尋` 這個標籤已經完全不存在了，看到它就是舊版。
- **搜不到的卡片一律排到清單最後**（`curate_tracks` 的最終排序鍵是
  `(bool(_no_spotify), 原始索引)`）。實測 15 首裡 3 首搜不到剛好都被 LLM 排在最前面，
  沒有封面、只有搜尋按鈕，第一眼看起來像整個功能壞掉。

### 搜尋結果快取
- `search_track()` 的結果跨使用者快取在 `_SEARCH_CACHE`（key 是 `_track_key()`，
  所以 `Song` 與 `Song (Remastered 2011)` 共用一筆）。LLM 推薦重複性很高，
  而所有人共用同一組 Client ID 的配額，重複搜尋是最沒必要的浪費。
- ⚠️ **回傳的一定要是複本**：呼叫端會往裡面塞 `reason` / `fame` / `_discovery`，
  回傳快取裡那個物件的話，第一次生成就把快取污染了（有測試防護）。
- ⚠️ **「找不到」也要快取**（幻覺曲目會被反覆推薦，每次重搜要打兩個請求），
  但 429 會拋例外、不會走到寫入那行，所以限流造成的失敗不會被寫進快取。
- `search_cache_info()` 的 hits/misses 會印在 `[NOVELTY]` log 裡。

### ⚠️ 速率限制與 spotipy 重試（踩過大坑，繞了兩圈才對）
- app 層級的 rate limit 撞到後，429 的 `Retry-After` 實測是 **21315 秒（約 6 小時）**，
  urllib3 會遵守它**真的 sleep 下去**——症狀是頁面永遠卡在「🔍 Spotify 搜尋歌曲...」。
- **兩個直覺的做法都不對**（都實測過）：
  1. `retries=0`：確實不睡了，但 urllib3 第一次 `increment()` 就丟 `MaxRetryError`，
     spotipy 的 handler **寫死**轉成 `SpotifyException(429)`——於是 500/502/503/504
     與連線中斷全部長得跟速率限制一模一樣，一顆暫時性 503 就讓整批搜尋短路。
  2. 只把 429 移出 `status_forcelist`：**沒用**。`Retry.is_retry()` 有一條獨立路徑——
     `total>0` 且 `respect_retry_after_header=True` 且回應帶 `Retry-After` 時，
     429 就算不在 forcelist 也照樣重試（429 在 `Retry.RETRY_AFTER_STATUS_CODES` 裡）。
- **正解**：`_harden()` 自己掛一個 `respect_retry_after_header=False` 的 `HTTPAdapter`
  （`retries=3`、`status_forcelist=(500,502,503,504)`）。所有 client 都要經過它
  （`_sp()` 與 guest client）。驗證法：
  `sp._session.get_adapter("https://api.spotify.com").max_retries.is_retry("GET", 429, True)`
  要是 `False`，`is_retry("GET", 503, True)` 要是 `True`。
- `_search_tracks_parallel()` 回傳 `(結果, 是否撞到限制)`，撞到就跳過補生成、
  `curate_tracks(spare_capped=False)` 不再套補位卡上限（搜不到不代表歌是假的），
  並顯示提示。
- 單次推薦的請求量要留意：15 首 → 24 候選 × (嚴格搜尋 + 可能的模糊搜尋) + 補生成一輪
  ≈ 上百個請求，而**所有使用者共用同一組 Client ID 的配額**。

### Gemini
- 模型：`gemini-2.5-flash`（`GEMINI_MODEL` 常數，在 `recommend.py`）
- **`thinking_budget=0`（`_NO_THINKING`）一定要留著**：2.5-flash 預設會先思考再回答，
  同一個 prompt 實測 **18.15s → 5.03s**（thoughts_token 2181–3052 → 0）。
  推薦歌單是「照規則產出 JSON」，不需要推理鏈；語言/曲風/避開歷史等限制實測都仍遵守。
- **`genai.Client()` 建構一次要 ~2.4 秒**，用 `_client()`（`lru_cache`）共用，別在每次生成時 new。
- `gemini-2.0-flash` 免費 tier 配額為 0，不要用
- 有 503 重試邏輯（3 次，8s/16s 間隔）
- 429/RESOURCE_EXHAUSTED 與 API Key 無效不重試，`_friendly_gemini_error()` 直接轉成中文友善訊息
- JSON 解析有 regex fallback（`_parse_json_robust()`）；code fence 統一由 `_strip_code_fence()` 處理

### 生成速度（2026-08 量測，訪客模式 15 首）
| 階段 | 改善前 | 改善後 | 作法 |
|---|---|---|---|
| IP 定位 + 天氣 | 3.3s（擋在按下生成之後） | ~0s | 頁面載入就背景預抓（`start_geo_prefetch()`） |
| 建立 genai.Client | 2.4s（每次） | ~0s（首次之後） | `_client()` 用 `lru_cache` 共用 |
| Gemini 生成 | 18.2s | 5.0s | `thinking_budget=0` |
| Spotify 搜尋 | 2.6s | 2.6s | 已是 8 workers 並行（提高到 15 反而變慢：2.27s vs 1.82s） |
| **合計** | **~26s** | **~8–10s** | |

- 登入模式的 profile 抓取已改成「頁面載入就背景並行預抓」（`start_profile_prefetch()`），
  不再擋在按下生成之後；收藏改成先看 `total` 再決定頁數，避免無條件送 10 個分頁請求。
- 量法：`app.py` 內暫時插 `_mark()` 印到 stderr（`streamlit run ... > log 2>&1` 再 grep `[PERF]`），
  量完記得移除。⚠️ 瀏覽器端量到的時間在無頭視窗下會虛高（rAF 被節流），以伺服器端數字為準。

### 時區（重要）
- Streamlit Cloud 的伺服器時鐘是 **UTC**，`datetime.now()` 會讓台灣使用者看到少 8 小時
  （13:58 顯示成 05:58），連帶「深夜/清晨」判斷全錯。
- 一律用 `_local_now()`（定義在 `spotify_api.py`，`app.py` 從那裡 import——
  ⚠️ 曾經整個漏掉這個 import，症狀是「自動偵測失敗：name '_local_now' is not defined」，
  自動定位/天氣永遠失敗、登入模式顯示結果時直接 NameError）。
  偏移存在 `st.session_state["geo_tz_offset"]`，查不到則退回 `DEFAULT_TZ_OFFSET`（+8）。
- ~~偏移取自 ipwho.is 的 `timezone.offset`，所以 `fetch_auto_context()` 必須先查地理位置
  再取時間。~~ **← 此段已於 2026-08-21 作廢，見下一節**：偏移改由瀏覽器提供
  （`sync_browser_timezone()` 在頁面載入時就寫好），IP 查到的只剩備援，
  `fetch_auto_context()` 的先後順序不再影響時間正確性。

### ⭐ 時區：向瀏覽器要，不要用 IP（2026-08-21 定案）

**`st.context` 有這些東西，不要再自己解 HTTP 標頭**：
`timezone`（`'Asia/Taipei'`）、`timezone_offset`（int）、`ip_address`、`locale`、`url`、`theme`。

- `_browser_tz_offset()` 讀 `st.context.timezone_offset`，寫進 `st.session_state["geo_tz_offset"]`，
  `_local_now()` 就正確了。**不需要網路請求、不受代理鏈影響、使用者掛 VPN 時也是他當地時間。**
- ⚠️ **單位與正負號**：`timezone_offset` 與 JS 的 `getTimezoneOffset()` 同慣例——
  「**落後** UTC 幾**分鐘**」，台北 UTC+8 回傳 **-480**。本專案 `geo_tz_offset` 是
  「領先 UTC 幾**秒**」，換算要 **`-mins * 60`**。有參數化測試釘住（含 UTC+0 與紐約）。
- ⚠️ **判斷有沒有值一定要用 `is not None`**：UTC+0 的偏移是 `0`，用 `or` 會被當成沒拿到。
- `sync_browser_timezone()` 在**每次頁面載入**就呼叫（module 層級，緊鄰 `start_geo_prefetch()`）——
  不能只在「自動偵測位置」開啟時做，關掉自動偵測的使用者一樣需要正確時刻
  （歌單名稱、推薦情境的「深夜/清晨」都靠它）。
- `st.context.ip_address` 在本機是 `'::ffff:127.0.0.1'`（socket 對端），雲端會是代理的 IP，
  **不能拿來做地理定位**。

### 位置偵測：拿不到使用者 IP 就別查（2026-08 修）

**症狀**：使用者在台北，畫面卻顯示「📍 08:27（清晨）｜The Dalles, United States｜晴朗 22.2°C」。
The Dalles 是 Google 機房所在地——ipwho.is 定位到的是**伺服器自己**。時刻判斷跟著全錯，
「清晨」的情境被送進 prompt，推薦整個歪掉。

**根因**：`_client_ip()` 取不到使用者 IP 時回空字串，而舊的 `_geo_weather_blocking()`
會照樣打**不帶 IP** 的 `https://ipwho.is`——那個端點的語意是「定位發出請求的這台機器」。
本機開發時剛好就是開發者自己的 IP，所以一直看起來是對的，只有雲端會露餡。

**兩層修法**：
1. `_geo_weather_blocking()` 在 `client_ip` 為空時**直接 return，完全不發請求**。
   時區退回 `DEFAULT_TZ_OFFSET`（+8）——沒有位置至少時間是對的，比顯示錯誤位置好。
2. `_client_ip()` 依序試 `_CLIENT_IP_HEADERS`（X-Forwarded-For、X-Real-Ip、
   Cf-Connecting-Ip…），並用 `_first_global_ip()` 掃**整條代理鏈**取第一個公開 IP
   （不能只取最左邊，那有可能是內網位址）。
3. 一個都挑不到時印 `[GEO] 找不到 client IP；可用標頭：[...]` 到 stderr。
   ⚠️ **只印標頭名稱不印值**——標頭內容含 cookie / token，不能進 log。

**本機開發是唯一例外**：`_is_local_dev()` 用 `Host` 標頭判斷（本機 `127.0.0.1:8501`、
雲端 `soundcurator.streamlit.app`）。本機直連時「伺服器」就是開發者自己的機器，
定位自己反而是對的，所以 `allow_self_lookup=True` 放行不帶 IP 的查詢——否則本機開發會
完全看不到位置與天氣。
⚠️ 去 port 不能無腦 `split(":")[0]`：IPv6 本身含冒號，`::1` 會被切成空字串（有測試釘住）。
⚠️ `_client_ip()` / `_is_local_dev()` 都碰 `st.context`，**必須在主執行緒算好再傳進背景執行緒**。

**雲端的結論（2026-08-21 從 Manage app 日誌確認）**：Streamlit Cloud **有送 `X-Forwarded-For`**，
但整條鏈裡**找不到任何公開 IP**——真實 client IP 在代理層就被剝掉了。雲端實際的標頭是：
```
['Accept-Encoding','Accept-Language','Cache-Control','Connection','Host','Origin','Pragma',
 'Sec-Websocket-*','Upgrade','User-Agent','X-Forwarded-For','X-Streamlit-User']
```
（`X-Streamlit-User` 是 Streamlit 自己加的使用者識別，不是 IP。）
→ **時區已改由瀏覽器提供**（見上一節），不再受影響。
→ **位置與天氣在雲端就是拿不到**，會靜默略過。要恢復的話只剩兩條路：
  改用瀏覽器的 Geolocation API（會跳權限提示），或前端打第三方 IP API 再回傳。
  兩者都要新增前端元件，成本不低——目前判斷「沒有位置」是可接受的。

**歷史紀錄**：實測本機只有
`['Accept-Encoding','Accept-Language','Cache-Control','Connection','Cookie','Host','Origin',
'Pragma','Sec-Websocket-*','Upgrade','User-Agent']`（直連本來就沒有 proxy 標頭）。
下次部署後到 Manage app 日誌看那行 `[GEO]`，把雲端實際送的標頭名補進 `_CLIENT_IP_HEADERS`
就能真正修好定位。在那之前雲端使用者看不到位置與天氣（時間正確），是可接受的降級。

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

## 主表單版面（Hero「想成為你專屬的歌單」，2026-08 漸進式揭露改版）

> 標題走 `styles.form_hero_html()`：一行**左對齊的大漸層字**「想成為你專屬的歌單」＋小圖示漂浮裝飾。

**設計（2026-08-22 定案，多輪迭代）**：演進是「三大圖示置中→拿掉圖示改左對齊→加回小裝飾」。
使用者最終要：大標題、左對齊（跟表單元素齊）、圖示縮小為精緻裝飾（不是舊的三大置中圖示）。
- **左對齊**：hero `text-align:left`，標題左緣對齊表單元素（實測 380==生成鈕左緣）。
  左對齊後 Streamlit 標題尾端錨點不再推偏（那是**置中**才有的問題），順帶少一個雷。
- **標題** `h2.y2k-form-title` 桌機 **2.9rem**、手機 2rem（!important；`.stMarkdown h2` 預設 2.25rem
  蓋不過，一定要寫 `h2.y2k-form-title { … !important }`）。⚠️ 別再回頭對齊登入 wordmark——
  之前試 2.6rem 頭重是因為當時還有**大圖示**；現在無大圖示、2.9rem 沒問題，且兩 hero 在不同頁本就不必同字級。
- **裝飾**（都掛 `.y2k-decor` 類別，方便手機一次收掉）：黑膠＋青星芒用 `position:absolute` 漂左上角；
  黃星芒＋音符＋紫星芒**接在標題後面 inline**（`align-self:flex-start/flex-end` + margin 做浮動高低差）。
  ⚠️ 右側裝飾**別用 `position:absolute; right:` 貼右邊緣**——hero 很寬會讓它們飄到遠處、把焦點拉散
  （使用者實測嫌棄過）；改成 inline 接在標題後才會「貼著標題、收攏」。左上的用絕對定位沒問題。
  ⚠️ hero 要 `position:relative`＋`min-height:148px` 撐出裝飾空間、且容器包住裝飾才不會蓋到下面表單。
  標題 div 要 `z-index:2` 蓋在裝飾上（萬一重疊，字在上面才讀得到）。
- **手機**（media query）：`.y2k-decor { display:none }`＋`.y2k-form-hero { min-height:0 }`——375px 下
  裝飾會蓋到縮小標題/溢出，直接收掉，只留大標題＋**標題尾那顆黃星芒**（它不是 `.y2k-decor`、刻意保留）。實測無水平溢出。

```
第一層（一進來就看到）  情境輸入（自動偵測 / 文字 / 圖片）→ 投射問題 → 生成按鈕
第二層（摺疊 expander） 推薦歌曲數 · 音樂偏好 · 現在的心情 · 關於你（圖示走 Material，見「圖示系統」）
（活動情境 pills 已於 2026-08 移除——與「分享一下你的日常吧」文字欄重複）
```

- **摺疊標題帶即時摘要**（`音樂偏好　·　日語 · Jazz`）。摘要必須在 expander 建立**之前**算好，
  所以一律從 `st.session_state` 讀值——因此**每個 widget 都必須有 `key=`**，新增欄位時別忘了。
- ⚠️ **每個 expander 也必須有自己的 `key=`**（`exp_songs` / `exp_music` / `exp_mood` / `exp_traits`）。
  沒有 key 時 Streamlit 用標題文字認元件，摘要一變就被當成新元件重建、摺疊狀態歸零——
  症狀是「拖一下滑桿面板就自己關起來」。`st.expander(key=...)` 需要 Streamlit >= 1.57。
- `_brief(items, limit=2)` 把多選縮成「前 2 項 +N」；`_summary(parts, empty)` 組合摘要、全空時顯示 empty。
- **生成按鈕用 `generate_slot = st.container()` 佔位**：版面在摺疊區上方，程式碼卻在所有 widget 之後，
  這樣 handler 才讀得到 `languages` / `mood_energy` 等變數。進度狀態也走 `generate_slot.columns()`。
- 投射問題那一列包在 `st.container(key="proj_row")` 裡，`styles.py` 用 `.st-key-proj_row` 把兩欄
  改成 `flex:0 0 auto; width:auto`、`gap:1.25rem`——題目長度 170–403px 差很多，固定欄寬時
  短題目後面會空一大片（量到 500px）。改完不論題目長短，按鈕都固定在題目右側 20px，
  最長那題也還在同一行（row 高度維持 40px）。
- **投射問題題庫 30 題、「換一題」走洗牌輪替**（`_rotate_projective()`，2026-08）：
  舊版 `random.choice` 只排除當前題，session 內連按幾次就看到舊題回鍋；
  現在整輪 30 題出完才重洗，重洗後第一題若撞上上一題會移到隊尾（三條測試釘住）。
  新增題目時維持「投射」性質——問具體小事（桌布/窗外/最後一則訊息），
  讓 AI 從回答反推狀態與生活風格，不要出直白的「你現在心情如何」。
- 兩欄情境輸入的高度要手動對齊：`text_area(height=106)` 對上 file_uploader 的實際高度（量出來 104±2）。
  標題由 `styles.context_label_html()` 統一產出（2026-08-22 起帶對話氣泡圖示 `SVG_CHAT`，
  版式同投射問題；左欄與右欄佔位**必須同一個 helper**，內容一致換行才一致）；
  它是 `<div>` 不是 `<p>`，`stMarkdownContainer` 的 -16px 負邊界要用
  `:has(.y2k-ctx-label)` 歸零，否則 textarea 會上移 16px 蓋到標題（量測後間距 9px）。
  右欄的標題已併進左欄那句「分享一下你的日常吧（也可以上傳圖片給 AI 分析）」，
  括號補充包在 `<span class="y2k-keep">`（`display:inline-block`）裡——窄螢幕換行時整段一起下去，
  不會斷成「…給 AI／分析）」；桌機（欄寬 547px）仍是一行，手機 375px 剛好斷在「（」之前。
  右欄改放**同一句、同一種元件**再用 CSS 藏起來（`st.container(key="ctx_label_spacer")`）：
  視窗窄到標題換行時左右會一起換行，兩個框的頂端才會永遠齊
  （量過 397px 欄寬單行、192px 欄寬雙行，`taTop == upTop`）。
  ⚠️ **只寫 `.st-key-ctx_label_spacer { visibility:hidden }` 沒用**——Streamlit 自己對
  `stMarkdownContainer` 設了 `visibility:visible`，會蓋掉繼承來的 hidden，文字照樣顯示。
  必須連子孫一起 `.st-key-ctx_label_spacer * { visibility:hidden !important }`；
  驗證要量那個 `<p>` 自己的 computed visibility，只量容器會誤判。
  手機版（≤640px）欄位會堆疊、不需要對齊，整塊 `display:none`。
- 推薦網格的卡片要等高，`▶ Spotify` 按鈕才會對齊：歌名 1/2 行、有無專輯、有無理由都會讓卡片高度不同。
  作法是 `st.container(key="track_grid")` + `.st-key-track_grid` 把
  column → verticalBlock → 第一個 elementContainer → stMarkdown → wrapper → stMarkdownContainer
  整條鏈拉成 flex/height:100%，卡片自己再 `height:100%`。**中間漏掉任何一層，短卡片就不會撐滿**
  （按鈕仍會齊，但卡片下緣會縮，量到 259 vs 317）。專輯名另外限一行 ellipsis——
  `First Love (The Original & the Very First Recording)` 這種長名稱換行就是這次不對齊的直接原因。
- Spotify 授權失敗的說明（人數上限／INVALID_CLIENT）不留在首頁：
  `consume_oauth_callback()` 把 `?error=` 或 token 交換例外寫進 `st.session_state["spotify_auth_error"]`，
  登入頁只在有值時 `st.warning()`。首頁平常只留一行「🔒 Token 只存在瀏覽器分頁記憶體」。
- expander 內距 `[data-testid="stExpanderDetails"]` 上下各 1.35rem（21.6px），0.75rem 太擠。
- 「推薦歌曲數」緊接在生成按鈕下方（程式碼也放在 `generate_slot` 之後、其他 expander 之前）。
  清除推薦歷史收在這一區內（罕用且不可逆）；歷史筆數顯示在生成按鈕下方。
- ⚠️ **widget 已經渲染之後**再用 `st.session_state["mbti"] = ...` 手動寫入會被 Streamlit 擋下。
  但「在該 widget 這一輪還沒建立**之前**先寫」是合法的——`app.py` 的「換一題」就靠這招
  重設 `projective_a`（寫完馬上 `st.rerun()`，下一輪 widget 才讀到新值）。
  看到那行不要當成 bug 去「修正」，會弄壞換題重設。

## 輸入欄位說明（登入頁）

### 進階（選填）：自備 Spotify App
| 欄位 | session_state key | 說明 |
|---|---|---|
| Spotify Client ID | `custom_SPOTIFY_CLIENT_ID` | 自動填入 Redirect URI |
| Spotify Client Secret | `custom_SPOTIFY_CLIENT_SECRET` | |
| Redirect URI | `custom_SPOTIFY_REDIRECT_URI` | 自動從 URL 組合 |

> Gemini 欄位已於 2026-08 移除——AI 由本站提供，見上方 Credential 管理。

### 推薦偏好輸入

⚠️ **widget key 與 Python 變數名不一定一樣**——摺疊區的即時摘要必須在 expander 建立
**之前**從 `st.session_state` 讀值（見「主表單版面」），讀的是 **key 欄**那一格，
不是變數名。寫 `st.session_state["languages"]` 會拿到 KeyError。

| 欄位 | Python 變數 | widget key（session_state 用這個） | 說明 |
|---|---|---|---|
| 情境文字 | `text_ctx` | `text_ctx` | 標籤走 `styles.context_label_html()`（含對話氣泡圖示） |
| 自動偵測 | `auto_ctx` | `auto_ctx` | 開啟後讀取 IP/天氣；隱私說明收在 `help=`（問號 tooltip）。IP 取自 `X-Forwarded-For` 最左段＝**使用者可偽造**，`_client_ip()` 會用 `ipaddress` 驗過、且只收 `is_global` 的位址才拼進 `https://ipwho.is/{ip}`（⚠️ RFC 文件範圍 `203.0.113.x` / `2001:db8::` 在 Python 3.12+ 才算 private，寫測試時很容易踩到——也是 dev container 用 3.11 會紅的那幾條） |
| 圖片上傳 | `uploaded` | `ctx_image` | Gemini Vision 分析氛圍 |
| 語言 | `languages` | **`lang_pills`** | Pills 多選 |
| 曲風 | `genres` | **`genre_pills`** | Pills 多選 |
| **指定歌手** | `fav_artists` | **`fav_artists_input`** | 文字輸入，逗號分隔，傳入 prompt 讓 AI 優先推薦 |
| 推薦數量 | `num_songs` | `num_songs` | 5–30 首 |
| 新藝人佔比 | `new_artist_ratio` | `new_artist_ratio` | 0–100%（僅登入模式） |
| **探索度** | `fame_mode`（經 `_GUEST_FAME_LABELS` 轉） | **`guest_fame_mode`**（存中文標籤） | 僅訪客模式：熟悉/均衡/探索，radio。均衡＝改版前行為，見「訪客探索度」段 |
| 投射問題回答 | `projective_answer` | `projective_a` | 題目本身在 `projective_q`、輪替順序在 `proj_order` |
| MBTI／血型／星座 | 同名 | `mbti` / `blood_type` / `zodiac` | 摘要用 |
| 心情雙軸 | 同名 | `mood_energy` / `mood_valence` | 1–10 slider |

## 常見操作

### 啟動開發伺服器
```powershell
streamlit run app.py
```
⚠️ **改了 `styles.py` / `recommend.py` / `spotify_api.py` 要重啟伺服器**，
存檔後重新整理瀏覽器**沒有用**——Streamlit 只重跑 `app.py`，`sys.modules` 裡的模組還是舊的
（跟雲端要 Reboot 是同一個機制，見「跨模組改動要手動 Reboot」）。
症狀很容易誤判：CSS 沒變、新加的 class 在 DOM 裡找不到，看起來像自己改錯了。

### 語法檢查
```powershell
python -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ('app.py','recommend.py','spotify_api.py','styles.py')]; print('OK')"
```

### 跑單元測試（改任何 .py 都要跑）
```powershell
python -m pytest -q
```

### 推到 Streamlit Cloud
```powershell
git add app.py recommend.py spotify_api.py styles.py .streamlit/config.toml
git commit -m "feat: ..."
git push origin main
```
Streamlit Cloud 會自動偵測 push 並重新部署（約 1–2 分鐘）。

#### ⚠️ 跨模組改動要手動 Reboot（2026-08 踩過）
Cloud 偵測到 push 後做的是 **`git pull` + 重跑腳本**（日誌顯示 `🔄 Updated app!`），
**不會重啟 Python 行程**。`sys.modules` 裡的 `recommend` / `spotify_api` / `styles`
仍是舊版 module 物件，於是新的 `app.py` 執行 `from recommend import 新名稱` 就會炸：

```
ImportError: cannot import name 'OVERGEN_FACTOR' from 'recommend'
```

——GitHub 上明明有那個名稱，本機也 import 得到，只有雲端壞。**這不是程式碼問題**。

- **判斷方式**：錯誤是 `cannot import name X from Y`（不是 `No module named`），
  而 `git show origin/main:Y.py` 裡確實有 X → 就是這個狀況。
- **修法**：share.streamlit.io → 該 app 的 **⋮ 選單 → Reboot**（重啟行程、重新 import）。
  再 push 一次沒有用，因為問題不在檔案。
- **只改 `app.py`** 時不會遇到（腳本本來就每次重跑）；**改了被 import 的模組**就要 Reboot。
- ✅ **例外：同一個 push 有動到 `requirements.txt` 時不必手動 Reboot**——Cloud 會重跑
  依賴安裝並重啟行程。實測 2026-08-21 那次 push 同時改了 `requirements.txt` 與
  `styles.py`／`recommend.py`，部署後新文案直接生效，沒有 ImportError。
  所以判斷方式是：**這次 push 有沒有動到相依設定**，有就自動好，沒有就要手動 Reboot。
- **為什麼熱重載在雲端不可靠——找到根因了**：日誌裡每隔幾分鐘就刷一次
  `OSError: [Errno 24] inotify instance limit reached`（偶爾是 `[Errno 28] watch limit reached`），
  Streamlit 的檔案監看器**在 Cloud 上根本啟動不了**（容器的 inotify 配額被吃光）。
  所以它偵測不到檔案變動、也就不會重新載入模組。這是平台限制，不是我們能修的，
  唯一對策就是 Reboot。⚠️ 這些 traceback 在日誌裡占了 95% 的篇幅，**是雜訊不是錯誤**，
  排查問題時直接略過，只找 `[GEO]`、`ImportError`、`NameError` 這類真正的訊息。
- ⚠️ **若 Reboot 後錯誤完全相同**，那就不是行程快取，而是伺服器上的檔案真的沒更新
  （pull 靜默失敗）。判別法：`git show origin/main:recommend.py | grep '^OVERGEN_FACTOR'`
  ——遠端有、雲端沒有＝檔案沒同步。這時要用 Manage app 看 pull 那段有沒有錯誤，
  或在 Settings 重新指定 branch 觸發完整 re-clone。

## 檔案結構

| 檔案 | 用途 | 常改？ |
|---|---|---|
| `app.py` | Streamlit UI 層 + 登入/訪客流程 | 是 |
| `recommend.py` | prompt / Gemini / JSON 解析 / `curate_tracks()` 驗證鏈（純邏輯，無 Streamlit） | 是 |
| `spotify_api.py` | OAuth / 搜尋 / 歌單 / 跨 session 歷史 | 偶爾 |
| `styles.py` | Y2K 主題 CSS / SVG / HTML helpers | 偶爾 |
| `test_*.py`（6 個） | `test_recommend`(125) / `test_spotify_api`(32) / `test_styles`(14) / `test_app`(40) / `test_ratelimit`(13) / `test_db`(21) | 改對應模組時同步 |
| `db.py` | 跨 session 持久化層（Supabase Postgres：回饋＋歷史＋同意）。純邏輯可測、psycopg 延遲載入。**Phase 1 已寫、尚未接上 app.py** | 見 `FEEDBACK_PERSISTENCE.md` |
| `FEEDBACK_PERSISTENCE.md` | 回饋＋歷史持久化（資料庫版）規格／計畫 | 動工前讀 |
| `ratelimit.py` | 生成請求節流（純邏輯，時間由參數傳入） | 偶爾 |
| `eval_bench.py` | 固定情境驗收跑分 CLI（訪客 S1–S5，見「驗收流程」） | 改演算法時跑 |
| `EVAL.md` | 驗收紀錄（每輪一節，含人工三題） | 改演算法時填 |
| `eval_runs/` | 驗收的 JSON 明細（要進版控，是歷史資料） | 自動產生 |
| `.streamlit/config.toml` | Streamlit 主題 + toolbarMode | 偶爾 |
| `requirements.txt` | pip 依賴——**直接依賴一律精確釘版（`==`）**，理由與升級流程寫在檔案開頭的註解，加新套件前先讀（用 `>=` 會讓 Dependabot 失效，且雲端裝到的永遠不是你測過的版本） | 偶爾 |
| `.github/dependabot.yml` | 每週自動開依賴更新 PR（配合上面的 `==` 釘版才有用） | 否 |
| `SECURITY.md` | 漏洞回報政策（私人 advisory + email，7 天回應） | 否 |
| `.devcontainer/` | GitHub 自動產生的樣板，**與本專案前提衝突**——見「dev container 的兩個陷阱」 | 否 |
| `.env` / `.env.example` | 本地 credentials（不加入 git） | 否 |
| `CLAUDE.md` | 這份交接文件——**改了行為就順手更新這裡** | 是 |
| `README.md` | 對使用者/其他開發者的說明（部署、限制、功能總覽） | 偶爾 |
| `m1~m4_*.py` | CLI 測試腳本（非主程式） | 否 |
| `fonts/` | ⚠️ **孤兒**：13.6 MB 的中文字型，原為 IG 分享圖卡渲染用，該功能已於 `72bf444` 移除，現在沒有任何程式碼引用——確認不需要就可以 `git rm -r fonts/` | 否 |
| `.claude/worktrees/` | ⚠️ **搜尋時的假訊號**：裡面有舊版 `app.py` / `README.md` / **`share_card.py`**（早就刪掉的 IG 圖卡）。它被 gitignore 所以 `git status` 看不到，但**全庫 grep 會撈到**——看到 `share_card` 之類的東西先確認路徑，別以為功能還在 | 否 |

## 近期修改紀錄（最新在上）

| Commit | 說明 |
|---|---|
| _(未 push)_ | feat: **訪客探索度三檔**（第 2 輪演算法第 2 項）——訪客表單新增「熟悉/均衡/探索」radio → `fame_mode`。均衡＝改版前行為（預設，逐字不動）；探索才降天花板（`GUEST_POP_CEILING_DISCOVERY=65`）＋在 guest prompt 套「至少一半 fame1-2」配額（兩件綁一起做，疑點1）。探索的挖法綁「知名歌手的專輯深軌」而非小眾藝人（小眾→幻覺/搜不到暴增，三版迭代才收斂）。S1 華語 fame≤2 0.07→0.33、S3 健身 0→0.27（`EVAL.md` 第 2 輪第 2 節）。+8 tests（共 222）。見「訪客探索度」段 |
| `00afdaf` | feat: **指定歌手保底佔比**（第 2 輪演算法第 1 項）——`recommend._apply_fav_floor` 在驗證鏈最後用真實深軌把清單補到至少 `FAV_MIN_SHARE=0.5` 來自點名歌手、放寬他們的同藝人上限、平均分配、零幻覺；`spotify_api.fav_artist_pool()` 重用 `_artist_catalog`；CJK 藝名（陳綺貞→Cheer Chen）走 `allow_top_result=True` 取搜尋第一筆（**只給保底、幻覺補救維持嚴格**，結果分開快取）。S4：指定歌手佔比 3/15→8/15、fav_share 0.20→0.53（`EVAL.md` 第 2 輪）。+15 tests。見「指定歌手保底」段 |
| `0d86919` | feat: 表單 hero 改版——放大漸層標題（2.9rem）左對齊＋小圖示漂浮裝飾（黑膠/青星芒 absolute 漂左上、黃星芒/音符/紫星芒 inline 貼標題後收攏、手機 `.y2k-decor` 收掉），取代三大置中圖示。⚠️ 右裝飾別用 `absolute; right:` 貼右邊緣（hero 很寬→飄太遠、焦點拉散）、改 inline 貼標題後才收攏; docs: 主表單版面段重寫 |
| `9b7455a`／`d83cbfa` | feat: 登入 hero Option C（黑膠當 Sound 的「o」＋tagline「不推弟，只推歌。還不快叫我乾歌」，取代三貼紙圖示＋漸層字）、高度對齊表單 hero（`min-height:117`＋`:has(.y2k-login-hero)` 歸零 -16px）；表單標題先 2.4→2.6rem 再改回 2.4rem（同字級會頭重、兩 hero 構圖不同故刻意不同字級——後於 0d86919 整個改版） |
| `fe869fb`／`5de7d2b` | refactor: 顯示名稱 Spotify Personal Discovery → **SoundCurator**（hero／分頁／分享文字／歌單敘述／docstring／README；`HISTORY_PLAYLIST_NAME` 未動）；docs: 部署網址 spotify-lml → `soundcurator.streamlit.app`（`_is_local_dev()` 只認 localhost、不受影響）。⚠️ 換子網域要同步 Streamlit App URL＋Spotify Redirect URI＋Streamlit Secrets 三處，否則方式二 redirect mismatch |
| `4efad24` | fix: 結果頁「AI 情境解讀」火花置中（translateY -1.5px）、框下邊距 0.8rem→1rem 使 →🧭 caption 間距回全站 16px 節奏（皆先量再改） |
| `210827a` | feat: 歌單命名有溫度化——Gemini 回應多生 `playlist_title`（短雙語 vibe 標籤，few-shot 你給的 Pre-Workout Warmth // 暖機午後 那類）＋ `playlist_blurb`（雜誌編輯口吻導言）；存歌單時 name 用 title、description 用 blurb（退 `context_interp`→自動生成時間戳），`create_playlist_with_tracks` 收 `description` 參數＋300 字上限；生成敘事行 emoji→Material 行內圖示（🔗→sync 等 11 個，⚠️ 警示保留）＋行內圖示補 `margin-right:0.4em`；結果控制列 `st.columns(vertical_alignment="center")`; docs: 驗收第 1 輪補完 S6（登入探索出圈率 100%、pop_blocked=10 證實登入天花板有效） |
| `63088e6` | docs: 驗收第 1 輪基準（訪客 S1–S5，全 15/15 可播、死卡 0；疑點——訪客 fame≤2 幾乎全靠補救、S4 指定歌手 fav_share 僅 0.27）; fix: eval_bench.py 修 Windows cp950 主控台印 🛠/✗ 的 UnicodeEncodeError（stdout/stderr 強制 UTF-8） |
| `861984d` | fix: 氣泡圖示的置中改對齊第一行（flex-start）——文字折行時 center 會讓氣泡浮在兩行中間差 13px，修後 1.1px；情境標題與投射問題兩處同步 |
| `99fe0fa` | fix: 登入 hero「圖示→標題」間距對齊表單版（墨水間距 13px==13px，margin 17px 為量測校準值；h1 要 padding:0）；feat: 情境標題加對話氣泡 SVG_CHAT（context_label_html 統一產出，左右欄同 helper）；移除登入卡片 y2k-mbr 手機強制斷行（標題已短，實測單行） |
| `a16c525` | feat: 圖示系統第二波全站清掃（登入頁/sidebar/清除鈕/提示框全轉 Material 或貼紙 SVG，新增 SVG_LOCK；刻意保留 🧭 與暫態敘事行）；fix: 投射列置中（div 沒有 p 邊距抵銷 -16px 負邊界）、markdown 行內圖示的第三種字型地雷（translate="no"）、圖示 line-height:1；copy: 「關於你」說明去「選填。」 |
| `a2bafef` | feat: Y2K 圖示系統兩層制取代全站 emoji——A 層自繪貼紙 SVG（剪貼板＋題目氣泡；投射問題 30 題去 emoji 統一用氣泡）、B 層 Material Rounded 染色（pills/生成鈕/四個 expander/換一題）；⚠️ expander 圖示 testid 是 stExpanderIcon 且會被全域 Nunito 蓋掉連字（:not() 排除清單要含它）。設計稿 artifact d2fc1112 |
| `5c70d25` | feat: 幻覺補救 repair-on-miss（搜不到→同歌手真實深軌替換，含跨使用者目錄快取；artist_albums limit 上限實測只剩 10）、訪客 fame 天花板（兩段式、只壓國民金曲層級、數量永不縮水）、驗收流程（eval_bench.py＋EVAL.md＋[FEEDBACK] log）；chore: use_container_width → width="stretch"（11 處，import 零棄用警告） |
| `081d791` | copy: 結果區「複製或分享歌單」→「複製歌單」；docs: Apple Music 曲目直連調查定案不做（iTunes Search API 中文召回率極差，見「播放平台選擇」段） |
| `5b88680` | feat: 投射問題題庫 15 → 30、「換一題」改洗牌輪替（整輪出完才重洗、跨輪不連續同題）——舊版 random.choice 換題會回鍋、15 題池子開 5 次頁面約五成機率撞題 |
| `72bf444` | revert: 撤除播放點擊中繼——Streamlit Cloud 的 app iframe sandbox 沒有 allow-top-navigation，轉導必被平台 X-Frame-Options 擋成「拒絕連線」（見「播放點擊計數」段的驗屍報告），播放按鈕回退直連；feat: 移除 IG 分享圖卡功能（share_card.py 刪除，Pillow 因上傳路徑仍保留釘版） |
| `5f2db78` | feat: 曲目回饋 👍/👎/🎧（兩種模式，session 級，餵進 prompt＋程式端排除）、播放點擊中繼計數（`?goto=` 白名單防 open redirect、[PLAY] stderr）、Apple Music 第三播放平台（搜尋頁、tw storefront） |
| `2fcc1c5` | fix: 訪客模式對齊登入版設計原則——prompt 歷史截 40（原本塞整份最多 200 筆）、超額生成 1.25×、補生成＋湊不滿說明開放給訪客、搜不到的卡排最後且超額時最先被裁（原本會佔清單開頭） |
| `c37dd28` | feat: 播放平台切換（Spotify/YouTube）、搜尋快取；fix(security): 依賴改精確釘版（Pillow 12.3.0 補 13 個 CVE、python-dotenv 1.2.3）、新增生成節流 `ratelimit.py`、定位查到伺服器自己；順帶修好被擋下的點擊會清掉既有歌單 |
| `ccce66c` | fix(security): OAuth 補上綁定瀏覽器的 `state`（防授權碼注入／login CSRF）、`?error=` 改走白名單（原本可在登入頁警告框注入釣魚連結與追蹤圖片，已實測確認）、`X-Forwarded-For` 改用 `ipaddress` 驗證（只收 is_global）、BYOK 步驟卡拆兩半中間夾原生 `st.code()`（自製複製鈕一直是死的，Streamlit 會濾掉 onclick）、`.claude/` 從 git 索引移除；feat: 出圈演算法 Phase 1＋2 同批進版——擴大已知宇宙（180 → 700+ 首）、`curate_tracks()` 驗證鏈＋流行度天花板＋EPC 重排、雙通道 prompt（去錨定／相鄰場景）、排除清單瘦身尾置、補生成迴圈、LLM 自評 fame 取代 popularity、spotipy 重試關閉（429 的 Retry-After 是 6 小時，會凍住整頁） |
| `e839b19` | perf: 生成時間 ~26s → ~8–10s（Gemini thinking 關閉、client 快取、地理資訊預抓、profile 並行）；fix: 時區改用 IP 偏移，不再顯示 UTC |
| `aa54504` | copy: 主表單標題改成「想成為你專屬的歌單」 |
| `9924520` | fix: 符桿收進符頭裡（桿底兩角落在旋轉橢圓外，從符頭右下角凸出來） |
| `5c1184a` | fix: 重畫 `SVG_NOTES`——符桁與符桿差 0.5px 沒接上（連通分量檢查：綠色 2 塊 → 1 塊） |
| `de76fa6` | feat: 主表單 Hero（插圖 + 漸層標題）、垂直間距改三級制 8/16/32（移除 .y2k-gap） |
| `1cf94d6` | fix: 情境標題的括號補充整段換行，不再斷在「給 AI／分析）」中間 |
| `d9406e5` | fix: 右欄重複標題真的藏起來（Streamlit 對 stMarkdownContainer 設了 visibility:visible） |
| `33d4bf3` | fix: 推薦網格卡片等高（按鈕對齊）；feat: 隱私說明收進 help tooltip、情境欄文案改版 |
| `87a3329` | fix: 曲目卡理由標籤被當成程式碼區塊（HTML 縮排 + 空的 album_html）、無理由時不畫空標籤；feat: 授權失敗說明改成失敗才顯示、投射問題按鈕貼齊題目、expander 內距加大 |
| `4e53694` | feat: 手機視覺層級（粗框只給主 CTA）、理由標籤對比修正、定位失敗優雅降級、訪客模式不顯示新藝人比例、maxUploadSize=10 |
| `7d97353` | feat: 移除活動 pills、兩欄標題字級統一 16px、情境雙框對齊、標題錨點隱藏 |
| `be5e05a` | feat: 設定情境改成漸進式揭露（情境+投射問題+生成按鈕在上，其餘 4 區摺疊帶即時摘要） |
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
