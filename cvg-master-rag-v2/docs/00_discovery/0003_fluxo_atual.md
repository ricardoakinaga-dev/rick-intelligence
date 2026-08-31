# 0003 — Fluxo Atual

## Objetivo

Visualizar como o processo funciona hoje — antes de propor solução.

---

## Sequência de Etapas Principais

### 1. Ingestão de Documentos

```
┌─────────────────────────────────────────────────────────────┐
│ 1. UPLOAD                                                  │
│   POST /documents/upload                                   │
│   multipart/form-data: file + workspace_id                  │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. VALIDAÇÃO                                               │
│   - Extensão aceita? (.pdf, .docx, .md, .txt)              │
│   - Magic bytes válidos?                                   │
│   - Tamanho < 50MB?                                       │
│   ❌ Se inválido → 400 Bad Request                         │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. PARSING                                                 │
│   - PDF: PyPDF2/pdfplumber (texto por página)              │
│   - DOCX: python-docx (texto puro)                         │
│   - MD: regex/parser simples                               │
│   - TXT: leitura direta                                   │
│   ❌ Se falhar → 413 Parse Failed                          │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. NORMALIZAÇÃO                                            │
│   - JSON estruturado com pages, sections, metadata          │
│   - Salvamento em src/data/documents/{workspace_id}/       │
│   - Arquivos: {document_id}_raw.json                       │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. CHUNKING (Recursive)                                    │
│   - chunk_size: 1000 caracteres                            │
│   - chunk_overlap: 200 caracteres                          │
│   - Não corta palavras no meio                            │
│   - Quebra por parágrafo quando possível                   │
│   - Output: {document_id}_chunks.json                      │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. EMBEDDINGS                                              │
│   - OpenAI text-embedding-3-small (1536 dim)              │
│   - Um vetor por chunk                                     │
│   - Cache local se documento não mudou                     │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. INDEXAÇÃO                                               │
│   - Qdrant collection: rag_phase0                         │
│   - Vetores densos (dense)                                 │
│   - Vetores esparsos (BM25/sparse)                         │
│   - Payload: chunk_id, document_id, text, page_hint       │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 8. RETORNO                                                 │
│   - 201 Created                                            │
│   - {document_id, status, chunk_count, pages}               │
└─────────────────────────────────────────────────────────────┘
```

---

### 2. Retrieval (Busca)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. RECEBIMENTO DA QUERY                                    │
│   POST /search                                             │
│   {query, workspace_id, top_k=5, threshold=0.70}           │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. EMBEDDING DA QUERY                                      │
│   - OpenAI text-embedding-3-small                          │
│   - Vetor de 1536 dimensões                                │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. BUSCA DENSA                                             │
│   - Qdrant: nearest neighbors top-20                       │
│   - Score: similaridade cosseno                            │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. BUSCA ESPARSA                                           │
│   - BM25 via Qdrant sparse embedding                      │
│   - Top-20 resultados                                      │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. FUSÃO RRF                                               │
│   - Reciprocal Rank Fusion (k=60)                          │
│   - Combina rankings densos e esparsos                     │
│   - Score final único                                      │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. FILTRAGEM                                               │
│   - workspace_id (sempre)                                  │
│   - document_id (se fornecido)                             │
│   - source_type, tags, page_hint_min/max (se fornecidos)  │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. RETORNO                                                 │
│   - Top-5 resultados                                       │
│   - Scores RRF                                             │
│   - low_confidence flag                                    │
└─────────────────────────────────────────────────────────────┘
```

---

### 3. Query (RAG Completo)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. RECEBIMENTO                                             │
│   POST /query                                               │
│   {query, workspace_id, top_k=5, threshold=0.70}           │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. RETRIEVAL                                               │
│   - Executa busca híbrida (mesmo processo do /search)       │
│   - Retorna top-5 chunks com scores                       │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. LOW CONFIDENCE CHECK                                    │
│   - best_score < threshold?                                │
│   - ❌ Sim → retorna resposta "não sei" com warning       │
│   - ✅ Não → continua                                      │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. MONTAGEM DE CONTEXTO                                   │
│   - Formata chunks com scores e instruções                 │
│   - Prompt: "Você é um assistente... use SOMENTE o         │
│     contexto fornecido abaixo..."                           │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. GERAÇÃO DE RESPOSTA                                     │
│   - GPT-4o-mini                                            │
│   - Streaming opcional                                     │
│   - Timeout configurável                                   │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. CITAÇÕES E GROUNDING                                    │
│   - Extrai citações dos chunks usados                       │
│   - Calcula citation_coverage                               │
│   - Verifica uncited_claims                                 │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. LOGGING E RETORNO                                      │
│   - Registra query em telemetry                            │
│   - Retorna resposta com metadados completos               │
└─────────────────────────────────────────────────────────────┘
```

---

## Decisões no Fluxo

### Decisão 1: Formato Aceito
- Apenas PDF, DOCX, MD, TXT
- XLSX, PPT, HTML adiados para fase futura

### Decisão 2: Estratégia de Chunking
- Apenas Recursive (1000/200)
- Semantic, Page-by-page, Agentic adiados

### Decisão 3: Retrieval Mode
- Apenas Híbrido (dense + sparse + RRF)
- Reranking adiado para F1

### Decisão 4: Threshold
- Default 0.70
- Configurável por query

### Decisão 5: Low Confidence
- Se best_score < threshold → "não sei"
- Não tenta recuperar contexto adicional

---

## Hand-offs

### Entre Backend e Frontend
- Frontend consome API REST
- Contratos definidos em 0009 e 0010
- Atualização de estado via sessão

### Entre Código e Qdrant
- Código gerencia corpus
- Qdrant gerencia vetores
- Sincronização validada por testes

### Entre Ingestão e Retrieval
- Ingestão produz chunks indexados
- Retrieval consome chunks indexados
- Contract: chunk_id, document_id, text, page_hint

---

## Gargalos Identificados

### Gargalo 1: Dataset Não Existe
- Impossibilita validação objetiva
- Gates只能用 critérios subjetivos
- Hit rate reportado pode não refletir realidade

### Gargalo 2: Auth Não Persistido
- Headers X-Enterprise-* como fallback
- Sessão não sobrevive a reinicializações
- RBAC não completamente enforceado no servidor

### Gargalo 3: Features Premium Pendentes
- HyDE, Semantic, Reranking prometidos mas não implementados
- Decisões de roadmap baseadas em intuição, não dados

### Gargalo 4: Observabilidade Limitada
- Sem request_id ponta a ponta
- Sem métricas por tenant
- Sem alertas configurados

---

## Falhas Conhecidas

### Falha 1: Parse de PDF Escaneado
- PDF com imagem (não texto) retorna texto vazio
- Sistema responde com erro, não com fallback

### Falha 2: Encoding Errado
- Documentos com encoding não-UTF8 podem causar falhas
- Fallback não implementado

### Falha 3: Qdrant Offline
- Se Qdrant cair, todo retrieval para
- Modo degradado não implementado

---

## Retrabalho Identificado

### Retrabalho 1: Sprint G1/G2
- Auth reimplementado após detecção de gap
- Admin panel recriado após，发现问题

### Retrabalho 2: Dataset
- Dataset placeholder usado em vez de dataset real
- Hit rate validado artificialmente como 100%

### Retrabalho 3: Documentação
- Documentos de rag-enterprise atualizados múltiplas vezes
- 0026-mapa-de-aderencia reconheceu necessidade de consistência

---

## Exceções Conhecidas

### Exceção 1: Upload em Workspace Isolado
- Durante validação de gate, workspace "playwright-ui" usado para testes
- Não faz parte do corpus canônico

### Exceção 2: Arquivos Arquivados
- não existe base paralela ativa de frontend fora de `frontend/`
- `src/data/documents-ARCHIVED/` — duplicatas arquivadas

### Exceção 3: Fallback Offline
- Sistema tem fallback determinístico para ambientes sem OPENAI_API_KEY
- Queries ainda retornam, mas sem embeddings reais

---

## Próximo Passo

Avançar para Problem Framing (0004_problem_framing.md)
