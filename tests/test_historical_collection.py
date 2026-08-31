import json
import sys
import unittest
import urllib.parse
from datetime import date
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import collector
from src.sources.base import NewsItem
from src.sources.hackernews import HackerNewsSource


class HistoricalCollectionTests(unittest.TestCase):
    def test_hackernews_uses_shanghai_natural_day_range(self):
        response = {
            "hits": [{
                "objectID": "1",
                "title": "Historical AI event",
                "created_at": "2026-08-10T16:30:00Z",
                "url": "https://example.com/event",
                "points": 42,
                "num_comments": 5,
            }]
        }
        requested_urls = []

        def fake_fetch(url, timeout=20):
            requested_urls.append(url)
            return json.dumps(response).encode("utf-8")

        with mock.patch("src.sources.hackernews.fetch_url", side_effect=fake_fetch):
            items = HackerNewsSource().fetch_for_date("2026-08-11")

        self.assertEqual(len(items), 1)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(requested_urls[0]).query)
        filters = query["numericFilters"][0]
        self.assertIn("created_at_i>=1786377600", filters)
        self.assertIn("created_at_i<1786464000", filters)

    def test_historical_collection_does_not_use_latest_only_feeds(self):
        historical_item = NewsItem(
            title="Historical AI event",
            source="HackerNews",
            source_type="community",
            timestamp="2026-08-11T03:00:00Z",
            link="https://example.com/event",
            points=42,
        )
        with mock.patch.object(
            collector.HackerNewsSource,
            "fetch_for_date",
            return_value=[historical_item],
        ) as historical_fetch, mock.patch.object(
            collector.TechCrunchSource,
            "fetch",
            side_effect=AssertionError("历史补采不应调用最新RSS"),
        ) as latest_feed:
            items = collector.collect_all(target_date="2026-08-11")

        historical_fetch.assert_called_once_with("2026-08-11")
        latest_feed.assert_not_called()
        self.assertEqual(items, [historical_item])

    def test_historical_timestamp_is_filtered_by_local_date(self):
        item = NewsItem(
            title="Midnight boundary",
            source="HackerNews",
            source_type="community",
            timestamp="2026-08-10T16:30:00Z",
            link="https://example.com/midnight",
            points=42,
        )
        self.assertEqual(collector.filter_age([item], "2026-08-11"), [item])
        self.assertEqual(collector.filter_age([item], "2026-08-10"), [])


if __name__ == "__main__":
    unittest.main()
