import tempfile
import unittest
from pathlib import Path

from cdf_hainan_stores import Store
from data_store import DataStore


def store(name="测试门店", phone="123"):
    return Store(name, "海南省海口市测试路", phone, "https://example.com/1", "https://example.com/1.jpg")


class DataStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = DataStore(Path(self.temp.name) / "test.db")
        self.database.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_store_change_statistics(self):
        self.assertEqual(self.database.replace_stores([store()]), {"added": 1, "updated": 0, "removed": 0})
        self.assertEqual(self.database.replace_stores([store(phone="456")]), {"added": 0, "updated": 1, "removed": 0})
        self.assertEqual(self.database.list_stores()[0]["phone"], "456")

    def test_crawl_run_lifecycle(self):
        run_id = self.database.start_run()
        self.assertEqual(self.database.latest_run()["status"], "running")
        self.database.finish_run(run_id, 1, {"added": 1, "updated": 0, "removed": 0})
        latest = self.database.latest_run()
        self.assertEqual(latest["status"], "success")
        self.assertEqual(latest["found_count"], 1)

    def test_failed_source_keeps_previous_snapshot(self):
        self.database.replace_stores([store()])
        changes = self.database.replace_source_stores([], {"wfj"})
        self.assertEqual(changes, {"added": 0, "updated": 0, "removed": 0})
        self.assertEqual(len(self.database.list_stores()), 1)

    def test_change_audit_and_backup(self):
        run_id = self.database.start_run()
        self.database.replace_source_stores([store()], {"cdf"}, run_id=run_id)
        changes = self.database.recent_changes()
        self.assertEqual(changes[0]["change_type"], "added")
        self.assertEqual(changes[0]["run_id"], run_id)
        backup = Path(self.temp.name) / "backup.db"
        self.database.backup_to(backup)
        self.assertTrue(backup.exists())


if __name__ == "__main__":
    unittest.main()
