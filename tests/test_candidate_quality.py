import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import generate_daily


def make_item(
    title,
    *,
    source="HackerNews",
    source_type="community",
    importance="B",
    points=0,
    summary="",
    link="https://example.com/item",
):
    return {
        "title": title,
        "source": source,
        "source_type": source_type,
        "importance": importance,
        "points": points,
        "summary": summary,
        "link": link,
        "published_at": "2026-08-19T08:00:00+08:00",
        "category": "model",
    }


class CandidateQualityTests(unittest.TestCase):
    def test_unrelated_high_heat_item_does_not_displace_ai_news(self):
        unrelated = make_item(
            "A 3D fruit fly on macOS desktop powered by a connectome",
            importance="A",
            points=500,
        )
        ai_news = make_item(
            "OpenAI pauses frontier model training",
            importance="C",
            points=25,
        )

        selected = generate_daily.select_candidates([unrelated, ai_news])

        self.assertEqual([item["title"] for item in selected], [ai_news["title"]])

    def test_academic_source_has_normal_quota(self):
        topics = [
            "Language model calibration under distribution shift",
            "Neural representation stability analysis",
            "Machine learning robustness measurement",
            "Transformer behavior across languages",
            "Deep learning uncertainty estimates",
            "Text-to-image semantic alignment",
            "Artificial intelligence fairness metrics",
            "LLM knowledge boundary study",
            "Reasoning model confidence analysis",
            "Embedding geometry in multilingual models",
            "Neural scaling behavior study",
            "Language model social bias analysis",
        ]
        papers = [
            make_item(
                title,
                source="arXiv",
                source_type="academic",
                summary="A routine language model evaluation paper.",
                link=f"https://arxiv.org/abs/{index}",
            )
            for index, title in enumerate(topics)
        ]

        selected = generate_daily.select_candidates(papers)

        self.assertEqual(
            len(selected),
            generate_daily.CANDIDATE_SOURCE_TYPE_LIMITS["academic"],
        )

    def test_extra_high_value_event_can_exceed_source_quota(self):
        major_topics = [
            "OpenAI frontier model release benchmark",
            "Anthropic launches Claude safety benchmark",
            "Nvidia releases a new AI inference chip",
            "Google launches Gemini reasoning model",
            "DeepSeek open sources an agent framework",
            "Qwen releases a multilingual language model",
            "Cerebras launches a large model cluster",
            "Mistral releases an enterprise AI model",
            "Meta open sources a new Llama model",
        ]
        major_papers = [
            make_item(
                title,
                source="arXiv",
                source_type="academic",
                importance="A",
                summary="A major language model release with developer impact.",
                link=f"https://arxiv.org/abs/major-{index}",
            )
            for index, title in enumerate(major_topics)
        ]

        selected = generate_daily.select_candidates(major_papers)

        self.assertEqual(len(selected), 9)

    def test_duplicate_event_is_sent_to_model_once(self):
        first = make_item(
            "OpenAI launches a new coding agent",
            source="TechCrunch",
            source_type="rss",
            link="https://example.com/openai-agent/",
        )
        duplicate = make_item(
            "OpenAI launches a new coding agent",
            source="HackerNews",
            source_type="community",
            points=200,
            link="https://example.com/openai-agent",
        )

        selected = generate_daily.select_candidates([first, duplicate])

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["source"], "HackerNews")

    def test_candidate_text_keeps_traceability_fields(self):
        item = make_item(
            "Anthropic releases a new Claude API",
            source="Anthropic",
            source_type="official",
            link="https://example.com/claude-api",
        )

        text = generate_daily._candidate_text([item])

        self.assertIn("信源：Anthropic（official）", text)
        self.assertIn("发布时间：2026-08-19T08:00:00+08:00", text)
        self.assertIn("原始链接：https://example.com/claude-api", text)


if __name__ == "__main__":
    unittest.main()
