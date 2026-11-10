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
    # 持仓股可能不在选股池里，也要取行情
    holdings_env = os.environ.get("HOLDINGS", "").strip()
    holdings_extra = [c.strip() for c in holdings_env.replace("，", ",").split(",") if c.strip()]
    quotes = fetch_quotes(sorted(set(all_codes) | set(holdings_extra)))
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

    # ---- 持仓优先：HOLDINGS=600519,300750 ----
    holdings_raw = os.environ.get("HOLDINGS", "").strip()
    holdings = [c.strip() for c in holdings_raw.replace("，", ",").split(",") if c.strip()]

    codes = []
    print("\n=== 你的持仓（优先分析）===", file=sys.stderr)
    if holdings:
        for c in holdings:
            if c not in codes:
                codes.append(c)
            q = quotes.get(c)
            if q:
                print(f"  [持仓] {q['name']}({c}) 涨{q['pct']:+.2f}% "
                      f"现价{q['price']:.2f}", file=sys.stderr)
            else:
                print(f"  [持仓] {c} （今日无行情，仍纳入分析）", file=sys.stderr)
    else:
        print("  （未配置 HOLDINGS，仅按板块选股）", file=sys.stderr)

    # ---- 板块补足到 TOTAL_TARGET ----
    target = int(os.environ.get("TOTAL_TARGET", "0") or 0)
    need = max(0, target - len(codes)) if target > 0 else 10 ** 6

    print("\n=== 板块选股 ===", file=sys.stderr)
    added = 0
    for r in selected:
        for p in r["picks"]:
            if added >= need:
                break
            if p["code"] in codes:
                continue
            codes.append(p["code"])
            added += 1
            print(f"  [{r['sector']}] {p['name']}({p['code']}) "
                  f"涨{p['pct']:+.2f}% 换手{p['turnover']:.2f}% 额{p.get('amount_wan',0)/10000:.1f}亿",
                  file=sys.stderr)
        if added >= need:
            break

    print(f"\n# 合计 {len(codes)} 只（持仓 {len(holdings)} + 板块新增 {added}）", file=sys.stderr)
    print(",".join(codes))


if __name__ == "__main__":
    main()
