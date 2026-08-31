# PHASE 2 — SPRINT 2.2: Query/RAG Module

## Objetivo
Implementar query RAG com contexto, citações e groundedness.

## Escopo
- Context retrieval
- LLM prompt construction
- Response generation
- Citation tracking
- Groundedness check

## Tasks

### Task 2.2.1: Context Assembly
**O QUE:** Montar contexto a partir dos chunks recuperados
**ONDE:** src/query/service.py
**COMO:** Concatenar chunks em prompt context
**DEPENDÊNCIA:** Sprint 2.1 (Retrieval)
**CRITÉRIO DE PRONTO:** Contexto montado corretamente para LLM

### Task 2.2.2: LLM Response Generation
**O QUE:** Gerar resposta via GPT-4o-mini com contexto
**ONDE:** src/query/service.py
**COMO:** OpenAI ChatCompletion com messages array
**DEPENDÊNCIA:** Sprint 2.2.1
**CRITÉRIO DE PRONTO:** Resposta gerada com base no contexto

### Task 2.2.3: Citation Extraction
**O QUE:** Extrair citações da resposta (chunk_ids usados)
**ONDE:** src/query/service.py
**COMO:** Mapear chunks usados no contexto → citation objects
**DEPENDÊNCIA:** Sprint 2.2.2
**CRITÉRIO DE PRONTO:** Citações incluídas na resposta

### Task 2.2.4: Groundedness Check
**O QUE:** Verificar se resposta está grounded nos chunks
**ONDE:** src/query/service.py
**COMO:** Verificar se claims da resposta aparecem nos chunks
**DEPENDÊNCIA:** Sprint 2.2.3
**CRITÉRIO DE PRONTO:** groundedness score calculado; low confidence warning se < 0.7

### Task 2.2.5: Query RAG API
**O QUE:** Expor API via POST /query
**ONDE:** src/query/routes.py
**COMO:** FastAPI route com retrieval → context → LLM → groundedness
**DEPENDÊNCIA:** Sprint 2.2.4
**CRITÉRIO DE PRONTO:** /query retorna resposta com citações e groundedness

## Riscos
- LLM pode gerar alucinações (mitigação: groundedness check rigoroso)

## Critérios de Validação
- [ ] Contexto montado corretamente
- [ ] Resposta generada via LLM
- [ ] Citações extraídas corretamente
- [ ] Groundedness check funcional
- [ ] Low confidence warning quando aplicável

## Status
⚪ PENDENTE