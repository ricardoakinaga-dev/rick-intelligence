# 0014 — Riscos, Custos e Decisões

## Objetivo

Documentar os principais riscos técnicos e operacionais, custos estimados, e decisões arquiteturais com justificativas — para referência futura e auditoria.

---

## 1. Riscos Técnicos

### Risco 1: Circularidade na Avaliação

**Descrição:** LLM gerando perguntas e julgando suas próprias respostas cria viés estrutural.

**Mitigação:**
- Revisão humana obrigatória para respostas com score < 0.70
- Dataset de perguntas reais de usuários (não só sintéticas)
- Judge como triagem, não como veredicto

**Severity:** Alta
**Probability:** Alta

---

### Risco 2: Overfitting no Benchmark

**Descrição:** Estratégia otimizada para perguntas específicas do dataset, não generaliza.

**Mitigação:**
- Dataset dividido: treino vs validação
- Benchmark testa em perguntas diferentes das de tuning
- Análise manual de resultados, não só scores

**Severity:** Alta
**Probability:** Média

---

### Risco 3: Complexidade Cresce Sem Controle

**Descrição:** Cada fase adiciona features que aumentam coupling e reduzem manutenibilidade.

**Mitigação:**
- Cada feature nova precisa de justificativa documentada
- Arquitetura modular: componentes fracamente acoplados
- Code review obrigatório antes de merge

**Severity:** Alta
**Probability:** Alta

---

### Risco 4: Custo de API Escalando sem Controle

**Descrição:** Embeddings + LLM calls crescem linearmente com documentos e queries, sem monitoramento de custo.

**Mitigação:**
- Monitorar custo por documento e por query desde Fase 0
- Estabelecer limites (threshold alto = menos chunks = menos tokens)
- Cache de embeddings (documentos não mudam frequentemente)

**Severity:** Média
**Probability:** Média

---

### Risco 5: Qdrant como Single Point of Failure

**Descrição:** Se Qdrant cair, todo o sistema de retrieval para.

**Mitigação:**
- Qdrant com replication em produção
- Health check com failover
- Modo "degraded" se Qdrant indisponível (responder "serviço temporariamente indisponível")

**Severity:** Alta
**Probability:** Baixa (com ops adequado)

---

### Risco 6: Latência Escalando com Tamanho do Dataset

**Descrição:** Queries em collections grandes (> 1M chunks) ficam mais lentas.

**Mitigação:**
- Índices otimizados no Qdrant
- Limitar busca ao workspace_id (já filtra muito)
- HNSW index para fast approximate nearest neighbor

**Severity:** Média
**Probability:** Média

---

### Risco 7: Documentos com Formatação Ruim

**Descrição:** PDFs escaneados, DOCXs com tabelas complexas, textos com encoding errado.

**Mitigação:**
- Validação de formato na ingestion
- Erro explícito se texto extraído está vazio
- Formatos não suportados devolvem erro claro (não silêncio)

**Severity:** Alta (para certos tipos de documento)
**Probability:** Alta (documentos reais raramente são limpos)

---

## 2. Riscos Operacionais

### Risco 8: Team Não Entende Tradeoffs

**Descrição:** Decisões técnicas sem compreensão de custos/benefícios levam a features desnecessárias.

**Mitigação:**
- Documentação de decisões (ADR - Architecture Decision Records)
- Revisões de arquitetura quinzenais
- Gate de fase inclui revisão de design

---

### Risco 9: Dataset Estático vs Realidade Dinâmica

**Descrição:** Documentos mudam, perguntas mudam, mas o sistema foi validado com snapshot.

**Mitigação:**
- Re-avaliar dataset periodicamente (mensal)
- Adicionar novas perguntas quando falhas surgirem
- Monitorar "unknown" queries (perguntas que ninguém previu)

---

## 3. Custos Estimados

### Custos de Infraestrutura (Fase 0-1, single tenant)

| Componente | Opção | Custo Mensal |
|---|---|---|
| Qdrant (local) | Docker | $0 (já existente) |
| Qdrant (cloud, dev) | Qdrant Cloud | ~$25-50 |
| OpenAI API | Pay-as-you-go | ~$50-200 (variável) |
| Compute (FastAPI) | 2 vCPU | ~$20-40 |
| Storage (files) | 100GB | ~$10 |
| **Total Fase 0-1** | | **~$80-300/mês** |

### Custos Estimados (Fase 3, multi-tenant)

| Componente | Opção | Custo Mensal |
|---|---|---|
| Qdrant Cloud (3 replicas) | Qdrant Cloud Enterprise | ~$500-1500 |
| Supabase | Pro plan | ~$75 |
| MinIO (S3) | 1TB | ~$50 |
| Compute (FastAPI, auto-scale) | 4-8 vCPU | ~$100-300 |
| OpenAI API (3 tenants) | Pay-as-you-go | ~$500-2000 |
| Cohere Rerank | Pay-as-you-go | ~$200-500 |
| Monitoring (Datadog) | Pro | ~$100-200 |
| **Total Fase 3** | | **~$1500-4600/mês** |

### Custo por Documento (estimativa)

| Item | Custo |
|---|---|
| Parsing | ~$0.001-0.01 (compute) |
| Embedding (OpenAI) | ~$0.0001 per 1000 tokens |
| Indexing (Qdrant) | ~$0.00001 per chunk |
| Agentic Chunking | ~$0.01-0.05 (GPT-4o-mini) |

### Custo por Query (estimativa)

| Modo | Custo |
|---|---|
| Retrieval only | ~$0.0001 (embed query) |
| Com LLM (GPT-4o-mini) | ~$0.002-0.01 |
| Com HyDE (2x LLM) | ~$0.004-0.02 |
| Com Reranking (Cohere) | +$0.005 per query |

---

## 4. Decisões Arquiteturais

### Decisão 1: Modular Monolith Inicialmente

**Decisão:** Fase 0 usa Modular Monolith (FastAPI com módulos), não microservices.

**Justificativa:**
- Comunicação inter-processo adiciona latência e complexidade
- Não existe necessidade de scaling independente ainda
- Debugging é mais simples em monolith
- Deployment é mais simples

**Revisitar:** Fase 2 ou 3, se serviço específico precisar escalar independentemente.

---

### Decisão 2: Qdrant como Vector DB

**Decisão:** Qdrant para vetores densos + esparsos (BM25 native).

**Justificativa:**
- Suporta dense + sparse natively (não precisa de dois bancos)
- Performance comprovada ( Benchmarks mostram > Pinecone, Weaviate)
- Easy setup (local ou cloud)
- Rust-based (performance)

**Alternativa considerada:** Pinecone (mais caro), Weaviate (mais complexo), Chroma (não escala).

---

### Decisão 3: OpenAI Embeddings

**Decisão:** `text-embedding-3-small` para vetores densos.

**Justificativa:**
- Barato ($0.02 per 1M tokens em Mar 2024)
- Performance boa (1536 dimensões)
- Latência baixa

**Alternativa:** `text-embedding-3-large` (mais caro, marginal benefit), Cohere (não dá para usar depois, porque já temos OpenAI para LLM).

---

### Decisão 4: GPT-4o-mini como LLM Principal

**Decisão:** GPT-4o-mini para geração de respostas.

**Justificativa:**
- Custo 10x menor que GPT-4o
- Performance suficiente para tarefas de recuperação
- Latência boa
- Disponibilidade boa

**Revisitar:** Se latency ou custo se tornarem problema, trocar para modelo mais barato (ex: Gemini Flash).

---

### Decisão 5: LangGraph ADIADO

**Decisão:** Fase 0 usa código simples (if/else) para roteamento.

**Justificativa:**
- Latência adicional do LangGraph não justifica
- Roteamento simples não precisa de graph
- "Canhão para matar mosca"

**Revisitar:** Fase 2 ou 3 quando orchestration precisar de estados complexos, memória de conversation, branching.

---

### Decisão 6: Sem Audio na Fase 0

**Decisão:** Audio (FasterWhisper) não entra antes de retrieval estar funcional.

**Justificativa:**
- Audio é input channel, não é core RAG
- Adiciona complexidade (transcrição, timestamps)
- Não bloqueia validação do núcleo

---

## 5. Matriz de Decisões Rápidas

| Pergunta | Resposta Padrão |
|---|---|
| "Vai ajudar na Fase 0?" | Se não é core retrieval → ADIAR |
| "LM Judge é veredicto?" | NÃO. É triagem. Revisão humana mandatory. |
| "Micro-serviços?" | NÃO até Fase 3. Modular monolith até lá. |
| "Armazenamento?" | Filesystem Fase 0, MinIO quando múltiplos serviços precisarem. |
| "Benchmark automatizado?" | NÃO até ter dataset real validado. |
| "White label?" | Fase 3, não antes. |

---

## Próximo Passo

Ir para `0015-roadmap-executivo.md` — roadmap executivo.