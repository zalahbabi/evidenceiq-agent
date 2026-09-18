import csv
import json
import statistics
import time
from pathlib import Path

from src.tier2_agent import ask_tier2


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmark_questions.json"
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"


def load_benchmarks():
    return json.loads(
        BENCHMARK_PATH.read_text(encoding="utf-8")
    )


def successful_tools(answer):
    return {
        call.tool
        for call in answer.tool_calls
        if call.ok
    }


def all_tools(answer):
    return {
        call.tool
        for call in answer.tool_calls
    }


def combined_successful_sql(answer):
    return "\n".join(
        call.code.lower()
        for call in answer.tool_calls
        if call.tool == "run_sql" and call.ok
    )


def execution_pass(answer, case):
    if case["expect_insufficient_data"]:
        return (
            answer.insufficient_data is True
            and len(answer.tool_calls) == 0
        )

    if answer.insufficient_data:
        return False

    required = set(case["required_tools"])
    successful = successful_tools(answer)

    # Only evidence-producing tools are required to have actually succeeded.
    return required.issubset(successful)


def tool_selection_pass(answer, case):
    actual = all_tools(answer)
    required = set(case["required_tools"])
    forbidden = set(case["forbidden_tools"])

    return (
        required.issubset(actual)
        and actual.isdisjoint(forbidden)
    )


def sql_rules_pass(answer, case):
    terms = [
        term.lower()
        for term in case.get("required_sql_terms", [])
    ]

    if not terms:
        return True

    sql = combined_successful_sql(answer)

    if not sql:
        return False

    return all(
        term in sql
        for term in terms
    )


def claim_sources_pass(answer, case):
    min_claims = int(case.get("min_claims", 0))

    if len(answer.claims) < min_claims:
        return False

    calls_by_index = {
        call.index: call
        for call in answer.tool_calls
    }

    for claim in answer.claims:
        # Claims without a numeric value do not require numeric evidence.
        if claim.value is None:
            continue

        if claim.source_tool_call is None:
            return False

        call = calls_by_index.get(
            claim.source_tool_call
        )

        if call is None:
            return False

        if not call.ok:
            return False

        if call.tool not in {
            "run_sql",
            "run_python",
        }:
            return False

    return True


def repair_used(answer):
    sql_calls = [
        call
        for call in answer.tool_calls
        if call.tool == "run_sql"
    ]

    return (
        len(sql_calls) >= 2
        and any(not call.ok for call in sql_calls)
        and any(call.ok for call in sql_calls)
    )


def evaluate_case(case):
    start = time.perf_counter()

    try:
        answer = ask_tier2(
            case["question"]
        )

        latency = time.perf_counter() - start

        execution_ok = execution_pass(
            answer,
            case,
        )

        tools_ok = tool_selection_pass(
            answer,
            case,
        )

        sql_ok = sql_rules_pass(
            answer,
            case,
        )

        claim_ok = claim_sources_pass(
            answer,
            case,
        )

        overall = (
            execution_ok
            and tools_ok
            and sql_ok
            and claim_ok
        )

        return {
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "latency_s": round(latency, 3),
            "expected_insufficient_data": case["expect_insufficient_data"],
            "actual_insufficient_data": answer.insufficient_data,
            "required_tools": "|".join(case["required_tools"]),
            "forbidden_tools": "|".join(case["forbidden_tools"]),
            "actual_tools": "|".join(
                sorted(all_tools(answer))
            ),
            "successful_tools": "|".join(
                sorted(successful_tools(answer))
            ),
            "execution_pass": execution_ok,
            "tool_selection_pass": tools_ok,
            "sql_rules_pass": sql_ok,
            "claim_sources_pass": claim_ok,
            "repair_used": repair_used(answer),
            "num_claims": len(answer.claims),
            "num_tool_calls": len(answer.tool_calls),
            "overall_pass": overall,
            "error": "",
        }

    except Exception as exc:
        latency = time.perf_counter() - start

        return {
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "latency_s": round(latency, 3),
            "expected_insufficient_data": case["expect_insufficient_data"],
            "actual_insufficient_data": "",
            "required_tools": "|".join(case["required_tools"]),
            "forbidden_tools": "|".join(case["forbidden_tools"]),
            "actual_tools": "",
            "successful_tools": "",
            "execution_pass": False,
            "tool_selection_pass": False,
            "sql_rules_pass": False,
            "claim_sources_pass": False,
            "repair_used": False,
            "num_claims": 0,
            "num_tool_calls": 0,
            "overall_pass": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def pct(values):
    if not values:
        return 0.0

    return round(
        sum(bool(v) for v in values)
        / len(values)
        * 100,
        2,
    )


def write_summary(results, path):
    latencies = [
        float(row["latency_s"])
        for row in results
    ]

    summary = {
        "questions": len(results),
        "execution_success_rate_pct": pct(
            [row["execution_pass"] for row in results]
        ),
        "tool_selection_accuracy_pct": pct(
            [row["tool_selection_pass"] for row in results]
        ),
        "sql_business_rule_pass_rate_pct": pct(
            [row["sql_rules_pass"] for row in results]
        ),
        "claim_source_validity_pct": pct(
            [row["claim_sources_pass"] for row in results]
        ),
        "overall_pass_rate_pct": pct(
            [row["overall_pass"] for row in results]
        ),
        "mean_latency_s": round(
            statistics.mean(latencies),
            3,
        ),
        "median_latency_s": round(
            statistics.median(latencies),
            3,
        ),
        "min_latency_s": round(
            min(latencies),
            3,
        ),
        "max_latency_s": round(
            max(latencies),
            3,
        ),
        "sql_repairs_used": sum(
            bool(row["repair_used"])
            for row in results
        ),
    }

    path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    return summary


def main():
    cases = load_benchmarks()

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    csv_path = (
        RESULTS_DIR
        / f"tier2_benchmark_{timestamp}.csv"
    )

    summary_path = (
        RESULTS_DIR
        / f"tier2_benchmark_{timestamp}_summary.json"
    )

    results = []

    print(
        f"Running {len(cases)} Tier 2 benchmark questions...\n"
    )

    for i, case in enumerate(
        cases,
        start=1,
    ):
        print(
            f"[{i:02d}/{len(cases):02d}] "
            f"{case['id']} - {case['question']}"
        )

        row = evaluate_case(case)
        results.append(row)

        status = (
            "PASS"
            if row["overall_pass"]
            else "FAIL"
        )

        print(
            f"    {status} | "
            f"{row['latency_s']} s | "
            f"tools={row['actual_tools'] or 'none'}"
        )

        if row["error"]:
            print(
                f"    ERROR: {row['error']}"
            )

    fieldnames = list(
        results[0].keys()
    )

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(results)

    summary = write_summary(
        results,
        summary_path,
    )

    print("\n" + "=" * 70)
    print("TIER 2 EVALUATION SUMMARY")
    print("=" * 70)
    print(
        f"Questions:                    {summary['questions']}"
    )
    print(
        "Execution success rate:       "
        f"{summary['execution_success_rate_pct']:.2f}%"
    )
    print(
        "Tool-selection accuracy:      "
        f"{summary['tool_selection_accuracy_pct']:.2f}%"
    )
    print(
        "SQL/business-rule pass rate:  "
        f"{summary['sql_business_rule_pass_rate_pct']:.2f}%"
    )
    print(
        "Claim-source validity:        "
        f"{summary['claim_source_validity_pct']:.2f}%"
    )
    print(
        "Overall benchmark pass rate:  "
        f"{summary['overall_pass_rate_pct']:.2f}%"
    )
    print(
        "Mean latency:                 "
        f"{summary['mean_latency_s']:.3f} s"
    )
    print(
        "Median latency:               "
        f"{summary['median_latency_s']:.3f} s"
    )
    print(
        f"SQL repairs used:              {summary['sql_repairs_used']}"
    )

    print("\nSaved:")
    print(f"  {csv_path}")
    print(f"  {summary_path}")


if __name__ == "__main__":
    main()
