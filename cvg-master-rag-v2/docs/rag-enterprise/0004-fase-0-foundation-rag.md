# 0004 — Fase 0: Foundation / Validation RAG

## Objetivo da Fase

Construir o núcleo validável mais simples possível do RAG.
Validar que o sistema consegue: ingestar documentos, chunkar, recuperar contexto relevante, e gerar respostas com grounding — tudo mensurável com dataset real.

---

## Contexto

- **Não é produto final.** É protótipo validado.
- **Arquitetura:** Modular Monolith (FastAPI + Qdrant + filesystem)
- **Escopo:** O menor possível que ainda prove valor
- **Tempo:** ~3-4 semanas

---

## Escopo Detalhado

### 1. Ingestão

#### Formatos aceitos
- PDF (texto, sem OCR complexo)
- DOCX (texto puro via python-docx)
- Markdown (.md)
- Texto puro (.txt)

#### Não aceitos nesta fase
- XLSX / CSV (adiado)
- PPT / HTML (adiado)
- Imagens dentro de PDF (sem OCR)
- Tabelas complexas (adiado)

#### Pipeline de ingestion

```
Upload (REST API)
    ↓
Validação de tipo (extensão + magic bytes)
    ↓
Parse por tipo:
  PDF → PyPDF2 / pdfplumber (texto por página)
  DOCX → python-docx (texto puro)
  MD → regex/parser simples (cabeçalhos + parágrafos)
  TXT → leitura direta
    ↓
Normalização para JSON estruturado
    ↓
Salvamento em disco (JSON + arquivo original)
    ↓
Retorno: document_id + metadata
```

#### Contrato de saída da ingestão

```json
{
  "document_id": "uuid",
  "owner_id": "workspace-001",
  "source_type": "pdf|docx|md|txt",
  "filename": "string",
  "page_count": "number|null",
  "char_count": "number",
  "extracted_at": "ISO8601",
  "raw_json_path": "src/data/documents/workspace-001/document_id_raw.json",
  "status": "parsed|failed|partial"
}
```

Notes:

- o corpus persistido fica em `src/data/documents/{workspace_id}/`
- cada documento ativo mantém o par `{document_id}_raw.json` + `{document_id}_chunks.json`

### 2. Chunking

#### Estratégia: Recursive Only

```
Parâmetros fixos:
  chunk_size: 1000 caracteres
  chunk_overlap: 200 caracteres

Regras:
  - Não corta palavra no meio de palavra
  - Quebra por parágrafo quando possível
  -Overlap garante continuidade de contexto

Sem variations nesta fase.
```

#### Output do chunking

Cada chunk deve conter:

```json
{
  "chunk_id": "uuid",
  "document_id": "fk",
  "chunk_index": "number",
  "text": "string (max ~1000 chars)",
  "start_char": "number",
  "end_char": "number",
  "page_hint": "number|null (para PDF)",
  "strategy": "recursive",
  "created_at": "ISO8601"
}
```

### 3. Armazenamento Vetorial

#### Qdrant (local ou cloud)

**Collection: `rag_phase0`**

Para cada chunk, gerar:

**Vetor Denso** (OpenAI `text-embedding-3-small`, 1536 dim):
- Payload: chunk_id, document_id, text (truncado 2000 chars), page_hint

**Vetor Esparso** (BM25 via Qdrant sparse embedding):
- Payload: chunk_id, document_id

**Estratégia de busca híbrida:**

```
Query textual
    ↓
Embedding denso (OpenAI) → busca top-20 no Qdrant (dense)
    ↓
BM25 query → busca top-20 no Qdrant (sparse)
    ↓
RRF Fusion (k=60) dos dois rankings
    ↓
Top-5 resultados finais
    ↓
Retorno com scores
```

**Limiar:** score >= 0.70 para considerar relevante. Abaixo disso, marcar como "low confidence".

### 4. Retrieval (Search Service)

#### Input

```json
{
  "query": "string",
  "top_k": 5,
  "threshold": 0.70,
  "workspace_id": "string"
}
```

#### Output

```json
{
  "query": "string",
  "results": [
    {
      "chunk_id": "uuid",
      "document_id": "uuid",
      "text": "string",
      "score": 0.85,
      "page_hint": "number|null",
      "source": "dense|sparse|rrf"
    }
  ],
  "total_candidates": 20,
  "retrieval_time_ms": 120,
  "low_confidence": false
}
```

#### Notas

- threshold configurável por query (default: 0.70)
- Se todos os resultados abaixo do threshold, marcar `low_confidence: true` e não enviar contexto para LLM (ou enviar aviso)
- Logs: todas as queries salvas com timestamp, query, resultados, scores

### 5. Resposta (Agent / LLM)

#### Fluxo

```
User query
    ↓
Search Service → retrieval top-5 chunks
    ↓
Se low_confidence: warn user or say "não sei"
    ↓
Montar contexto: chunks + scores + instructions
    ↓
LLM (GPT-4o-mini) → resposta com base no contexto
    ↓
Log: query, context_used, response, latency
```

#### Prompt base (Fase 0)

```
Você é um assistente de IA que responde perguntas
usando SOMENTE o contexto fornecido abaixo.

Se a informação do contexto não for suficiente para
responder, diga "Não sei" — não invente resposta.

Contexto:
{ chunks格式化ados }

Pergunta: { query }

Resposta (use apenas informações do contexto):
```

#### Output

```json
{
  "answer": "string",
  "chunks_used": ["chunk_id", ...],
  "confidence": "high|medium|low",
  "grounded": true,
  "latency_ms": 890
}
```

### 6. Dataset de Validação (CRÍTICO)

#### Requisitos

- Mínimo 20 perguntas reais (não sintéticas)
- Cada pergunta tem:
  - id
  - pergunta (texto)
  - document_id (ID canônico do documento)
  - trecho_esperado (evidência que deveria ser recuperada)
  - resposta_esperada (resumo do que deveria ser dito)
  - dificuldade (easy|medium|hard)
  - categoria (fato|procedimento|política|detalhes)

#### Origem

- Perguntas de usuários reais (se disponíveis)
- Perguntas derivadas de documentos reais pelo time de negócio
- NUNCA apenas perguntas geradas por LLM

#### Formato

```json
{
  "dataset_id": "phase0_validation",
  "questions": [
    {
      "id": 1,
      "pergunta": "Qual o prazo para reembolso?",
      "document_id": "doc-001",
      "trecho_esperado": "O prazo para solicitação de reembolso é de 30 dias...",
      "resposta_esperada": "30 dias corridos após a purchase",
      "dificuldade": "easy",
      "categoria": "procedimento"
    }
  ]
}
```

---

## Arquitetura Técnica — Fase 0

```
                    ┌──────────────┐
                    │   Client     │
                    │  (cURL ou   │
                    │  Postman)   │
                    └──────┬───────┘
                           │ HTTP
                           ▼
              ┌─────────────────────────┐
              │    FastAPI (Python)     │
              │                         │
              │  ┌─────────────────┐   │
              │  │  /upload        │   │
              │  │  /documents     │   │
              │  │  /search        │   │
              │  │  /query         │   │
              │  └─────────────────┘   │
              └───────────┬─────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
    ┌───────────┐  ┌───────────┐  ┌──────────────┐
    │  Qdrant   │  │  Filesystem│  │  OpenAI API  │
    │ (vectors) │  │  (JSONs)   │  │ (embeddings) │
    └───────────┘  └───────────┘  └──────────────┘
```

### Decisões Arquiteturais

| Decisão | Escolha | Justificativa |
|---|---|---|
| Backend | FastAPI (Python) | Contrato claro, fácil de iterar, LLM-friendly |
| Vector DB | Qdrant | Suporta dense+sparse natively, fácil setup |
| Storage | Filesystem local | JSONs em disco, simples e auditável |
| Embeddings | OpenAI `text-embedding-3-small` | Barato, bom, 1536 dim |
| LLM | GPT-4o-mini | Custo-benefício, rápido |
| Orquestração | Código simples (if/else) | Sem LangGraph em Fase 0 |

---

## API Endpoints — Fase 0

### POST /documents/upload

Upload de documento para ingestion.

**Request:** multipart/form-data
- `file`: arquivo (PDF, DOCX, MD, TXT)
- `workspace_id`: string (default: "default")

**Response 201:**
```json
{
  "document_id": "uuid",
  "status": "parsed",
  "chunk_count": 12,
  "pages": 5
}
```

**Response 400:**
```json
{
  "error": "unsupported_format",
  "message": "Apenas PDF, DOCX, MD, TXT são aceitos nesta fase"
}
```

---

### GET /documents/{document_id}

Retorna metadata do documento.

---

### POST /search

Busca híbrida no knowledge base.

**Request:**
```json
{
  "query": "string",
  "workspace_id": "default",
  "top_k": 5,
  "threshold": 0.70
}
```

**Response:**
```json
{
  "query": "string",
  "results": [...],
  "total_candidates": 20,
  "low_confidence": false
}
```

---

### POST /query

Busca + resposta do agente.

**Request:**
```json
{
  "query": "string",
  "workspace_id": "default",
  "top_k": 5,
  "threshold": 0.70
}
```

**Response:**
```json
{
  "answer": "string",
  "chunks_used": ["uuid", ...],
  "confidence": "high",
  "grounded": true,
  "latency_ms": 1200,
  "retrieval": {...}
}
```

---

## Quality Gate — Fase 0

### Definição

**GATE F0** é cumprido se e somente se TODAS as condições abaixo forem verdadeiras:

#### A. Infraestrutura
- [ ] Upload de PDF/DOCX/MD/TXT funciona e retorna document_id
- [ ] Parsing extrai texto corretamente (verificado spot-check)
- [ ] Chunking recursive gera chunks de ~1000 caracteres com overlap 200
- [ ] Vetores densos são gerados e indexados no Qdrant
- [ ] Vetores esparsos (BM25) são gerados e indexados no Qdrant
- [ ] Busca híbrida retorna resultados com scores RRF

#### B. Retrieval Quality
- [ ] Dataset de 20+ perguntas reais montado
- [ ] Para cada pergunta do dataset: retrieval executado e score registrado
- [ ] Hit Rate top-5 >= 60% (12/20 perguntas retornam documento correto no top-5)
- [ ] Se hit rate < 60%: documento de análise de falhas é gerado

#### C. Resposta Quality
- [ ] Para perguntas do dataset, resposta é gerada com contexto recuperado
- [ ] low_confidence é标记ado corretamente (sem falsos negativos)
- [ ] Latência média < 5 segundos por query (sem web search)

#### D. Observabilidade
- [ ] Logs de todas as queries salvos (query, timestamp, results, scores, latency)
- [ ] Métricas básicas exportadas: hit_rate, avg_latency, avg_score
- [ ] Falhas documentadas com razão e não apenas com exception

#### E. Documentação
- [ ] Todos os endpoints documentados (input, output, erros)
- [ ] README com instruções de setup e run
- [ ] Contratos de ingestion, retrieval e evaluation documentados

---

### Critério de Pass/Fail

```
SE (A AND B AND C AND D AND E):
    → GATE APROVADO → avançar para Fase 1
SENÃO:
    → GATE REPROVADO → listar falhas → corrigir → tentar novamente
```

**Importante:** Não "relaxar" threshold para passar gate. Se hit rate é 58%, o sistema precisa melhorar, não o gate precisa ser ajustado.

---

## Checklist de Entregáveis — Fase 0

### Infraestrutura
- [ ] API REST com FastAPI para upload, search, query
- [ ] Parser para PDF, DOCX, MD, TXT
- [ ] Module de chunking recursive (1000/200)
- [ ] Module de geração de embeddings (OpenAI)
- [ ] Module de indexação no Qdrant (dense + sparse)
- [ ] Module de busca híbrida com RRF
- [ ] Module de resposta com LLM (GPT-4o-mini)
- [ ] Logging de queries e resultados

### Dataset
- [ ] 20+ perguntas reais (não sintéticas)
- [ ] Trecho esperado e documento fonte para cada pergunta
- [ ] Formato JSON exportável
- [ ] Revisão humana confirmando que perguntas fazem sentido

### Testes
- [ ] Teste funcional de upload de cada formato
- [ ] Teste de retrieval com dataset completo
- [ ] Análise de falhas (quais perguntas não retornaram contexto correto)
- [ ] Latência medida para 20+ queries

### Documentação
- [ ] README com setup e run
- [ ] Contrato de APIs (OpenAPI/Swagger)
- [ ] Contrato de chunk schema
- [ ] Contrato de search result
- [ ] Este documento de Fase 0

---

## Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| PDF com senha ou imagem escaneada | Média | Alto | Validar formato antes de processar; falhar explicitamente |
| Qdrant local sem persistência | Baixa | Alto | Backup do volume; ou Qdrant cloud |
| OpenAI API rate limit | Média | Médio | Rate limiting; cache de embeddings |
| Chunking quebra contexto | Alta | Médio | Tuning de chunk_size/overlap; fallback para chunks maiores |
| LLM não segue instrução de grounding | Média | Médio | Prompt testado com casos difíceis; monitoramento de groundedness |

---

## Próximo Passo

Ir para `0005-fase-1-rag-profissional.md` — detalhamento da Fase 1 (ou pular para `0008-arquitetura-alvo-e-arquitetura-atual.md` para ver a arquitetura de referência).
