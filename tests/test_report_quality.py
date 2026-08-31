import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import generate_daily


TARGET_DATE = "2026-08-18"
SOURCE_URL = "https://example.com/openai-release"


def candidate(link=SOURCE_URL):
    return {
        "title": "OpenAI releases a new coding agent",
        "source": "OpenAI",
        "source_type": "official",
        "importance": "A",
        "points": 0,
        "summary": "OpenAI released a coding agent for developers.",
        "link": link,
        "published_at": "2026-08-18T10:00:00+08:00",
        "category": "agent",
    }


def valid_report(target_date=TARGET_DATE, source_url=SOURCE_URL):
    detail = "这是一段用于验证日报正文完整性的说明。" * 35
    return f"""# 📡 AI信息雷达日报 | {target_date}

## 今日AI一句话总结
今天最值得关注的是可靠的AI智能体开始落地。

# 1. 今日重要AI事件
### OpenAI发布新的编码智能体——A级
- **发生了什么**：OpenAI发布了新的编码智能体。
- **信源**：OpenAI（official）
- **原始发布时间**：2026-08-18T10:00:00+08:00
- **原始链接**：[官方原文]({source_url})
- **分析**：{detail}

# 2. 新模型观察
今日无重大新模型发布。

# 3. AI工具发现
编码智能体值得开发者关注。

# 3.5 AI智能体推荐
建议先在低风险任务中试用。

# 4. AI新名词解释
动作边界是智能体可以执行的操作范围。

# 5. 创造机会分析
可以开发智能体权限审计工具。

# 6. 学习建议
学习工具权限、失败保护和操作审计。
"""


class ReportQualityValidationTests(unittest.TestCase):
    def test_valid_report_passes(self):
        report = valid_report(
            source_url=SOURCE_URL + "?utm_source=newsletter"
        )
        result = generate_daily.validate_daily_report(
            report,
            TARGET_DATE,
            [candidate()],
        )
        self.assertTrue(result.startswith("# 📡 AI信息雷达日报"))

    def test_wrong_report_date_fails(self):
        with self.assertRaisesRegex(RuntimeError, "目标日期"):
            generate_daily.validate_daily_report(
                valid_report(target_date="2026-08-19"),
                TARGET_DATE,
                [candidate()],
            )

    def test_missing_required_section_fails(self):
        report = valid_report().replace("# 6. 学习建议", "学习建议")
        with self.assertRaisesRegex(RuntimeError, "缺少板块.*学习建议"):
            generate_daily.validate_daily_report(report, TARGET_DATE, [candidate()])

    def test_unknown_important_event_link_fails(self):
        with self.assertRaisesRegex(RuntimeError, "素材之外的链接"):
            generate_daily.validate_daily_report(
                valid_report(source_url="https://fake.example/invented"),
                TARGET_DATE,
                [candidate()],
            )

    def test_small_same_domain_url_error_is_repaired_to_original_candidate(self):
        wrong = (
            "https://techcrunch.com/2026/08/20/"
            "a-third-of-webpages-published-since-chatgpts-launch-show-signs-of-ai-authorship-finds"
        )
        original = (
            "https://techcrunch.com/2026/08/20/"
            "a-third-of-webpages-published-since-chatgpts-launch-show-signs-of-ai-authorship-study-finds/"
        )
        candidates = [{
            "source": "TechCrunch",
            "title": "AI authorship study",
            "url": original,
        }]

        repaired = generate_daily.repair_candidate_urls(
            f"来源：[TechCrunch]({wrong})",
            candidates,
        )

        self.assertIn(original.rstrip("/"), repaired)
        self.assertNotIn(wrong, repaired)

    def test_different_domain_url_is_never_repaired(self):
        wrong = "https://attacker.example.com/official-release"
        candidates = [{
            "source": "OpenAI",
            "title": "Official release",
            "url": "https://openai.com/official-release",
        }]
        self.assertEqual(
            generate_daily.repair_candidate_urls(wrong, candidates),
            wrong,
        )

    def test_missing_important_event_link_fails(self):
        report = valid_report().replace(
            f"[官方原文]({SOURCE_URL})",
            "未提供链接",
        )
        with self.assertRaisesRegex(RuntimeError, "没有保留任何原始链接"):
            generate_daily.validate_daily_report(report, TARGET_DATE, [candidate()])


class ReportQualityFailureProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.daily_dir = self.root / "data" / "daily"
        self.realtime_dir = self.root / "data" / "realtime"
        self.status_dir = self.root / "data" / "update_status"
        self.daily_dir.mkdir(parents=True)
        self.realtime_dir.mkdir(parents=True)
        self.patchers = [
            mock.patch.object(generate_daily, "BASE_DIR", self.root),
            mock.patch.object(generate_daily, "DAILY_DIR", self.daily_dir),
            mock.patch.object(generate_daily, "UPDATE_STATUS_DIR", self.status_dir),
            mock.patch.object(generate_daily, "project_today", return_value=date(2026, 8, 20)),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_invalid_ai_output_marks_failed_and_preserves_existing_report(self):
        old_path = self.daily_dir / "2026-08-17.md"
        old_content = "# 原有日报\n\n这份日报不能被不合格输出覆盖。\n"
        old_path.write_text(old_content, encoding="utf-8")
        pool_path = self.realtime_dir / f"{TARGET_DATE}.json"
        pool_path.write_text(
            json.dumps({
                "collect_date": TARGET_DATE,
                "items": [candidate()],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        owner = generate_daily.claim_finalization_task(TARGET_DATE, force=True)
        self.assertIsNotNone(owner)

        with mock.patch.object(
            generate_daily,
            "call_router",
            return_value="# AI信息雷达日报 | 2026-08-19\n错误日期",
        ):
            with self.assertRaisesRegex(RuntimeError, "质量校验失败"):
                generate_daily.run_claimed_finalization(
                    TARGET_DATE,
                    owner,
                    force=True,
                )

        self.assertEqual(old_path.read_text(encoding="utf-8"), old_content)
        self.assertFalse((self.daily_dir / f"{TARGET_DATE}.md").exists())
        self.assertEqual(
            generate_daily.get_finalization_status(TARGET_DATE)["status"],
            generate_daily.STATUS_FAILED,
        )


if __name__ == "__main__":
    unittest.main()
