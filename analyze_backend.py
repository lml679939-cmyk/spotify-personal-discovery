"""analyze_backend.py — 後台累積回饋/歷史資料的**唯讀**分析報告（CLI）。

用法：
    python analyze_backend.py                # 完整報告
    python analyze_backend.py --min-n 5      # 只印樣本數 >= 5 的分段（預設 1 ＝全印）
    python analyze_backend.py --top 15       # top 歌手清單取幾筆（預設 10）

設計原則（見 FEEDBACK_PERSISTENCE.md「回饋訊號設計」段）：
  - 滿意度用**中位數**（percentile_cont 0.5），不是平均——免得少數極端值主宰。
  - 按 **ctx 意圖**切：探索度 fame_mode / 語言 / 曲風 / 心情雙軸 mood_energy·mood_valence。
  - 每個分段都印 **n（樣本數）**；n 小的數字別當真（LLM 有隨機性、看趨勢不看單點）。

只讀不寫、只印聚合（不印 user_key 值，只印曲名/歌手這種非個資）。連線走 db._config()
（本機 `.env` 或 Streamlit Secrets 的 `SUPABASE_DB_URL`）——跟 app 同一個 DB。這是**本機開發工具**
（比照 eval_bench.py），不在雲端跑。

⚠️ 資料分三層（分析時心裡要有數）：
  - **記名**（登入或已同意訪客）：user_key = 64-hex 雜湊（`~ '^[0-9a-f]{64}$'`）。可回讀到「同一人/瀏覽器」。
  - **匿名歌單評分**：user_key = `'anon'`。純聚合、不可回溯。
  - **匿名逐首回饋**：user_key = `'anon:'+gen_id`（分析用 `like 'anon:%'`）。同上、每次生成各自獨立。
"""
import argparse
import sys

from dotenv import load_dotenv

load_dotenv()          # 讀專案根目錄 .env（SUPABASE_DB_URL / PERSIST_HMAC_SECRET）
import db              # noqa: E402  延遲到 load_dotenv 後，讓 _config() 讀得到 env

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows cp950 主控台印中文/emoji 免爆
except Exception:
    pass

HASHED = r"user_key ~ '^[0-9a-f]{64}$'"     # 記名身分（雜湊）的判別式


def hr(title: str) -> None:
    print(f"\n{'=' * 66}\n  {title}\n{'=' * 66}")


def sub(title: str) -> None:
    print(f"\n— {title} —")


def main() -> int:
    ap = argparse.ArgumentParser(description="後台回饋/歷史資料唯讀分析")
    ap.add_argument("--min-n", type=int, default=1, help="只印樣本數 >= 此值的分段（預設 1）")
    ap.add_argument("--top", type=int, default=10, help="top 歌手清單筆數（預設 10）")
    args = ap.parse_args()
    MIN_N, TOP = args.min_n, args.top

    if not db.is_enabled():
        print("DB 未啟用：缺 SUPABASE_DB_URL / PERSIST_HMAC_SECRET（檢查 .env）。")
        return 1
    conn = db.get_conn()
    if conn is None:
        print("連不上 DB。")
        return 1

    def q(sql: str, params=None):
        # ⚠️ 只在有 params 時才傳給 execute——否則 psycopg 會把 SQL 裡的字面 `%`（如 like 'anon:%'）
        # 當成占位符解析而報錯。無 params 走 execute(sql) 就把 `%` 當字面。
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            return cur.fetchall()

    def rows(sql, params=None, *, empty="（無資料）"):
        try:
            r = q(sql, params)
        except Exception as e:
            print(f"  ⚠️ 查詢失敗：{e}")
            return []
        if not r:
            print(f"  {empty}")
        return r

    # ── 1) 資料概況 ─────────────────────────────────────────────
    hr("1. 資料概況")
    for tbl in ("consent", "feedback", "history", "playlist_feedback"):
        n = q(f"select count(*) from {tbl}")[0][0]
        print(f"  {tbl:20s} {n} 列")
    sub("身分層")
    login_n = q(f"select count(distinct user_key) from consent where {HASHED}")[0][0]
    pf_anon = q("select count(*) from playlist_feedback where user_key = 'anon'")[0][0]
    fb_anon_gens = q("select count(distinct user_key) from feedback where user_key like 'anon:%'")[0][0]
    print(f"  記名身分（登入＋已同意訪客，雜湊）：{login_n}")
    print(f"  匿名歌單評分列（anon）：{pf_anon}")
    print(f"  匿名逐首回饋的生成數（anon:gen_id）：{fb_anon_gens}")
    rng = q("select min(recommended_at), max(recommended_at) from history")[0]
    print(f"  歷史時間範圍：{rng[0]} → {rng[1]}")

    # ── 2) 歌單滿意度（playlist_feedback）────────────────────────
    hr("2. 歌單滿意度（rating 1不太合 / 2還可以 / 3很對味）")
    tot = q("select count(*) from playlist_feedback where rating is not null")[0][0]
    if tot == 0:
        print("  （還沒有評分資料。等真實流量累積再看。）")
    else:
        med = q("select percentile_cont(0.5) within group (order by rating), "
                "round(avg(saved::int)*100,1) from playlist_feedback where rating is not null")[0]
        print(f"  全體：n={tot}  中位數={med[0]}  加入率(saved)={med[1]}%")

        def seg(label, expr, extra_where=""):
            sub(f"按 {label} 切")
            r = rows(
                f"select {expr} as seg, count(*) n, "
                f"percentile_cont(0.5) within group (order by rating) med, "
                f"round(avg(saved::int)*100,1) save_pct "
                f"from playlist_feedback where rating is not null {extra_where} "
                f"group by {expr} order by n desc")
            for seg_v, n, med_v, save in r:
                if n < MIN_N:
                    continue
                flag = "  ⚠️n小" if n < 10 else ""
                print(f"    {str(seg_v):18s} n={n:<4d} 中位數={med_v} 加入率={save}%{flag}")

        seg("探索度 fame_mode", "ctx->>'fame_mode'")
        seg("語言 lang", "ctx->>'lang'")
        seg("曲風 genre", "ctx->>'genre'")
        seg("新藝人% new_ratio（登入）", "ctx->>'new_ratio'")
        seg("活力 mood_energy 分桶",
            "case when (ctx->>'mood_energy')::int<=3 then 'low(1-3)' "
            "when (ctx->>'mood_energy')::int>=8 then 'high(8-10)' else 'mid(4-7)' end",
            "and ctx->>'mood_energy' is not null")
        seg("情緒 mood_valence 分桶",
            "case when (ctx->>'mood_valence')::int<=3 then 'low(1-3)' "
            "when (ctx->>'mood_valence')::int>=8 then 'high(8-10)' else 'mid(4-7)' end",
            "and ctx->>'mood_valence' is not null")

    # ── 3) 逐首回饋（feedback）——調選歌用 ────────────────────────
    hr("3. 逐首回饋（👍 like / 👎 dislike / 🎧 heard）")
    if q("select count(*) from feedback")[0][0] == 0:
        print("  （還沒有逐首回饋。）")
    else:
        sub("狀態分布")
        for st, n in rows("select state, count(*) from feedback group by state order by count(*) desc"):
            print(f"    {st:10s} {n}")
        sub("出圈 vs 非出圈的按讚率")
        for disc, n, likes in rows(
                "select is_discovery, count(*), "
                "round(100.0*count(*) filter (where state='like')/nullif(count(*),0),1) "
                "from feedback group by is_discovery order by is_discovery"):
            print(f"    is_discovery={str(disc):5s} n={n:<4d} 按讚率={likes}%")
        sub("知名度 fame 分布（被回饋的曲目）")
        for fame, n, likes in rows(
                "select fame, count(*), "
                "round(100.0*count(*) filter (where state='like')/nullif(count(*),0),1) "
                "from feedback where fame is not null group by fame order by fame"):
            print(f"    fame={fame} n={n:<4d} 按讚率={likes}%")
        sub(f"最常被讚/被倒讚的歌手（top {TOP}）")
        for artist, likes, dislikes in rows(
                "select artist, count(*) filter (where state='like') likes, "
                "count(*) filter (where state='dislike') dislikes "
                "from feedback group by artist "
                "having count(*) filter (where state in ('like','dislike'))>0 "
                "order by likes desc, dislikes asc limit %s", (TOP,)):
            print(f"    {artist:28s} 👍{likes}  👎{dislikes}")

    print("\n" + "=" * 66)
    print("  提示：n 小的分段只是雜訊，看趨勢與大樣本；查詢範本見 FEEDBACK_PERSISTENCE.md。")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
