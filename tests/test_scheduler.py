import tempfile
import unittest
from pathlib import Path

from scheduler import CrawlScheduler


class SchedulerTest(unittest.TestCase):
    def test_settings_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            scheduler = CrawlScheduler(path, lambda: True)
            status = scheduler.save({"enabled": False, "interval_hours": 12})
            self.assertFalse(status["enabled"])
            self.assertIsNone(status["next_run_at"])
            loaded = CrawlScheduler(path, lambda: True).status()
            self.assertEqual(loaded["interval_hours"], 12)

    def test_rejects_unsafe_frequency(self):
        with tempfile.TemporaryDirectory() as directory:
            scheduler = CrawlScheduler(Path(directory) / "settings.json", lambda: True)
            with self.assertRaises(ValueError):
                scheduler.save({"enabled": True, "interval_hours": 1})


if __name__ == "__main__":
    unittest.main()
