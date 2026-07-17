from pathlib import Path
import tempfile
import unittest
from unittest import mock
from codex_hue import cli


class FileLockTests(unittest.TestCase):
    def test_nonblocking_lock_reports_contention(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_file = Path(temporary_directory) / "test.lock"
            with cli.FileLock(lock_file):
                with cli.FileLock(lock_file, nonblocking=True) as acquired:
                    self.assertIsNone(acquired)

    def test_lock_can_be_reacquired_after_release(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_file = Path(temporary_directory) / "test.lock"
            with cli.FileLock(lock_file) as first:
                self.assertIsNotNone(first)
            with cli.FileLock(lock_file, nonblocking=True) as second:
                self.assertIsNotNone(second)


class WorkerProcessTests(unittest.TestCase):
    def test_windows_worker_is_detached_without_posix_session_flag(self):
        with mock.patch.object(cli.os, "name", "nt"):
            options = cli.worker_popen_kwargs()
        self.assertIn("creationflags", options)
        self.assertNotIn("start_new_session", options)
        self.assertTrue(options["close_fds"])

    def test_posix_worker_starts_a_new_session(self):
        with mock.patch.object(cli.os, "name", "posix"):
            options = cli.worker_popen_kwargs()
        self.assertTrue(options["start_new_session"])
        self.assertNotIn("creationflags", options)


if __name__ == "__main__":
    unittest.main()
