import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import app
import collector
from src.sources import base
from src.sources.base import NewsItem


def news_item():
    return NewsItem(
        title="OpenAI releases a new coding agent",
        source="OpenAI",
        source_type="official",
        timestamp="2026-08-20T08:00:00+08:00",
        link="https://example.com/openai-agent",
    )


class AlwaysFailOpener:
    def open(self, request, timeout=20):
        raise OSError("HTTP 403 blocked")


class MutatingProxyFailOpener:
    def __init__(self, requests):
        self.requests = requests

    def open(self, request, timeout=20):
        request.set_proxy("127.0.0.1:10090", "https")
        self.requests.append(request)
        raise OSError("proxy unavailable")


class DirectSuccessOpener:
    def __init__(self, requests):
        self.requests = requests

    def open(self, request, timeout=20):
        self.requests.append(request)
        return io.BytesIO(b"direct response")


class SourceHealthTests(unittest.TestCase):
    def test_direct_fallbacks_do_not_inherit_system_proxy(self):
        with mock.patch.object(
            base.urllib.request,
            "ProxyHandler",
            side_effect=lambda proxies=None: ("proxy", proxies),
        ) as proxy_handler, mock.patch.object(
            base.urllib.request,
            "build_opener",
            return_value=object(),
        ):
            base._build_openers()

        proxy_configs = [call.args[0] for call in proxy_handler.call_args_list]
        self.assertEqual(proxy_configs.count({}), 2)

    def test_proxy_failure_does_not_pollute_direct_request(self):
        requests = []
        openers = [
            ("proxy", MutatingProxyFailOpener(requests)),
            ("direct", DirectSuccessOpener(requests)),
        ]
        with mock.patch.object(base, "_OPENERS", openers):
            with base.source_request_health("HackerNews") as health:
                content = base.fetch_url("https://example.com/feed")

        self.assertEqual(content, b"direct response")
        self.assertEqual(len(requests), 2)
        self.assertIsNot(requests[0], requests[1])
        self.assertEqual(requests[0].host, "127.0.0.1:10090")
        self.assertEqual(requests[1].host, "example.com")
        self.assertEqual(health["requests"], 1)
        self.assertEqual(health["failed_requests"], 0)

    def test_request_failure_is_recorded_without_network_call(self):
        openers = [("one", AlwaysFailOpener()), ("two", AlwaysFailOpener())]
        with mock.patch.object(base, "_OPENERS", openers):
            with base.source_request_health("Reddit") as health:
                with self.assertRaisesRegex(OSError, "403"):
                    base.fetch_url("https://example.com/feed")

        self.assertEqual(health["source"], "Reddit")
        self.assertEqual(health["requests"], 1)
        self.assertEqual(health["failed_requests"], 1)
        self.assertIn("403", health["errors"][0])

    def test_health_status_distinguishes_all_four_states(self):
        cases = [
            ([news_item()], {"requests": 1, "failed_requests": 0, "errors": []}, None, "ok"),
            ([news_item()], {"requests": 2, "failed_requests": 1, "errors": ["timeout"]}, None, "partial"),
            ([], {"requests": 1, "failed_requests": 1, "errors": ["403"]}, None, "failed"),
            ([], {"requests": 1, "failed_requests": 0, "errors": []}, None, "empty"),
        ]
        for items, request_health, error, expected in cases:
            with self.subTest(expected=expected):
                result = collector._source_health_result(
                    object(), items, request_health, 25, error=error
                )
                self.assertEqual(result["status"], expected)

    def test_pool_persists_health_and_app_reads_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            realtime_dir = root / "data" / "realtime"
            realtime_dir.mkdir(parents=True)
            path = realtime_dir / "2026-08-20.json"
            health = {
                "HackerNews": {
                    "status": "ok", "items": 5, "requests": 1,
                    "failed_requests": 0, "duration_ms": 20, "error": "",
                },
                "Reddit": {
                    "status": "failed", "items": 0, "requests": 3,
                    "failed_requests": 3, "duration_ms": 50, "error": "HTTP 403",
                },
                "arXiv": {
                    "status": "partial", "items": 2, "requests": 3,
                    "failed_requests": 1, "duration_ms": 40, "error": "timeout",
                },
                "DeepSeek": {
                    "status": "empty", "items": 0, "requests": 1,
                    "failed_requests": 0, "duration_ms": 10, "error": "",
                },
            }
            collector._write_pool(path, "2026-08-20", [news_item()], health)

            payload = json.loads(path.read_text(encoding="utf-8"))
            summary = payload["stats"]["source_health_summary"]
            self.assertEqual(summary["total"], 4)
            self.assertEqual(summary["available"], 2)

            with mock.patch.object(app, "REALTIME_DIR", realtime_dir):
                info = app.load_realtime_info("2026-08-20")
            self.assertEqual(info["source_health_available"], 2)
            self.assertEqual(info["failed_sources"], ["Reddit"])
            self.assertEqual(info["partial_sources"], ["arXiv"])
            self.assertEqual(info["empty_sources"], ["DeepSeek"])

    def test_old_pool_without_health_remains_compatible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            realtime_dir = Path(temp_dir)
            (realtime_dir / "2026-08-20.json").write_text(
                json.dumps({
                    "total": 3,
                    "stats": {"by_importance": {"A": 1}, "by_category": {}},
                }),
                encoding="utf-8",
            )
            with mock.patch.object(app, "REALTIME_DIR", realtime_dir):
                info = app.load_realtime_info("2026-08-20")

        self.assertEqual(info["total"], 3)
        self.assertEqual(info["a_count"], 1)
        self.assertEqual(info["source_health_total"], 0)


if __name__ == "__main__":
    unittest.main()
