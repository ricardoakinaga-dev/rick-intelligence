#!/usr/bin/env python3
"""
Agregação de Logs e Telemetria — RAG Phase 0/1

Lê os logs JSON Lines e produz métricas agregadas.

Uso:
    python scripts/aggregate_logs.py                    # últimas 24h
    python scripts/aggregate_logs.py --hours 168         # última semana
    python scripts/aggregate_logs.py --output report.json # salvar JSON

Ref: 0019-observabilidade-e-metricas.md
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import LOGS_DIR

CANONICAL_LOGS_FILE = LOGS_DIR / "queries.jsonl"
LEGACY_LOGS_FILE = Path(__file__).parent.parent.parent / "data" / "logs" / "queries.jsonl"


def get_logs_file() -> Path:
    """Return canonical logs path, with legacy fallback when needed."""
    if CANONICAL_LOGS_FILE.exists():
        return CANONICAL_LOGS_FILE
    return LEGACY_LOGS_FILE


def parse_args():
    parser = argparse.ArgumentParser(description="Agregar logs de queries RAG")
    parser.add_argument("--hours", type=int, default=24, help="Janela de tempo em horas (default: 24)")
    parser.add_argument("--output", type=str, help="Salvar relatório em JSON")
    parser.add_argument("--verbose", action="store_true", help="Mostrar detalhes")
    return parser.parse_args()


def read_logs(hours: int = 24) -> list[dict]:
    """Lê logs do arquivo JSON Lines dentro da janela de tempo."""
    logs_file = get_logs_file()
    if not logs_file.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    logs = []

    with open(logs_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                # Parse timestamp
                ts_str = entry.get("timestamp", "")
                if ts_str:
                    # Handle both with and without Z suffix
                    ts_str = ts_str.replace("Z", "+00:00")
                    try:
                        ts = datetime.fromisoformat(ts_str)
                    except ValueError:
                        ts = datetime.now(timezone.utc)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)

                    if ts < cutoff:
                        continue

                logs.append(entry)
            except json.JSONDecodeError:
                continue

    return logs


def aggregate_retrieval_metrics(logs: list[dict]) -> dict:
    """Agrega métricas de retrieval."""
    retrieval_logs = [l for l in logs if "retrieval_time_ms" in l]

    if not retrieval_logs:
        return {
            "total_queries": 0,
            "avg_latency_ms": 0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
            "p99_latency_ms": 0,
            "low_confidence_rate": 0.0,
            "avg_results_count": 0.0
        }

    retrieval_times = sorted([l["retrieval_time_ms"] for l in retrieval_logs])
    result_counts = [l.get("results_count", 0) for l in retrieval_logs]
    low_conf_count = sum(1 for l in retrieval_logs if l.get("low_confidence", False))

    total = len(retrieval_logs)

    def percentile(data, p):
        idx = int(len(data) * p / 100)
        idx = min(idx, len(data) - 1)
        return data[idx]

    return {
        "total_queries": total,
        "avg_latency_ms": sum(retrieval_times) / total if total else 0,
        "p50_latency_ms": percentile(retrieval_times, 50),
        "p95_latency_ms": percentile(retrieval_times, 95),
        "p99_latency_ms": percentile(retrieval_times, 99),
        "low_confidence_rate": low_conf_count / total if total else 0.0,
        "avg_results_count": sum(result_counts) / total if total else 0.0
    }


def aggregate_answer_metrics(logs: list[dict]) -> dict:
    """Agrega métricas de resposta/answer."""
    answer_logs = [l for l in logs if "answer" in l and "latency_ms" in l]

    if not answer_logs:
        return {
            "total_answers": 0,
            "avg_latency_ms": 0,
            "p95_latency_ms": 0,
            "grounded_rate": 0.0,
            "confidence_distribution": {"high": 0, "medium": 0, "low": 0}
        }

    total = len(answer_logs)
    latencies = sorted([l["latency_ms"] for l in answer_logs])
    grounded_count = sum(1 for l in answer_logs if l.get("grounded", False))
    confidences = defaultdict(int)

    for l in answer_logs:
        conf = l.get("confidence", "unknown")
        confidences[conf] += 1

    def percentile(data, p):
        idx = int(len(data) * p / 100)
        idx = min(idx, len(data) - 1)
        return data[idx]

    return {
        "total_answers": total,
        "avg_latency_ms": sum(latencies) / total if total else 0,
        "p95_latency_ms": percentile(latencies, 95) if latencies else 0,
        "grounded_rate": grounded_count / total if total else 0.0,
        "confidence_distribution": dict(confidences)
    }


def aggregate_by_hour(logs: list[dict]) -> dict:
    """Agrega métricas por hora."""
    by_hour = defaultdict(lambda: {
        "queries": 0,
        "avg_latency_ms": 0,
        "low_confidence": 0
    })

    for log in logs:
        ts_str = log.get("timestamp", "")
        if ts_str:
            try:
                ts_str = ts_str.replace("Z", "")
                dt = datetime.fromisoformat(ts_str)
                hour_key = dt.strftime("%Y-%m-%d %H:00")
            except ValueError:
                continue
        else:
            continue

        by_hour[hour_key]["queries"] += 1
        by_hour[hour_key]["avg_latency_ms"] += log.get("retrieval_time_ms", 0)
        if log.get("low_confidence", False):
            by_hour[hour_key]["low_confidence"] += 1

    # Calculate averages
    for hour, data in by_hour.items():
        if data["queries"] > 0:
            data["avg_latency_ms"] = data["avg_latency_ms"] / data["queries"]

    return dict(sorted(by_hour.items()))


def generate_report(hours: int = 24) -> dict:
    """Gera relatório completo de telemetria."""
    logs = read_logs(hours)

    report = {
        "report_generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "window_hours": hours,
        "total_logs": len(logs),
        "retrieval": aggregate_retrieval_metrics(logs),
        "answers": aggregate_answer_metrics(logs),
        "by_hour": aggregate_by_hour(logs)
    }

    return report


def print_report(report: dict, verbose: bool = False):
    """Imprime relatório formatado."""
    print("=" * 60)
    print("RAG TELEMETRIA REPORT")
    print("=" * 60)
    print(f"Gerado em: {report['report_generated_at']}")
    print(f"Janela: {report['window_hours']} horas")
    print(f"Total de logs: {report['total_logs']}")
    print()

    r = report["retrieval"]
    print("RETRIEVAL")
    print("-" * 40)
    print(f"  Total queries:        {r['total_queries']}")
    print(f"  Avg latency:          {r['avg_latency_ms']:.0f}ms")
    print(f"  P50 latency:          {r['p50_latency_ms']:.0f}ms")
    print(f"  P95 latency:          {r['p95_latency_ms']:.0f}ms")
    print(f"  P99 latency:          {r['p99_latency_ms']:.0f}ms")
    print(f"  Low confidence rate:  {r['low_confidence_rate']:.1%}")
    print(f"  Avg results returned: {r['avg_results_count']:.1f}")
    print()

    a = report["answers"]
    print("ANSWERS")
    print("-" * 40)
    print(f"  Total answers:       {a['total_answers']}")
    print(f"  Avg latency:        {a['avg_latency_ms']:.0f}ms")
    print(f"  P95 latency:        {a['p95_latency_ms']:.0f}ms")
    print(f"  Grounded rate:       {a['grounded_rate']:.1%}")
    conf = a['confidence_distribution']
    print(f"  Confidence:         high={conf.get('high', 0)}, medium={conf.get('medium', 0)}, low={conf.get('low', 0)}")
    print()

    if verbose and report["by_hour"]:
        print("BY HOUR")
        print("-" * 40)
        for hour, data in list(report["by_hour"].items())[-12:]:
            print(f"  {hour}: {data['queries']:3d} queries, {data['avg_latency_ms']:.0f}ms avg, {data['low_confidence']} low_conf")
        print()

    print("=" * 60)


def main():
    args = parse_args()

    report = generate_report(hours=args.hours)

    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Relatório salvo em: {output_path}")

    print_report(report, verbose=args.verbose)


if __name__ == "__main__":
    main()
