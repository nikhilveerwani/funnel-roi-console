"""Generate SYNTHETIC ad spend and lead-funnel data for the Funnel & ROI Console demo.

A made-up business sells a high-ticket online programme. Leads come from paid campaigns
(and organic), attend a live demo session, get qualified, and some buy.

Nothing is real, but the traps are:
  * campaigns get RENAMED in the ad platform while old links keep the old name in the UTM,
    so joining spend to leads on campaign NAME silently drops leads; the ID never changes,
  * UTMs arrive messy: mixed case, stray spaces, URL-encoding, a few with no ID at all,
  * sales land days or weeks after the lead, so recent cohorts look worse than they are,
  * planted stories for the console to find: a cheap-lead campaign that never sells, a
    prospecting campaign whose cost per lead jumps (creative fatigue), and a campaign
    that keeps spending after its landing page broke.

Every day is seeded from its date, so history is stable as the window rolls forward.
Usage: python pipeline/generate_synthetic.py --out data --days 120
"""
import argparse
import csv
import datetime as dt
import os
import random
import urllib.parse

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# id, channel, name, daily spend (INR), base CPL (INR), lead->sale rate, story
CAMPAIGNS = [
    (61804411, "Google Search", "GS_Brand_Exact", 9000, 260, 0.075, None),
    (61804412, "Google Search", "GS_Generic_Career_Switch", 26000, 720, 0.030, None),
    (61804413, "Google Search", "GS_Competitor_Terms", 14000, 980, 0.028, None),
    (61804414, "Google Search", "GS_Course_Fees_Intent", 12000, 640, 0.042, None),
    (61804420, "Google Display", "GD_Remarketing_All", 8000, 310, 0.022, None),
    (61804421, "Google Display", "GD_Affinity_Tech_Pros", 15000, 140, 0.0012, "cheap_junk"),
    (61804430, "YouTube", "YT_Testimonial_15s", 11000, 690, 0.018, None),
    (23850101, "Meta", "FB_Prospecting_Senior_Engineers", 32000, 610, 0.024, "fatigue"),
    (23850102, "Meta", "FB_Prospecting_Managers_30plus", 24000, 820, 0.031, None),
    (23850103, "Meta", "FB_Lookalike_Buyers_1pct", 21000, 540, 0.027, "renamed"),
    (23850104, "Meta", "FB_Retargeting_Site_7d", 9000, 330, 0.046, None),
    (23850105, "Meta", "IG_Reels_Career_Stories", 16000, 470, 0.014, None),
    (23850106, "Meta", "FB_Lead_Form_Webinar", 18000, 290, 0.011, None),
    (23850107, "Meta", "FB_Prospecting_Freshers_Tier2", 10000, 230, 0.004, None),
    (71200301, "LinkedIn", "LI_Sponsored_Directors", 14000, 2100, 0.060, None),
    (71200302, "LinkedIn", "LI_Lead_Gen_Data_Roles", 12000, 1500, 0.036, "broken_lp"),
]
RENAMED_TO = "FB_LAL_Purchasers_1pct_v2"   # new name for the 'renamed' campaign from RENAME_DAY on
PRICE = (65000, 140000)                      # programme price range, INR


def utm_for(rng, name, cid):
    """The campaign UTM as it arrives in the CRM: name__id, often messy."""
    raw = f"{name}__{cid}"
    r = rng.random()
    if r < 0.06:
        raw = raw.lower()
    elif r < 0.10:
        raw = f" {raw} "
    elif r < 0.13:
        raw = urllib.parse.quote(raw.replace("_", " "), safe="")
    elif r < 0.145:
        raw = name                                     # ID missing: cannot be matched
    return raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--today", help="IST date treated as today (default: current date)")
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(IST).date()
    start = today - dt.timedelta(days=args.days)
    rename_day = today - dt.timedelta(days=45)
    os.makedirs(args.out, exist_ok=True)

    spend_rows, lead_rows = [], []
    for d in range(args.days):
        day = start + dt.timedelta(days=d)
        if day >= today:
            break
        days_ago = (today - day).days
        dow = day.weekday()
        for cid, channel, name, budget, cpl, cvr, story in CAMPAIGNS:
            rng = random.Random(f"{cid}-{day.isoformat()}")
            live_name = RENAMED_TO if story == "renamed" and day >= rename_day else name
            spend = budget * rng.uniform(0.85, 1.12) * (0.8 if dow >= 5 else 1.0)
            eff_cpl = cpl * rng.uniform(0.85, 1.18)
            if story == "fatigue" and days_ago <= 9:
                eff_cpl *= 1 + 0.07 * (10 - days_ago)        # creative fatigue: CPL climbs
            n_leads = int(spend / eff_cpl + rng.random())
            if story == "broken_lp" and days_ago <= 4:
                n_leads = 0                                   # landing page broke, spend continues
            clicks = int(n_leads * rng.uniform(6, 14)) + rng.randrange(20, 80)
            spend_rows.append([day.isoformat(), cid, live_name, channel, int(clicks * rng.uniform(25, 60)), clicks, round(spend, 2)])

            for i in range(n_leads):
                t = dt.datetime.combine(day, dt.time(rng.randrange(24), rng.randrange(60)), IST)
                # most leads arrive via links built with the name at the time; older ads keep the old name
                name_in_link = name if (story == "renamed" and rng.random() < 0.55) else live_name
                lead_rows.append(_funnel(rng, f"P{cid % 10000:04d}{day.strftime('%y%m%d')}{i:03d}", t,
                                         utm_for(rng, name_in_link, cid), channel, cvr, today))

        # organic / direct leads: no campaign
        rng = random.Random(f"organic-{day.isoformat()}")
        for i in range(int(rng.gauss(55, 8))):
            t = dt.datetime.combine(day, dt.time(rng.randrange(24), rng.randrange(60)), IST)
            lead_rows.append(_funnel(rng, f"O{day.strftime('%y%m%d')}{i:03d}", t, "", "Organic", 0.035, today))

    def write(name, header, rows):
        with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(header); w.writerows(rows)

    write("ad_spend_daily.csv", ["date", "campaign_id", "campaign_name", "channel", "impressions", "clicks", "spend_inr"], spend_rows)
    write("leads.csv", ["lead_id", "created_at", "utm_campaign", "utm_source", "attended_at", "qualified",
                        "sale_at", "revenue_inr"], lead_rows)
    print(f"synthetic: {len(spend_rows)} spend rows, {len(lead_rows)} leads ({args.days} days to {today})")


def _funnel(rng, lead_id, created, utm, source, cvr, today):
    """Walk one lead through attend -> qualify -> sale, with realistic lags, cut off at today."""
    now = dt.datetime.combine(today, dt.time(0, 0), IST)
    attended = qualified = sale = None
    revenue = 0
    if rng.random() < min(0.95, 0.30 + cvr * 6):
        attended = created + dt.timedelta(hours=rng.uniform(4, 96))
        if rng.random() < min(0.95, 0.25 + cvr * 8):
            qualified = True
            if rng.random() < cvr / ((0.30 + cvr * 6) * (0.25 + cvr * 8)):
                sale = attended + dt.timedelta(days=rng.lognormvariate(2.0, 0.7))   # median ~7 days
                revenue = rng.randrange(*PRICE, 500)
    if attended and attended >= now:
        attended = qualified = sale = None; revenue = 0
    if sale and sale >= now:
        sale = None; revenue = 0
    iso = lambda x: x.isoformat(timespec="minutes") if x else ""
    return [lead_id, iso(created), utm, source, iso(attended), "1" if qualified else "0", iso(sale), revenue]


if __name__ == "__main__":
    main()
