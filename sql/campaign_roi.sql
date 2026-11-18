-- Campaign ROI in BigQuery Standard SQL: ad spend joined to the lead funnel on CAMPAIGN ID.
-- Same rules as pipeline/transform.py. Table names are generic placeholders.
--
--   `project.ads.spend_daily`   date, campaign_id, campaign_name, channel, clicks, spend_inr
--   `project.crm.leads`         lead_id, created_at, utm_campaign, attended_at, qualified, sale_at, revenue_inr
--
-- Why the ID: campaign names change in the ad platform, but links already out in the world keep
-- the old name in utm_campaign. A name join silently drops those leads; the numeric ID never changes.

DECLARE maturity_days INT64 DEFAULT 30;

WITH leads AS (
  SELECT
    l.*,
    DATE(l.created_at, 'Asia/Kolkata') AS lead_date,
    -- 'FB_Name__23850101' -> 23850101, tolerant of case, spaces and URL-encoding
    SAFE_CAST(REGEXP_EXTRACT(
      REPLACE(TRIM(REGEXP_REPLACE(l.utm_campaign, r'%20', ' ')), ' ', '_'),
      r'__(\d{6,})_*$') AS INT64) AS campaign_id
  FROM `project.crm.leads` l
),

funnel AS (                                   -- outcomes belong to the lead's creation date
  SELECT lead_date, campaign_id,
         COUNT(*)                         AS leads,
         COUNTIF(attended_at IS NOT NULL) AS attended,
         COUNTIF(qualified)               AS qualified,
         COUNTIF(sale_at IS NOT NULL)     AS sales,
         SUM(IFNULL(revenue_inr, 0))      AS revenue_inr
  FROM leads
  WHERE campaign_id IS NOT NULL
  GROUP BY 1, 2
),

spend AS (
  SELECT date AS lead_date, campaign_id,
         ANY_VALUE(channel) AS channel,
         SUM(clicks) AS clicks, SUM(spend_inr) AS spend_inr
  FROM `project.ads.spend_daily`
  GROUP BY 1, 2
),

daily AS (
  SELECT
    COALESCE(s.lead_date, f.lead_date)     AS lead_date,
    COALESCE(s.campaign_id, f.campaign_id) AS campaign_id,
    s.channel,
    IFNULL(s.spend_inr, 0) AS spend_inr, IFNULL(s.clicks, 0) AS clicks,
    IFNULL(f.leads, 0) AS leads, IFNULL(f.attended, 0) AS attended, IFNULL(f.qualified, 0) AS qualified,
    IFNULL(f.sales, 0) AS sales, IFNULL(f.revenue_inr, 0) AS revenue_inr
  FROM spend s
  FULL OUTER JOIN funnel f USING (lead_date, campaign_id)
),

latest_name AS (                              -- show the current name, report on the ID
  SELECT campaign_id, ARRAY_AGG(campaign_name ORDER BY date DESC LIMIT 1)[OFFSET(0)] AS campaign_name
  FROM `project.ads.spend_daily`
  GROUP BY 1
)

SELECT
  d.campaign_id, n.campaign_name, ANY_VALUE(d.channel) AS channel,
  SUM(d.spend_inr) AS spend_inr,
  SUM(d.leads) AS leads,
  SAFE_DIVIDE(SUM(d.spend_inr), SUM(d.leads))       AS cpl_inr,
  SAFE_DIVIDE(SUM(d.attended), SUM(d.leads))        AS attend_rate,
  SUM(d.sales) AS sales,
  SAFE_DIVIDE(SUM(d.spend_inr), SUM(d.sales))       AS cost_per_sale_inr,
  SAFE_DIVIDE(SUM(d.revenue_inr), SUM(d.spend_inr)) AS roas,
  -- share of the range's leads still inside the maturity window: ROAS will still rise
  SAFE_DIVIDE(SUM(IF(d.lead_date > DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL maturity_days DAY), d.leads, 0)),
              SUM(d.leads)) AS share_of_leads_still_maturing
FROM daily d
LEFT JOIN latest_name n USING (campaign_id)
WHERE d.lead_date BETWEEN DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 90 DAY)
                      AND DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 1 DAY)
GROUP BY d.campaign_id, n.campaign_name
ORDER BY spend_inr DESC;
