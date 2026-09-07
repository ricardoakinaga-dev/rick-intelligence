"""Root Professor backend adapter for the canonical chat service.

This module is the only API-facing adapter between the root orchestration
package and HTTP.  It does not reimplement retrieval, citation validation, or
provider retry policy.
"""

from __future__ import annotations

from collections.abc import Sequence

from rick_contracts.chat import Citation
from rick_contracts.professor import ProfessorRequest
from rick_contracts.providers import ChatCompletionResult, ProviderMessage
from rick_contracts.security import RetrievalContext
from rick_professor import ProfessorLimits, ProfessorOrchestrator


class ProfessorBackendError(Exception):
    """Safe API-adapter failure with a stable stage only."""

    _ALLOWED = {"lease_unavailable", "lease_lost", "retrieval_failed", "provider_failed", "citation_invalid"}

    def __init__(self, stage: str) -> None:
        self.stage = stage if stage in self._ALLOWED else "provider_failed"
        super().__init__(self.stage)


class ProviderChatAdapter:
    """Adapt the typed provider client to Professor's `complete` port."""

    def __init__(self, provider) -> None:
        self.provider = provider

    async def complete(
        self, *, messages: Sequence[ProviderMessage], conversation_id: str
    ) -> ChatCompletionResult:
        correlation_id = f"chat-{conversation_id}"[:128]
        return await self.provider.chat_completion(
            messages=messages,
            correlation_id=correlation_id,
        )


class OwnedLeaseAdapter:
    """Expose the Professor owner-token port over a root LeaseClient.

    `LeaseClient.acquire()` intentionally generates its own owner token for
    high-level callers. Professor already owns a per-run token, so this seam
    uses the client's validated low-level owner-bound operations instead.
    """

    def __init__(self, client) -> None:
        self.client = client

    async def acquire(self, *, key: str, owner: str, ttl_ms: int) -> dict[str, bool]:
        acquired = await self.client.acquire_owned(key, owner, ttl_ms)
        return {"acquired": acquired}

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> dict[str, bool]:
        renewed = await self.client.renew_owned(key, owner, ttl_ms)
        return {"renewed": renewed}

    async def release(self, *, key: str, owner: str) -> dict[str, bool]:
        released = await self.client.release_owned(key, owner)
        return {"released": released}


class ProfessorChatBackend:
    """ChatBackend implementation backed by root retrieval + Professor."""

    provider_kind = "professor"

    def __init__(self, *, retrieval, provider, lease=None, limits: ProfessorLimits | None = None) -> None:
        self.retrieval = retrieval
        self.provider = ProviderChatAdapter(provider)
        self.lease = OwnedLeaseAdapter(lease) if lease is not None else None
        self.orchestrator = ProfessorOrchestrator(
            retrieval=retrieval,
            chat_provider=self.provider,
            lease_manager=self.lease,
            limits=limits,
        )

    async def generate(self, *, message: str, context: dict, conversation_id: str) -> dict:
        request = ProfessorRequest(
            query=message,
            conversation_id=conversation_id,
            retrieval_context=RetrievalContext.model_validate(context),
        )
        result = await self.orchestrator.run(request)
        if result.evidence_status == "GENERATION_FAILED":
            raise ProfessorBackendError(str(result.metadata.get("failure_stage", "provider_failed")))
        if result.evidence_status == "CITATION_INVALID":
            raise ProfessorBackendError("citation_invalid")
        return {
            "answer": result.answer,
            "citations": [c.model_dump(mode="json") for c in result.citations],
            "metadata": {
                "backend": "professor",
                "evidence_status": result.evidence_status,
                **result.metadata,
            },
        }
