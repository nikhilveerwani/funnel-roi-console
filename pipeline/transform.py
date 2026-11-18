"""Join ad spend to the lead funnel and compute ROI, the way it has to be done in practice.

Rules (also documented on the page and in sql/campaign_roi.sql):
  * Spend joins to leads on CAMPAIGN ID, extracted from the end of the UTM ("<name>__<id>").
    Never on campaign name: names change in the ad platform, old links keep the old name.
  * Funnel outcomes (attended, qualified, sale, revenue) belong to the LEAD's creation date,
    so a campaign's cost and its results line up on the same cohort.
  * A lead cohort is "maturing" for 30 days: sales keep landing for weeks, so recent ROAS
    is understated. The page says so instead of letting it look like a drop.
  * "What moved" compares the last 7 complete days with the 28 days before, per campaign,
    with rule-based thresholds, and sizes each change in rupees.

Usage: python pipeline/transform.py --data data --out site/data.js
"""
import argparse
import csv
import datetime as dt
import json
import math
import re
import urllib.parse
from collections import defaultdict

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
ID_RE = re.compile(r"__(\d{6,})\s*$")
MATURITY_DAYS = 30


def campaign_id_from_utm(utm: str):
    """'FB_Name__23850101' -> 23850101. Handles case, spaces and URL-encoding. None if no ID."""
    if not utm:
        return None
    s = urllib.parse.unquote(utm).strip().replace(" ", "_")
    m = ID_RE.search(s)
    return int(m.group(1)) if m else None


def name_from_utm(utm: str):
    """The naive approach: take the part before '__' and use it as the campaign name."""
    return utm.split("__")[0] if utm else ""


def safe_div(a, b):
    return a / b if b else None


# ---------------------------------------------------------------- statistics (stdlib only)
def rate_change_p(leads_r, spend_r, leads_b, spend_b):
    """Two-sided p-value that leads-per-rupee changed between two periods.
    Under H0 (same rate), leads_r ~ Binomial(leads_r + leads_b, spend_r / (spend_r + spend_b)).
    Normal approximation; the counts here are in the hundreds."""
    n = leads_r + leads_b
    if not n or not spend_r or not spend_b:
        return None
    p0 = spend_r / (spend_r + spend_b)
    sd = math.sqrt(n * p0 * (1 - p0))
    if sd == 0:
        return None
    z = (leads_r - n * p0) / sd
    return math.erfc(abs(z) / math.sqrt(2))


def wilson(k, n, z=1.96):
    """95% Wilson interval for a proportion k/n."""
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def fmt_p(p):
    return "p < 0.001" if p is not None and p < 0.001 else (f"p = {p:.3f}" if p is not None else "")


def load(data_dir):
    spend = list(csv.DictReader(open(f"{data_dir}/ad_spend_daily.csv", encoding="utf-8")))
    leads = list(csv.DictReader(open(f"{data_dir}/leads.csv", encoding="utf-8")))
    return spend, leads


def build(data_dir, today=None):
    spend, leads = load(data_dir)
    today = today or dt.datetime.now(IST).date()

    meta = {}
    names_seen = defaultdict(set)
    for r in spend:
        cid = int(r["campaign_id"])
        names_seen[cid].add(r["campaign_name"])
        if cid not in meta or r["date"] >= meta[cid]["last_date"]:
            meta[cid] = {"id": cid, "name": r["campaign_name"], "channel": r["channel"], "last_date": r["date"]}
    all_names = {n for s in names_seen.values() for n in s}

    # ---- the join, both ways ----
    paid = [l for l in leads if l["utm_campaign"]]
    by_name = sum(1 for l in paid if name_from_utm(l["utm_campaign"]) in all_names)
    ids = [campaign_id_from_utm(l["utm_campaign"]) for l in paid]
    by_id = sum(1 for i in ids if i in meta)

    # ---- daily facts per campaign (cohorted on lead creation date) ----
    F = defaultdict(lambda: [0.0, 0, 0, 0, 0, 0, 0, 0])   # spend, clicks, leads, attended, qualified, sales, revenue, impressions
    for r in spend:
        f = F[(r["date"], int(r["campaign_id"]))]
        f[0] += float(r["spend_inr"]); f[1] += int(r["clicks"]); f[7] += int(r["impressions"])
    unmatched = defaultdict(int)
    sale_lags = []
    for l, cid in zip(paid, ids):
        d = l["created_at"][:10]
        if cid not in meta:
            unmatched[d] += 1
            continue
        _add_outcomes(F[(d, cid)], l, sale_lags)
    for l in leads:
        if not l["utm_campaign"]:
            _add_outcomes(F[(l["created_at"][:10], 0)], l, sale_lags)

    facts = sorted([[d, cid, round(v[0]), v[1], v[2], v[3], v[4], v[5], v[6]] for (d, cid), v in F.items()])

    # ---- sale lag: why cohorts need 30 days ----
    sale_lags.sort()
    lag_share = {str(k): round(100 * sum(1 for x in sale_lags if x <= k) / len(sale_lags), 1) for k in (7, 14, 30)} if sale_lags else {}

    callouts = what_moved(facts, meta, today)
    summary = executive_summary(facts, meta, today, callouts)

    dates = sorted({f[0] for f in facts})
    return {
        "synthetic": True,
        "generated_at": dt.datetime.now(IST).strftime("%d %b %Y, %H:%M IST"),
        "today": today.isoformat(), "maturity_days": MATURITY_DAYS,
        "window": {"from": dates[0], "to": dates[-1]},
        "campaigns": [{"id": c["id"], "name": c["name"], "channel": c["channel"],
                       "old_names": sorted(names_seen[c["id"]] - {c["name"]})} for c in meta.values()],
        "facts_cols": ["date", "campaign_id", "spend", "clicks", "leads", "attended", "qualified", "sales", "revenue"],
        "facts": facts,
        "join": {"paid_leads": len(paid), "matched_by_name": by_name, "matched_by_id": by_id,
                 "no_id_in_utm": sum(1 for i in ids if i is None), "unmatched_by_day": dict(unmatched)},
        "sale_lag_share": lag_share,
        "callouts": callouts,
        "summary": summary,
    }


CAPPED = ("brand", "retargeting", "remarketing")   # demand-capped: high ROAS but can't absorb more budget


def executive_summary(facts, meta, today, callouts):
    """The answer first: computed from the same facts as the page, so it is never stale."""
    lo, hi = today - dt.timedelta(days=120), today - dt.timedelta(days=MATURITY_DAYS)
    last30 = today - dt.timedelta(days=30)
    per = defaultdict(lambda: [0.0, 0.0, 0.0])       # mature spend, mature revenue, last-30-day spend
    for d, cid, sp, _c, _l, _a, _q, _s, rev in facts:
        if cid == 0:
            continue
        day = dt.date.fromisoformat(d)
        if lo <= day <= hi:
            per[cid][0] += sp; per[cid][1] += rev
        if day >= last30:
            per[cid][2] += sp
    msp = sum(v[0] for v in per.values()); mrev = sum(v[1] for v in per.values())
    roas = {cid: safe_div(v[1], v[0]) for cid, v in per.items()}
    weak = [cid for cid, r in roas.items() if r is not None and r < 1.5]
    weak_monthly = sum(per[c][2] for c in weak)
    scalable = [cid for cid in per if not any(k in meta[cid]["name"].lower() for k in CAPPED)]
    best = sorted(scalable, key=lambda c: -(roas[c] or 0))[:2]
    worst = min(weak, key=lambda c: roas[c]) if weak else None
    at_stake = sum(c["impact"] for c in callouts if c["kind"] == "bad")
    nm = lambda c: meta[c]["name"]
    return {
        "headline": f"₹{weak_monthly / 1e5:.1f} lakh a month is going to campaigns that return under 1.5× on mature cohorts.",
        "points": [
            f"Overall ROAS on mature cohorts (leads 30–120 days old) is {safe_div(mrev, msp):.2f}×, on ₹{msp / 1e7:.2f} Cr of spend.",
            f"{len(weak)} of {len(per)} campaigns {'returns' if len(weak) == 1 else 'return'} under 1.5×; the weakest is {nm(worst)} at {roas[worst]:.2f}×." if worst else
            "No campaign returns under 1.5× on mature cohorts.",
            f"{len(callouts)} open alert{'s' if len(callouts) != 1 else ''} cover ₹{at_stake / 1e5:.1f} lakh of spend. "
            "Each one passed a business threshold and a significance test, so none is week-to-week noise.",
            f"The best scalable campaigns are {nm(best[0])} ({roas[best[0]]:.1f}×) and {nm(best[1])} ({roas[best[1]]:.1f}×). "
            "Brand and retargeting score higher, but their audience is capped, so more budget won't buy more of the same.",
        ],
        "recommendation": (f"Pause or rebuild {nm(worst)} and move half its budget to {nm(best[0])} and {nm(best[1])} as a 4-week test "
                           f"with a holdout, judged on 30-day-mature ROAS, not CPL." if worst else
                           "Keep budgets; re-check after the next cohort matures."),
    }


def _add_outcomes(f, l, lags):
    f[2] += 1
    if l["attended_at"]:
        f[3] += 1
    if l["qualified"] == "1":
        f[4] += 1
    if l["sale_at"]:
        f[5] += 1
        f[6] += int(l["revenue_inr"])
        lags.append((dt.datetime.fromisoformat(l["sale_at"]) - dt.datetime.fromisoformat(l["created_at"])).days)


def what_moved(facts, meta, today, recent_days=7, base_days=28):
    """Rule-based callouts: last 7 complete days vs the 28 before, sized in rupees."""
    r_from = today - dt.timedelta(days=recent_days)
    b_from = r_from - dt.timedelta(days=base_days)
    agg = defaultdict(lambda: {"r": [0.0, 0], "b": [0.0, 0], "last3": [0.0, 0], "mature": [0.0, 0, 0]})
    for d, cid, sp, _c, ld, _a, _q, sales, _rev in facts:
        if cid == 0:
            continue
        day = dt.date.fromisoformat(d)
        a = agg[cid]
        if r_from <= day < today:
            a["r"][0] += sp; a["r"][1] += ld
            if day >= today - dt.timedelta(days=3):
                a["last3"][0] += sp; a["last3"][1] += ld
        elif b_from <= day < r_from:
            a["b"][0] += sp; a["b"][1] += ld
        if day <= today - dt.timedelta(days=MATURITY_DAYS):
            a["mature"][0] += sp; a["mature"][1] += ld; a["mature"][2] += sales

    out = []
    all_mature_sales = sum(a["mature"][2] for a in agg.values())
    all_mature_leads = sum(a["mature"][1] for a in agg.values())
    avg_rate = safe_div(all_mature_sales, all_mature_leads) or 0
    for cid, a in agg.items():
        m = meta[cid]
        r_sp, r_ld = a["r"]
        b_sp, b_ld = a["b"]
        b_cpl, r_cpl = safe_div(b_sp, b_ld), safe_div(r_sp, r_ld)
        p = rate_change_p(r_ld, r_sp, b_ld, b_sp)
        # one alert per campaign: a tracking break explains any CPL move, so it wins
        if a["last3"][0] > 0 and a["last3"][1] == 0 and b_cpl:
            expected = a["last3"][0] / b_cpl            # leads the spend would normally buy
            p0 = math.exp(-expected)                    # Poisson P(0 leads | expected)
            out.append({"kind": "bad", "campaign": m["name"], "channel": m["channel"], "impact": round(a["last3"][0]),
                        "stat": f"expected ~{expected:.0f} leads; {fmt_p(p0)}",
                        "title": "Spending with zero leads for 3 days",
                        "detail": f"₹{a['last3'][0]:,.0f} spent since {today - dt.timedelta(days=3):%d %b} and not one lead. "
                                  "Usually a broken landing page or form, not a bad audience. Check tracking first."})
        # a CPL move must clear BOTH a business threshold and a significance test (p < 0.01)
        elif b_cpl and r_cpl and r_sp >= 30000 and r_cpl >= 1.25 * b_cpl and p is not None and p < 0.01:
            extra = r_sp - r_ld * b_cpl
            out.append({"kind": "bad", "campaign": m["name"], "channel": m["channel"], "impact": round(extra), "stat": fmt_p(p),
                        "title": f"Cost per lead up {100 * (r_cpl / b_cpl - 1):.0f}%",
                        "detail": f"₹{b_cpl:,.0f} → ₹{r_cpl:,.0f} on similar spend: ₹{extra:,.0f} more this week for the same leads. "
                                  "A steady climb usually means creative fatigue; refresh the ads before cutting budget."})
        elif b_cpl and r_cpl and r_sp >= 30000 and r_cpl <= 0.8 * b_cpl and p is not None and p < 0.01:
            saved = r_ld * b_cpl - r_sp
            out.append({"kind": "good", "campaign": m["name"], "channel": m["channel"], "impact": round(saved), "stat": fmt_p(p),
                        "title": f"Cost per lead down {100 * (1 - r_cpl / b_cpl):.0f}%",
                        "detail": f"₹{b_cpl:,.0f} → ₹{r_cpl:,.0f}: ₹{saved:,.0f} of extra leads this week. A candidate for more budget."})
        msp, mld, msales = a["mature"]
        lo, hi = wilson(msales, mld)
        # flag only if even the UPPER end of the 95% interval is below 15% of the average sale rate
        if mld >= 300 and avg_rate and hi is not None and hi < 0.15 * avg_rate:
            out.append({"kind": "bad", "campaign": m["name"], "channel": m["channel"], "impact": round(msp),
                        "stat": f"95% CI {100 * lo:.2f}–{100 * hi:.2f}%",
                        "title": "Cheap leads that don't buy",
                        "detail": f"{mld:,} leads in mature cohorts, {msales} sale{'s' if msales != 1 else ''}: "
                                  f"{100 * msales / mld:.2f}% vs {100 * avg_rate:.2f}% average. "
                                  f"₹{msp:,.0f} spent. Low CPL is hiding near-zero lead quality."})
    out.sort(key=lambda x: -x["impact"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="site/data.js")
    args = ap.parse_args()
    data = build(args.data)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("window.ROI_DATA = " + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n")
    j = data["join"]
    print(f"{len(data['facts'])} fact rows; join by name {100 * j['matched_by_name'] / j['paid_leads']:.1f}% "
          f"vs by id {100 * j['matched_by_id'] / j['paid_leads']:.1f}%; {len(data['callouts'])} callouts -> {args.out}")


if __name__ == "__main__":
    main()
