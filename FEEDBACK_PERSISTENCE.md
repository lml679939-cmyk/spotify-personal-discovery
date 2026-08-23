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
- 新增依賴：`psycopg[binary]==<釘版>`（照 requirements.txt 的 `==` 釘版紀律）。

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
  ctx         jsonb,                      -- {lang, genre, mode/new_ratio, traits 派生訊號…}
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
```
- **current-state（upsert）而非 append-only**：v1 夠用（涵蓋「重建＋基本聚合」）。要做時間序列
  深度分析再加一張 append-only events log（列在 Phase 5）。
- ⚠️ **`ctx` 不存原始情境自由文字**（可能含個資）——只存**派生訊號**（語言/曲風/模式/fame）。資料最小化。

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

## 訪客資料（之後再說，Phase 5）
訪客沒有穩定身分 → 無法跨 session 重建。但訪客回饋對**聚合探勘**仍有價值：可存成匿名列
（無 user_key 或每 session 隨機 id）純供分析、不做個人化重建。需要自己的告知。**v1 不含**。

## 測試
- **純邏輯（pytest）**：rows ↔ `track_feedback`/history 的往返（`_track_key` 重建、單選覆蓋、trim 邊界）。
  DB 用假 client / 交易回滾的測試 schema。
- **降級注入**：DB 呼叫拋例外 → 生成正常、UI 降級回 session。
- **同意閘**：未同意 → 不寫 DB；同意後 → 寫。
- **手動**：A 裝置給回饋＋同意 → B 裝置登入 → 回饋/歷史都在；按刪除 → 兩邊清空。

## 分階段落地
- **Phase 0（你做，gating）**：建 Supabase 專案、跑上面的 DDL、把 pooler 連線字串與 `PERSIST_HMAC_SECRET`
  填進 Streamlit Secrets（本機 `.env` 也放一份供開發）。
- ✅ **Phase 1（`db.py`，已寫 2026-08-23）**：user_key 雜湊、key_str、feedback/history/consent 的
  upsert/delete/load/trim/delete_all、`is_enabled`/`get_conn`/`reset_conn`（psycopg 延遲載入）。
  **純邏輯＋假 conn 測試 21 條**（`test_db.py`，不需 Supabase）。
- ✅ **Phase 2（`app.py` 接線，已寫 2026-08-23）**：`import db`；登入算 `persist_uk`（HMAC，快取）；
  `_persist_login_sync`（同意閘＋讀回回饋/歷史 seed session）；`_render_persist_sidebar`（未同意→同意鈕、
  已同意→刪除鈕）；`_render_feedback` 變動時 `_persist_feedback`（帶 `last_gen_ctx` 情境快照）；
  生成時 `_persist_history`＋trim（與 Spotify 歌單**雙寫**）。全部 try/except 降級、死連線 `reset_conn()`
  自癒。`psycopg[binary]==3.3.4` 進 requirements。**⚠️ 現在 `db.is_enabled()` False → 全 no-op、
  行為與改版前一致；要等 Phase 0 填好 Secrets 才真的生效，屆時必做登入實測**（登入→同意→按讚→
  換裝置/清 session 再登入看回饋在不在→按刪除→確認清空）。
- **Phase 3（待實測後）**：登入頁文案微調（目前揭露靠同意閘，已可接受）＋（選）舊 Spotify 歷史一次性匯入。
- **Phase 4（選）**：停掉或維持雙寫 Spotify 歷史歌單的決定。
- **Phase 5（選，另案）**：訪客匿名探勘、events-log 深度分析表。

## 工作量粗估
Phase 1–3 約 1–2 天含測試（多數複雜度在同意閘與降級路徑，DB CRUD 本身不難）。**前提是 Phase 0
你先把 Supabase 開好、連線字串就位。** 演算法探勘（拿 `feedback` 表回頭調權重）是這之後的獨立收穫。
