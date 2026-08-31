# 驗證做法

一個資安修改要能拿出**數字**才算完成。以下四種是這次稽核用過的，附上當時的實際結果，
方便判斷「什麼樣的輸出算通過」。

共同原則：**先量改動前、再量改動後，兩邊用同一個腳本。** 只量改動後的話，你不知道
數字是修好帶來的還是本來就這樣。

---

## A. 攻擊模擬（純邏輯模組）

適用：節流、額度、任何「攻擊者反覆嘗試」的機制。直接 import 模組、餵時間戳，
不需要起伺服器。

**HIGH-3（節流桶被整批清空）的驗證**——建立 100 位已用完額度的使用者，
再灌入三波全新 cookie，看他們的額度會不會被洗掉：

```python
import ratelimit as rl
T = 1_000_000.0
for u in range(100):                      # 100 位使用者各用完 40 次
    t = T
    for _ in range(rl.DAILY_MAX):
        rl.consume(f"user{u}", t); t += rl.COOLDOWN_SEC + 1
before = sum(1 for u in range(100) if not rl.consume(f"user{u}", t)[0])
for wave in range(3):                     # 攻擊：三波全新 cookie
    for i in range(rl.MAX_BUCKETS + 50):
        rl.acquire(f"atk-{wave}-{i}", t + 1 + wave)
after = sum(1 for u in range(100) if not rl.consume(f"user{u}", t + 10)[0])
```

實際結果：`before 100/100 → after 100/100`，桶子表 4999/5000。修好前 `after` 會掉。

**HIGH-2（沒有全站上限）的驗證**——攻擊者每 2 秒換一個新 cookie 連跑 6 小時：

```python
for step in range(0, 6 * 3600, 2):
    ok, why, _, _ = rl.acquire(f"atk-{step}", T + step)
```

實際結果：10,800 次嘗試 → **只有 400 次通過**（撞到 `GLOBAL_DAILY_MAX`）。
同時要確認**被擋下的真實使用者個人額度沒被扣**（40/40）。

⚠️ 主控台是 cp950，印 emoji 會 `UnicodeEncodeError`。加 `PYTHONIOENCODING=utf-8`
或只印 ASCII。

## B. 對真實資料庫的唯讀對照

適用：連線行為、權限、RLS。**唯讀，不寫任何一列**，所以對正式資料安全。

⚠️ 腳本放 scratchpad 時要 `load_dotenv(<明確路徑>)`——從 stdin 執行時
`find_dotenv()` 會因為沒有呼叫端 frame 而拋 AssertionError。
⚠️ 需要 `PYTHONPATH=<專案路徑>` 才 import 得到 `db`。
⚠️ **跑完把複製到暫存區的 `.env` 刪掉**（那是連線字串）。

**MED-4（共用單一連線）的驗證**——同一順序跑兩次、只換連線取得方式：
A 送一句會失敗的語句，緊接著 B 送完全正常的查詢。

```python
def probe(get_cm, label):
    try:
        with get_cm() as c, c.cursor() as cur:
            cur.execute("select 1/0")          # A
    except Exception as e:
        a = type(e).__name__
    try:
        with get_cm() as c, c.cursor() as cur:
            cur.execute("select 1")            # B：什麼都沒做錯
            b = f"OK -> {cur.fetchone()[0]}"
    except Exception as e:
        b = f"FAILED -> {type(e).__name__}"
```

實際結果：

```
單一全域連線      A: DivisionByZero   B: FAILED -> InFailedSqlTransaction
db.connection()   A: DivisionByZero   B: OK -> 1
```

那行 `InFailedSqlTransaction` 就是「跨使用者耦合」的實證。

**DDL 類改動（開 RLS、revoke）** 則用「量 → 改 → 再量」：改動前後都用
**應用程式自己的連線路徑**（`db.connection()`）數同樣幾張表的列數。若 owner 沒有
真的 bypass RLS，這個數字會掉到 0。

實際結果：`consent=2 feedback=10 history=125 playlist_feedback=3` 前後完全一致，
`anon` 授權筆數 24 → 0。

## C. 把前端邏輯抽出來用 Node 實跑

適用：元件裡的 JS。子字串檢查（「有沒有寫 `getRandomValues`」）只能證明**有寫**，
證明不了**寫對**——位元運算錯一個 mask 就會產生不合格的 UUID，而測試看不出來。

**MED-5（訪客 ID 的 CSPRNG）的驗證**——把 `newId()` 從 HTML 抽出來，
用 `new Function(...)` 建起來，分別餵「有 randomUUID」與「只有 getRandomValues」
兩種 crypto 物件，各跑 5000 次：

```javascript
const start = src.indexOf("function newId() {");
const end = src.indexOf("function readOrCreate() {");
const newId = new Function(src.slice(start, end) + " return newId;")();
```

檢查每個 id：符合 UUID 正規形式、第 15 字元是 `4`（version）、
第 20 字元屬於 `89ab`（variant）、全部不重複。

實際結果：兩條路徑各 5000/5000 全數合格、無重複；無 crypto 時如設計回 `null`。

## D. 在本機重現雲端條件，用瀏覽器實測

適用：任何跟 cookie、標頭、前端元件有關的判斷。**這是上次翻船的地方**——
只跑單元測試會漏掉。

```bash
streamlit run app.py --server.port 8599 --server.headless true --server.enableXsrfProtection false
```

⚠️ 然後**必須到瀏覽器把 `_streamlit_xsrf` cookie 刪掉**（cookie 不分 port）。
沒刪的話你以為在測無 cookie 路徑，其實走的還是 cookie 那條。

用瀏覽器工具取這些值判斷：

```javascript
const a = [...document.querySelectorAll('a')].find(x => x.textContent.includes('Spotify 登入'));
({
  xsrfCookiePresent: document.cookie.includes('_streamlit_xsrf'),
  loginButtonShown: !!a,
  hasState: a ? new URL(a.href).searchParams.has('state') : null,
  alerts: [...document.querySelectorAll('[data-testid="stAlert"]')].map(e => e.innerText.slice(0, 60)),
  probeHeight: document.querySelector('.st-key-guest_id_probe')?.getBoundingClientRect().height
})
```

實際結果（修好後）：`xsrfCookiePresent: false`、`loginButtonShown: true`、
`hasState: true`、`alerts: []`、`probeHeight: 0`（隱形元件沒佔版面）。

⚠️ **合成點擊可能送不進 Streamlit 的 React handler**（試過 ref、座標、提到前景都不行）。
量測與讀取沒問題，但要「點按鈕走完流程」的部分可能得請使用者手動確認——
**這種情況要老實講，不要把「沒驗到」寫成「驗過了」。**

---

## 最後一關：證明迴歸測試不是空過的

寫完測試之後，把**舊版邏輯**也跑一次，確認它真的會失敗。一條「本來就會過」的測試
等於沒有測試，而且會給人虛假的安全感。

**MED-6 的做法**——手動用空金鑰算出舊版會產生的簽章，兩邊各驗一次：

```python
def old_sign(nonce, ts, secret=""):        # 舊版：空祕密照樣簽下去
    return hmac.new(secret.encode(), f"{ts}.{nonce}".encode(), hashlib.sha256).hexdigest()

forged = f"{issued_at}.{nonce}.{old_sign(nonce, issued_at)}"
old_accepts = hmac.compare_digest(forged.split(".")[2], old_sign(nonce, issued_at))
new_accepts = spotify_api._verify_oauth_state(forged)
```

實際結果：`[OLD] True` / `[NEW] False`。這一行才真正證明修法有效。
