import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import app
import generate_daily


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class ReportRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.daily_dir = self.root / "data" / "daily"
        self.realtime_dir = self.root / "data" / "realtime"
        self.status_dir = self.root / "data" / "update_status"
        self.daily_dir.mkdir(parents=True)
        self.realtime_dir.mkdir(parents=True)

        self.patchers = [
            mock.patch.object(app, "BASE_DIR", self.root),
            mock.patch.object(app, "DAILY_DIR", self.daily_dir),
            mock.patch.object(app, "REALTIME_DIR", self.realtime_dir),
            mock.patch.object(app, "READ_STATUS_PATH", self.root / "data" / "read_status.json"),
            mock.patch.object(generate_daily, "BASE_DIR", self.root),
            mock.patch.object(generate_daily, "DAILY_DIR", self.daily_dir),
            mock.patch.object(generate_daily, "UPDATE_STATUS_DIR", self.status_dir),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def write_report(self, report_date):
        path = self.daily_dir / f"{report_date}.md"
        path.write_text(
            f"# AI信息雷达日报 · {report_date}\n\n"
            "## 今日AI一句话总结\n\n"
            f"这是 {report_date} 的完整日报。\n",
            encoding="utf-8",
        )
        return path

    def write_pool(self, pool_date, items=None):
        path = self.realtime_dir / f"{pool_date}.json"
        path.write_text(
            json.dumps({
                "collect_date": pool_date,
                "items": items or [{
                    "source": "HackerNews",
                    "title": "OpenAI releases an AI developer tool",
                    "url": "https://example.com/item",
                    "published_at": f"{pool_date}T12:00:00+08:00",
                }],
            }),
            encoding="utf-8",
        )
        return path

    def test_status_states(self):
        target = "2026-08-18"
        self.assertEqual(
            generate_daily.get_finalization_status(target)["status"],
            generate_daily.STATUS_NOT_STARTED,
        )

        owner = generate_daily.claim_finalization_task(target)
        self.assertIsNotNone(owner)
        self.assertEqual(
            generate_daily.get_finalization_status(target)["status"],
            generate_daily.STATUS_RUNNING,
        )

        generate_daily._write_task_status(target, generate_daily.STATUS_FAILED, "测试失败")
        generate_daily._release_finalization_lock(target, owner)
        failed = generate_daily.get_finalization_status(target)
        self.assertEqual(failed["status"], generate_daily.STATUS_FAILED)

        self.write_report(target)
        self.assertEqual(
            generate_daily.get_finalization_status(target)["status"],
            generate_daily.STATUS_SUCCESS,
        )

    def test_ten_concurrent_claims_have_one_owner(self):
        target = "2026-08-18"
        barrier = threading.Barrier(10)

        def claim():
            barrier.wait()
            return generate_daily.claim_finalization_task(target)

        with ThreadPoolExecutor(max_workers=10) as pool:
            tokens = list(pool.map(lambda _: claim(), range(10)))

        owners = [token for token in tokens if token]
        self.assertEqual(len(owners), 1)
        generate_daily._release_finalization_lock(target, owners[0])

    def test_0006_running_keeps_latest_completed_report(self):
        self.write_report("2026-08-18")
        fixed_now = datetime(2026, 8, 20, 0, 6, tzinfo=LOCAL_TZ)
        with mock.patch.object(
            generate_daily, "project_today", return_value=date(2026, 8, 20)
        ):
            owner = generate_daily.claim_finalization_task("2026-08-19")
        self.assertIsNotNone(owner)

        with mock.patch.object(app, "project_today", return_value=date(2026, 8, 20)):
            status = app.get_report_update_status(fixed_now)
            client = app.app.test_client()
            response = client.get("/")
            manual_check = client.post("/api/update-check")

        self.assertEqual(status["target_date"], "2026-08-19")
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["latest_completed_date"], "2026-08-18")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(manual_check.get_json()["status"], "running")
        self.assertIn("昨日日报正在生成中".encode("utf-8"), response.data)
        self.assertIn("2026-08-18".encode("utf-8"), response.data)
        generate_daily._release_finalization_lock("2026-08-19", owner)

    def test_ten_update_checks_start_one_background_task(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def hold_task(target_date, owner_token):
            started.set()
            release.wait(timeout=3)
            generate_daily._release_finalization_lock(target_date, owner_token)
            finished.set()

        target = app.report_target_date()
        self.write_pool(target)
        client = app.app.test_client()
        with mock.patch.object(
            app, "_run_claimed_report_finalization", side_effect=hold_task
        ) as runner:
            responses = [client.post("/api/update-check") for _ in range(10)]
            self.assertTrue(started.wait(timeout=1))
            self.assertTrue(all(response.status_code == 200 for response in responses))
            self.assertTrue(all(response.get_json()["status"] == "running" for response in responses))
            self.assertEqual(runner.call_count, 1)
            release.set()
            self.assertTrue(finished.wait(timeout=1))

    def test_continuity_distinguishes_recoverable_and_missing_pool(self):
        self.write_report("2026-08-18")
        self.write_pool("2026-08-19")
        fixed_now = datetime(2026, 8, 21, 8, 0, tzinfo=LOCAL_TZ)

        continuity = generate_daily.get_report_continuity(fixed_now)

        self.assertEqual(continuity["missing_dates"], ["2026-08-19", "2026-08-20"])
        self.assertEqual(continuity["recoverable_dates"], ["2026-08-19"])
        self.assertEqual(continuity["missing_pool_dates"], ["2026-08-20"])
        self.assertEqual(generate_daily.find_pending_report_date(fixed_now), "2026-08-19")

    def test_pending_selector_prioritizes_yesterday_then_oldest_gap(self):
        self.write_report("2026-08-18")
        self.write_pool("2026-08-19")
        self.write_pool("2026-08-20")
        fixed_now = datetime(2026, 8, 21, 8, 0, tzinfo=LOCAL_TZ)

        self.assertEqual(generate_daily.find_pending_report_date(fixed_now), "2026-08-20")
        self.write_report("2026-08-20")
        self.assertEqual(generate_daily.find_pending_report_date(fixed_now), "2026-08-19")

    def test_stale_lock_can_be_reclaimed_without_duplicate_owner(self):
        target = "2026-08-19"
        self.write_pool(target)
        fixed_now = datetime(2026, 8, 20, 8, 0, tzinfo=LOCAL_TZ)
        owner = generate_daily.claim_finalization_task(target)
        self.assertIsNotNone(owner)
        _, lock_path = generate_daily._task_paths(target)
        stale_time = lock_path.stat().st_mtime - generate_daily.LOCK_STALE_SECONDS - 1
        os.utime(lock_path, (stale_time, stale_time))

        self.assertEqual(
            generate_daily.get_finalization_status(target)["status"],
            generate_daily.STATUS_FAILED,
        )
        replacement = generate_daily.claim_finalization_task(target)
        self.assertIsNotNone(replacement)
        self.assertNotEqual(owner, replacement)
        generate_daily._release_finalization_lock(target, replacement)

    def test_automatic_retry_is_bounded_but_manual_retry_remains_available(self):
        target = "2026-08-19"
        self.write_pool(target)
        fixed_now = datetime(2026, 8, 20, 8, 0, tzinfo=LOCAL_TZ)
        generate_daily.UPDATE_STATUS_DIR.mkdir(parents=True, exist_ok=True)
        status_path, _ = generate_daily._task_paths(target)
        status_path.write_text(json.dumps({
            "target_date": target,
            "status": generate_daily.STATUS_FAILED,
            "attempt_count": generate_daily.AUTOMATIC_RETRY_LIMIT,
            "updated_at": "2026-08-20T00:00:00+08:00",
            "error": "测试失败",
        }), encoding="utf-8")

        self.assertIsNone(generate_daily.find_pending_report_date(fixed_now, automatic=True))
        self.assertEqual(generate_daily.find_pending_report_date(fixed_now), target)

    def test_finalization_window_boundary(self):
        before = datetime(2026, 8, 20, 0, 4, 59, tzinfo=LOCAL_TZ)
        at_start = datetime(2026, 8, 20, 0, 5, 0, tzinfo=LOCAL_TZ)
        self.assertFalse(app.finalization_window_open(before))
        self.assertTrue(app.finalization_window_open(at_start))
        self.assertEqual(app.report_target_date(at_start), "2026-08-19")

    def test_failed_generation_preserves_old_report(self):
        old_path = self.write_report("2026-08-18")
        old_content = old_path.read_text(encoding="utf-8")
        target = "2026-08-17"
        owner = generate_daily.claim_finalization_task(target, force=True)

        with mock.patch.object(
            generate_daily,
            "finalize_report",
            side_effect=RuntimeError("模拟 AI 请求失败"),
        ):
            with self.assertRaisesRegex(RuntimeError, "模拟 AI 请求失败"):
                generate_daily.run_claimed_finalization(target, owner, force=True)

        self.assertEqual(old_path.read_text(encoding="utf-8"), old_content)
        self.assertFalse((self.daily_dir / f"{target}.md").exists())
        self.assertEqual(
            generate_daily.get_finalization_status(target)["status"],
            generate_daily.STATUS_FAILED,
        )

    def test_success_switches_latest_completed_date(self):
        self.write_report("2026-08-18")
        self.write_report("2026-08-19")
        fixed_now = datetime(2026, 8, 20, 0, 8, tzinfo=LOCAL_TZ)

        with mock.patch.object(app, "project_today", return_value=date(2026, 8, 20)):
            status = app.get_report_update_status(fixed_now)

        self.assertEqual(status["status"], "success")
        self.assertEqual(status["latest_completed_date"], "2026-08-19")

    def test_empty_history_has_explicit_empty_state(self):
        with mock.patch.object(app, "project_today", return_value=date(2026, 8, 20)):
            response = app.app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("还没有日报".encode("utf-8"), response.data)

    def test_history_detail_reports_and_read_sync_remain_available(self):
        self.write_report("2026-08-18")
        client = app.app.test_client()

        detail = client.get("/daily/2026-08-18")
        reports = client.get("/api/reports")
        read_sync = client.post("/api/read/2026-08-18")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(reports.status_code, 200)
        self.assertEqual(read_sync.status_code, 204)
        payload = json.loads(reports.data.decode("utf-8"))
        self.assertEqual(payload["reports"][0]["date"], "2026-08-18")

    def test_instance_identity_marks_main_source_edition(self):
        response = app.app.test_client().get("/api/instance")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["project_id"], "ai-radar-portable-source")
        self.assertEqual(response.get_json()["edition"], "source")

    def test_schedule_installer_fails_closed_and_uses_pending_recovery(self):
        script = (PROJECT_DIR / "tools" / "setup_schedule.ps1").read_text(encoding="utf-8")
        self.assertIn("$ErrorActionPreference = 'Stop'", script)
        self.assertIn("--finalize-pending", script)
        self.assertIn("Scheduled task verification failed", script)
        self.assertIn("\\hermes-agent\\", script)
        self.assertIn("import flask, markdown", script)
        self.assertIn("OutputEncoding", script)
        self.assertIn("Out-File -FilePath", script)


if __name__ == "__main__":
    unittest.main()
