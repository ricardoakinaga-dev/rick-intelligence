"""
LLM Judge Service — Triagem de respostas para revisão humana.

Este módulo implementa o Judge como FERRAMENTA DE TRIAGEM, não como veredicto final.
Respostas com low confidence ou judge_score < threshold são marcados para revisão humana.

Contraste com abordagem errada:
  ❌ "LLM Judge decide se a resposta é válida" (viés estrutural)
  ✅ "LLM Judge triagem quais respostas precisam de validação humana"

Ref: 0016-backlog-priorizado.md (P1 - REPROJETAR)
     0011-contratos-de-avaliacao.md (Contrato 4: Judge Result)
"""
import os
import time
from typing import Literal
from openai import OpenAI

from core.config import LLM_MODEL


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


# Threshold para triagem — abaixo disso, marca para revisão humana
DEFAULT_THRESHOLD = 0.70


JUDGE_PROMPT_VERSION = "v1"


SYSTEM_PROMPT = """Você é um avaliador de qualidade de respostas geradas por RAG.
Sua tarefa é fazer TRIAGEM — identificar quais respostas precisam de revisão humana.

Critérios de avaliação:
1. GROUNDEDNESS - A resposta está fundamentada no contexto fornecido?
2. RELEVANCE - A resposta é relevante para a pergunta?
3. HALLUCINATION - A resposta contém informação não presente no contexto?

Responda APENAS com um JSON válido, sem explicações adicionais."""


USER_PROMPT_TEMPLATE = """Contexto recuperado:
{context}

Pergunta: {query}

Resposta gerada: {answer}

Avalie a resposta e retorne o seguinte JSON:
{{
  "groundedness": "yes|partial|no",
  "relevance": "high|medium|low",
  "hallucination": "none|minor|major",
  "overall_score": 0.0-1.0,
  "justification": "Breve justificativa da avaliação",
  "needs_human_review": true|false
}}

Regras:
- needs_human_review = true se overall_score < 0.70 OU hallucination = "major" OU groundedness = "no" OU relevance = "low"
- Justificativa deve ter 20-100 caracteres"""


def judge_answer(
    query: str,
    answer: str,
    chunks: list[dict],
    threshold: float = DEFAULT_THRESHOLD,
    model: str = LLM_MODEL
) -> dict:
    """
    Avalia uma resposta gerada e retorna resultado de triagem.

    Args:
        query: Pergunta original
        answer: Resposta gerada pelo LLM
        chunks: Lista de chunks usados como contexto (dict com 'text', 'score', etc)
        threshold: Score mínimo para não precisar de revisão humana
        model: Modelo LLM para avaliação

    Returns:
        dict com campos:
        - groundedness: yes|partial|no
        - relevance: high|medium|low
        - hallucination: none|minor|major
        - overall_score: float 0.0-1.0
        - justification: str
        - needs_human_review: bool
        - latency_ms: float
    """
    if not client.api_key:
        raise RuntimeError("OPENAI_API_KEY não está configurado.")

    if not answer or not chunks:
        return {
            "groundedness": "no",
            "relevance": "low",
            "hallucination": "major",
            "overall_score": 0.0,
            "justification": "Resposta ou contexto vazio",
            "needs_human_review": True,
            "latency_ms": 0.0
        }

    # Build context from chunks
    context_parts = []
    for i, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        score = chunk.get("score", 0.0)
        page = chunk.get("page_hint")
        context_parts.append(
            f"[Trecho {i+1}] (score: {score:.2f}, page: {page or '?'})\n{text[:500]}"
        )

    context = "\n\n".join(context_parts)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        context=context,
        query=query,
        answer=answer
    )

    start = time.time()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
        max_tokens=300
    )

    latency_ms = (time.time() - start) * 1000

    content = response.choices[0].message.content or "{}"

    # Parse JSON response
    try:
        import json
        # Try to extract JSON from response (in case there's extra text)
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            result = json.loads(content[json_start:json_end])
        else:
            result = json.loads(content)
    except json.JSONDecodeError:
        result = {
            "groundedness": "unknown",
            "relevance": "unknown",
            "hallucination": "unknown",
            "overall_score": 0.0,
            "justification": f"Erro ao parsear resposta do judge: {content[:100]}",
            "needs_human_review": True
        }

    result["latency_ms"] = latency_ms
    result["judge_model"] = model
    result["judge_prompt_version"] = JUDGE_PROMPT_VERSION

    return result


def triage_answers(
    queries: list[dict],
    threshold: float = DEFAULT_THRESHOLD
) -> list[dict]:
    """
    Faz triagem de múltiplas respostas em batch.

    Args:
        queries: Lista de dicts com 'query', 'answer', 'chunks'
        threshold: Score mínimo para não marcar para revisão

    Returns:
        Lista de resultados de triagem
    """
    results = []
    for item in queries:
        result = judge_answer(
            query=item["query"],
            answer=item["answer"],
            chunks=item["chunks"],
            threshold=threshold
        )
        results.append(result)

    # Summary
    needs_review = sum(1 for r in results if r["needs_human_review"])
    print(f"Triagem: {needs_review}/{len(results)} respostas precisam de revisão humana")

    return results
