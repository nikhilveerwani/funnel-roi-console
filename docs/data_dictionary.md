# Data dictionary

## Inputs (synthetic, from `pipeline/generate_synthetic.py`)

### `ad_spend_daily.csv`: one row per campaign per day

| Column | Type | Meaning |
|---|---|---|
| `date` | date (IST) | Spend date |
| `campaign_id` | integer | Ad platform's campaign ID. **Stable**: never changes on rename |
| `campaign_name` | text | Name *on that day*. Can change mid-flight |
| `channel` | text | Google Search, Google Display, YouTube, Meta, LinkedIn |
| `impressions`, `clicks` | integer | Delivery counts |
| `spend_inr` | decimal | Spend in ₹ |

### `leads.csv`: one row per lead, with funnel outcomes

| Column | Type | Meaning |
|---|---|---|
| `lead_id` | text | Unique lead ID |
| `created_at` | timestamp (IST) | When the lead registered. **Cohort date for all outcomes** |
| `utm_campaign` | text | `"<name>__<campaign_id>"` as captured by the form. Can be lower-cased, padded, URL-encoded, carry an old name, or (about 1.5%) have no ID. Blank = organic |
| `utm_source` | text | Channel label from the form |
| `attended_at` | timestamp | Joined a live demo session (blank = didn't) |
| `qualified` | 0/1 | Passed qualification |
| `sale_at` | timestamp | Purchase time (blank = no sale yet) |
| `revenue_inr` | integer | Booked revenue in ₹ (0 if no sale) |

## Output: `site/data.js`

| Field | Meaning |
|---|---|
| `facts` | `[date, campaign_id, spend, clicks, leads, attended, qualified, sales, revenue]` per campaign per lead-creation date. `campaign_id = 0` is organic |
| `campaigns` | ID, latest name, channel, and any **old names** (flagged "renamed" on the page) |
| `join` | Paid leads, matched by name, matched by ID, leads with no ID in the UTM |
| `sale_lag_share` | % of all sales landed within 7, 14 and 30 days of the lead |
| `callouts` | Rule-based alerts: kind, campaign, title, detail, ₹ impact, statistic |
| `summary` | Executive summary: headline, points, recommendation |

## Metric definitions

| Metric | Definition |
|---|---|
| **CPL** | spend ÷ leads, same campaign and same lead-creation dates |
| **Attend / qualify / sale rate** | outcome count ÷ leads created in the range |
| **Cost per sale** | spend ÷ sales from leads created in the range |
| **ROAS** | revenue from leads created in the range ÷ spend on those dates |
| **Mature cohort** | leads created 30–120 days ago. Used for any ROAS comparison between campaigns |
| **Maturing share** | share of a range's leads under 30 days old: their ROAS will still rise |

## Alert rules (last 7 complete days vs the 28 before)

| Alert | Business threshold | Statistical test |
|---|---|---|
| Spending with zero leads | spend in last 3 days > 0, zero leads | Poisson P(0 leads \| expected leads at baseline CPL) |
| CPL up / down | ≥ +25% / ≤ −20%, recent spend ≥ ₹30k | Conditional binomial (Poisson rate) test on leads per ₹, p < 0.01 |
| Cheap leads that don't buy | ≥ 300 mature leads | Upper end of 95% Wilson interval below 15% of the average sale rate |
