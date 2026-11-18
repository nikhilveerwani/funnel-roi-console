import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from transform import campaign_id_from_utm, name_from_utm, what_moved  # noqa: E402


class CampaignIdFromUtm(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(campaign_id_from_utm("FB_Prospecting_Senior__23850101"), 23850101)

    def test_case_and_spaces(self):
        self.assertEqual(campaign_id_from_utm("  fb_prospecting_senior__23850101 "), 23850101)

    def test_url_encoded_with_spaces_for_underscores(self):
        self.assertEqual(campaign_id_from_utm("FB%20Prospecting%20Senior%20%2023850101"), 23850101)

    def test_missing_id(self):
        self.assertIsNone(campaign_id_from_utm("FB_Prospecting_Senior"))
        self.assertIsNone(campaign_id_from_utm(""))

    def test_renamed_campaign_keeps_its_id(self):
        old, new = "FB_Lookalike_Buyers_1pct__23850103", "FB_LAL_Purchasers_1pct_v2__23850103"
        self.assertEqual(campaign_id_from_utm(old), campaign_id_from_utm(new))
        self.assertNotEqual(name_from_utm(old), name_from_utm(new))   # why a name join loses leads


class WhatMoved(unittest.TestCase):
    TODAY = dt.date(2026, 11, 18)
    META = {1: {"name": "Camp A", "channel": "Meta"}, 2: {"name": "Camp B", "channel": "Google"}}

    def facts(self, cid, days, spend, leads, sales=0):
        out = []
        for back in days:
            d = (self.TODAY - dt.timedelta(days=back)).isoformat()
            out.append([d, cid, spend, 0, leads, 0, 0, sales, sales * 100000])
        return out

    def test_zero_leads_with_spend_is_flagged(self):
        f = self.facts(1, range(4, 36), 10000, 20, 1) + self.facts(1, range(1, 4), 10000, 0)
        c = what_moved(f, self.META, self.TODAY)
        self.assertEqual(c[0]["title"], "Spending with zero leads for 3 days")
        self.assertEqual(c[0]["impact"], 30000)

    def test_cpl_jump_is_flagged_and_sized(self):
        f = self.facts(1, range(8, 36), 10000, 20, 1) + self.facts(1, range(1, 8), 10000, 10, 1)
        c = [x for x in what_moved(f, self.META, self.TODAY) if x["title"].startswith("Cost per lead up")]
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["impact"], 35000)        # 70k spent, 70 leads' worth at old CPL = 35k

    def test_small_noise_is_not_flagged(self):
        f = self.facts(1, range(8, 36), 10000, 20, 1) + self.facts(1, range(1, 8), 10000, 18, 1)
        self.assertEqual(what_moved(f, self.META, self.TODAY), [])

    def test_cheap_leads_that_never_buy(self):
        good = self.facts(2, range(31, 61), 10000, 20, 2)          # 10% sale rate
        junk = self.facts(1, range(31, 61), 10000, 80, 0)          # cheap, zero sales
        c = what_moved(good + junk, self.META, self.TODAY)
        self.assertTrue(any(x["campaign"] == "Camp A" and x["title"] == "Cheap leads that don't buy" for x in c))


if __name__ == "__main__":
    unittest.main()
