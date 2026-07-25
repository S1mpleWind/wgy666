"""Run repeatable repository-assistant quality sampling against a live API."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import statistics
import time
from typing import Any

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = BACKEND_ROOT / "evaluation" / "qa_cases.json"
DEFAULT_OUTPUT = BACKEND_ROOT / "evaluation" / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate repository assistant answers.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--owner")
    parser.add_argument("--name")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def load_suite(path: Path) -> dict[str, Any]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation suite must contain a non-empty cases list.")

    seen: set[str] = set()
    for case in cases:
        missing = {"id", "category", "question", "expected_keyword_groups", "expected_files"} - set(case)
        if missing:
            raise ValueError(f"Case {case.get('id', '<unknown>')} is missing: {sorted(missing)}")
        if case["id"] in seen:
            raise ValueError(f"Duplicate case id: {case['id']}")
        seen.add(case["id"])
        if not all(isinstance(group, list) and group for group in case["expected_keyword_groups"]):
            raise ValueError(f"Case {case['id']} has an invalid expected_keyword_groups value.")
    return suite


def contains_term(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()


def score_response(case: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    answer = str(payload.get("answer", ""))
    citations = payload.get("citations") or []
    citation_paths = {
        str(citation.get("path"))
        for citation in citations
        if isinstance(citation, dict) and citation.get("path")
    }

    keyword_matches = [
        any(contains_term(answer, term) for term in group)
        for group in case["expected_keyword_groups"]
    ]
    expected_files = case.get("expected_files") or []
    file_matches = [
        any(path == expected or path.endswith(f"/{expected}") for path in citation_paths)
        for expected in expected_files
    ]
    forbidden_hits = [
        term for term in case.get("forbidden_terms", []) if contains_term(answer, term)
    ]

    fact_coverage = sum(keyword_matches) / len(keyword_matches) if keyword_matches else 1.0
    file_coverage = sum(file_matches) / len(file_matches) if file_matches else 1.0
    citation_available = 1.0 if citations else 0.0
    no_forbidden_claim = 0.0 if forbidden_hits else 1.0
    answer_available = 1.0 if len(answer.strip()) >= 20 else 0.0
    automatic_score = round(
        100
        * (
            0.5 * fact_coverage
            + 0.25 * file_coverage
            + 0.1 * citation_available
            + 0.1 * no_forbidden_claim
            + 0.05 * answer_available
        ),
        1,
    )
    return {
        "automatic_score": automatic_score,
        "fact_coverage": round(fact_coverage, 3),
        "file_coverage": round(file_coverage, 3),
        "citation_count": len(citations),
        "matched_keyword_groups": sum(keyword_matches),
        "total_keyword_groups": len(keyword_matches),
        "matched_files": sum(file_matches),
        "total_expected_files": len(file_matches),
        "forbidden_hits": forbidden_hits,
    }


async def run_case(
    client: httpx.AsyncClient,
    owner: str,
    name: str,
    case: dict[str, Any],
    run_number: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = await client.post(
            "/api/assistant/chat",
            json={
                "owner": owner,
                "name": name,
                "message": case["question"],
                "freshness": "cache_first",
                "history": [],
            },
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if not response.is_success:
            return {
                "case_id": case["id"],
                "run": run_number,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "error": payload.get("detail", response.text),
                "automatic_score": 0.0,
            }
        return {
            "case_id": case["id"],
            "run": run_number,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "answer": payload.get("answer", ""),
            "tool_calls": payload.get("tool_calls", []),
            "citations": payload.get("citations", []),
            **score_response(case, payload),
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "case_id": case["id"],
            "run": run_number,
            "status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": str(exc),
            "automatic_score": 0.0,
        }


def summarize(cases: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_case[result["case_id"]].append(result)

    case_summaries = []
    for case in cases:
        runs = by_case[case["id"]]
        scores = [float(run["automatic_score"]) for run in runs]
        latencies = [float(run["latency_ms"]) for run in runs]
        case_summaries.append({
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "average_score": round(statistics.fmean(scores), 1),
            "score_stddev": round(statistics.pstdev(scores), 1) if len(scores) > 1 else 0.0,
            "average_latency_ms": round(statistics.fmean(latencies), 1),
            "successful_runs": sum(run.get("status_code") == 200 for run in runs),
            "total_runs": len(runs),
            "manual_accuracy_0_to_2": None,
            "manual_completeness_0_to_2": None,
            "manual_clarity_0_to_2": None,
        })

    all_scores = [summary["average_score"] for summary in case_summaries]
    all_latencies = [float(result["latency_ms"]) for result in results]
    return {
        "case_count": len(cases),
        "request_count": len(results),
        "successful_requests": sum(result.get("status_code") == 200 for result in results),
        "average_score": round(statistics.fmean(all_scores), 1),
        "pass_rate_at_70": round(100 * sum(score >= 70 for score in all_scores) / len(all_scores), 1),
        "average_latency_ms": round(statistics.fmean(all_latencies), 1),
        "case_summaries": case_summaries,
    }


def markdown_report(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        "# 仓库问答质量采样报告",
        "",
        f"- 仓库：`{metadata['repository']}`",
        f"- 生成时间：{metadata['generated_at']}",
        f"- 问题数：{summary['case_count']}",
        f"- 总请求数：{summary['request_count']}",
        f"- 请求成功数：{summary['successful_requests']}",
        f"- 自动评分均值：{summary['average_score']} / 100",
        f"- 自动评分 70 分通过率：{summary['pass_rate_at_70']}%",
        f"- 平均响应时间：{summary['average_latency_ms']} ms",
        "",
        "> 自动评分只检查预期事实关键词、引用文件和禁用表述，不能代替人工判断。请由两名成员分别填写准确性、完整性和表达清晰度（每项 0-2 分）。",
        "",
        "| 编号 | 类型 | 自动分 | 波动 | 成功次数 | 平均耗时(ms) | 人工评分 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in summary["case_summaries"]:
        lines.append(
            f"| {item['id']} | {item['category']} | {item['average_score']} | "
            f"{item['score_stddev']} | {item['successful_runs']}/{item['total_runs']} | "
            f"{item['average_latency_ms']} | 待填写 |"
        )
    lines.extend([
        "",
        "## 人工复核规则",
        "",
        "- 准确性：0=存在明显错误，1=基本正确但有小问题，2=事实正确。",
        "- 完整性：0=未回答核心问题，1=覆盖主要内容，2=要点完整且引用充分。",
        "- 清晰度：0=难以理解，1=基本清楚，2=结构清晰且表述简洁。",
        "- 两名成员独立评分；分歧超过 1 分时共同复核原始回答和引用代码。",
    ])
    return "\n".join(lines) + "\n"


async def async_main(args: argparse.Namespace) -> int:
    suite = load_suite(args.cases)
    cases = suite["cases"][: args.case_limit] if args.case_limit else suite["cases"]
    owner = args.owner or suite["repository"]["owner"]
    name = args.name or suite["repository"]["name"]

    categories = sorted({case["category"] for case in cases})
    print(f"Validated {len(cases)} cases across {len(categories)} categories: {', '.join(categories)}")
    if args.validate_only:
        return 0
    if args.runs < 1:
        raise ValueError("--runs must be at least 1.")

    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as client:
        for case_index, case in enumerate(cases, start=1):
            for run_number in range(1, args.runs + 1):
                print(f"[{case_index}/{len(cases)}] {case['id']} run {run_number}/{args.runs}")
                results.append(await run_case(client, owner, name, case, run_number))
                if args.delay > 0:
                    await asyncio.sleep(args.delay)

    summary = summarize(cases, results)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    metadata = {
        "repository": f"{owner}/{name}",
        "base_url": args.base_url,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs_per_case": args.runs,
    }
    report = {"metadata": metadata, "summary": summary, "results": results}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"qa-evaluation-{timestamp}.json"
    markdown_path = args.output_dir / f"qa-evaluation-{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(metadata, summary), encoding="utf-8")
    print(f"JSON results: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
