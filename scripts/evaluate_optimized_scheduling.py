from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.scheduling_optimization_utils import (
    derive_optimized_dataset,
    evaluate_dataset,
)


REPORT_DIR = PROJECT_ROOT / "data" / "evaluation_reports"
DATASETS = {
    "balanced_5000": (PROJECT_ROOT / "data" / "scenario_synthetic_center_balanced_5000", "spread"),
    "highload_5000": (PROJECT_ROOT / "data" / "scenario_synthetic_center_highload_5000", "spread"),
    "highload_peak_500": (PROJECT_ROOT / "data" / "scenario_synthetic_center_highload_5000", "head"),
    "stress_load": (PROJECT_ROOT / "data" / "scenario_synthetic_center_large", "spread"),
}


def main() -> None:
    stress_path = DATASETS["stress_load"][0]
    if not DATASETS["balanced_5000"][0].exists():
        derive_optimized_dataset(stress_path, DATASETS["balanced_5000"][0], "balanced")
    if not DATASETS["highload_5000"][0].exists():
        derive_optimized_dataset(stress_path, DATASETS["highload_5000"][0], "highload")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        name: evaluate_dataset(path, integration_order_limit=500, sample_mode=sample_mode)
        for name, (path, sample_mode) in DATASETS.items()
    }
    report_path = REPORT_DIR / "scheduling_optimization_report.json"
    summary_path = REPORT_DIR / "scheduling_optimization_summary.md"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(_summary_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "summary": str(summary_path), "datasets": report}, ensure_ascii=False, indent=2))


def _summary_markdown(report: dict) -> str:
    lines = ["# 调度优化检测报告", ""]
    for name, item in report.items():
        metrics = item["strategy_results"].get("sla_guarded_hybrid", {}).get("metrics", {})
        comparison = item["comparison"]
        lines.extend(
            [
                f"## {name}",
                "",
                f"- 场景标签：`{item['scenario_label']}`",
                f"- 抽样模式：`{item['sample_mode']}`",
                f"- 导入订单：`{item['created_orders']}`",
                f"- 优化策略 SLA 达标率：`{metrics.get('on_time_rate', 0)}`",
                f"- VIP SLA 达标率：`{metrics.get('vip_sla_rate', 0)}`",
                f"- 加急延期率：`{metrics.get('urgent_delay_rate', 0)}`",
                f"- SLA 相对 baseline 提升：`{comparison['sla_on_time_rate_delta']}`",
                f"- 总延期分钟下降比例：`{comparison['total_delay_reduction_ratio']}`",
                f"- 重排平均耗时 ms：`{comparison['rebuild_latency_avg_ms']}`",
                f"- 重排 P95 ms：`{comparison['rebuild_latency_p95_ms']}`",
                "",
            ]
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
