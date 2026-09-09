"""Evidence authority for the RICK Intelligence reasoning boundary.

The package is deliberately independent from applications, retrieval
backends, providers, and Professor orchestration.  A caller supplies an
authorized scope and a retrieval candidate; this package issues a new
server-owned identifier and validates the resulting evidence before it can be
passed to a decision layer.
"""

from rick_evidence.models import (
    EVIDENCE_BUNDLE_CONTRACT_VERSION,
    EVIDENCE_CONTRACT_VERSION,
    Evidence,
    EvidenceBundle,
    EvidenceScope,
    server_bundle_id,
    server_evidence_id,
)
from rick_evidence.validator import (
    ClaimSupportReport,
    CitationValidationReport,
    EvidenceValidationError,
    EvidenceValidationReport,
    EvidenceValidator,
)

__all__ = [
    "ClaimSupportReport",
    "CitationValidationReport",
    "EVIDENCE_BUNDLE_CONTRACT_VERSION",
    "EVIDENCE_CONTRACT_VERSION",
    "Evidence",
    "EvidenceBundle",
    "EvidenceScope",
    "EvidenceValidationError",
    "EvidenceValidationReport",
    "EvidenceValidator",
    "server_bundle_id",
    "server_evidence_id",
]
