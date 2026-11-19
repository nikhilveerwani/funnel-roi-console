"""Funnel & ROI Console: interactive Streamlit version.

Same synthetic data and the same tested rules as the static page (pipeline/transform.py):
spend joins leads on campaign ID, outcomes are cohorted on lead date, ROAS is judged on
30-day-mature cohorts, and every alert passes a business threshold plus a significance test.

Adds what a static page can't: filters, and a budget simulator ("what if I move this money?")
with an explicit, adjustable diminishing-returns assumption.

Run locally:  streamlit run streamlit_app.py
"""
import datetime as dt
import subprocess
import sys
import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "pipeline"))
import transform  # noqa: E402  (the same module the tests cover)

st.set_page_config(page_title="Funnel & ROI Console", page_icon="📈", layout="wide")

NAVY, AMBER, GREEN, RED, GREY = "#1F3864", "#E8A317", "#2E9E5B", "#D64545", "#8A94A6"
VERDICT_COLOR = {"Scale": GREEN, "Keep": NAVY, "Fix": AMBER, "Cut": RED}
CUT_BELOW = 1.5   # mature ROAS under this doesn't cover cost of delivery; same line as the executive summary


# ------------------------------------------------------------------ data
@st.cache_data(ttl=6 * 3600, show_spinner="Generating today's synthetic data…")
def load(today_iso: str):
    """Regenerate the synthetic window ending today (each day is seeded from its date, so
    history is stable), then run the production transform on it."""
    out = Path(tempfile.gettempdir()) / f"roi_console_{today_iso}"
    if not (out / "leads.csv").exists():
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "generate_synthetic.py"),
                        "--out", str(out), "--days", "120", "--today", today_iso], check=True, capture_output=True)
    data = transform.build(str(out), today=dt.date.fromisoformat(today_iso))
    facts = pd.DataFrame(data["facts"], columns=data["facts_cols"])
    facts["date"] = pd.to_datetime(facts["date"]).dt.date
    camps = pd.DataFrame(data["campaigns"]).rename(columns={"id": "campaign_id"})
    organic = pd.DataFrame([{"campaign_id": 0, "name": "Organic / no UTM", "channel": "Organic", "old_names": []}])
    facts = facts.merge(pd.concat([camps, organic]), on="campaign_id", how="left")
    return data, facts


def inr(x):
    if x is None or pd.isna(x):
        return "–"
    a, sign = abs(x), "-" if x < 0 else ""   # leading "-" also lets st.metric colour the delta red
    return sign + (f"₹{a / 1e7:.2f} Cr" if a >= 1e7 else f"₹{a / 1e5:.1f} L" if a >= 1e5 else f"₹{a:,.0f}")


def div(a, b):
    return a / b if b else None


today = dt.datetime.now(transform.IST).date()
data, facts = load(today.isoformat())
mature_cut = today - dt.timedelta(days=transform.MATURITY_DAYS)
capped = lambda name: any(k in name.lower() for k in transform.CAPPED)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### Filters")
    channels = sorted(facts["channel"].unique())
    pick = st.multiselect("Channels", channels, default=[c for c in channels if c != "Organic"])
    d0, d1 = facts["date"].min(), facts["date"].max()
    rng = st.date_input("Lead date range", (d0, d1), min_value=d0, max_value=d1)
    st.caption("ROAS columns always use **mature cohorts** (leads 30+ days old), whatever the range, "
               "because sales keep landing for weeks after a lead arrives.")
    st.divider()
    st.markdown("**Demo with synthetic data.** The production version runs on company data I can't share.")
    st.markdown("[Static version](https://nikhilveerwani.github.io/funnel-roi-console/) · "
                "[Code](https://github.com/nikhilveerwani/funnel-roi-console) · "
                "[Portfolio](https://nikhilveerwani.github.io/)")

lo_d, hi_d = (rng if isinstance(rng, (list, tuple)) and len(rng) == 2 else (d0, d1))
F = facts[facts["channel"].isin(pick) & facts["date"].between(lo_d, hi_d)]

# ------------------------------------------------------------------ header + summary
st.title("Funnel & ROI Console")
st.markdown("Every rupee of ad spend, joined on **campaign ID** to what those leads did: attended, qualified, bought. "
            "Which campaigns to **scale, fix or cut**, and what happens if you move the money.")
st.info("🧪 **Demo with synthetic data**, regenerated daily. Numbers are illustrative; the method is the point.", icon=None)

s = data["summary"]
with st.container(border=True):
    st.markdown(f"#### {s['headline']}")
    for p in s["points"]:
        st.markdown(f"- {p}")
    st.markdown(f"**Recommendation:** {s['recommendation']}")

t = F[["spend", "leads", "attended", "qualified", "sales", "revenue"]].sum()
young = F.loc[F["date"] > mature_cut, "leads"].sum()
k = st.columns(6)
k[0].metric("Spend", inr(t.spend))
k[1].metric("Leads", f"{int(t.leads):,}", f"CPL {inr(div(t.spend, t.leads))}", delta_color="off", delta_arrow="off")
k[2].metric("Attended", f"{div(t.attended, t.leads) or 0:.0%}", f"{int(t.attended):,} leads", delta_color="off", delta_arrow="off")
k[3].metric("Sales", f"{int(t.sales):,}", f"cost/sale {inr(div(t.spend, t.sales))}", delta_color="off", delta_arrow="off")
k[4].metric("ROAS", f"{div(t.revenue, t.spend) or 0:.2f}×", f"{inr(t.revenue)} revenue", delta_color="off", delta_arrow="off")
k[5].metric("Still maturing", f"{div(young, t.leads) or 0:.0%}", "of leads < 30 days old", delta_color="off", delta_arrow="off")

tab_c, tab_sim, tab_alert, tab_trend, tab_dq = st.tabs(
    ["Scale · fix · cut", "Budget simulator", "What moved", "Trend", "Data quality"])


# ------------------------------------------------------------------ per-campaign table
def campaign_table(df):
    paid = df[df["campaign_id"] != 0]
    allc = paid.groupby(["campaign_id", "name", "channel"], as_index=False)[["spend", "leads", "attended", "sales", "revenue"]].sum()
    mat = (paid[paid["date"] <= mature_cut].groupby("campaign_id")[["spend", "revenue", "leads", "sales"]].sum()
           .rename(columns=lambda c: "m_" + c))
    last30 = paid[paid["date"] > today - dt.timedelta(days=30)].groupby("campaign_id")["spend"].sum().rename("spend_30d")
    c = allc.join(mat, on="campaign_id").join(last30, on="campaign_id").fillna(0)
    c["cpl"] = c["spend"] / c["leads"].where(c["leads"] > 0)
    c["roas"] = c["m_revenue"] / c["m_spend"].where(c["m_spend"] > 0)
    c["capped"] = c["name"].map(capped)
    avg_cpl = div(c["spend"].sum(), c["leads"].sum())
    # Benchmark = median ROAS of SCALABLE campaigns. The all-campaign average is inflated by brand and
    # retargeting, which would mark every healthy prospecting campaign as "below average".
    bench = c.loc[~c["capped"], "roas"].median()

    def verdict(r):
        if pd.isna(r.roas):
            return "Keep"
        if r.roas < CUT_BELOW:
            return "Cut"
        if r.capped:
            return "Keep"
        if r.roas >= bench:
            return "Scale"
        return "Fix" if r.cpl <= avg_cpl else "Keep"
    c["verdict"] = c.apply(verdict, axis=1)
    return c.sort_values("spend", ascending=False), avg_cpl, bench


C, avg_cpl, bench = campaign_table(F)

with tab_c:
    if C.empty:
        st.warning("No paid campaigns in this filter.")
    else:
        st.markdown(f"Each bubble is a campaign, sized by spend.\n"
                    f"- **Scale**: mature ROAS at or above the median scalable campaign (**{bench:.2f}×**)\n"
                    f"- **Fix**: below that, but leads are cheap (CPL under **{inr(avg_cpl)}**). The targeting or follow-up is leaking\n"
                    f"- **Cut**: under **{CUT_BELOW}×** ROAS\n"
                    "- **Keep**: everything else. Brand and retargeting are never *Scale*: their audience is capped, so more budget doesn't buy more of the same.")
        base = alt.Chart(C.dropna(subset=["roas", "cpl"]))
        pts = base.mark_circle(opacity=0.8, stroke="white", strokeWidth=1).encode(
            x=alt.X("cpl:Q", scale=alt.Scale(type="log"), title="Cost per lead (₹, log)"),
            y=alt.Y("roas:Q", scale=alt.Scale(type="log"), title="ROAS on mature cohorts (log)"),
            size=alt.Size("spend:Q", legend=None, scale=alt.Scale(range=[60, 1600])),
            color=alt.Color("verdict:N", scale=alt.Scale(domain=list(VERDICT_COLOR), range=list(VERDICT_COLOR.values())),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=["name", "channel", alt.Tooltip("spend:Q", format=",.0f"), alt.Tooltip("cpl:Q", format=",.0f", title="CPL"),
                     alt.Tooltip("roas:Q", format=".2f", title="ROAS"), "sales", "verdict"])
        rules = (alt.Chart(pd.DataFrame({"x": [avg_cpl]})).mark_rule(strokeDash=[4, 4], color=GREY).encode(x="x:Q") +
                 alt.Chart(pd.DataFrame({"y": [bench]})).mark_rule(strokeDash=[4, 4], color=GREEN).encode(y="y:Q") +
                 alt.Chart(pd.DataFrame({"y": [CUT_BELOW]})).mark_rule(strokeDash=[4, 4], color=RED).encode(y="y:Q"))
        st.altair_chart((pts + rules).properties(height=420), width="stretch")

        show = C[["verdict", "name", "channel", "spend", "leads", "cpl", "sales", "roas"]].round({"cpl": 0, "spend": 0}).rename(columns={
            "verdict": "Verdict", "name": "Campaign", "channel": "Channel", "spend": "Spend (₹)", "leads": "Leads",
            "cpl": "CPL (₹)", "sales": "Sales", "roas": "Mature ROAS"})
        st.dataframe(show, hide_index=True, width="stretch", column_config={
            "Spend (₹)": st.column_config.NumberColumn(format="localized"),
            "CPL (₹)": st.column_config.NumberColumn(format="localized"),
            "Leads": st.column_config.NumberColumn(format="localized"),
            "Mature ROAS": st.column_config.NumberColumn(format="%.2f×")})

# ------------------------------------------------------------------ budget simulator
with tab_sim:
    st.markdown("**What if you move the money?** Change any campaign's monthly budget and see the projected revenue. "
                "Spend doesn't scale revenue 1:1, so the model assumes diminishing returns:")
    st.latex(r"\text{revenue}' = \text{revenue}_{30d} \times \left(\frac{\text{budget}'}{\text{budget}}\right)^{e}")
    cc = st.columns(2)
    e_open = cc[0].slider("Elasticity, normal campaigns (e)", 0.2, 1.0, 0.7, 0.05,
                          help="1.0 = every extra rupee earns the average ROAS. Lower = faster saturation.")
    e_cap = cc[1].slider("Elasticity, brand & retargeting", 0.0, 0.6, 0.2, 0.05,
                         help="Capped audiences saturate fast: extra budget mostly buys the same people again.")

    sim = C[C["spend_30d"] > 0].copy()
    sim["e"] = sim["capped"].map({True: e_cap, False: e_open})
    sim["rev_30d"] = sim["spend_30d"] * sim["roas"].fillna(0)        # run-rate revenue at mature ROAS
    sim["marginal"] = sim["e"] * sim["roas"].fillna(0)               # ROAS of the NEXT rupee

    # Buttons set a preset plan and bump the editor's key, so stale manual edits don't override the preset.
    if "plan" not in st.session_state or set(st.session_state.plan) != set(sim["name"]):
        st.session_state.plan, st.session_state.ver = {n: 0 for n in sim["name"]}, st.session_state.get("ver", 0) + 1
    b = st.columns([1, 1, 3])
    if b[0].button("Apply recommendation", type="primary",
                   help="Cut the weakest campaign under 1.5×; move half its budget to the two best scalable campaigns."):
        weak = sim[sim["roas"] < 1.5]
        plan = {n: 0 for n in sim["name"]}
        if not weak.empty:
            worst = weak.loc[weak["roas"].idxmin()]
            plan[worst["name"]] = -100
            for _, r in sim[~sim["capped"]].nlargest(2, "roas").iterrows():
                plan[r["name"]] = round(100 * worst["spend_30d"] / 4 / r["spend_30d"])
        st.session_state.plan, st.session_state.ver = plan, st.session_state.ver + 1
    if b[1].button("Reset"):
        st.session_state.plan, st.session_state.ver = {n: 0 for n in sim["name"]}, st.session_state.ver + 1

    sim["Change %"] = sim["name"].map(st.session_state.plan)
    edit = st.data_editor(
        sim[["name", "channel", "spend_30d", "roas", "marginal", "Change %"]].rename(columns={
            "name": "Campaign", "channel": "Channel", "spend_30d": "Budget, last 30d (₹)", "roas": "Avg ROAS", "marginal": "Next-rupee ROAS"}),
        hide_index=True, width="stretch", disabled=["Campaign", "Channel", "Budget, last 30d (₹)", "Avg ROAS", "Next-rupee ROAS"],
        column_config={"Budget, last 30d (₹)": st.column_config.NumberColumn(format="localized"),
                       "Avg ROAS": st.column_config.NumberColumn(format="%.2f×"),
                       "Next-rupee ROAS": st.column_config.NumberColumn(format="%.2f×", help="elasticity × average ROAS"),
                       "Change %": st.column_config.NumberColumn(min_value=-100, max_value=300, step=5)},
        key=f"editor{st.session_state.ver}")
    plan_now = dict(zip(edit["Campaign"], edit["Change %"].fillna(0)))

    sim["new_spend"] = sim["spend_30d"] * (1 + sim["name"].map(plan_now) / 100)
    ratio = (sim["new_spend"] / sim["spend_30d"]).clip(lower=0)
    sim["new_rev"] = sim["rev_30d"] * ratio ** sim["e"]
    S0, S1, R0, R1 = sim["spend_30d"].sum(), sim["new_spend"].sum(), sim["rev_30d"].sum(), sim["new_rev"].sum()

    m = st.columns(4)
    m[0].metric("Monthly budget", inr(S1), inr(S1 - S0) if abs(S1 - S0) > 1 else "no change", delta_color="off", delta_arrow="off")
    m[1].metric("Projected revenue", inr(R1), inr(R1 - R0))
    m[2].metric("ROAS", f"{div(R1, S1) or 0:.2f}×", f"{(div(R1, S1) or 0) - (div(R0, S0) or 0):+.2f}×")
    m[3].metric("Extra revenue per ₹ moved", f"{div(R1 - R0, (sim['new_spend'] - sim['spend_30d']).abs().sum() / 2) or 0:.2f}×",
                help="Revenue gained per rupee reallocated. Above 0 means the move pays for itself.")

    chg = sim[sim["new_spend"].round() != sim["spend_30d"].round()].assign(delta=lambda d: d["new_rev"] - d["rev_30d"])
    if not chg.empty:
        st.altair_chart(alt.Chart(chg).mark_bar().encode(
            x=alt.X("delta:Q", title="Change in monthly revenue (₹)"),
            y=alt.Y("name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
            color=alt.condition("datum.delta >= 0", alt.value(GREEN), alt.value(RED)),
            tooltip=["name", alt.Tooltip("delta:Q", format=",.0f")]).properties(height=60 + 44 * len(chg)),
            width="stretch")
    st.caption("This is a planning model, not a forecast. Elasticity is an assumption: estimate it from past budget changes, "
               "then confirm any move with a 4-week test against a holdout before rolling it out.")

# ------------------------------------------------------------------ alerts
with tab_alert:
    st.markdown("Last 7 complete days vs the 28 before. An alert fires only if it clears a **business threshold and a "
                "statistical test** (Poisson rate test p < 0.01, 95% Wilson interval, or Poisson chance of zero leads).")
    al = [a for a in data["callouts"] if a["channel"] in pick]
    if not al:
        st.success("Nothing moved beyond noise this week.")
    for a in al:
        icon = "🔴" if a["kind"] == "bad" else "🟢"
        with st.container(border=True):
            st.markdown(f"{icon} **{a['title']}**: {a['campaign']} ({a['channel']}) · **{inr(a['impact'])}** · `{a['stat']}`")
            st.markdown(a["detail"])

# ------------------------------------------------------------------ trend
with tab_trend:
    wk = F.assign(week=pd.to_datetime(F["date"]).dt.to_period("W").dt.start_time).groupby("week", as_index=False)[
        ["spend", "leads", "revenue"]].sum()
    wk["CPL"] = wk["spend"] / wk["leads"]
    wk["mature"] = wk["week"].dt.date <= mature_cut
    st.markdown("Weekly spend and cost per lead. Revenue for recent weeks is shown faded: those cohorts are still maturing, "
                "so their ROAS will rise. It isn't a drop.")
    bars = alt.Chart(wk).mark_bar(color=NAVY).encode(x=alt.X("week:T", title=None), y=alt.Y("spend:Q", title="Spend (₹)"))
    line = alt.Chart(wk).mark_line(color=AMBER, point=True).encode(x="week:T", y=alt.Y("CPL:Q", title="CPL (₹)"))
    st.altair_chart(alt.layer(bars, line).resolve_scale(y="independent").properties(height=300), width="stretch")
    wk["ROAS"] = wk["revenue"] / wk["spend"]
    st.altair_chart(alt.Chart(wk).mark_bar().encode(
        x=alt.X("week:T", title=None), y=alt.Y("ROAS:Q", title="ROAS by lead week"),
        color=alt.condition("datum.mature", alt.value(GREEN), alt.value("#C9D7C9")),
        tooltip=[alt.Tooltip("week:T"), alt.Tooltip("ROAS:Q", format=".2f"), "mature"]).properties(height=240),
        width="stretch")

# ------------------------------------------------------------------ data quality
with tab_dq:
    j = data["join"]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Why join on campaign ID, not name**")
        jd = pd.DataFrame({"Join key": ["Campaign name", "Campaign ID"],
                           "Matched": [j["matched_by_name"] / j["paid_leads"], j["matched_by_id"] / j["paid_leads"]]})
        st.altair_chart(alt.Chart(jd).mark_bar(size=38).encode(
            x=alt.X("Matched:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])), y=alt.Y("Join key:N", title=None),
            color=alt.Color("Join key:N", scale=alt.Scale(range=[RED, GREEN]), legend=None),
            tooltip=[alt.Tooltip("Matched:Q", format=".1%")]).properties(height=140), width="stretch")
        st.caption("Campaigns get renamed in the ad platform; old links keep the old name. "
                   f"{j['paid_leads'] - j['matched_by_name']:,} paid leads would be orphaned by a name join.")
        renamed = [c for c in data["campaigns"] if c["old_names"]]
        if renamed:
            st.dataframe(pd.DataFrame([{"Live name": c["name"], "Old name(s) still in links": ", ".join(c["old_names"])} for c in renamed]),
                         hide_index=True, width="stretch")
    with c2:
        st.markdown("**Why ROAS waits 30 days**")
        lag = data["sale_lag_share"]
        ld = pd.DataFrame({"Days after lead": [f"≤ {k}" for k in lag], "Share of sales": [v / 100 for v in lag.values()]})
        st.altair_chart(alt.Chart(ld).mark_bar(color=NAVY, size=38).encode(
            x=alt.X("Days after lead:N", sort=None, title="Days from lead to sale"),
            y=alt.Y("Share of sales:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            tooltip=[alt.Tooltip("Share of sales:Q", format=".0%")]).properties(height=220), width="stretch")
        st.caption("Judging last week's ROAS today would miss most of its sales, so recent cohorts are labelled maturing.")

st.caption(f"Data window {data['window']['from']} → {data['window']['to']} · generated {data['generated_at']} · "
           "built by Nikhil Veerwani")
