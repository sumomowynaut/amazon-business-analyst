"""Rebuild the documented synthetic example. Not a general report importer."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from render_report import render_report

ROOT = Path(__file__).resolve().parents[1]
NUMERIC = ("sessions", "units", "orders", "sales", "ad_spend", "ad_sales", "clicks",
           "impressions", "cogs", "selling_fees", "fulfillment_fees", "other_variable_costs")
COSTS = ("cogs", "selling_fees", "fulfillment_fees", "other_variable_costs", "ad_spend")


def ratio(numerator, denominator):
    return numerator / denominator if denominator != 0 else None


def money(value):
    return f"{value:,.2f}"


def percent(value):
    return "不可计算" if value is None else f"{value * 100:.2f}%"


def summarize(rows):
    totals = {key: sum((row[key] for row in rows), Decimal(0)) for key in NUMERIC}
    totals["contribution"] = totals["sales"] - sum(totals[key] for key in COSTS)
    totals["acos"] = ratio(totals["ad_spend"], totals["ad_sales"])
    totals["tacos"] = ratio(totals["ad_spend"], totals["sales"])
    totals["unit_session"] = ratio(totals["units"], totals["sessions"])
    totals["cpc"] = ratio(totals["ad_spend"], totals["clicks"])
    return totals


def read_example():
    with (ROOT / "examples" / "sample-data.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    seen = set()
    for row in rows:
        key = (row["period"], row["marketplace"], row["sku"])
        if key in seen:
            raise ValueError(f"Duplicate example key: {key}")
        seen.add(key)
        if row["currency"] != "USD" or row["marketplace"] != "US":
            raise ValueError("This documented example requires US / USD")
        for key in NUMERIC:
            row[key] = Decimal(row[key])
            if not row[key].is_finite() or row[key] < 0:
                raise ValueError(f"Invalid nonnegative example field: {key}")
    if {(r["period"], r["sku"]) for r in rows} != {
        (period, sku) for period in ("baseline", "current") for sku in ("DEMO-A", "DEMO-B")
    }:
        raise ValueError("Example needs both documented periods and both demo SKUs")
    return rows


def build_report(rows):
    grouped = defaultdict(list)
    by_sku = {}
    for row in rows:
        grouped[row["period"]].append(row)
        by_sku[(row["period"], row["sku"])] = summarize([row])
    old, new = summarize(grouped["baseline"]), summarize(grouped["current"])
    a0, a1 = by_sku[("baseline", "DEMO-A")], by_sku[("current", "DEMO-A")]
    deltas = {sku: by_sku[("current", sku)]["sales"] - by_sku[("baseline", sku)]["sales"]
              for sku in ("DEMO-A", "DEMO-B")}
    metrics = []
    for label, key in (("销售额（USD）", "sales"), ("广告花费（USD）", "ad_spend"),
                       ("归因销售额（USD）", "ad_sales"), ("贡献利润（USD）", "contribution")):
        metrics.append([label, money(old[key]), money(new[key]), money(new[key] - old[key])])
    for label, key in (("ACOS", "acos"), ("TACOS", "tacos"), ("件数／Sessions", "unit_session")):
        delta = ("不可计算" if old[key] is None or new[key] is None
                 else f"{(new[key] - old[key]) * 100:+.2f}个百分点")
        metrics.append([label, percent(old[key]), percent(new[key]), delta])
    return {
        "title": "销售与贡献利润变化分析",
        "subtitle": "模拟数据示例 · US · USD\n基期：2026-09-01至09-14；本期：2026-09-15至09-28",
        "summary": [
            f"【证据支持】销售额由{money(old['sales'])}降至{money(new['sales'])}美元，"
            f"变化{percent(ratio(new['sales'] - old['sales'], old['sales']))}。"
            f"DEMO-A变化{money(deltas['DEMO-A'])}美元，DEMO-B变化{money(deltas['DEMO-B'])}美元。",
            f"【证据支持】广告花费由{money(old['ad_spend'])}增至{money(new['ad_spend'])}美元，"
            f"整体ACOS由{percent(old['acos'])}升至{percent(new['acos'])}。"
            "这说明归因口径下的收入效率下降，尚不能证明广告导致总销售下滑。",
            f"【证据支持】已覆盖成本下的贡献利润由{money(old['contribution'])}降至"
            f"{money(new['contribution'])}美元。优先检查DEMO-A的流量、投放组合和运营事件，"
            "补齐证据后再确定预算调整方案。",
        ],
        "sections": [
            {"title": "分析范围与待检验解释", "paragraphs": [
                "目标是解释两期差异并确定下一步核查顺序。样本只有两个商品，均为完整14天；"
                "广告归因窗口在本示例中假定已经成熟。所有数字为模拟，不代表真实经营结果。",
                "候选解释包括商品流量与转化变化、广告成本及组合变化，以及缺货、价格或促销事件。"
                "现有数据可以检验前两项的汇总表现；事件记录缺失，无法确认其作用。",
            ]},
            {"title": "关键指标", "page_break": True,
             "table": {"columns": ["指标", "基期", "本期", "变化"], "rows": metrics},
             "paragraphs": ["比率由汇总分子与分母重新计算。贡献利润已扣除采购、佣金、履约、"
                            "其他可变成本和广告费用，未覆盖固定费用与税务，不是净利润。"]},
            {"title": "销售变化主要集中在DEMO-A", "page_break": True,
             "chart": {"title": "各商品对销售额变化的贡献", "unit": "USD",
                       "labels": list(deltas), "values": [float(v) for v in deltas.values()],
                       "source": "sample-data.csv；按SKU计算本期sales减基期sales。"},
             "paragraphs": [
                 f"【证据支持】DEMO-A的Sessions由{money(a0['sessions'])}降至{money(a1['sessions'])}，"
                 f"件数／Sessions由{percent(a0['unit_session'])}降至{percent(a1['unit_session'])}。"
                 "流量与该比率同时变化，需进一步检查日期、设备或投放来源构成。",
                 "【待验证解释】商品缺货、价格调整、促销结束和流量构成变化都可能与结果相容。"
                 "目前没有对应记录，不能把销售下降归因于其中任一项。",
             ]},
            {"title": "广告与利润需要共同核查", "page_break": True,
             "table": {"columns": ["商品", "基期ACOS", "本期ACOS", "贡献利润变化（USD）"],
                       "rows": [[sku, percent(by_sku[("baseline", sku)]["acos"]),
                                 percent(by_sku[("current", sku)]["acos"]),
                                 money(by_sku[("current", sku)]["contribution"] -
                                       by_sku[("baseline", sku)]["contribution"])]
                                for sku in ("DEMO-A", "DEMO-B")]},
             "paragraphs": [
                 f"DEMO-A的CPC由{money(a0['cpc'])}升至{money(a1['cpc'])}美元。"
                 "聚合CPC变化可能来自竞价、位置或关键词组合；没有细分报告时不能判定具体原因。",
                 "DEMO-B的观察表现相对稳定，但这不等于它能承接无限追加预算。缺少库存和"
                 "边际投放数据，暂不承诺扩量收益。总销售与广告归因销售没有直接相减为自然销售。",
             ]},
            {"title": "行动顺序与复查方式", "page_break": True,
             "table": {"columns": ["顺序", "具体动作", "所需证据与复查"], "rows": [
                 ["优先", "补充DEMO-A每日销售、可售库存、价格和促销日志，定位变化开始时间。",
                  "核对Sessions、件数／Sessions、可售状态及事件日期。"],
                 ["随后", "取得同窗口广告活动、位置和搜索词明细，核查花费增量集中对象。",
                  "先对齐明细覆盖，再检查花费、点击、CPC、归因订单与销售。"],
                 ["证据齐备后", "结合贡献利润与库存，提出小范围预算或投放测试。",
                  "调整幅度与观察期由基线和业务约束决定；复查总销售、贡献利润及归因表现。"],
             ]},
             "paragraphs": ["如果广告归因尚未成熟、口径不一致或商品存在缺货，先纠正这些问题再评估投放。"
                            "本报告未给出自动执行指令或未经测算的预算调整比例。"]},
            {"title": "限制与下一步数据", "paragraphs": [
                "【数据不足】仅有两个汇总期间，不能建立可靠季节性、长期预测或因果效应。"
                "没有广告订单，无法计算广告订单转化率；没有库存、运营日志和搜索词明细，无法确认机制。",
                "成本范围按示例说明确定。真实应用需核对税费、退款、采购、物流及费用分摊，"
                "遗漏成本可能改变盈利判断。",
            ]},
        ],
        "sources": [
            "来源：examples/sample-data.csv，4行模拟记录；背景与字段定义见examples/brief.md。",
            "sales、ad_spend、ad_sales按period分别求和；商品贡献为同SKU本期sales减基期sales。",
            "ACOS＝ad_spend／ad_sales；TACOS＝ad_spend／sales；件数／Sessions＝units／sessions。",
            "贡献利润＝sales－cogs－selling_fees－fulfillment_fees－other_variable_costs－ad_spend。",
            "计算使用Decimal保留精度，展示统一保留两位小数；百分点变化根据未舍入比率计算。",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "example")
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    report = build_report(read_example())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "sample-report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = render_report(report, args.output_dir / "sample-report.pdf", args.font, args.output_dir)
    print(f"Created: {json_path}\nCreated: {result}")


if __name__ == "__main__":
    main()
