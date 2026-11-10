
import time
import traceback


def probe(name, fn):
    t0 = time.time()
    try:
        r = fn()
        print(f"[OK]   {name:<26} {time.time()-t0:6.1f}s  -> {str(r)[:110]}")
    except Exception as e:
        print(f"[FAIL] {name:<26} {time.time()-t0:6.1f}s  -> {type(e).__name__}: {str(e)[:110]}")


import requests as rq

print("=== raw HTTP ===")
for name, url, ref in [
    ("腾讯行情", "https://qt.gtimg.cn/q=sh600519", None),
    ("新浪行情", "https://hq.sinajs.cn/list=sh600519", "https://finance.sina.com.cn"),
    ("东财push2", "https://push2.eastmoney.com/api/qt/stock/get?secid=1.600519&fields=f43", None),
]:
    def go(u=url, r=ref):
        h = {"User-Agent": "Mozilla/5.0"}
        if r:
            h["Referer"] = r
        resp = rq.get(u, timeout=15, headers=h)
        return f"HTTP {resp.status_code} len={len(resp.content)}"
    probe(name, go)

print("\n=== akshare ===")
import akshare as ak

probe("stock_zh_a_spot_em", lambda: ak.stock_zh_a_spot_em().shape)
probe("stock_zh_a_hist", lambda: ak.stock_zh_a_hist(symbol="600519", period="daily",
                                                   start_date="20261101", end_date="20261110").shape)
probe("stock_zh_a_spot(新浪)", lambda: ak.stock_zh_a_spot().shape)
probe("stock_board_industry_name_em", lambda: ak.stock_board_industry_name_em().shape)
probe("stock_zh_index_spot_em", lambda: ak.stock_zh_index_spot_em(symbol="上证系列指数").shape)

print("\n=== efinance ===")
import efinance as ef

probe("get_realtime_quotes", lambda: ef.stock.get_realtime_quotes(["600519"]).shape)
probe("get_quote_history", lambda: ef.stock.get_quote_history("600519").shape)
probe("get_realtime_quotes(板块)", lambda: ef.stock.get_realtime_quotes(["行业板块"]).shape)
