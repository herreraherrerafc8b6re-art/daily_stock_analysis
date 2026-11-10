# -*- coding: utf-8 -*-
"""
Daily sector picker.
Reads sector_pool_pruned.json, fetches realtime quotes from Tencent (fast + reliable),
scores each stock, and outputs the day's STOCK_LIST.

Env:
  PICK_PER_SECTOR   how many stocks per sector (default 1)
  PICK_TOP_SECTORS  how many most-active sectors to take (default 3, 0 = all)
"""
import json
import os
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
POOL = os.environ.get("SECTOR_POOL_FILE", os.path.join(HERE, "sector_pool_pruned.json"))
PER_SECTOR = int(os.environ.get("PICK_PER_SECTOR", "1"))
TOP_SECTORS = int(os.environ.get("PICK_TOP_SECTORS", "3"))


def prefix(code):
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("0", "3", "2")):
        return "sz" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sh" + code


def fetch_quotes(codes):
    """Batch quote from Tencent. Returns {code: dict}."""
    out = {}
    batch = 60
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        url = "https://qt.gtimg.cn/q=" + ",".join(prefix(c) for c in chunk)
        try:
            r = requests.get(url, timeout=20,
                             headers={"User-Agent": "Mozilla/5.0",
                                      "Referer": "https://finance.qq.com"})
            r.encoding = "gbk"
            for line in r.text.split(";"):
                line = line.strip()
                if "=" not in line or '"' not in line:
                    continue
                body = line.split('"')[1] if '"' in line else ""
                f = body.split("~")
                if len(f) < 40:
                    continue
                code = f[2].strip()
                try:
                    out[code] = {
                        "name": f[1],
                        "price": float(f[3] or 0),
                        "prev": float(f[4] or 0),
                        "pct": float(f[32] or 0),        # 涨跌幅 %
                        "amount_wan": float(f[37] or 0),  # 成交额 万元
                        "turnover": float(f[38] or 0),    # 换手率 %
                        "amplitude": float(f[43] or 0) if len(f) > 43 else 0.0,
                    }
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f"[warn] batch quote failed: {type(e).__name__}: {e}", file=sys.stderr)
    return out


def score(q):
    """Blend momentum, liquidity and turnover into one 0-100ish score."""
    pct = q["pct"]
    amount = q.get("amount_wan", 0) / 10000.0   # 亿元
    turnover = q.get("turnover", 0)
    # momentum: reward positive, penalise blow-off (>9.5% near limit up)
    mom = pct if pct <= 9.5 else 9.5 - (pct - 9.5) * 2
    liq = min(amount, 50.0) ** 0.5 * 3.0        # 成交额 0-50亿 -> 0-21
    tor = min(turnover, 25.0) ** 0.5 * 1.5
    return mom * 1.0 + liq + tor


def main():
    pool = json.load(open(POOL, encoding="utf-8"))
    sectors = pool["sectors"]

    all_codes = [s["code"] for d in sectors.values() for s in d["stocks"]]
    quotes = fetch_quotes(sorted(set(all_codes)))
    print(f"# quotes fetched: {len(quotes)}/{len(set(all_codes))}", file=sys.stderr)

    rows = []
    for sector, d in sectors.items():
        cands = []
        for s in d["stocks"]:
            q = quotes.get(s["code"])
            if not q or q["price"] <= 0:
                continue
            q["code"] = s["code"]
            q["sector"] = sector
            q["score"] = score(q)
            cands.append(q)
        if not cands:
            continue
        cands.sort(key=lambda x: x["score"], reverse=True)
        # sector strength = best stock's momentum + breadth
        avg_pct = sum(c["pct"] for c in cands) / len(cands)
        sector_strength = avg_pct * 2 + cands[0]["score"] * 0.3
        rows.append({"sector": sector, "strength": sector_strength,
                     "avg_pct": avg_pct, "picks": cands[:PER_SECTOR],
                     "all": cands})

    rows.sort(key=lambda x: x["strength"], reverse=True)

    print("\n=== 板块强弱排序 ===", file=sys.stderr)
    for i, r in enumerate(rows, 1):
        print(f"{i:>2}. {r['sector']:<10} 均涨{r['avg_pct']:>6.2f}%  强度{r['strength']:>7.2f}",
              file=sys.stderr)

    selected = rows[:TOP_SECTORS] if TOP_SECTORS > 0 else rows

    print("\n=== 今日选股 ===", file=sys.stderr)
    codes = []
    for r in selected:
        for p in r["picks"]:
            codes.append(p["code"])
            print(f"  [{r['sector']}] {p['name']}({p['code']}) "
                  f"涨{p['pct']:+.2f}% 换手{p['turnover']:.2f}% 额{p.get('amount_wan',0)/10000:.1f}亿",
                  file=sys.stderr)

    print(",".join(codes))


if __name__ == "__main__":
    main()
