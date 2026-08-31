"""
Evaluation Service — structured evaluation with LLM Judge (triagem) + human review.
LLM Judge is used ONLY for triage — human review is the final verdict.
"""
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from models.schemas import EvaluationResult, EvaluationResponse, VariantResult, ABEvaluationResponse, ChunkingVariantResult, ChunkingABResponse, QueryExpansionVariantResult, QueryExpansionABResponse
from core.config import DATASETS_DIR, DATA_DIR, EMBEDDING_DIM


def _embedding_is_valid(emb: object) -> bool:
    """Return True if emb is a list of EMBEDDING_DIM floats."""
    return (
        isinstance(emb, list)
        and len(emb) == EMBEDDING_DIM
        and all(isinstance(x, (int, float)) for x in emb)
    )


def _ensure_backup_has_embeddings(chunks: list[dict], workspace_id: str) -> list[dict]:
    """
    Ensure the backup chunks list has a valid embedding field in every chunk.

    Uses the same validation as _restore_embeddings_if_needed:
      - Fast path: all chunks already have valid embeddings → return unchanged
      - Qdrant path: read from Qdrant by chunk_id, validate each before injecting;
        embeddings that fail validation are treated as "not found"
      - If Qdrant unavailable: return chunks as-is (backup lacks embeddings;
        restoration will fall back to API or zeros — unavoidable without Qdrant)

    This guarantees that backups created before embeddings were stored in the chunks
    file are still restorable offline (without API) as long as Qdrant is available,
    and that invalid embeddings from Qdrant do not corrupt the backup.
    """
    if not chunks:
        return chunks

    # Fast path: all chunks already have valid embeddings (same rule as restore)
    if all(_embedding_is_valid(c.get("embedding")) for c in chunks):
        return chunks

    # Try to read from Qdrant using chunk_ids
    chunk_ids = [c.get("chunk_id") for c in chunks if c.get("chunk_id")]
    if not chunk_ids:
        return chunks

    try:
        from services.vector_service import get_client, QDRANT_COLLECTION
        client = get_client()
        point_ids = [abs(hash(cid)) % (2**63) for cid in chunk_ids]
        records = client.retrieve(
            collection_name=QDRANT_COLLECTION,
            ids=point_ids,
            with_vectors=True,
        )
        # Build chunk_id → embedding map, only for VALID embeddings
        emb_map: dict[str, list[float]] = {}
        for record in records:
            payload = record.payload or {}
            chunk_id = payload.get("chunk_id")
            dense_vec = record.vector.get("dense") if record.vector else None
            if chunk_id and dense_vec is not None and _embedding_is_valid(dense_vec):
                emb_map[chunk_id] = dense_vec

        # Inject valid embeddings into chunks that are missing or have invalid ones.
        # This ensures the backup is self-contained even when the chunks file
        # had invalid (wrong-dimension, wrong-type) embeddings.
        for c in chunks:
            chunk_id = c.get("chunk_id")
            has_valid = _embedding_is_valid(c.get("embedding"))
            if chunk_id in emb_map and not has_valid:
                c["embedding"] = emb_map[chunk_id]
    except Exception:
        # Qdrant unavailable during backup creation — backup will lack embeddings.
        # Restore will fall back to API or zeros. This is unavoidable without Qdrant.
        pass

    return chunks


# ── LLM Judge ─────────────────────────────────────────────────────────────

LLM_JUDGE_PROMPT = """Você é um avaliador de qualidade de respostas de RAG.

Contexto recuperado:
{context}

Pergunta do usuário:
{query}

Resposta gerada:
{answer}

Avalie:
1. A resposta está fundamentada no contexto? (groundedness: yes/parcial/no)
2. A resposta responde a pergunta? (relevance: high/medium/low)
3. Há alucinação? (hallucination: none/minor/major)

Dê um score de 0 a 1 para a qualidade geral.
Justifique em 1-2 frases.

Responda no formato:
score: X.XX
groundedness: yes/parcial/no
relevance: high/medium/low
hallucination: none/minor/major
justificativa: ..."""


def llm_judge(query: str, context_texts: list[str], answer: str) -> dict:
    """
    Use LLM to score a query-answer pair for triage purposes.
    Returns a dict with score, groundedness, relevance, hallucination, justification.
    """
    if not context_texts:
        return {
            "score": 0.0,
            "groundedness": "no",
            "relevance": "low",
            "hallucination": "major",
            "justificativa": "Sem contexto recuperado",
            "needs_review": True,
        }

    context_combined = "\n---\n".join(context_texts[:5])
    prompt = LLM_JUDGE_PROMPT.format(
        context=context_combined,
        query=query,
        answer=answer,
    )

    try:
        response_text, _, _ = generate_answer(prompt, [{"text": context_combined, "chunk_id": "judge"}])
        # Parse the response
        lines = response_text.strip().split("\n")
        result = {
            "score": 0.5,
            "groundedness": "parcial",
            "relevance": "medium",
            "hallucination": "none",
            "justificativa": response_text[:200],
            "needs_review": True,
        }
        for line in lines:
            line = line.strip().lower()
            if line.startswith("score:"):
                try:
                    result["score"] = float(line.split(":")[1].strip())
                except (IndexError, ValueError):
                    pass
            elif line.startswith("groundedness:"):
                val = line.split(":")[1].strip()
                result["groundedness"] = val
            elif line.startswith("relevance:"):
                result["relevance"] = line.split(":")[1].strip()
            elif line.startswith("hallucination:"):
                result["hallucination"] = line.split(":")[1].strip()
            elif line.startswith("justificativa:"):
                result["justificativa"] = line.split(":", 1)[1].strip()

        # Flag for review if score < 0.80
        result["needs_review"] = result["score"] < 0.80
        return result

    except Exception as e:
        return {
            "score": 0.0,
            "groundedness": "unknown",
            "relevance": "unknown",
            "hallucination": "unknown",
            "justificativa": f"Erro no judge: {e}",
            "needs_review": True,
        }


# ── Evaluation Runner ──────────────────────────────────────────────────────

class EvaluationService:
    """
    Runs structured evaluation on a dataset:
    1. For each question: retrieve + generate answer
    2. Run LLM Judge for triage
    3. Flag low-score answers for human review
    4. Log results for later analysis
    """

    def __init__(self):
        self.telemetry = None  # Imported lazily to avoid circular

    def run_evaluation(
        self,
        workspace_id: str,
        dataset_path: Path,
        top_k: int = 5,
        run_judge: bool = True,
        reranking: bool | None = None,
        reranking_method: str | None = None,
        save_results: bool = True,
        query_expansion: bool | None = None,
    ) -> EvaluationResponse:
        """
        Run full evaluation on a dataset.
        Returns aggregated results and per-question details.
        """
        dataset_path = self._resolve_dataset_path(dataset_path)
        from core.config import RERANKING_METHOD
        effective_method = reranking_method if reranking_method else RERANKING_METHOD

        # Load dataset
        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)
        questions = dataset["questions"]
        dataset_threshold = float(dataset.get("retrieval_threshold", 0.70) or 0.70)

        total = len(questions)
        hits_at_1 = 0
        hits_at_3 = 0
        hits_at_5 = 0
        judged_total = 0
        judge_scores = []
        top_scores = []
        low_confidence_count = 0
        retrieval_low_confidence_count = 0
        grounded_count = 0
        judge_grounded_count = 0
        judge_needs_review_count = 0
        total_latency = 0

        question_results = []
        flagged_for_review = []

        evaluation_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        from models.schemas import QueryRequest
        from services.search_service import search_and_answer

        by_difficulty_counts = {}
        by_difficulty_hits = {}
        by_category_counts = {}
        by_category_hits = {}

        for q in questions:
            q_id = q["id"]
            pergunta = q["pergunta"]
            expected_doc = q.get("document_id", "")
            question_workspace_id = q.get("workspace_id") or workspace_id
            question_threshold = float(q.get("threshold", dataset_threshold) or dataset_threshold)
            difficulty = q.get("dificuldade", "medium")
            category = q.get("categoria", "procedimento")

            query_req = QueryRequest(
                query=pergunta,
                workspace_id=question_workspace_id,
                top_k=top_k,
                threshold=question_threshold,
                reranking=reranking,
                reranking_method=reranking_method,
                query_expansion=q.get("query_expansion") if q.get("query_expansion") is not None else query_expansion,
            )
            answer_resp = search_and_answer(query_req)

            retrieval_payload = answer_resp.retrieval or {}
            retrieval_results = retrieval_payload.get("results", [])
            retrieved_docs = [r.get("document_id") for r in retrieval_results if r.get("document_id")]
            top_score = retrieval_results[0].get("score", 0.0) if retrieval_results else 0.0
            top_scores.append(top_score)
            hit_at_1 = len(retrieved_docs) > 0 and retrieved_docs[0] == expected_doc
            hit_at_5 = expected_doc in retrieved_docs
            hits_at_1 += 1 if hit_at_1 else 0
            hits_at_5 += 1 if hit_at_5 else 0
            hits_at_3 += 1 if expected_doc in retrieved_docs[:3] else 0
            best_score_rank = None
            if expected_doc in retrieved_docs:
                best_score_rank = retrieved_docs.index(expected_doc) + 1

            by_difficulty_counts[difficulty] = by_difficulty_counts.get(difficulty, 0) + 1
            by_difficulty_hits[difficulty] = by_difficulty_hits.get(difficulty, 0) + (1 if hit_at_5 else 0)
            by_category_counts[category] = by_category_counts.get(category, 0) + 1
            by_category_hits[category] = by_category_hits.get(category, 0) + (1 if hit_at_5 else 0)

            judge_result = None
            if run_judge and retrieval_results:
                context_texts = [result.get("text", "") for result in retrieval_results if result.get("text")]
                judge_result = llm_judge(pergunta, context_texts, answer_resp.answer)
                judge_scores.append(judge_result["score"])
                judged_total += 1
                if judge_result.get("groundedness") == "yes":
                    judge_grounded_count += 1
                if judge_result["needs_review"]:
                    judge_needs_review_count += 1
                    flagged_for_review.append({
                        "question_id": q_id,
                        "pergunta": pergunta,
                        "answer": answer_resp.answer,
                        "score": judge_result["score"],
                        "reason": judge_result["justificativa"],
                    })

            retrieval_low_confidence = bool(
                retrieval_payload.get("retrieval_low_confidence", answer_resp.low_confidence)
            )

            if answer_resp.grounded:
                grounded_count += 1
            if answer_resp.low_confidence:
                low_confidence_count += 1
            if retrieval_low_confidence:
                retrieval_low_confidence_count += 1
            total_latency += answer_resp.latency_ms or retrieval_payload.get("retrieval_time_ms", 0) or 0

            needs_review = bool(judge_result["needs_review"]) if judge_result else bool(
                answer_resp.grounding.needs_review if answer_resp.grounding else False
            )
            if needs_review and not judge_result:
                flagged_for_review.append({
                    "question_id": q_id,
                    "pergunta": pergunta,
                    "answer": answer_resp.answer,
                    "score": None,
                    "reason": answer_resp.grounding.reason if answer_resp.grounding else "needs_review",
                })

            question_results.append({
                "question_id": str(q_id),
                "pergunta": pergunta,
                "hit_top_1": hit_at_1,
                "hit_top_3": expected_doc in retrieved_docs[:3],
                "hit_top_5": hit_at_5,
                "retrieved_documents": retrieved_docs[:3],
                "correct_document_id": expected_doc,
                "best_score": top_score,
                "best_score_rank": best_score_rank,
                "judge_score": judge_result["score"] if judge_result else None,
                "grounded": bool(answer_resp.grounded),
                "citation_coverage": float(answer_resp.citation_coverage or 0.0),
                "low_confidence": bool(answer_resp.low_confidence),
                "retrieval_low_confidence": retrieval_low_confidence,
                "judge_groundedness": judge_result.get("groundedness") if judge_result else None,
                "needs_review": needs_review,
                "reranking_applied": answer_resp.retrieval.get("reranking_applied", False) if answer_resp.retrieval else False,
                "reranking_method": answer_resp.retrieval.get("reranking_method") if answer_resp.retrieval else None,
            })

        duration = time.time() - start_time
        avg_latency = total_latency / total if total > 0 else 0

        # Compute aggregates
        hr1 = hits_at_1 / total if total > 0 else 0.0
        hr3 = hits_at_3 / total if total > 0 else 0.0
        hr5 = hits_at_5 / total if total > 0 else 0.0
        avg_score = sum(top_scores) / len(top_scores) if top_scores else 0.0
        avg_judge_score = sum(judge_scores) / len(judge_scores) if judge_scores else 0.0
        low_conf_rate = low_confidence_count / total if total > 0 else 0.0
        retrieval_low_conf_rate = retrieval_low_confidence_count / total if total > 0 else 0.0
        grounded_rate = grounded_count / total if total > 0 else 0.0
        judge_grounded_rate = (judge_grounded_count / judged_total) if judged_total > 0 else None
        judge_review_rate = (judge_needs_review_count / judged_total) if judged_total > 0 else None
        by_difficulty = {
            key: {
                "count": by_difficulty_counts[key],
                "hit_rate_top5": round(by_difficulty_hits.get(key, 0) / by_difficulty_counts[key], 4),
            }
            for key in sorted(by_difficulty_counts)
        }
        by_category = {
            key: {
                "count": by_category_counts[key],
                "hit_rate_top5": round(by_category_hits.get(key, 0) / by_category_counts[key], 4),
            }
            for key in sorted(by_category_counts)
        }

        from core.config import RERANKING_METHOD

        result = EvaluationResponse(
            evaluation_id=evaluation_id,
            workspace_id=workspace_id,
            total_questions=total,
            hit_rate_top_1=hr1,
            hit_rate_top_3=hr3,
            hit_rate_top_5=hr5,
            avg_latency_ms=avg_latency,
            avg_score=avg_score,
            low_confidence_rate=low_conf_rate,
            retrieval_low_confidence_rate=retrieval_low_conf_rate,
            groundedness_rate=grounded_rate,
            observed_groundedness_rate=grounded_rate,
            judge_score=avg_judge_score if run_judge else None,
            judged_questions=judged_total,
            judge_groundedness_rate=judge_grounded_rate if run_judge else None,
            judge_needs_review_rate=judge_review_rate if run_judge else None,
            flagged_for_review_count=len(flagged_for_review),
            duration_seconds=duration,
            by_difficulty=by_difficulty,
            by_category=by_category,
            question_results=question_results,
            reranking_applied=reranking is True,
            reranking_method=effective_method if reranking is True else None,
        )

        # Log to telemetry
        try:
            from services.telemetry_service import get_telemetry
            tel = get_telemetry()
            tel.log_evaluation(
                evaluation_id=evaluation_id,
                workspace_id=workspace_id,
                total_questions=total,
                hit_at_1=hr1,
                hit_at_3=hr3,
                hit_at_5=hr5,
                avg_latency_ms=avg_latency,
                avg_score=avg_score,
                low_confidence_rate=low_conf_rate,
                groundedness_rate=grounded_rate,
                duration_seconds=duration,
                reranking_applied=reranking is True,
                reranking_method=effective_method if reranking is True else None,
            )
        except Exception:
            pass  # Non-fatal

        return result

    def _resolve_dataset_path(self, dataset_path: Path) -> Path:
        """
        Resolve dataset paths passed from tests, CLI, or API callers.

        The suite sometimes passes a path relative to the repository root
        (for example `src/data/default/dataset.json`) while running from the
        `src/` directory. To keep the runner resilient, accept the provided
        path first and then try a few canonical fallbacks.
        """
        if dataset_path.exists():
            return dataset_path

        candidates = []
        try:
            from core.config import BASE_DIR, DATA_DIR
            candidates.extend([
                BASE_DIR.parent / dataset_path,
                BASE_DIR / dataset_path,
                DATA_DIR / "default" / "dataset.json",
            ])
        except Exception:
            pass

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return dataset_path

    def run_ab_evaluation(
        self,
        workspace_id: str,
        dataset_path: Path,
        top_k: int = 5,
        run_judge: bool = False,
        variant_method: str = "bm25f",
        query_expansion: bool = False,
    ) -> ABEvaluationResponse:
        """
        Run A/B comparison: baseline (no reranking) vs variant (with specified method).
        Returns structured comparison with deltas.
        """
        dataset_path = self._resolve_dataset_path(dataset_path)

        baseline = self.run_evaluation(
            workspace_id=workspace_id,
            dataset_path=dataset_path,
            top_k=top_k,
            run_judge=run_judge,
            reranking=False,
            save_results=False,
        )

        variant = self.run_evaluation(
            workspace_id=workspace_id,
            dataset_path=dataset_path,
            top_k=top_k,
            run_judge=run_judge,
            reranking=True,
            reranking_method=variant_method,
            save_results=False,
            query_expansion=query_expansion,
        )

        baseline_variant = VariantResult(
            variant_name="baseline",
            reranking_applied=False,
            reranking_method=None,
            query_expansion_applied=False,
            query_expansion_method=None,
            total_questions=baseline.total_questions,
            hit_rate_top_1=baseline.hit_rate_top_1,
            hit_rate_top_3=baseline.hit_rate_top_3,
            hit_rate_top_5=baseline.hit_rate_top_5,
            avg_latency_ms=baseline.avg_latency_ms,
            avg_score=baseline.avg_score,
            low_confidence_rate=baseline.low_confidence_rate,
            judge_score=baseline.judge_score,
            duration_seconds=baseline.duration_seconds,
        )

        variant_variant = VariantResult(
            variant_name="variant",
            reranking_applied=True,
            reranking_method=variant_method,
            query_expansion_applied=query_expansion,
            query_expansion_method="hyde" if query_expansion else None,
            total_questions=variant.total_questions,
            hit_rate_top_1=variant.hit_rate_top_1,
            hit_rate_top_3=variant.hit_rate_top_3,
            hit_rate_top_5=variant.hit_rate_top_5,
            avg_latency_ms=variant.avg_latency_ms,
            avg_score=variant.avg_score,
            low_confidence_rate=variant.low_confidence_rate,
            judge_score=variant.judge_score,
            duration_seconds=variant.duration_seconds,
        )

        delta_hr1 = variant.hit_rate_top_1 - baseline.hit_rate_top_1
        delta_hr3 = variant.hit_rate_top_3 - baseline.hit_rate_top_3
        delta_hr5 = variant.hit_rate_top_5 - baseline.hit_rate_top_5
        delta_latency = variant.avg_latency_ms - baseline.avg_latency_ms
        delta_score = variant.avg_score - baseline.avg_score
        delta_low_conf = variant.low_confidence_rate - baseline.low_confidence_rate

        # Determine winner based on HIT@5 (primary quality metric)
        if delta_hr5 > 0.001:
            winner = "variant"
        elif delta_hr5 < -0.001:
            winner = "baseline"
        else:
            winner = "tie"

        return ABEvaluationResponse(
            evaluation_id=baseline.evaluation_id,
            workspace_id=workspace_id,
            baseline=baseline_variant,
            variant=variant_variant,
            delta_hit_at_1=delta_hr1,
            delta_hit_at_3=delta_hr3,
            delta_hit_at_5=delta_hr5,
            delta_avg_latency_ms=delta_latency,
            delta_avg_score=delta_score,
            delta_low_confidence_rate=delta_low_conf,
            winner=winner,
        )

    def run_query_expansion_ab_evaluation(
        self,
        workspace_id: str,
        dataset_path: Path,
        top_k: int = 5,
        run_judge: bool = False,
    ) -> QueryExpansionABResponse:
        """
        Run A/B comparison: baseline (no query expansion) vs variant (with HyDE expansion).
        Returns structured comparison with deltas.
        """
        dataset_path = self._resolve_dataset_path(dataset_path)

        baseline = self.run_evaluation(
            workspace_id=workspace_id,
            dataset_path=dataset_path,
            top_k=top_k,
            run_judge=run_judge,
            reranking=False,
            save_results=False,
            query_expansion=False,
        )

        variant = self.run_evaluation(
            workspace_id=workspace_id,
            dataset_path=dataset_path,
            top_k=top_k,
            run_judge=run_judge,
            reranking=False,
            save_results=False,
            query_expansion=True,
        )

        baseline_variant = QueryExpansionVariantResult(
            variant_name="baseline",
            query_expansion_applied=False,
            query_expansion_method=None,
            total_questions=baseline.total_questions,
            hit_rate_top_1=baseline.hit_rate_top_1,
            hit_rate_top_3=baseline.hit_rate_top_3,
            hit_rate_top_5=baseline.hit_rate_top_5,
            avg_latency_ms=baseline.avg_latency_ms,
            avg_score=baseline.avg_score,
            low_confidence_rate=baseline.low_confidence_rate,
            judge_score=baseline.judge_score,
            duration_seconds=baseline.duration_seconds,
        )

        variant_variant = QueryExpansionVariantResult(
            variant_name="variant",
            query_expansion_applied=True,
            query_expansion_method="hyde",
            total_questions=variant.total_questions,
            hit_rate_top_1=variant.hit_rate_top_1,
            hit_rate_top_3=variant.hit_rate_top_3,
            hit_rate_top_5=variant.hit_rate_top_5,
            avg_latency_ms=variant.avg_latency_ms,
            avg_score=variant.avg_score,
            low_confidence_rate=variant.low_confidence_rate,
            judge_score=variant.judge_score,
            duration_seconds=variant.duration_seconds,
        )

        delta_hr1 = variant.hit_rate_top_1 - baseline.hit_rate_top_1
        delta_hr3 = variant.hit_rate_top_3 - baseline.hit_rate_top_3
        delta_hr5 = variant.hit_rate_top_5 - baseline.hit_rate_top_5
        delta_latency = variant.avg_latency_ms - baseline.avg_latency_ms
        delta_score = variant.avg_score - baseline.avg_score
        delta_low_conf = variant.low_confidence_rate - baseline.low_confidence_rate

        if delta_hr5 > 0.001:
            winner: str | None = "variant"
        elif delta_hr5 < -0.001:
            winner = "baseline"
        else:
            winner = "tie"

        return QueryExpansionABResponse(
            evaluation_id=baseline.evaluation_id,
            workspace_id=workspace_id,
            baseline=baseline_variant,
            variant=variant_variant,
            delta_hit_at_1=delta_hr1,
            delta_hit_at_3=delta_hr3,
            delta_hit_at_5=delta_hr5,
            delta_avg_latency_ms=delta_latency,
            delta_avg_score=delta_score,
            delta_low_confidence_rate=delta_low_conf,
            winner=winner,
        )

    def run_chunking_ab_evaluation(
        self,
        document_id: str,
        workspace_id: str = "default",
        dataset_path: Path | None = None,
        top_k: int = 5,
        run_judge: bool = False,
    ) -> ChunkingABResponse:
        """
        Run A/B comparison between recursive and semantic chunking for a single document.

        Flow:
        1. Detect original chunking strategy from disk (before any modifications)
        2. Backup current chunks to disk
        3. Run baseline evaluation with recursive chunking
        4. Reindex document with semantic chunking
        5. Run variant evaluation with semantic chunking
        6. Restore corpus to its ORIGINAL strategy (not just recursive)

        corpus_restored=True only when the document ends in its original strategy.

        Parameters:
            document_id: document to evaluate
            workspace_id: workspace containing the document
            dataset_path: optional; defaults to workspace's dataset.json
            top_k: number of results to retrieve per query
            run_judge: whether to run LLM judge

        Returns ChunkingABResponse with structured comparison.
        """
        from core.config import DOCUMENTS_DIR

        if dataset_path is None:
            dataset_path = self._resolve_dataset_path(DATA_DIR / workspace_id / "dataset.json")

        # ── Step 0: Verify document exists ───────────────────────
        doc_dir = DOCUMENTS_DIR / workspace_id
        raw_path = doc_dir / f"{document_id}_raw.json"
        chunks_path = doc_dir / f"{document_id}_chunks.json"
        if not raw_path.exists():
            raise ValueError(f"Raw JSON não encontrado: {raw_path}")

        # ── Detect original strategy BEFORE any modifications ─────
        # Read from disk chunks file to know what the document actually uses
        original_chunks = []
        if chunks_path.exists():
            try:
                with open(chunks_path, encoding="utf-8") as f:
                    original_chunks = json.load(f)
            except Exception:
                original_chunks = []

        original_strategy = (
            original_chunks[0].get("strategy", "recursive")
            if original_chunks
            else "recursive"
        )

        # ── Step 1: Backup current chunks with embeddings from Qdrant ──
        # The chunks file may not contain embeddings (Chunk model has no embedding field).
        # Ensure the backup is self-contained by reading current embeddings from Qdrant.
        backup_chunks = _ensure_backup_has_embeddings(original_chunks, workspace_id)

        backup_path = doc_dir / f"{document_id}_chunks_backup.json"
        backup_exists = backup_path.exists()
        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(backup_chunks, f, ensure_ascii=False)
        except Exception as e:
            raise RuntimeError(f"Falha ao fazer backup dos chunks: {e}")

        from services.ingestion_service import reindex_document
        from services.telemetry_service import get_telemetry

        try:
            # ── Step 2: Baseline evaluation (recursive) ───────────
            baseline_chunks, _, baseline_latency_ms = reindex_document(
                document_id, workspace_id, chunking_strategy="recursive"
            )
            try:
                tel = get_telemetry()
                tel.log_reindex(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    chunking_strategy="recursive",
                    chunk_count=baseline_chunks,
                    processing_time_ms=baseline_latency_ms,
                    embedding_status="regenerated",
                    source="chunking_ab_baseline",
                )
            except Exception:
                pass  # Non-fatal

            baseline_result = self.run_evaluation(
                workspace_id=workspace_id,
                dataset_path=dataset_path,
                top_k=top_k,
                run_judge=run_judge,
                reranking=False,
                save_results=False,
            )
            baseline_chunks_count = len(
                json.load(open(chunks_path, encoding="utf-8"))
            ) if chunks_path.exists() else 0

            baseline_variant = ChunkingVariantResult(
                strategy="recursive",
                chunk_count=baseline_chunks_count,
                hit_rate_top_1=baseline_result.hit_rate_top_1,
                hit_rate_top_3=baseline_result.hit_rate_top_3,
                hit_rate_top_5=baseline_result.hit_rate_top_5,
                avg_latency_ms=baseline_result.avg_latency_ms,
                avg_score=baseline_result.avg_score,
                low_confidence_rate=baseline_result.low_confidence_rate,
                judge_score=baseline_result.judge_score,
                duration_seconds=baseline_result.duration_seconds,
            )

            # ── Step 3: Reindex with semantic ──────────────────────
            variant_chunks, _, variant_latency_ms = reindex_document(
                document_id, workspace_id, chunking_strategy="semantic"
            )
            try:
                tel = get_telemetry()
                tel.log_reindex(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    chunking_strategy="semantic",
                    chunk_count=variant_chunks,
                    processing_time_ms=variant_latency_ms,
                    embedding_status="regenerated",
                    source="chunking_ab_variant",
                )
            except Exception:
                pass  # Non-fatal

            # ── Step 4: Variant evaluation (semantic) ──────────────
            variant_result = self.run_evaluation(
                workspace_id=workspace_id,
                dataset_path=dataset_path,
                top_k=top_k,
                run_judge=run_judge,
                reranking=False,
                save_results=False,
            )
            variant_chunks_count = len(
                json.load(open(chunks_path, encoding="utf-8"))
            ) if chunks_path.exists() else 0

            variant_variant = ChunkingVariantResult(
                strategy="semantic",
                chunk_count=variant_chunks_count,
                hit_rate_top_1=variant_result.hit_rate_top_1,
                hit_rate_top_3=variant_result.hit_rate_top_3,
                hit_rate_top_5=variant_result.hit_rate_top_5,
                avg_latency_ms=variant_result.avg_latency_ms,
                avg_score=variant_result.avg_score,
                low_confidence_rate=variant_result.low_confidence_rate,
                judge_score=variant_result.judge_score,
                duration_seconds=variant_result.duration_seconds,
            )

            # ── Step 5: Restore from BACKUP (faithful restoration) ──
            # Restore the EXACT chunks that existed before the A/B test.
            # This uses the backup as canonical source — not re-chunking from raw,
            # which could produce different chunks (especially for semantic strategy).
            # Qdrant is restored via reindex_document, which regenerates embeddings
            # if the backup didn't store them (ensures valid vectors, not zeros).
            import shutil as _shutil
            _shutil.copy2(backup_path, chunks_path)  # Restore file from backup
            _, embedding_status, restore_latency_ms = reindex_document(
                document_id, workspace_id, chunks=original_chunks
            )  # Restore Qdrant + write embeddings to file; return (count, status, latency)
            try:
                tel = get_telemetry()
                tel.log_reindex(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    chunking_strategy=original_strategy,
                    chunk_count=len(original_chunks),
                    processing_time_ms=restore_latency_ms,
                    embedding_status=embedding_status,
                    source="chunking_ab_restore",
                )
            except Exception:
                pass  # Non-fatal

            # Verify: disk should match the original in the fields that matter for retrieval
            # (text, strategy, chunk_ids). The embedding field may differ if we had to
            # regenerate it, but Qdrant now has valid vectors so retrieval works correctly.
            try:
                with open(chunks_path, encoding="utf-8") as f:
                    restored_disk = json.load(f)
            except Exception:
                restored_disk = None

            if restored_disk and original_chunks:
                # Compare semantic fields; ignore 'embedding' (may have been regenerated)
                def _semantic_eq(a, b):
                    return (
                        a.get("chunk_id") == b.get("chunk_id")
                        and a.get("text") == b.get("text")
                        and a.get("strategy") == b.get("strategy")
                        and a.get("chunk_index") == b.get("chunk_index")
                    )
                corpus_restored = (
                    len(restored_disk) == len(original_chunks)
                    and all(_semantic_eq(r, o) for r, o in zip(restored_disk, original_chunks))
                )
            else:
                corpus_restored = False

        except Exception as e:
            # Attempt faithful restoration from backup
            try:
                import shutil as _shutil
                if backup_path.exists():
                    _shutil.copy2(backup_path, chunks_path)
                    reindex_document(document_id, workspace_id, chunks=original_chunks)
            except Exception:
                pass
            raise RuntimeError(f"Erro durante chunking A/B: {e}")

        finally:
            # Remove backup file
            try:
                if not backup_exists:
                    backup_path.unlink(missing_ok=True)
            except Exception:
                pass

        # Deltas
        delta_hr1 = variant_result.hit_rate_top_1 - baseline_result.hit_rate_top_1
        delta_hr3 = variant_result.hit_rate_top_3 - baseline_result.hit_rate_top_3
        delta_hr5 = variant_result.hit_rate_top_5 - baseline_result.hit_rate_top_5
        delta_latency = variant_result.avg_latency_ms - baseline_result.avg_latency_ms
        delta_score = variant_result.avg_score - baseline_result.avg_score
        delta_low_conf = variant_result.low_confidence_rate - baseline_result.low_confidence_rate

        # Determine winner based on HIT@5
        if delta_hr5 > 0.001:
            winner: str | None = "variant"
        elif delta_hr5 < -0.001:
            winner = "baseline"
        else:
            winner = "tie"

        evaluation_id = baseline_result.evaluation_id

        # Log chunking A/B telemetry with embedding status
        try:
            from services.telemetry_service import get_telemetry
            tel = get_telemetry()
            tel.log_evaluation(
                evaluation_id=evaluation_id,
                workspace_id=workspace_id,
                total_questions=baseline_result.total_questions,
                hit_at_1=baseline_result.hit_rate_top_1,
                hit_at_3=baseline_result.hit_rate_top_3,
                hit_at_5=baseline_result.hit_rate_top_5,
                avg_latency_ms=baseline_result.avg_latency_ms,
                avg_score=baseline_result.avg_score,
                low_confidence_rate=baseline_result.low_confidence_rate,
                groundedness_rate=baseline_result.groundedness_rate,
                duration_seconds=baseline_result.duration_seconds,
                embedding_status=embedding_status,
            )
        except Exception:
            pass  # Non-fatal

        return ChunkingABResponse(
            evaluation_id=evaluation_id,
            workspace_id=workspace_id,
            document_id=document_id,
            baseline=baseline_variant,
            variant=variant_variant,
            delta_hit_at_1=delta_hr1,
            delta_hit_at_3=delta_hr3,
            delta_hit_at_5=delta_hr5,
            delta_avg_latency_ms=delta_latency,
            delta_avg_score=delta_score,
            delta_low_confidence_rate=delta_low_conf,
            winner=winner,
            corpus_restored=corpus_restored,
            embedding_status=embedding_status,
        )
