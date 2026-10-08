"""Server-owned, deliberately narrow request classification.

This policy is a technical non-clinical allowlist, not a clinical classifier.
Whole-request matches are intentional: adding an unreviewed clause cannot
inherit permission from an otherwise harmless question. No retrieval result,
caller risk label, model, or external service participates in classification.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from rick_decision.contracts import DomainRisk, IntentClarity, UserIntent


REQUEST_POLICY_VERSION = "rick-nonclinical-request-v1"
CLINICAL_REQUEST_POLICY_VERSION = "rick-clinical-domain-v1"
_VERSION = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class RequestClassification:
    policy_version: str
    reason_code: str
    domain_risk: DomainRisk = DomainRisk.UNKNOWN
    intent: UserIntent = UserIntent()
    allows_answer: bool = False
    human_review_required: bool = False
    retry_query: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.policy_version, str) or not _VERSION.fullmatch(self.policy_version):
            raise ValueError("invalid request policy version")
        if not isinstance(self.reason_code, str) or not _CODE.fullmatch(self.reason_code):
            raise ValueError("invalid request policy reason")
        if not isinstance(self.domain_risk, DomainRisk) or not isinstance(self.intent, UserIntent):
            raise ValueError("invalid request classification")
        if type(self.allows_answer) is not bool or type(self.human_review_required) is not bool:
            raise ValueError("invalid answer/review permission")
        if self.allows_answer and (
            self.domain_risk is not DomainRisk.LOW or self.intent.clarity is not IntentClarity.CLEAR
        ):
            raise ValueError("only explicit low-risk clear intent is answerable")
        if self.retry_query is not None and (
            not isinstance(self.retry_query, str) or not 1 <= len(self.retry_query) <= 512
        ):
            raise ValueError("invalid retry query")

    def metadata(self) -> dict[str, str | bool]:
        return {
            "request_policy_version": self.policy_version,
            "request_policy_reason": self.reason_code,
            "request_domain_risk": self.domain_risk.value,
            "request_intent": self.intent.intent_code,
            "request_intent_clarity": self.intent.clarity.value,
            "request_policy_allows_answer": self.allows_answer,
            "request_policy_human_review_required": self.human_review_required,
            "domain_acceptance": (
                "clinical_broad_intake_human_review" if self.human_review_required
                else "nonclinical_technical_only"
            ),
        }


class RequestClassifier(Protocol):
    def classify(self, query: str, *, history: Sequence[str] = ()) -> RequestClassification: ...


@dataclass(frozen=True, slots=True)
class _InformationalRule:
    intent: str
    questions: frozenset[str]
    retry_query: str


# Finite, reviewable sentences; normalization handles case, accents, whitespace
# and a terminal question mark only. Do not change these to substring matches.
_INFORMATIONAL_RULES = (
    _InformationalRule(
        "document_upload_help",
        frozenset({
            "how do i upload a document", "how can i upload a document",
            "how do i upload a document in rick", "how do i upload a pdf",
            "como enviar um documento", "como enviar um documento no rick",
            "como faco upload de um documento", "como fazer upload de um documento",
        }),
        "document upload enviar documento arquivo colecao rick",
    ),
    _InformationalRule(
        "source_citation_help",
        frozenset({
            "how do i cite sources", "how do citations work in rick",
            "what are source citations", "como citar fontes",
            "como funcionam as citacoes no rick", "o que sao citacoes de fontes",
        }),
        "source citations references fontes citacoes documentos rick",
    ),
    _InformationalRule(
        "collection_help",
        frozenset({
            "what is a document collection", "how do document collections work",
            "what is a collection in rick", "o que e uma colecao de documentos",
            "como funcionam as colecoes de documentos", "o que e uma colecao no rick",
        }),
        "document collections organize colecao documentos organizacao rick",
    ),
    _InformationalRule(
        "document_retry_help",
        frozenset({
            "how do i retry a failed document upload", "how do i check document ingestion status",
            "como repetir um upload de documento que falhou", "como consultar o status de ingestao de um documento",
        }),
        "document upload retry ingestion status repetir envio documento falhou rick",
    ),
)
_AMBIGUOUS = frozenset({"document", "documento", "upload", "collection", "colecao", "help with documents", "ajuda com documentos"})
_UNSUPPORTED = frozenset({"tell me a joke", "conte uma piada", "write a poem", "escreva um poema"})
_CLINICAL = re.compile(
    r"\b(?:clinical|clinico\w*|clinica\w*|patient\w*|paciente\w*|diagnos\w*|"
    r"dose\w*|dosage\w*|dosagem|prescrib\w*|prescrev\w*|treat\w*|tratamento\w*|"
    r"medicat\w*|medicamento\w*|anest\w*|eutana\w*|euthana\w*|"
    r"emergency|emergencia\w*|bleeding|sangramento|intoxica\w*|poison\w*|"
    r"vomit\w*|pain|symptom\w*|sintoma\w*|vacin\w*|vaccin\w*|"
    r"cao|caes|gato\w*|dog\w*|cat|cats)\b|\bmg\s*/\s*kg\b"
)
_INJECTION = re.compile(
    r"\b(?:ignore|disregard|override|bypass|jailbreak|finja|desconsidere)\b|"
    r"system\s+(?:prompt|message)|(?:prompt|mensagem)\s+(?:de|do)\s+sistema|"
    r"(?:risk|risco)\s*[:=]\s*(?:low|baixo)|<\|(?:system|assistant)|```"
)


def _normalize(text: str) -> str | None:
    if not isinstance(text, str) or not 1 <= len(text) <= 4_000:
        return None
    # Do not erase hidden instructions or format/bidi controls to obtain an
    # allowed question. Ordinary whitespace is the only permitted control.
    if any(unicodedata.category(char).startswith("C") and char not in "\t\r\n" for char in text):
        return None
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    return " ".join(normalized.split()).removesuffix("?").strip()


class NonClinicalRequestPolicy:
    """Version one permits only standalone product-information questions.

    Unknown and contextual requests do not inherit a LOW classification.
    Risk indicators aid conservative denial; they never authorize a request.
    """

    def __init__(self, *, version: str | None = REQUEST_POLICY_VERSION) -> None:
        self.version = version

    def classify(self, query: str, *, history: Sequence[str] = ()) -> RequestClassification:
        if self.version != REQUEST_POLICY_VERSION:
            return RequestClassification("unavailable", "request_policy_unavailable")
        text = _normalize(query)
        if text is None:
            return RequestClassification(REQUEST_POLICY_VERSION, "request_outside_policy")
        if not isinstance(history, (list, tuple)) or len(history) > 50:
            return RequestClassification(REQUEST_POLICY_VERSION, "history_outside_policy")
        prior = [_normalize(item) for item in history]
        if any(item is None for item in prior):
            return RequestClassification(REQUEST_POLICY_VERSION, "history_outside_policy")
        for item in [text, *prior]:
            if _INJECTION.search(item):
                return RequestClassification(REQUEST_POLICY_VERSION, "instruction_override_attempt", DomainRisk.HIGH)
            if _CLINICAL.search(item):
                return RequestClassification(REQUEST_POLICY_VERSION, "clinical_review_required", DomainRisk.HIGH)
        if prior:
            return RequestClassification(REQUEST_POLICY_VERSION, "contextual_request_unreviewed")
        if text in _AMBIGUOUS:
            return RequestClassification(
                REQUEST_POLICY_VERSION, "nonclinical_intent_ambiguous", DomainRisk.LOW,
                UserIntent(intent_code="product_help", clarity=IntentClarity.AMBIGUOUS),
            )
        if text in _UNSUPPORTED:
            return RequestClassification(
                REQUEST_POLICY_VERSION, "intent_outside_product_scope", DomainRisk.LOW,
                UserIntent(intent_code="unsupported", clarity=IntentClarity.UNSUPPORTED),
            )
        for rule in _INFORMATIONAL_RULES:
            if text in rule.questions:
                return RequestClassification(
                    REQUEST_POLICY_VERSION, "nonclinical_information_allowlisted", DomainRisk.LOW,
                    UserIntent(intent_code=rule.intent, clarity=IntentClarity.CLEAR),
                    allows_answer=True, retry_query=rule.retry_query,
                )
        return RequestClassification(REQUEST_POLICY_VERSION, "request_unrecognized")


class ClinicalDomainPolicy:
    """Broad clinical intake with mandatory human review before answering.

    D04 authorizes the clinical domain to enter the canonical workflow, but it
    does not authorize autonomous clinical advice. Clinical requests are
    classified explicitly and marked for human review; the decision layer
    therefore returns ESCALATE before provider generation. Product-help
    questions retain the reviewed low-risk allowlist of the base policy.
    """

    def __init__(self) -> None:
        self._base = NonClinicalRequestPolicy()

    def classify(self, query: str, *, history: Sequence[str] = ()) -> RequestClassification:
        result = self._base.classify(query, history=history)
        if result.reason_code == "clinical_review_required":
            return RequestClassification(
                CLINICAL_REQUEST_POLICY_VERSION,
                "clinical_domain_review_required",
                DomainRisk.HIGH,
                result.intent,
                allows_answer=False,
                human_review_required=True,
                retry_query=result.retry_query,
            )
        return RequestClassification(
            CLINICAL_REQUEST_POLICY_VERSION,
            result.reason_code,
            result.domain_risk,
            result.intent,
            result.allows_answer,
            result.human_review_required,
            result.retry_query,
        )


def classify_request(
    classifier: RequestClassifier | None,
    query: str,
    *,
    history: Sequence[str] = (),
) -> RequestClassification:
    """Fail closed when server composition omits or breaks its classifier."""
    if classifier is None:
        return RequestClassification("unavailable", "request_policy_unavailable")
    try:
        result = classifier.classify(query, history=history)
        if not isinstance(result, RequestClassification):
            raise TypeError("classifier returned an invalid result")
        return result
    except Exception:
        # Safe metadata must not contain exceptions or untrusted query text.
        return RequestClassification("unavailable", "request_classifier_failed")
