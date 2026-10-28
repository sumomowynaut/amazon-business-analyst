"""Structure and rendering checks for scripts/render_report.py.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_report import render_report, validate_report  # noqa: E402

BASE = {
    "title": "测试报告",
    "subtitle": "模拟数据",
    "summary": ["第一条结论"],
    "sections": [
        {
            "title": "指标",
            "paragraphs": ["正文"],
            "table": {"columns": ["指标", "值"], "rows": [["ACOS", "20.00%"], ["TACOS", 0.15]]},
            "chart": {"title": "变化贡献", "unit": "USD", "labels": ["A", "B"],
                      "values": [100.0, -40.0], "source": "sample-data.csv"},
        },
        {"title": "图片缺失", "image": {"path": "nope.png", "caption": "图注", "source": "来源"}},
    ],
    "sources": ["来源：测试"],
}


def variant(**changes):
    report = copy.deepcopy(BASE)
    report.update(changes)
    return report


class ValidationTests(unittest.TestCase):
    def assert_rejected(self, report, label):
        with self.assertRaises(ValueError, msg=label):
            validate_report(report)

    def test_base_is_valid(self):
        self.assertIs(validate_report(BASE), BASE)

    def test_title_required(self):
        self.assert_rejected(variant(title="  "), "blank title")
        self.assert_rejected({k: v for k, v in BASE.items() if k != "title"}, "missing title")

    def test_sections_required(self):
        self.assert_rejected(variant(sections=[]), "no sections")
        self.assert_rejected(variant(sections={"title": "x"}), "sections not a list")

    def test_table_shape(self):
        broken = copy.deepcopy(BASE)
        broken["sections"][0]["table"]["rows"].append(["只有一列"])
        self.assert_rejected(broken, "row shorter than columns")

    def test_table_rejects_missing_values(self):
        for bad in (None, float("nan"), float("inf"), True):
            broken = copy.deepcopy(BASE)
            broken["sections"][0]["table"]["rows"].append(["缺失", bad])
            self.assert_rejected(broken, f"cell {bad!r}")

    def test_table_width_limit(self):
        broken = copy.deepcopy(BASE)
        broken["sections"][0]["table"] = {"columns": [f"c{i}" for i in range(9)],
                                          "rows": [["v"] * 9]}
        self.assert_rejected(broken, "nine columns")

    def test_chart_length_mismatch(self):
        broken = copy.deepcopy(BASE)
        broken["sections"][0]["chart"]["values"] = [1.0]
        self.assert_rejected(broken, "labels and values differ")

    def test_chart_rejects_none(self):
        broken = copy.deepcopy(BASE)
        broken["sections"][0]["chart"]["values"] = [1.0, None]
        self.assert_rejected(broken, "null chart value")

    def test_remote_image_rejected(self):
        broken = copy.deepcopy(BASE)
        broken["sections"][1]["image"]["path"] = "https://example.com/a.png"
        self.assert_rejected(broken, "remote image")

    def test_page_break_must_be_bool(self):
        broken = copy.deepcopy(BASE)
        broken["sections"][0]["page_break"] = "yes"
        self.assert_rejected(broken, "page_break string")


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from render_report import select_font
        try:
            cls.font = select_font()
        except ValueError as exc:
            raise unittest.SkipTest(f"no CJK font available: {exc}") from exc
        try:
            import pypdf  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest("pypdf not installed") from exc
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "report.pdf"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def render(self, report):
        report = copy.deepcopy(report)
        report["sections"] = [s for s in report["sections"] if "image" not in s]
        return render_report(report, self.out, self.font, ROOT)

    def test_pdf_created_and_searchable(self):
        import pypdf
        self.render(BASE)
        self.assertTrue(self.out.is_file())
        reader = pypdf.PdfReader(str(self.out))
        self.assertGreaterEqual(len(reader.pages), 1)
        text = "".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("测试报告", text)
        self.assertIn("ACOS", text)

    def test_failure_leaves_no_partial_file(self):
        target = Path(self.tmp.name) / "missing-image.pdf"
        with self.assertRaises(ValueError):
            render_report(BASE, target, self.font, ROOT)
        self.assertFalse(target.exists())
        leftovers = [p for p in Path(self.tmp.name).glob("tmp*.pdf")]
        self.assertEqual(leftovers, [])


class ExampleTests(unittest.TestCase):
    def test_example_builds_consistent_report(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_example
        report = build_example.build_report(build_example.read_example())
        validate_report(report)
        rows = build_example.read_example()
        totals = build_example.summarize(rows[:2])
        self.assertEqual(totals["sales"], 20000)
        self.assertEqual(totals["ad_spend"], 2600)
        # ACOS is recomputed from aggregate spend and aggregate attributed sales.
        self.assertAlmostEqual(float(totals["acos"]), 2600 / 9200)

    def test_example_json_roundtrips(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_example
        report = build_example.build_report(build_example.read_example())
        again = json.loads(json.dumps(report, ensure_ascii=False))
        validate_report(again)


if __name__ == "__main__":
    unittest.main()
