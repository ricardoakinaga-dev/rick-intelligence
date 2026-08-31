"""
SLI/SLO Definitions — Service Level Indicators and Objectives

Documenta os indicadores de nível de serviço e seus objetivos
para o RAG Enterprise Premium.

SLI: Service Level Indicator — métrica mensurável
SLO: Service Level Objective — meta target para o SLI
"""

from dataclasses import dataclass
from enum import Enum


class SLICategory(Enum):
    """Categoria do SLI."""
    AVAILABILITY = "availability"
    LATENCY = "latency"
    QUALITY = "quality"
    RELIABILITY = "reliability"


@dataclass
class SLIDefinition:
    """Definição formal de um SLI."""
    name: str
    description: str
    category: SLICategory
    unit: str  # e.g., "ms", "%", "count"
    measurement_method: str  # como é medido
    query_pattern: str  #日志查询 padrão


@dataclass
class SLOTarget:
    """Objetivo de nível de serviço."""
    sli_name: str
    target_value: float
    min_value: float | None = None  # Para métricas onde "higher is better"
    alert_threshold: float | None = None  # Threshold para disparar alerta
    alert_severity: str = "high"  # critical, high, medium
    window: str = "7d"  # Janela de avaliação


# ── SLI Definitions ───────────────────────────────────────────────────────────

SLI_DEFINITIONS: dict[str, SLIDefinition] = {
    "vector_store_availability": SLIDefinition(
        name="vector_store_availability",
        description="Percentual de tempo que o Qdrant está acessível para operações de query",
        category=SLICategory.AVAILABILITY,
        unit="%",
        measurement_method="GET /health verifica qdrant_ok; ratio de queries bem-sucedidas vs total",
        query_pattern="status:query AND workspace_id:{workspace} AND error:null",
    ),
    "latency_p99": SLIDefinition(
        name="latency_p99",
        description="Latência no percentil 99 para queries RAG completas (search + answer)",
        category=SLICategory.LATENCY,
        unit="ms",
        measurement_method="total_latency_ms no log de queries; percentile 99",
        query_pattern="type:query AND workspace_id:{workspace} | stats p99(total_latency_ms)",
    ),
    "latency_p50": SLIDefinition(
        name="latency_p50",
        description="Latência mediana (p50) para queries RAG completas",
        category=SLICategory.LATENCY,
        unit="ms",
        measurement_method="total_latency_ms no log de queries; percentile 50",
        query_pattern="type:query AND workspace_id:{workspace} | stats p50(total_latency_ms)",
    ),
    "retrieval_latency_p99": SLIDefinition(
        name="retrieval_latency_p99",
        description="Latência no percentil 99 para a etapa de retrieval (search only)",
        category=SLICategory.LATENCY,
        unit="ms",
        measurement_method="retrieval_time_ms no log de queries; percentile 99",
        query_pattern="type:query AND workspace_id:{workspace} | stats p99(retrieval_time_ms)",
    ),
    "error_rate_ingestion": SLIDefinition(
        name="error_rate_ingestion",
        description="Taxa de erros em operações de ingestão de documentos",
        category=SLICategory.RELIABILITY,
        unit="%",
        measurement_method="count(status:error) / count(total) no ingestion log",
        query_pattern="type:ingestion AND workspace_id:{workspace} AND status:error",
    ),
    "hit_rate_top1": SLIDefinition(
        name="hit_rate_top1",
        description="Taxa de acerto no top-1 (resposta correta na primeira posição)",
        category=SLICategory.QUALITY,
        unit="%",
        measurement_method="hit: true AND rank <= 1 / total_queries no evaluation log",
        query_pattern="type:evaluation AND workspace_id:{workspace} | stats avg(hit_at_1)",
    ),
    "hit_rate_top5": SLIDefinition(
        name="hit_rate_top5",
        description="Taxa de acerto no top-5 (resposta correta nas primeiras 5 posições)",
        category=SLICategory.QUALITY,
        unit="%",
        measurement_method="hit: true AND rank <= 5 / total_queries no evaluation log",
        query_pattern="type:evaluation AND workspace_id:{workspace} | stats avg(hit_at_5)",
    ),
    "groundedness_rate": SLIDefinition(
        name="groundedness_rate",
        description="Percentual de respostas que estão grounded (citam fontes válidas)",
        category=SLICategory.QUALITY,
        unit="%",
        measurement_method="grounded: true / total_queries no answer log",
        query_pattern="type:query AND workspace_id:{workspace} AND grounded:true",
    ),
    "no_context_rate": SLIDefinition(
        name="no_context_rate",
        description="Percentual de queries que retornaram 'no context' (low confidence)",
        category=SLICategory.QUALITY,
        unit="%",
        measurement_method="low_confidence: true / total_queries no query log",
        query_pattern="type:query AND workspace_id:{workspace} AND low_confidence:true",
    ),
    "disk_usage": SLIDefinition(
        name="disk_usage",
        description="Percentual de uso do disco no diretório de logs",
        category=SLICategory.AVAILABILITY,
        unit="%",
        measurement_method="shutil.disk_usage(LOGS_DIR).used / shutil.disk_usage(LOGS_DIR).total",
        query_pattern="N/A (métrica de sistema)",
    ),
}


# ── SLO Targets ───────────────────────────────────────────────────────────────

SLO_TARGETS: dict[str, SLOTarget] = {
    "vector_store_availability": SLOTarget(
        sli_name="vector_store_availability",
        target_value=99.5,
        min_value=99.5,
        alert_threshold=99.0,
        alert_severity="critical",
        window="1d",
    ),
    "latency_p99": SLOTarget(
        sli_name="latency_p99",
        target_value=3000.0,  # 3 segundos
        alert_threshold=5000.0,  # 5 segundos
        alert_severity="critical",
        window="1d",
    ),
    "latency_p50": SLOTarget(
        sli_name="latency_p50",
        target_value=1000.0,  # 1 segundo
        alert_threshold=2000.0,
        alert_severity="high",
        window="1d",
    ),
    "retrieval_latency_p99": SLOTarget(
        sli_name="retrieval_latency_p99",
        target_value=1000.0,  # 1 segundo para retrieval
        alert_threshold=2000.0,
        alert_severity="high",
        window="1d",
    ),
    "error_rate_ingestion": SLOTarget(
        sli_name="error_rate_ingestion",
        target_value=2.0,  # <2%
        alert_threshold=5.0,
        alert_severity="critical",
        window="7d",
    ),
    "hit_rate_top1": SLOTarget(
        sli_name="hit_rate_top1",
        target_value=60.0,  # 60%
        alert_threshold=50.0,
        alert_severity="high",
        window="30d",
    ),
    "hit_rate_top5": SLOTarget(
        sli_name="hit_rate_top5",
        target_value=80.0,  # 80%
        alert_threshold=50.0,
        alert_severity="high",
        window="30d",
    ),
    "groundedness_rate": SLOTarget(
        sli_name="groundedness_rate",
        target_value=85.0,  # 85%
        alert_threshold=70.0,
        alert_severity="high",
        window="7d",
    ),
    "no_context_rate": SLOTarget(
        sli_name="no_context_rate",
        target_value=10.0,  # <10%
        alert_threshold=20.0,
        alert_severity="high",
        window="7d",
    ),
    "disk_usage": SLOTarget(
        sli_name="disk_usage",
        target_value=80.0,  # <80%
        alert_threshold=90.0,
        alert_severity="medium",
        window="1d",
    ),
}


# ── Helper Functions ──────────────────────────────────────────────────────────

def get_sli(name: str) -> SLIDefinition | None:
    """Get SLI definition by name."""
    return SLI_DEFINITIONS.get(name)


def get_slo(name: str) -> SLOTarget | None:
    """Get SLO target by name."""
    return SLO_TARGETS.get(name)


def get_slo_status(name: str, current_value: float) -> tuple[bool, str]:
    """
    Evaluate if current value meets SLO target.

    Returns:
        (is_healthy, message)
    """
    slo = get_slo(name)
    if not slo:
        return True, f"Unknown SLO: {name}"

    if slo.min_value is not None:
        # Higher is better (e.g., hit rate)
        is_healthy = current_value >= slo.min_value
        message = f"{name}: {current_value} vs target >= {slo.min_value}"
    else:
        # Lower is better (e.g., latency)
        is_healthy = current_value <= slo.target_value
        message = f"{name}: {current_value} vs target <= {slo.target_value}"

    return is_healthy, message


def get_all_slos() -> list[SLOTarget]:
    """Return all SLO targets."""
    return list(SLO_TARGETS.values())


def get_slos_by_category(category: SLICategory) -> list[SLOTarget]:
    """Return SLO targets filtered by category."""
    return [
        slo for name, slo in SLO_TARGETS.items()
        if SLI_DEFINITIONS.get(name, SLIDefinition(name=name, description="", category=category, unit="", measurement_method="", query_pattern="")).category == category
    ]


def format_slo_report(workspace_id: str, current_metrics: dict) -> str:
    """
    Generate a human-readable SLO report.

    Args:
        workspace_id: Workspace being reported
        current_metrics: Dict of metric values {sli_name: value}

    Returns:
        Formatted report string
    """
    lines = [
        f"=== SLO Report: {workspace_id} ===",
        "",
    ]

    for category in SLICategory:
        lines.append(f"[{category.value.upper()}]")
        slos = get_slos_by_category(category)
        for slo in slos:
            value = current_metrics.get(slo.sli_name)
            if value is None:
                status = "⚪ NO DATA"
            else:
                is_healthy, _ = get_slo_status(slo.sli_name, value)
                status = "✅ OK" if is_healthy else f"❌ BREACH (target: {slo.target_value})"

            lines.append(f"  {slo.sli_name}: {value} {status}")

        lines.append("")

    return "\n".join(lines)


# ── Alert Rule Generator ───────────────────────────────────────────────────────

def generate_alert_rules() -> list[dict]:
    """
    Generate alert rules from SLO targets.
    Used by telemetry_service.get_alerts().

    Returns:
        List of alert rule dicts compatible with get_alerts().
    """
    rules = []
    for name, slo in SLO_TARGETS.items():
        sli = SLI_DEFINITIONS.get(name)
        if not slo.alert_threshold:
            continue

        # Determine firing condition
        if sli and sli.category in (SLICategory.QUALITY, SLICategory.AVAILABILITY):
            if name in ("hit_rate_top1", "hit_rate_top5", "groundedness_rate"):
                # Higher is better — alert when BELOW threshold
                rules.append({
                    "name": f"{name}_below_slo",
                    "severity": slo.alert_severity,
                    "condition": "below_threshold",
                    "threshold": slo.alert_threshold,
                    "window": slo.window,
                    "slo_target": slo.target_value,
                    "unit": sli.unit,
                })
            else:
                # Lower is better — alert when ABOVE threshold
                rules.append({
                    "name": f"{name}_above_threshold",
                    "severity": slo.alert_severity,
                    "condition": "above_threshold",
                    "threshold": slo.alert_threshold,
                    "window": slo.window,
                    "slo_target": slo.target_value,
                    "unit": sli.unit,
                })

    return rules