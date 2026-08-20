# CLAUDE.md — AI 開發者交接文件

本文件供 AI 助手（Claude / 其他 LLM）在接手本專案時快速理解架構與注意事項。

## 專案概覽

**Spotify Personal Discovery** — 個人化音樂推薦 Streamlit Web App。

- **主要入口**：`app.py`（Streamlit UI 層）
- **模組拆分**：`recommend.py`（prompt/Gemini/去重，無 Streamlit 依賴、可單元測試）、`spotify_api.py`（OAuth/搜尋/歌單/歷史）
- **樣式集中管理**：`styles.py`（Y2K/Retro Pop 主題）
- **測試**：`test_recommend.py`（86）+ `test_spotify_api.py`（22）+ `test_styles.py`（9）+ `test_app.py`（23），共 140 tests
  ⚠️ `test_app.py` 會 import `app.py`＝把登入頁渲染一遍（約 5s，不發網路請求）。純邏輯請放 `recommend.py`。
- **語言**：Python 3.12+
- **框架**：Streamlit >= 1.57（`st.expander(key=...)` 需要）
- **外部 API**：Spotify Web API（via Spotipy）、Google Gemini 2.5 Flash
- **部署**：Streamlit Community Cloud — `https://spotify-lml.streamlit.app`
- **GitHub**：`https://github.com/lml679939-cmyk/spotify-personal-discovery`
- **使用者偏好語言**：繁體中文

## 交接：先讀這 5 分鐘

**跑起來**
```powershell
streamlit run app.py                    # 本機開發（.env 要有 GEMINI_API_KEY / SPOTIFY_*）
python -m pytest -q                     # 140 tests，改任何 .py 都要跑
```

**照任務找地方**

| 你要做的事 | 先看 | 一定要先讀的段落 |
|---|---|---|
| 改推薦品質／出圈程度 | `recommend.py` 的 `build_prompt()` / `curate_tracks()` | 「出圈演算法」整段 |
| 改版面、間距、顏色 | `styles.py`（CSS 全在 `_build_global_css()`） | 「版面幾何」「視覺層級」（含垂直間距三級制） |
| 改 Spotify 相關 | `spotify_api.py` | 「Spotify API 限制」「速率限制與 spotipy 重試」 |
| 查為什麼很慢 | 「生成速度」表 | 同段的量法（`_mark()` 印 stderr） |
| 時間顯示不對 | `_local_now()` | 「時區」 |

**最容易重蹈的覆轍**（每一條都真的發生過，細節在對應段落）
1. `datetime.now()` — 雲端是 UTC，台灣少 8 小時。一律 `_local_now()`。
2. Gemini 的 `thinking_budget=0` 被拿掉 — 生成時間會從 5s 變回 18s。
3. spotipy 預設重試 — 429 的 `Retry-After` 是 6 小時，urllib3 會真的睡下去，整頁凍住。
4. 注入的 HTML 有縮排 — Streamlit markdown 會當成程式碼區塊印出原始碼。
5. 憑感覺調 CSS — 這個專案的版面問題幾乎都要「量了才知道真正原因」。
6. prompt 裡塞長排除清單 — 遵守率會掉，保證要寫在程式端（`curate_tracks()`）。
7. 以為 `st.session_state` 撐得過 OAuth 來回 — **不會**，跳去 Spotify 再導回是整頁重載，
   session_state 整個重生。OAuth state 因此做成無狀態簽章，見「OAuth state」。
8. 把網址參數（`?error=`）原樣回顯到 `st.warning()` — alert 會渲染 Markdown，
   反引號可跳脫 code span，等於讓人在登入頁插釣魚連結。一律走白名單。

**現在還沒做的**（依價值排序）
- LLM 只提名歌手、曲目改由 `artist_albums` + `album_tracks` 取得，可根治歌名幻覺
  （代價：每位歌手約 3 個請求，要先解決共用 Client ID 的速率限制）
- 歌單寫入仍是 403（需要 Spotify Quota Extension，個人開發者實際上申請不到）
- 推薦結果的評分回饋（目前沒有任何學習訊號）

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
| `refill_exclude` | 補生成那一輪才有：把第一輪已經產出的 (曲名, 歌手) 傳回去，避免重複提名（僅 `build_prompt()`） |

### 出圈演算法（novelty，2026-08 Phase 1）

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
- **未來方向**：`artist_top_tracks` 已 403，但 `artist_albums` + `album_tracks` 還能用。
  改成「LLM 只提名歌手 → 曲目由 Spotify 提供」可以徹底消滅這類幻覺
  （代價是每位歌手約 3 個請求，要先解決上面的速率限制問題）。

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

**訪客模式**（`profile is None` → `_basic_dedupe()`）不走驗證鏈，但有兩個行為差異：
`_basic_dedupe` 會截斷到 `num_songs`，且去重鍵改用 `_track_key`（括號內容一律剝除），
所以同藝人的 `Interlude (I)` / `Interlude (II)` 會被視為同一首。都偏保守，不會出錯。

### 歷史去重
- 三個上限別搞混：`HISTORY_KEEP=200`（session 內保留幾筆）、
  `PROMPT_HISTORY_MAX=40`（其中真正寫進 prompt 的筆數，清單愈長 LLM 遵守率愈差）、
  `PERSISTENT_HISTORY_MAX=500`（Spotify 歷史歌單保留上限）。
  **完整的排除靠程式端 `curate_tracks()`，prompt 只是機率優化。**
- **Session 內**：`st.session_state["recommend_history"]`
- **跨 Session**（僅登入模式）：寫入 Spotify 私人歌單 `🤖 AI Discovery History`
- 訪客模式只有 session 內歷史
- 歷史歌單上限 `PERSISTENT_HISTORY_MAX=500` 首，超過時 `_trim_persistent_history()` 自動修剪最舊的
- 清空/修剪都用 `_playlist_replace_items()`：`PUT /playlists/{id}/items` 整批取代（失敗 fallback 舊 `/tracks` 路徑）

## UI 主題系統（Y2K / Retro Pop）

### styles.py 結構
- **CSS**：`_build_global_css()` — 在 f-string 內，所有 CSS `{}` 須寫成 `{{}}` 否則 Python SyntaxError
- **SVG 常數**：`SVG_CASSETTE`, `SVG_VINYL`, `SVG_NOTES`, `SVG_BOOMBOX`, `SVG_SPARKLE`
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
  - `form_hero_html()` — 主表單頁 Hero（音符/卡帶/黑膠三個圖示 + 漸層標題「想成為你專屬的歌單」）
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
  讓內容在 `min-height:130px` 內垂直置中；標題在全形冒號後插 `<br class="y2k-mbr">`，
  該 `<br>` 桌機 `display:none`、手機 `display:inline`，避免「方式一：直接開始（推薦，免」硬斷。
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

### 播放平台選擇（Spotify / YouTube）
- 結果區有「用什麼聽」的 radio（`key="play_platform"`），影響曲目卡的按鈕與分享文字。
  `recommend.play_link(track, platform)` 回傳 `(按鈕文字, 連結)`。
- **YouTube 走純搜尋網址**（`youtube.com/results?search_query=…`），不需要任何 API、
  不吃配額、不用 OAuth。⚠️ **不要改用 YouTube Data API**：`search.list` 一次 100 units、
  每天總共才 10,000 units，等於全站一天約 100 次搜尋——解析一份歌單就要 24 次。
  建立歌單（`playlists.insert` 50 + `playlistItems.insert` 50/首）約 800 units/份，
  全站一天 12 份。而且未通過 Google 驗證的 app 同樣有 100 人上限，沒有繞過授權問題。
- 選 YouTube 時，Spotify 搜不到的曲目不再顯示「🔍 搜尋」——換平台後通常真的播得到。

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
  自動定位/天氣永遠失敗、登入模式顯示結果時直接 NameError）：時區偏移取自 ipwho.is 的
  `timezone.offset`，存在 `st.session_state["geo_tz_offset"]`，查不到則退回 `DEFAULT_TZ_OFFSET`（+8）。
- 偏移是在 `_fetch_geo_weather()` 裡寫進 session_state 的，所以 `fetch_auto_context()`
  必須**先查地理位置再取時間**，順序反過來第一次會用到預設值。

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

> 標題已從 `st.subheader()` 改成 `styles.form_hero_html()`（圖示 + 漸層字，與登入頁同一套視覺）。

```
第一層（一進來就看到）  情境輸入（自動偵測 / 文字 / 圖片）→ 投射問題 → ✨ 生成按鈕
第二層（摺疊 expander） ⚙️ 推薦歌曲數 · 🎵 音樂偏好 · 😊 現在的心情 · 🧠 關於你
（活動情境 pills 已於 2026-08 移除——與「分享一下你的日常吧」文字欄重複）
```

- **摺疊標題帶即時摘要**（`🎵 音樂偏好　·　日語 · Jazz`）。摘要必須在 expander 建立**之前**算好，
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
- 兩欄情境輸入的高度要手動對齊：`text_area(height=106)` 對上 file_uploader 的實際高度（量出來 104±2）。
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
- 「⚙️ 推薦歌曲數」緊接在生成按鈕下方（程式碼也放在 `generate_slot` 之後、其他 expander 之前）。
  清除推薦歷史收在這一區內（罕用且不可逆）；歷史筆數顯示在生成按鈕下方。
- ⚠️ 別再用 `st.session_state["mbti"] = ...` 手動寫入——widget 有 `key` 時 Streamlit 會報錯。

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
| 情境文字 | `text_ctx` | 標籤「**分享一下你的日常吧（也可以上傳圖片給 AI 分析）**」，自由描述當下情境 |
| 自動偵測 | `auto_ctx` | 開啟後讀取 IP/天氣；隱私說明收在 `help=`（問號 tooltip），不再用 `st.caption` 佔版面。IP 取自 `X-Forwarded-For` 最左段＝**使用者可偽造**，`_client_ip()` 會用 `ipaddress` 驗過、且只收 `is_global` 的位址才拼進 `https://ipwho.is/{ip}`（⚠️ RFC 文件範圍 `203.0.113.x` / `2001:db8::` 在 Python 3.12+ 算 private，寫測試時很容易踩到） |
| 圖片上傳 | `uploaded` | Gemini Vision 分析氛圍 |
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
| `recommend.py` | prompt / Gemini / JSON 解析 / `curate_tracks()` 驗證鏈（純邏輯，無 Streamlit） | 是 |
| `spotify_api.py` | OAuth / 搜尋 / 歌單 / 跨 session 歷史 | 偶爾 |
| `test_recommend.py` | recommend.py 單元測試（pytest） | 改 recommend.py 時同步 |
| `styles.py` | Y2K 主題 CSS / SVG / HTML helpers | 偶爾 |
| `share_card.py` | IG Story 圖卡生成（Pillow） | 偶爾 |
| `.streamlit/config.toml` | Streamlit 主題 + toolbarMode | 偶爾 |
| `requirements.txt` | pip 依賴 | 偶爾 |
| `.env` / `.env.example` | 本地 credentials（不加入 git） | 否 |
| `CLAUDE.md` | 這份交接文件——**改了行為就順手更新這裡** | 是 |
| `README.md` | 對使用者/其他開發者的說明（部署、限制、功能總覽） | 偶爾 |
| `m1~m4_*.py` | CLI 測試腳本（非主程式） | 否 |

## 近期修改紀錄（最新在上）

| Commit | 說明 |
|---|---|
| （工作區，尚未 commit） | fix(security): `X-Forwarded-For` 改用 `ipaddress` 驗證（只收 is_global）；BYOK 步驟卡的 URI 移出 onclick 改走 `data-` 屬性；`.claude/` 從 git 索引移除。BYOK 步驟卡拆成兩半、中間改夾原生 `st.code()`——那顆自製複製鈕一直是死的（Streamlit 會濾掉 onclick），順帶讓 redirect_uri 完全不經過 unsafe_allow_html |
| （工作區，尚未 commit） | fix(security): OAuth 補上綁定瀏覽器的 `state`（防授權碼注入／login CSRF）；`?error=` 改走白名單（原本可在登入頁警告框注入釣魚連結與追蹤圖片，已實測確認） |
| （工作區，尚未 commit） | feat: 出圈演算法 Phase 2——雙通道 prompt（去錨定／相鄰場景／溫和校準）、排除清單瘦身尾置、補生成迴圈；fix: Spotify 拿掉 popularity 改用 LLM 自評 fame、補位卡上限、spotipy 重試關閉（429 的 Retry-After 是 6 小時，會凍住整頁）、提示訊息改走 session_state |
| （工作區，尚未 commit） | feat: 出圈演算法 Phase 1——擴大已知宇宙（180 → 700+ 首）、搜尋加取 popularity/artist ID、`curate_tracks()` 驗證鏈＋流行度天花板＋EPC 重排；fix: `app.py` 漏掉 `_local_now` import（自動定位一直失敗、登入模式顯示結果會 NameError） |
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
