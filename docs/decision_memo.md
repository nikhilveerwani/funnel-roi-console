# Decision memo: where the next rupee of ad spend should go

**To:** CEO, Head of Marketing · **From:** Analytics · **Data:** synthetic demo, last 120 days

> Figures are from the live demo on the day this memo was written. The console recomputes them every morning, and the [live executive summary](https://nikhilveerwani.github.io/funnel-roi-console/) always shows today's numbers.

## The decision

Should we keep allocating budget by **cost per lead**, as we do today, or by **return on spend after leads have had time to buy**?

## What we found

1. **CPL points the wrong way.** The cheapest campaign (Google Display, Affinity Tech Pros, about ₹145 per lead) is the worst investment: about 0.2% of its leads buy, against 2.2% on average (95% interval 0.11–0.29%, so this is not bad luck). Ranked by CPL, it would get *more* budget.
2. **About ₹4 lakh a month goes to campaigns returning under 1.5×** on mature cohorts (leads 30–120 days old). Overall ROAS on mature cohorts is about 4.9×.
3. **Recent weeks always look worse than they are.** Only about 40% of sales land within a week of the lead; 99% within 30 days. Any review of "last week's ROAS" will cut campaigns that are working.
4. **Our current spend-to-lead join loses about 13% of paid leads.** It matches on campaign name, which breaks when a campaign is renamed or a UTM arrives lower-case or URL-encoded. Matching on campaign ID recovers them (about 98.5% matched).

## Options

| Option | Upside | Risk |
|---|---|---|
| **A. Keep allocating by CPL** | Simple, fast feedback | Keeps funding cheap leads that don't buy |
| **B. Reallocate now by mature ROAS** | Moves money to what pays back | ROAS falls as a campaign scales; brand and retargeting can't absorb more |
| **C. Test, then reallocate (recommended)** | Measures the real marginal return before committing | 4 weeks of patience |

## Recommendation: Option C

1. **Pause or rebuild Affinity Tech Pros now.** The evidence is strong, and the spend at stake is the largest single item.
2. **Move half its budget to the two best *scalable* campaigns** (GS Course Fees Intent, FB Lookalike Purchasers) for 4 weeks, with a holdout region. Brand and retargeting are excluded because their audience is capped.
3. **Judge the test on 30-day-mature ROAS, not CPL.** The console labels immature ranges, so nobody reads week one as a failure.
4. **Switch the spend join to campaign ID** in the reporting layer. It is a one-line change in the SQL (`REGEXP_EXTRACT` on the UTM) and restores the missing 13% of leads to their campaigns.

## What would change this recommendation

- The holdout shows the best campaigns' ROAS dropping sharply with more budget (saturation): stop at the point where marginal ROAS falls below 2×.
- Finance net revenue (after refunds and EMI defaults) differs materially by channel: re-rank on net revenue.
