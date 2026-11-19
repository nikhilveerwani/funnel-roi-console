"""Smoke-test the Streamlit app end to end with Streamlit's AppTest (skipped if Streamlit isn't installed)."""
import os
import unittest

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # the pipeline tests must still run with the stdlib alone
    AppTest = None

APP = os.path.join(os.path.dirname(__file__), "..", "streamlit_app.py")


@unittest.skipIf(AppTest is None, "streamlit not installed")
class StreamlitAppTest(unittest.TestCase):
    def setUp(self):
        self.at = AppTest.from_file(APP, default_timeout=120).run()

    def test_renders_without_errors(self):
        self.assertFalse(self.at.exception, self.at.exception)
        self.assertEqual(self.at.title[0].value, "Funnel & ROI Console")
        self.assertEqual(len(self.at.metric), 10)   # 6 KPIs + 4 simulator tiles

    def test_recommendation_raises_revenue_without_new_budget(self):
        self.at.button[0].click().run()            # "Apply recommendation"
        self.assertFalse(self.at.exception, self.at.exception)
        m = {x.label: x for x in self.at.metric}
        self.assertTrue(m["Projected revenue"].delta.startswith("₹"), m["Projected revenue"].delta)   # gain, not "-₹"
        self.assertTrue(m["Monthly budget"].delta.startswith("-"), m["Monthly budget"].delta)        # on less money
        self.assertTrue(m["ROAS"].delta.startswith("+"), m["ROAS"].delta)


if __name__ == "__main__":
    unittest.main()
