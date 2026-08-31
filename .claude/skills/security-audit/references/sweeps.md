# 掃描清單

這些是 2026-08-31 稽核實際跑過的檢查。每組都寫了「看到什麼算有問題」，
因為多數指令的**乾淨結果是沒有輸出**——不知道要看什麼的話，很容易把「沒輸出」
誤讀成「沒跑到」。

⚠️ 所有全庫 grep 都要排除 `.claude/worktrees/`：那裡有舊版程式碼的副本
（被 gitignore、`git status` 看不到，但 grep 撈得到）。看到路徑在那底下的先確認。

---

## 1. 祕密外洩

```bash
git log --all --oneline -- .env .streamlit/secrets.toml
git diff | grep -icE "postgres://|postgresql://|supabase\.co|sk-|AIza|client_secret *="
```

**有問題的徵兆**：第一條有任何輸出（祕密曾經進過版控，即使後來刪掉，歷史裡還在——
必須輪替那些金鑰，不是把檔案刪掉就好）。第二條非 0（正要 commit 的內容含祕密）。

順手確認 `.env.example` / `secrets.toml.example` 裡是佔位字串而不是真值，
而且**新加的祕密有補進範本**（上次 `SUPABASE_DB_URL` / `PERSIST_HMAC_SECRET` 就漏了）。

## 2. 危險呼叫與注入

```bash
grep -rn "eval(\|exec(\|pickle\|os.system\|subprocess\|shell=True\|__import__" --include=*.py . | grep -v "\.claude/"
grep -rn "execute(f\"\|execute(f'\|execute(.*%.*%\|\.format(" --include=*.py . | grep -v "\.claude/"
```

**有問題的徵兆**：第一條**任何**輸出都要看。第二條要判斷 f-string 內插的是不是常數
——`analyze_backend.py` 有幾處 `execute(f"...{tbl}...")`，但 `tbl` 來自寫死的 tuple，
那是安全的；內插使用者輸入才是問題。

## 3. XSS（注入 HTML）

```bash
grep -c "unsafe_allow_html" app.py
grep -n "escape" styles.py | head -30
```

**有問題的徵兆**：`styles.py` 裡有任何把 track/reason/使用者輸入直接放進 f-string
而沒過 `html_mod.escape()` 的 helper。逐個看 `track_card_html` / `track_list_html` /
`context_interpretation_html` / `results_header_html` 的內插點。

⚠️ Streamlit 的 `st.warning()` 等 alert **會渲染 Markdown**（雖然不允許 HTML）。
所以任何回顯到 alert 的值也要當成注入面——`?error=` 就是因此改走白名單的。

## 4. SSRF（對「資料裡帶來的網址」發請求）

```bash
grep -rn "requests\.\(get\|post\)\|urlopen\|httpx" --include=*.py . | grep -v "\.claude/" | grep -v test_
```

**有問題的徵兆**：任何一個目標網址不是寫死常數的呼叫。目前應該只有三處：
`ipwho.is`（IP 已用 `ipaddress` 驗過 `is_global`）、`open-meteo`（座標）、
`share_card.fetch_covers`（已有 `_is_spotify_cdn` 白名單 ＋ `allow_redirects=False`）。

⚠️ 白名單不能寫成 `endswith("scdn.co")`——`evil-scdn.co` 會過關。要比對帶點的
`.scdn.co`。⚠️ 沒有 `allow_redirects=False` 的話，白名單只驗第一個網址，跟著轉址走等於白驗。

## 5. 身分與授權（對應不變條件 1、2）

```bash
grep -n "user_key\|_effective_uk\|_persist_uk" app.py | head -40
grep -n "where user_key" db.py
```

**有問題的徵兆**：任何 DB 查詢的 `user_key` 不是伺服器端算出來的；任何寫入路徑
沒檢查 `persist_needs_consent`；`anon` 匿名鍵沒有帶 `gen_id`（會讓不同訪客的回饋
在主鍵上互撞、被 upsert 蓋成一列）。

## 6. 節流與濫用防護（對應不變條件 3）

```bash
grep -n "ratelimit\." app.py
```

**有問題的徵兆**：生成流程走 `consume()` 而不是 `acquire()`——前者只看個人額度，
全站閘門等於沒有。`consume()` 保留原始語意是因為被既有測試釘住，有一條測試專門
標示這個差別。

## 7. 日誌洩密（對應不變條件 6）

```bash
grep -rn "print(" --include=*.py app.py spotify_api.py recommend.py db.py share_card.py
```

**有問題的徵兆**：印出 cookie／標頭的**值**（只能印名稱）、原始 Spotify ID、
訪客的原始 UUID、例外的**訊息**（只能印型別——訊息可能含連線字串或資料內容）。

## 8. 依賴

```bash
grep -v "^#" requirements.txt | grep -v "^$"
pip list --outdated 2>/dev/null | head -20
```

**有問題的徵兆**：直接依賴用 `>=` 而不是 `==`（雲端會裝到你沒測過的版本，而且
Dependabot 對範圍幾乎不會動作）。新加的套件沒釘版。

⚠️ `psycopg-pool` 是**獨立套件**，`psycopg[binary]` 裡沒有——加連線池相關的東西時
容易漏。漏了不會 crash（被 try/except 接住），但持久化會靜默失效。

## 9. 資料庫端的權限姿態

```sql
select tablename, rowsecurity from pg_tables where schemaname = 'public';
select grantee, table_name, privilege_type from information_schema.role_table_grants
 where table_schema = 'public' and grantee in ('anon', 'authenticated');
```

**有問題的徵兆**：任何 `rowsecurity = false`，或 `anon`/`authenticated` 有任何授權筆數。

⚠️ 兩者都要看：**`TRUNCATE` 不受 RLS 約束**，所以光開 RLS 不夠，權限一定要一起 revoke。
上次稽核時 `anon` 沒有 SELECT/INSERT/UPDATE/DELETE（讀寫路徑本來就斷的），卻仍握有
`REFERENCES, TRIGGER, TRUNCATE`。

跑法見 `verify-recipes.md` 的「對真實資料庫的唯讀查詢」。

## 10. 上傳與外部輸入

```bash
grep -n "file_uploader\|uploaded\." app.py
```

**有問題的徵兆**：採信 `uploaded.type`（瀏覽器宣告的值）或副檔名。
`file_uploader(type=[...])` **只比對副檔名**，內容是什麼它不管。
應該走 `_sniff_image_mime()` 以檔頭判定。

⚠️ 讀檔用 `getvalue()` 不用 `read()`——後者會把讀取位置移到結尾，之後再讀就是空的。
