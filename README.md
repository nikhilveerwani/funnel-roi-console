<div align="center">

# Funnel &amp; ROI Console

**Where the money goes, and what comes back: ad spend joined to the full lead funnel on campaign ID, with scale / fix / cut and "what moved this week" in rupees.**

[![Live demo](https://img.shields.io/badge/Live_demo-open_the_console-2F4BD8?style=for-the-badge)](https://nikhilveerwani.github.io/funnel-roi-console/)
[![Refresh console](https://github.com/nikhilveerwani/funnel-roi-console/actions/workflows/refresh.yml/badge.svg)](https://github.com/nikhilveerwani/funnel-roi-console/actions/workflows/refresh.yml)
![Synthetic data](https://img.shields.io/badge/data-synthetic-B7791F)

<a href="https://nikhilveerwani.github.io/funnel-roi-console/"><img src="docs/screenshot.png" alt="Console screenshot" width="860"></a>

</div>

> **Demo with synthetic data.** I built and run the production version of this console on company data I can't share. This repo is a clean-room rebuild: fresh code, a made-up business with 16 campaigns across Google, Meta, YouTube and LinkedIn, and the same rules.

## The problem

Marketing reports cost per lead. Sales reports revenue. Nobody can say which campaign's rupees turned into which sales, so budget follows the cheapest leads rather than the most profitable ones.

Joining the two sounds easy. In practice it breaks in three quiet ways:

1. **The join key.** The obvious join is campaign *name*. But campaigns get renamed in the ad platform, while links already out in the world keep the old name in the UTM. UTMs also arrive lower-cased, with stray spaces, or URL-encoded. In this demo a name join loses **about 13% of paid leads**. The numeric campaign ID never changes, and matches **about 98.5%**.
2. **Timing.** Sales land days or weeks after the lead (here, only about 40% within a week, 99% within a month). Judge last week's campaigns on sales so far and every new campaign looks like a failure.
3. **Cheap ≠ good.** The lowest cost-per-lead campaign can be the worst investment if those leads never buy.

## What the console shows

| View | Decision it supports |
|---|---|
| **KPIs** with a maturity note | Spend, leads, CPL, sales, cost per sale and ROAS for any range or channel, and an honest flag when the range is too recent for final numbers |
| **What moved this week** | Rule-based alerts sized in rupees: spend with zero leads (broken landing page), CPL jumps (creative fatigue), cheap leads that never buy |
| **Scale, fix or cut** | Every campaign by CPL vs ROAS on **mature cohorts only**, sized by spend, against average and break-even lines |
| **Weekly spend and CPL** | Is efficiency drifting? |
| **Funnel by channel** | Attend → qualify → buy rates: where each channel loses people |
| **Every campaign** | A sortable table, with renamed campaigns flagged and the share of each campaign's leads still maturing |
| **Join quality** | Name join vs ID join, and the sale-lag curve behind the 30-day maturity rule |

## The rules (and why)

- **Join on campaign ID**, extracted from the end of the UTM (`name__id`). The extraction tolerates case, spaces and URL-encoding. Names are display-only: the latest name is shown, and old names are kept as a "renamed" hint. Leads without an ID are reported as unmatched, never guessed.
- **Outcomes belong to the lead's creation date**, so spend on a day sits next to what *those* leads did, whenever they bought.
- **A cohort matures for 30 days** before its ROAS is judged. The data supports this: 99% of sales land within 30 days.
- **"What moved" is rules, not a language model.** It compares the last 7 days with the 28 before. It only fires above ₹30k weekly spend, with thresholds of +25% / −20% CPL, zero leads for 3 days, and a sale rate under 15% of average. Every alert carries a rupee figure, so the biggest problem is at the top.

## How it works

```mermaid
flowchart LR
  A[Ad spend<br/>daily per campaign] --> C[Transform<br/>ID from UTM, join,<br/>cohort facts, what moved]
  B[CRM leads<br/>UTM + funnel outcomes] --> C
  C --> D[data.js<br/>daily facts per campaign]
  D --> E[Static page<br/>aggregates any range<br/>or channel in-browser]
  F[GitHub Actions<br/>daily 10:00 IST] -. tests, rebuild, deploy .-> C
```

| Path | What it is |
|---|---|
| `pipeline/generate_synthetic.py` | Synthetic spend and leads, with the traps built in: a renamed campaign, messy UTMs, sale lag, and planted stories |
| `pipeline/transform.py` | ID extraction, the join (both ways, to measure the gap), daily cohort facts, sale-lag curve, rule-based callouts |
| `sql/campaign_roi.sql` | The same join and metrics in BigQuery SQL (`REGEXP_EXTRACT` on the UTM, full outer join of spend and funnel, maturity share) |
| `tests/` | ID extraction edge cases, and each callout rule (including that small noise does *not* fire) |
| `site/index.html` | A single static page (vanilla JS + Chart.js) |

## Run it locally

```bash
python -m unittest discover -s tests
python pipeline/generate_synthetic.py --out data --days 120
python pipeline/transform.py --data data --out site/data.js
# open site/index.html
```

It uses only the Python standard library.

---

<sub>Built by <a href="https://nikhilveerwani.github.io/">Nikhil Veerwani</a> · Analytics, BI &amp; Growth · All data in this repository is synthetic.</sub>
