import unittest

from core.task_store import TaskStore


class TestTaskStore(unittest.TestCase):
    def setUp(self):
        self._store = TaskStore(":memory:")

    def test_create_tasks(self):
        regions = [
            {"region": "温州市", "safe_filename": "温州市"},
            {"region": "杭州市", "safe_filename": "杭州市"},
        ]
        count = self._store.create_tasks(regions)
        self.assertEqual(count, 2)

    def test_update_status(self):
        self._store.create_tasks([{"region": "测试", "safe_filename": "测试"}])
        tasks = self._store.get_all_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["gif_status"], "pending")

        self._store.update_task_status(1, "gif", "completed", "test.gif")
        task = self._store.get_task(1)
        self.assertEqual(task["gif_status"], "completed")
        self.assertEqual(task["gif_path"], "test.gif")

    def test_get_failed(self):
        self._store.create_tasks([
            {"region": "A", "safe_filename": "A"},
            {"region": "B", "safe_filename": "B"},
        ])
        self._store.update_task_status(1, "gif", "failed", error="err1")
        failed = self._store.get_failed_tasks()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["region"], "A")

    def test_get_stats(self):
        self._store.create_tasks([
            {"region": "A", "safe_filename": "A"},
            {"region": "B", "safe_filename": "B"},
            {"region": "C", "safe_filename": "C"},
        ])
        stats = self._store.get_stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["pending"], 3)
        self.assertEqual(stats["completed"], 0)


if __name__ == "__main__":
    unittest.main()
