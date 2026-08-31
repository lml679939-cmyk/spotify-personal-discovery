# 回饋＋歷史持久化（資料庫版）規格／計畫

> 狀態：**規劃中，尚未動工**。決策已定（2026-08-23）：**Supabase Postgres**、
> **歷史一起搬進 DB**、**完整隱私流程**。前置條件是 Phase 0（建 Supabase 專案＋設 Secrets）。
> 先讀 CLAUDE.md 的「使用者回饋」「歷史去重」「Credential 管理」三段。

## 為什麼是資料庫（不是 Spotify 歌單）
使用者定調：**「數據要在自己手上、拿來優化演算法」**。兩個硬理由：
1. **跨使用者聚合分析只有 DB 做得到**。Spotify 歌單鎖在各自帳號，app 只讀得到「當下登入
   這一位」，讀不到全體 → 無法蒐集回饋來調演算法。
2. **靠歌單名字找回很脆**。現有歷史用 `HISTORY_PLAYLIST_NAME` 靠名字找
   （[spotify_api.py:843](spotify_api.py:843)）——**使用者一改名就失聯**（歷史消失或每次重建
   重複歌單）。這是**現在就存在的 bug**，順便一起修。

## 目標
- 登入使用者的**回饋**（👍/👎/🎧）與**推薦歷史**跨 session、跨裝置留存。
- **把每筆回饋的「情境」也存下來**（fame、是否出圈、橋接理由、語言/曲風/模式）——這是能回頭
  分析「哪種出圈橋接被按讚、使用者愛 fame≤2 還是 fame3」的**演算法金礦**，也是這整件事的真正價值。
- 站方存資料 → **走完整隱私流程**（雜湊 ID＋告知同意＋刪除鍵）。

## 技術選型
- **DB：Supabase（Postgres 免費 500MB）。**
- **連法：直接 Postgres 連線字串**（`psycopg` 或 `st.connection("sql")`），不用 supabase-py REST
  ——這樣**換 Neon 只要改連線字串**（符合選型時的承諾）。
  ⚠️ Supabase 對 serverless 要用**連線池（pooler，Transaction mode，port 6543）**的連線字串，
  不要用直連 5432，否則連線數會爆。
- **連線字串＋祕密**放 Streamlit Secrets（跟 `GEMINI_API_KEY` 同一處）：
  - `SUPABASE_DB_URL`（pooler 連線字串）
  - `PERSIST_HMAC_SECRET`（雜湊 Spotify id 用，見「隱私」）
- 新增依賴：`psycopg[binary]==<釘版>` ＋ `psycopg-pool==<釘版>`（照 requirements.txt 的 `==` 釘版紀律；⚠️ pool 是獨立套件，`psycopg[binary]` 裡沒有）。

## 身分：雜湊後的 Spotify user id
- `user_key = HMAC-SHA256(PERSIST_HMAC_SECRET, spotify_user_id)`（`sp.current_user()["id"]`）。
- **不可逆、穩定、跨裝置一致**；DB 就算外洩也不直接對到「這是誰的 Spotify」。
- ⚠️ 回饋內容＋曲目樣態仍可能有一定識別性 → 靠「資料最小化＋可刪除」把風險壓到最低。

## Schema（Postgres）
```sql
create table consent (
  user_key       text primary key,
  consented_at   timestamptz not null,
  consent_version int not null           -- 條款改版時 bump，觸發重新同意
);

create table feedback (
  user_key    text not null,
  track_key   text not null,             -- _track_key = (正規化歌名, 正規化主藝人)
  title       text not null,
  artist      text not null,
  state       text not null,             -- like / dislike / heard（單選）
  -- ↓ 演算法探勘用的情境快照（回饋當下那首歌的來歷）
  fame        int,
  is_discovery boolean,
  reason      text,                       -- 橋接理由
  ctx         jsonb,                      -- {guest, lang, genre, fame_mode, new_ratio, mood_energy, mood_valence}
  updated_at  timestamptz not null,
  primary key (user_key, track_key)
);
create index feedback_mine_idx on feedback (state, is_discovery, fame);  -- 聚合分析用

create table history (
  user_key       text not null,
  track_key      text not null,
  title          text not null,
  artist         text not null,
  recommended_at timestamptz not null,
  primary key (user_key, track_key)
);
create index history_user_time_idx on history (user_key, recommended_at desc);

-- 歌單層級訊號（2026-08-23 加）：每次生成一列，gen_id 為鍵。見「回饋訊號設計」段
create table playlist_feedback (
  user_key   text not null,
  gen_id     text not null,
  rating     int,                          -- 3 段滿意度 1/2/3（看一眼就能答、不需聆聽）
  saved      boolean not null default false, -- 點了「加入 Spotify」＝想收藏整份（行為訊號）
  copied     boolean not null default false, -- 保留欄位（複製是 st.code 客戶端動作、目前抓不到）
  num_songs  int,
  ctx        jsonb,                         -- 意圖快照（同 feedback，供按意圖切片分析）
  created_at timestamptz not null,
  updated_at timestamptz not null,
  primary key (user_key, gen_id)
);
create index playlist_fb_mine_idx on playlist_feedback (rating, saved);
```
- **current-state（upsert）而非 append-only**：v1 夠用（涵蓋「重建＋基本聚合」）。要做時間序列
  深度分析再加一張 append-only events log（列在 Phase 5）。
- ⚠️ **`ctx` 只存結構化派生訊號**：語言、曲風、探索度(`fame_mode`)/新藝人%(`new_ratio`)、**心情雙軸
  (`mood_energy`/`mood_valence`，1-10)**。**刻意不存**原始情境自由文字、投射答案、MBTI/星座/血型
  ——自由文字可能含個資、星座血型是準識別碼且對品味零效度。心情雙軸是唯一「結構化＋有效度＋識別風險低」
  才收的表單訊號（2026-08-30 加，commit 見 changelog）。資料最小化。
- `playlist_feedback` 已由整合測試建好、上線驗過（coalesce/OR 累積、中文 jsonb、delete_all 清除）。

## 回饋訊號設計（2026-08-23 研究後定案）
**問題**：使用者拿到歌單 ≠ 已聆聽，所以逐首「喜歡/不喜歡」是**過早的訊號**，當下答得出的
只有「聽過/沒聽過」。文獻佐證：Netflix 5 星→讚/倒讚評分量 +200%（粗粒度＋低成本＝更多回饋）；
Spotify/Deezer 幾乎不靠明確評分，靠**行為訊號**（收藏→聽完→重聽→加入歌單，skip 當警報），
且訊號要放在**意圖**脈絡讀。量表粒度研究：5–7 選項是甜蜜點，再細邊際遞減，且「粒度的好處會被
填答率稍降就抵銷」——所以 **0–100 不用（極端值＋低填答），改粗粒度**。

**本站的設計**（受限於「歌在外部播放、抓不到 skip/聽完」）：
1. **主訊號＝歌單層級行為**：點「加入 Spotify」→ `_persist_playlist(saved=True)`（不管 403，
   意圖已表達）。二元、無極端值、比嘴巴說可信。（複製走 st.code 客戶端複製鈕，抓不到，故只抓加入。）
2. **主動打分＝3 段**（不是 0–100）：歌曲清單之後「這份合你今天的味嗎？」→ 三顆**文字** pill
   「不太合／還可以／很對味」→ `rating` 1/2/3（⚠️ 用文字不用 sentiment 圖示——使用者反映圖示看不出意義）。
   看一眼就能答。**登入者同意後才顯示；訪客也顯示但匿名收**（`user_key="anon"`，見「訪客資料」段）。
3. **單曲層級**：🎧 保留（當下答得出＋出圈校準）；👍/👎 保留但**定位成「聽了再回來標」**
   （文案已改）——稀疏但精準，不當主要滿意度指標。
4. **分析用穩健統計＋按意圖切**（`ctx`）。**已包成 `analyze_backend.py`**（唯讀 CLI，本機連同一個 DB
   跑 `python analyze_backend.py`）——自動印滿意度中位數、按 fame_mode/語言/曲風/心情雙軸切、逐首回饋
   （出圈/fame 按讚率、top 歌手）；`--min-n` 濾掉小樣本。下面是它內含查詢的骨架：
```sql
-- 3 段滿意度用中位數（不是平均，免得極端值主宰），並按意圖(探索度)切開
select ctx->>'fame_mode' as mode,
       count(*) n, percentile_cont(0.5) within group (order by rating) as median_rating,
       avg(saved::int) as save_rate
from playlist_feedback where rating is not null group by ctx->>'fame_mode';
```
```sql
-- 收藏率 by 探索度/新藝人%——哪種意圖的歌單使用者最想收
select ctx->>'fame_mode' as mode, ctx->>'new_ratio' as new_ratio,
       count(*) n, round(100.0*avg(saved::int),1) as save_pct
from playlist_feedback group by 1,2 order by save_pct desc nulls last;
```

## 模組分層
- 新增 `db.py`：所有 DB 呼叫集中在這（連線快取、upsert、讀取、刪除、trim）。**不 import streamlit
  的 UI 元件**（連線用 secrets，可單元測試——純轉換邏輯 rows↔dict 抽成純函式）。
- `app.py`：登入後接讀取/同意閘；回饋 handler 接寫入；生成接歷史 upsert。
- 保留 `recommend.py` / `spotify_api.py` 不碰 DB（分層乾淨）。

## 讀（登入時）
1. 取 `user_key`。查 `consent`。
2. **沒同意** → 顯示同意 UI，**在同意前一律 session 級、不讀不寫 DB**。
3. **已同意** → 背景並行載入（比照 `start_profile_prefetch`）：
   - `feedback` → 重建 `st.session_state["track_feedback"]`（用 title+artist 重建 `_track_key`）。
   - `history` → 塞回 session 歷史，供去重與 prompt。
4. DB 讀失敗 → 靜默降級成空 session（跟全新 session 一樣），生成照跑。

## 寫（回饋變動時）
- 使用者點 pill → **樂觀更新 session dict**（UI 立即反映）→ **背景執行緒** upsert 一列 feedback
  （含 fame/is_discovery/reason/ctx 情境快照，從當下那張卡與表單狀態抓）。單選＝同一 `track_key`
  upsert 覆蓋 state。
- 取消回饋（再點一次）→ delete 該列。

## 寫（生成時，歷史）
- 生成完 upsert 這批的 history 列（取代 `append_to_persistent_history` 的歌單寫入）。
- 回饋曲目本來就併進 history（程式端排除）→ DB history 拿到聯集。
- **trim**：每位使用者留最新 `PERSISTENT_HISTORY_MAX=500` 列，多的 `delete ... where recommended_at < …`。

## 隱私流程（完整）
- **同意閘**：本功能上線後首次登入 → 顯示告知＋一次性勾選
  「我同意本站儲存我的回饋與推薦歷史以改善推薦（資料經雜湊、可隨時刪除）」→ 寫 `consent`。
  未同意前只用 session 級。`consent_version` bump 時要求重新同意。
- **文案改**：登入頁「不儲存任何資料」那句 → 改成準確版（登入且同意後會存雜湊回饋/歷史於本站 DB），
  附一段簡短隱私說明。⚠️ 訪客與「未同意的登入者」仍是零留存，文案要分清楚。
- **刪除鍵**：sidebar/設定放「刪除我在本站的所有資料」→ 確認後 `delete from feedback/history/consent
  where user_key=…`。
- **雜湊 id**：只存 `HMAC(spotify_id)`，永不存原始 id。

## 降級（絕不因為 DB 壞掉就讓生成失敗）
- 所有 DB 呼叫各自 try/except、失敗 → log 一行 + 回退 session 級（比照 `append_to_persistent_history`
  現有的 try/except 態度）。連線斷、Supabase 額度爆、同意未載入 → 一律當「這次沒有持久化」處理。

## 現有歷史的遷移
- 舊使用者的歷史在 Spotify 歌單（若當初 items-write 沒被 403）。首次登入做**盡力而為的一次性匯入**：
  `_get_history_playlist_id` 找得到（沒被改名的）就讀進 DB，之後 DB 為準；改過名的找不到就算了。
- **歌單要不要繼續雙寫？** 兩個選項（實作時再定）：(a) 停掉歌單、DB 唯一真相；(b) 繼續雙寫歌單
  當「使用者看得到的探索歷史」便利品、但演算法只讀 DB。建議 (b)，成本低又保留使用者體驗。

## 訪客資料
訪客沒有穩定身分 → 無法跨 session 重建個人化。但訪客是主要、不限人數的模式，用量最大，
其滿意度對**聚合探勘**很有價值。
**核心原則：想要「資料」用匿名收（不需同意）；想「跨 session 記住這個人」才需要同意卡。**
匿名、不可回溯的聚合在 ePrivacy/GDPR 下不需同意（同意是針對「在裝置存持久 id 追蹤個人」）。所以未同意的
訪客也照收匿名聚合、不默認追蹤——別因為「我出了 API 錢」就想默默記住訪客，那在法律與本站姿態上都站不住。

- ✅ **訪客歌單滿意度（匿名）**：`_persist_playlist` 對未同意訪客用固定 `user_key="anon"`＋唯一 `gen_id`，
  帶 `ctx` 意圖快照。分析走 `where user_key='anon'`。
- ✅ **訪客逐首 👍/👎/🎧（匿名聚合，不需同意）**：未同意訪客的逐首回饋寫 `feedback` 表、`user_key="anon:"+gen_id`。
  ⚠️ **gen_id 必須進 key**：feedback 主鍵是 (user_key, track_key)，用固定 `"anon"` 會讓不同訪客/生成對同一首歌
  互撞成一列；加 gen_id 各自成列可計數、同份歌單內仍唯一。分析走 `where user_key like 'anon:%'`
  （＝哪些歌/歌手在哪種 `ctx` 意圖下被讚/倒讚，調**選歌**用）。歷史仍 session 級（整份聆聽史綁 id 較具識別性）。
- ✅ **同意後升級為記名（Phase 5，per-browser）**：自建 localStorage 元件給「每瀏覽器」一個匿名代號 `guest_uk`
  （**不跨裝置**），同意後逐首回饋/歷史/歌單評分都記名持久化、跨 session 讀回。**同意卡文案以好處領頭**
  （越用越準、不再推你看過的），隱私事實仍完整揭露。詳見文末「Phase 5」段。

## 測試
- **純邏輯（pytest）**：rows ↔ `track_feedback`/history 的往返（`_track_key` 重建、單選覆蓋、trim 邊界）。
  DB 用假 client / 交易回滾的測試 schema。
- **降級注入**：DB 呼叫拋例外 → 生成正常、UI 降級回 session。
- **同意閘**：未同意 → 不寫 DB；同意後 → 寫。
- **手動**：A 裝置給回饋＋同意 → B 裝置登入 → 回饋/歷史都在；按刪除 → 兩邊清空。

## 分階段落地
- ✅ **Phase 0（已完成，使用者做）**：Supabase 專案建好、DDL 跑好（含後加的 `playlist_feedback`）、
  pooler(Session,5432) 連線字串＋`PERSIST_HMAC_SECRET` 填進 Streamlit Secrets 與本機 `.env`。**DB 已生效**。
- ✅ **Phase 1（`db.py`，已上線）**：user_key 雜湊、key_str、feedback/history/consent/**playlist_feedback**
  的 upsert/delete/load/trim/delete_all、`is_enabled`/`get_pool`/`connection()`/`close_pool`（psycopg 與 psycopg_pool 皆延遲載入）。
  純邏輯＋假 conn 測試（`test_db.py`），且**對真實 Supabase 跑過整合測試**（連線/schema/中文 jsonb/
  coalesce+OR 累積/delete_all 全對）。
- ✅ **Phase 2（`app.py` 接線，已上線並實測）**：登入算 `persist_uk`（HMAC）；`_persist_login_sync`
  （同意閘＋讀回回饋/歷史 seed session）；**同意卡 `_render_consent_banner`（結果區頂端，粉底卡）**＋
  刪除鍵 `_render_persist_sidebar`（sidebar）；`_render_feedback` 變動→`_persist_feedback`（帶 `ctx`）；
  生成→`_persist_history`＋trim（與 Spotify 歌單雙寫）；**歌單層級 `_persist_playlist`（滿意度/加入行為）
  ＋`_render_playlist_rating`（3 段文字，清單之後）**。**訪客滿意度匿名收**（`user_key="anon"`）。全部
  try/except 降級。**2026-08-31（MED-4）改用連線池**：舊版單一全域連線會讓不同使用者的交易互相污染（A 的 commit 提交 B 的半成品、B 出錯則 A 一起失敗），已對真實 DB 驗證前後差異，見 CLAUDE.md「DB 連線」段。`psycopg[binary]==3.3.4` ＋ `psycopg-pool==3.3.1` 進 requirements。
- **Phase 3（待資料累積，下一步）**：拿 `feedback`/`playlist_feedback` 回頭**調演算法**（中位數、按 `ctx`
  意圖切）——這才是持久化的目的。**分析工具已就緒＝`analyze_backend.py`**（`python analyze_backend.py`），
  等真實流量累積直接跑。查詢原則見「回饋訊號設計」段。
- **Phase 4（選）**：停掉或維持雙寫 Spotify 歷史歌單的決定；登入頁文案（目前揭露靠同意卡，可接受）。
- ✅ **Phase 5（全部完成、已上線）**：訪客的**逐首回饋/歷史/歌單評分**持久化——**每瀏覽器**匿名代號
  （localStorage 自建元件、**不跨裝置**、同意後記名；未同意走匿名聚合）。push＋Reboot＋正式站驗過。詳見文末「Phase 5」段。
  （events-log 深度分析表仍另案。）

## 工作量粗估
Phase 1–3 約 1–2 天含測試（多數複雜度在同意閘與降級路徑，DB CRUD 本身不難）。**前提是 Phase 0
你先把 Supabase 開好、連線字串就位。** 演算法探勘（拿 `feedback` 表回頭調權重）是這之後的獨立收穫。

---

# Phase 5：訪客跨 session 持久化（per-browser localStorage id）

> 狀態：**全部完成並已上線正式站（2026-08-30，push＋Reboot＋真實 DB 驗過）。** 未同意訪客的逐首回饋
> 後來也加了匿名聚合（`anon:"+gen_id`）＋同意卡文案改「賣好處」（commit `cc7cc13`）。「忘記我」localStorage
> 輪替＝使用者拍板**不做**。
> 決策已定：**只到「每瀏覽器」、不跨裝置**（取捨見下段）；DB 只存 `HMAC(guest_local_id)`；**先同意才寫**；
> 元件**自建**（vanilla JS、零第三方）。維護前先讀 CLAUDE.md「OAuth state」（`_browser_secret` 為何不夠）、
> 「播放點擊計數」（iframe sandbox 的教訓）、「濫用防護」（`_rate_key` 不可退回固定字串那課）。

## 目標
給訪客一個**存在瀏覽器 localStorage、自己產生的匿名代號**，讓訪客的逐首回饋（👍/👎/🎧）與歷史
能跨 session 留存，且 `playlist_feedback` 能**按「同一瀏覽器」分組**——解掉「1 個人評 50 次
vs 50 個人各評 1 次」（現況見上方「訪客資料」段與 CLAUDE.md 對訪客資料的限制）。

## 為什麼只到「每瀏覽器」、不跨裝置（取捨已定案）
「跨裝置 ＋ 匿名 ＋ 精確」三者不可能同時成立。唯一能跨裝置串匿名訪客的手段是**瀏覽器指紋**，而指紋：
① 本來就不準（碰撞＋漂移＝**假精確**，比 per-browser 更糟）；② 在本平台**拿不到料**（Streamlit Cloud
連 client IP 都拿不到，見 CLAUDE.md「位置偵測」）；③ 是隱私紅線、與本站一路的姿態相反。
要「精確跨裝置每人資料」的正解＝**登入**（`user_key=HMAC(spotify_id)` 本就跨裝置精確），
施力點是**擴大登入涵蓋**（把在意的人加進 25 人白名單），不是追蹤訪客。故訪客定在 per-browser，
對「調旋鈕」已夠準——把「全 anon」變「按瀏覽器分組」已解掉九成的「分不出人」，剩一成（同人多裝置）
幾乎不會翻轉「哪個 fame_mode 中位數較高」這種結論。

## 5.0 Spike 結果（已驗證，是後續的地基）
自建雙向元件 `guest_id_component/index.html`（vanilla JS、手刻 Streamlit postMessage 協定、
零第三方、`setFrameHeight(0)` 隱形）：
- ✅ 元件在**雲端巢狀 iframe** 能渲染、把 localStorage id 回傳 Python（本機 `spike_guest_id.py`
  ＋正式站 `?spike=guestid` 臨時探針都驗過，探針已移除）。
- ✅ **整頁重整（新 session）id 不變**——localStorage 在雲端同源生效（外層 app iframe sandbox
  含 `allow-same-origin`＋`allow-scripts`，元件同源、共用同一份 localStorage）。
- ✅ 新元件靜態路由**自動熱更新即註冊、不需 Reboot**。
- ⚠️ 回傳是**非同步**：首次 render 元件回 `None`，元件 postback 後觸發 rerun 才拿到 id——
  接線時必須能吃「第一輪 None、第二輪才有值」，不能假設一進來就有 id。
- 讀不到 localStorage（無痕/被擋）→ 元件回 `null`（try/catch 寫好；本機難強制觸發，以推理＋雲端未報錯為準）。

## 身分與雜湊
- 瀏覽器首訪：元件在 localStorage 生一個 UUID（key `sc_guest_id`；`crypto.randomUUID()` 優先）。
- `guest_user_key = HMAC(PERSIST_HMAC_SECRET, uuid)`（`db.guest_user_key()`，**沿用登入的同一把雜湊**）
  ——DB 只存雜湊，原始 UUID 只活在瀏覽器。
- 清 localStorage／無痕 ＝ 新代號（可接受；訪客本就不保證延續）。

## 資料模型（改動很小，不建新表）
- `feedback`／`history` 兩表**本就以 `user_key` 為鍵、與登入共用**，訪客現在只是被跳過 →
  改成走 `guest_user_key` 即可。
- `playlist_feedback`：訪客列從固定 `anon` 換成 `guest_user_key`。**保留對既有 `anon` 舊列的相容**——
  舊 anon 列留著（＝升級前的訪客聚合，`where user_key='anon'` 仍查得到），新列可按瀏覽器分組。
- ⚠️ **分析語意變更要寫進註解**：升級後訪客資料**可按瀏覽器分組**，但仍**不是「人」**
  （多裝置＝多代號），分析查詢與文件都要講清楚，別誤當「不重複使用者」。

## 隱私升級與同意（這是明確的降級，必須誠實揭露）
現況承諾「純聚合、不可回溯」→ Phase 5 後訪客資料**可回溯到那個瀏覽器**（非到人、不跨裝置）。因此：
- **訪客揭露同意卡**（首次要寫入前才出現）：誠實文案——「我們用一個存在你**這台瀏覽器**的隨機代號
  記住你的回饋與歷史，好讓推薦更準。這**不是帳號、不跨裝置、不含個資**，可隨時一鍵清除。」
  同意前維持今天行為（session 級 ＋ 匿名 `anon` 聚合）。**實作後改成「賣好處」文案**（好處領頭、
  隱私事實仍完整揭露），見「訪客資料」段與 `_render_consent_banner`。
- **刪除控制**：sidebar 的「刪除我在本站的所有資料」對訪客走 `db.delete_all(guest_user_key)`（清 DB 資料）。
  ⚠️ **不清 localStorage 的 `sc_guest_id`**——localStorage 輪替**決定不做**（見「子階段」末列），所以同瀏覽器
  再訪是同一個空身分、需重新同意。資料已可刪＝隱私責任已盡。
- **文案已改**：未同意訪客評分標「匿名統計」；同意卡揭露 localStorage 代號的存在。登入頁「Token 只存記憶體」
  未改（那是講 Spotify token、與 DB 持久化無關，不誤導）。

## 紅線（綁既有教訓）
- **讀不到 id → 只降級成 session 級，絕不退回固定字串**（否則全體共用一個 id、互相污染，
  同 CLAUDE.md `_rate_key()` 那課）。
- **localStorage 空的（無痕）→ 優雅降級**，比照整個持久化層「壞掉就降級、絕不讓生成失敗」。
- 元件回傳**非同步** → 接線要容忍第一輪 None（見 5.0 spike 記錄）。

## 子階段
- ✅ **5.0 Spike**（gate）：`guest_id_component/` 自建元件 ＋ 本機/雲端驗證（重整 id 不變、不需 Reboot）。
- ✅ **5.1**（inert）：`db.guest_user_key()`＝`HMAC(secret,"guest:"+uuid)`（+3 tests）；`_guest_local_id()`
  包住元件並吃「非同步首輪 None」；`_ensure_guest_uk()` 解析並快取 `guest_uk`（讀不到→不設、降 session，
  絕不退固定字串）；元件 keyed＋`position:absolute` 隱形（零版面 footprint、仍執行）。
- ✅ **5.2**：把登入持久化路徑一般化到訪客——`_effective_uk()`（登入 persist_uk／訪客 guest_uk）、
  `_persist_login_sync`→`_persist_sync`；逐首👍/👎/🎧＋歷史＋歌單評分**已同意→記名 `guest_uk`**、
  **未同意→匿名 `anon`**（維持改版前）；訪客版同意卡文案（per-browser、不跨裝置）；跨 session 同意載回。
  **對真實 DB 驗過**（同意→逐首/歷史/評分全寫 guest_uk、重整不重問）。
- ✅ **5.3（併入 5.2）**：訪客 `playlist_feedback` 已同意走 `guest_uk`、未同意走 `anon`，舊 anon 列相容保留。
- ✅ **5.4**：測試（`guest_user_key` 已測；路由是 Streamlit glue，走真實 DB 整合驗證）＋ 文件（CLAUDE.md、
  README、本檔）＋ 文案定稿。
- ✅ **後續（commit `cc7cc13`）**：未同意訪客的逐首回饋也走**匿名聚合**（`anon:"+gen_id`，見「訪客資料」段）；
  同意卡文案改「賣好處」（好處領頭、隱私事實仍完整揭露）。
- ❌ **決定不做**：「忘記我」的 localStorage **輪替**（刪除鍵已清 DB 資料＝隱私責任已盡，只差沒清瀏覽器 uuid；
  輪替純體驗、價值不足，使用者拍板不做）。要做得給 `guest_id_component` 加 reset 指令。**別再當待辦重提。**

## 測試策略（實際採用）
- **純邏輯（pytest）**：`guest_user_key` 雜湊穩定性/命名空間/不洩漏（`test_db.py` +3）。路由是 Streamlit glue，
  不硬做單元測試（比照 app.py 慣例）。
- **真實 DB 整合驗證**（本機 app 連同一個 Supabase，已跑過）：未同意訪客 👍 → `anon:gen_id` 記入；同意卡出現
  → 同意 → 逐首/歷史/評分全寫 `guest_uk`（非 anon）；重整/重啟 → 同一把 key、同意不重問；刪除鍵 → DB 該 key 列清光。
- **雲端**：正式站 `?spike=guestid` 探針驗過元件在雲端 iframe 可行（探針已移除）；上線後訪客同意卡實地出現。
