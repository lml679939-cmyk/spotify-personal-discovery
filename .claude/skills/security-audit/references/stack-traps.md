# 這個技術堆疊的陷阱

每一條都是實際踩過、量過的。共同特徵是**本機正常、正式站壞掉**，或**看起來有防護、
實際上沒有**——所以光讀程式碼看不出來，要知道去量什麼。

---

## 1. Streamlit Cloud 的握手標頭沒有 `Cookie`，也沒有真實 client IP

**這是本專案最容易誤判的一條。** 雲端的 `st.context.headers` 實際內容：

```
['Accept-Encoding','Accept-Language','Cache-Control','Connection','Host','Origin',
 'Pragma','Sec-Websocket-*','Upgrade','User-Agent','X-Forwarded-For','X-Streamlit-User']
```

本機直連則有 `Cookie`。所以：

- **任何依賴 cookie 的機制在正式站上不會生效。** `_xsrf_secret()` 在雲端永遠回空字串。
- **`X-Forwarded-For` 裡挑不出公開 IP**，真實 client IP 在代理層就被剝掉了。
- `X-Streamlit-User` 是 Streamlit 自己加的識別，**不是 IP**，也不要拿來當 per-browser
  祕密（公開 app 的匿名訪客可能拿到同一個值＝等於沒有綁定）。

**代價**：MED-6 把「拿不到瀏覽器祕密」改成 fail closed 之後，正式站登入全掛。
現在的做法是兩個來源：cookie（本機）→ localStorage 代號（雲端唯一可用）。

**在本機重現雲端條件的方法**：

```bash
streamlit run app.py --server.port 8599 --server.headless true --server.enableXsrfProtection false
```

⚠️ 然後**還要到瀏覽器把 `_streamlit_xsrf` cookie 刪掉**——cookie 不分 port，
別的 port 留下的會讓你以為關掉 XSRF 就沒 cookie 了（第一次驗證就是這樣被騙過去的）。

## 2. `st.session_state` 撐不過 OAuth 來回

跳去 Spotify 再導回是**整頁重新載入**，session_state 整個重生（實測 nonce
`e2b32d96` → `909f0aa6`）。所以教科書寫法「nonce 存 session_state、回來比對」
在這裡永遠失敗＝登入直接壞掉。

state 因此做成無狀態簽章：`時間戳.nonce.HMAC(瀏覽器祕密, "時間戳.nonce")`。

## 3. localStorage 元件是非同步的：首輪必定回 `None`

自建元件（`guest_id_component/`）在第一次 render 一定回 `None`，要等 postback
觸發 rerun 才有值。

⚠️ **把 `None` 當成失敗的話，每個正常使用者都會在首輪被誤判。** 所以元件在
localStorage 真的不可用時回字串 `"unavailable"`（終局，可以直接判失敗），
`None` 則代表 pending（要再等一輪）。`browser_id_pending()` 就是給呼叫端問這個差別的。

⚠️ **元件一次 script run 只能呼叫一次**——同一個 widget key 渲染兩次會
DuplicateWidgetID。全專案只有 `_resolve_browser_id()` 一個呼叫點，其他地方讀
`_browser_id()`。

⚠️ **`_resolve_browser_id()` 必須排在 `consume_oauth_callback()` 之前**，
否則回呼時拿不到綁定對象。

## 4. 單一全域 DB 連線 ↔ Streamlit 的多執行緒

Streamlit 每位使用者的 session 是同一行程裡的不同執行緒。psycopg3 的連線本身有內部鎖
不會 crash，但**交易邊界是連線層級的**：

- A 的 `commit()` 會順手提交 B 還沒寫完的語句
- B 的語句一報錯讓交易進入 aborted 狀態，**A 的寫入也會跟著失敗**

症狀是「偶爾失敗、重試又好了」，而「死連線自癒」那種補丁正好把它偽裝成暫時性問題。
正解是連線池（`db.connection()`），每個 `with` 區塊拿到自己的連線＝自己的交易。

⚠️ **失敗時不要重置連線**：死連線由池子的 `check` 自動汰換，在那裡整池關掉反而會
把其他使用者正在用的好連線一起丟掉＝重演舊版的失敗模式。

## 5. Supabase 的 `public` schema 預設對外開放

Supabase 會把 `public` schema 的表透過 PostgREST 開放給 `anon` / `authenticated`，
而 anon key 在它的設計裡本來就是「要發給瀏覽器」的公開值。本站完全不用 PostgREST
（走直連 Postgres），所以那條路徑應該整個關掉。

⚠️ **加新表就要一起 `enable row level security` 並 revoke。** `playlist_feedback`
就是後來才加、開 RLS 時被漏掉的那張。DDL 已併進 `FEEDBACK_PERSISTENCE.md` 的 schema
區塊，照那份建表就不會漏。

⚠️ **`TRUNCATE` 不受 RLS 約束**，光開 RLS 擋不住它，權限一定要一起 revoke。

app 以 owner（`postgres`）連線、owner 預設 bypass RLS，所以這些設定**不影響現有功能**
——但這句話要用「改動前後數同樣幾張表的列數」量出來，不要當成理所當然。

## 6. 節流的淘汰順序是安全決策

桶子表滿了要丟哪一個？**直覺的 LRU 是錯的**：洪水攻擊送進來的全是新桶，LRU 會優先
踢掉累積最久、最接近上限的老使用者——正好踢錯人。

正確的損失函數是「這個桶目前握有多少額度」：先丟整桶過期的（零損失），再丟有效
時間戳最少的（攻擊者那些各只有 1 筆的桶會第一批出局，而他本來就在換 cookie，丟不丟
對他沒差）。

更早的版本是滿了就 `clear()`——那等於讓任何人花近乎零的成本就能把全體使用者的
額度歸零，而且可反覆做。**淘汰策略一律要問「攻擊者能不能利用這個行為」。**

## 7. per-browser 節流在雲端一直是失效的（已修，但要知道為什麼）

`_rate_key()` 吃的是同一個瀏覽器祕密，所以在拿不到 cookie 的雲端一直退回
per-session 隨機 id ＝ **重新整理就洗掉額度**。

這也是為什麼**全站閘門**（`GLOBAL_HOURLY_MAX` / `GLOBAL_DAILY_MAX`）重要：
它不看使用者身分，所以繞不掉，是最壞情況的唯一天花板。

## 8. `file_uploader(type=[...])` 只比對副檔名

`uploaded.type` 是**瀏覽器宣告的**值。兩者都由使用者控制，所以叫 `x.png` 但內容是
EPS/JPEG2000 的檔案照樣會被對應的解碼器解析（`requirements.txt` 把 Pillow 釘在
12.3.0 就是為了那批解析器 CVE）。

走 `_sniff_image_mime()` 以檔頭判定。⚠️ 刻意用**純位元組比對、不丟給 PIL 判斷**
——那等於為了驗證先解析一次未知內容，正好是要避開的那一步。

## 9. Streamlit alert 會渲染 Markdown

`st.warning()` / `st.error()` 不允許 HTML，但**會渲染 Markdown**。所以把網址參數
原樣回顯進去，攻擊者放一個反引號就能跳出 code span，接著插入任意 Markdown——
實測可在官方樣式的警告框裡產生釣魚連結與會被實際抓取的 `<img>`（靜默外洩 IP／UA）。

因此 `?error=` 走白名單，而且**不要把代碼本身插回訊息裡**，也不要把 `str(e)` 存進
`spotify_auth_error`（例外訊息含 Spotify 回傳的內容，同樣會被回顯）。

## 10. 部署相關

- **改了被 import 的模組（不是只有 `app.py`）要手動 Reboot**：Cloud 只做
  `git pull` + 重跑腳本，`sys.modules` 裡還是舊的 module 物件。症狀是
  `ImportError: cannot import name X`，但 GitHub 上明明有 X。
- **例外**：同一個 push 有動到 `requirements.txt` 時會自動重啟（會重跑依賴安裝）。
- 日誌裡的 `inotify instance limit reached` traceback 佔了 95% 篇幅，**是雜訊不是錯誤**。
  只找 `[AUTH]`／`[DB]`／`[GEO]`／`[GUEST]`／`ImportError`／`NameError`。

## 11. 用腳本改檔案時的跳脫陷阱（操作面，但會真的弄壞程式碼）

用 heredoc + Python 改檔案時，`\n`、`\x89` 這類跳脫序列容易被多剝一層，
結果把**真的換行／真的位元組**寫進原始碼，造成 `SyntaxError: unterminated string literal`。
這次踩了兩次。

**對策**：需要特殊字元時完全避開反斜線——用 `chr(10)`、`bytes([0x89, 0x50, ...])`。
另外**多步替換要逐步做並各自 assert**，序列替換失敗時很難從行號判斷是哪一步斷的。
