import unittest
from unittest.mock import patch

import sources
from cdf_hainan_stores import Store


class SourceIsolationTest(unittest.TestCase):
    def test_one_source_failure_does_not_drop_success(self):
        good = Store("测试店", "海南省海口市", "", "https://example.com/1", "")
        collectors = {"cdf": lambda: [good], "wfj": lambda: (_ for _ in ()).throw(RuntimeError("timeout"))}
        with patch.object(sources, "COLLECTORS", collectors):
            stores, results = sources.crawl_all()
        self.assertEqual(stores, [good])
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
