# PLANO PREMIUM ENTERPRISE — RAG Database Builder
### Versão 1.0 — Baseado no Framework Smith AI (Breno / Lolab Academy)

---

## 1. VISÃO GERAL

Construção de um sistema RAG (Retrieval Augmented Generation) de **nível enterprise** capaz de processar documentações complexas, gigantescas, com múltiplos tipos de arquivos (PDF, Word, Excel, TXT, Markdown), tabelas e dados estruturados — e entregar agentes de IA que performam com **acurácia superior a 90%**.

Diferencial: o sistema não é "ingênuo" (naive RAG). Cada documento passa por um processo rigoroso de **injestão, chunking inteligente, avaliação, benchmark e refinaria** antes de ir para produção. Só assim o agente atende com qualidade.

---

## 2. PILARES DO SISTEMA

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ARQUITETURA RAG ENTERPRISE                   │
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐           │
│  │   INGESTÃO   │───▶│   RETRIEVAL  │───▶│   REFINARIA  │           │
│  │  (Ingestion) │    │ (Retrieval)  │    │ (Evaluation  │           │
│  │              │    │              │    │  + Benchmark)│           │
│  └──────────────┘    └──────────────┘    └──────────────┘           │
│         │                   │                                        │
│  • Document    ┌───────────┴───────────┐                           │
│    Service     │     BANCO VETORIAL     │                           │
│  • Chunking    │  (Qdrant + Milvus)    │                           │
│    Strategies  │                       │                           │
│  • MiniIO      │  • Vetor Denso (OpenAI│                           │
│    Storage     │    Embeddings)        │                           │
│                │  • Vetor Esparço (BM25│                           │
│                │    via Qdrant)         │                           │
│                │  • Híbrida (RRF Fusion)│                           │
│                └───────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. ESTÁGIOS DETALHADOS

### ESTÁGIO 1 — INGESTÃO (Ingestion Service)

#### 3.1 Serviço de Documentos (Document Service)
- Recebe arquivos: PDF, DOCX, XLSX, TXT, MD, HTML
- Converte todos para formato **JSON estruturado** (texto extraído por página/seção)
- Salva os JSONs no **MinIO** (storage S3-compatible) para testes repetidos sem re-upload
- Armazena metadados: tipo de arquivo, número de páginas/seções, data de upload, empresa dona

#### 3.2 Estratégias de Chunking (4 opções)

| Estratégia | Descrição | Melhor para |
|---|---|---|
| **Recursive** | Corta por caracteres/Tokens definindo overlap. Olha parágrafos, não corta palavras no meio. | Documentos gerais, rápida execução |
| **Semantic** | Usa biblioteca experimental do LangGraph. Entende distância semântica entre vetores. | Documentos com contexto complexo |
| **Page by Page** | Cada chunk = 1 página inteira do PDF. Usa número de páginas do documento. | Contratos, documentos jurídicos |
| **Agentic** | LLM (GPT-4o-mini) como "agente chunker". Prompt profissional com regras de validação. Divide o documento em janelas de max 8.000 caracteres, envia para LLM Mini que retorna chunks de 500-1000 caracteres. Overlap de 800 para evitar perda de contexto. | Documentação técnica complexa (Ferrari do chunking) |

#### 3.3 Armazenamento Vetorial (Qdrant)
Para cada chunk, gerar **DOIS vetores** (busca híbrida):
- **Vetor Denso**: OpenAI `text-embedding-3-small` (1536 dimensões). Entende sinônimos, contexto, intenção.
- **Vetor Esparço (BM25)**: Modelo nativo do Qdrant. Palavras exatas, termos técnicos, códigos, nomes próprios, siglas.

---

### ESTÁGIO 2 — RETRIEVAL (Retrieval + Reranking)

#### 3.4 Busca Híbrida (Padrão Enterprise)
```
Query do usuário
     │
     ▼
┌──────────────────────────────────────────────┐
│           BUSCA HÍBRIDA                      │
│                                              │
│  ┌─────────────────┐  ┌─────────────────┐   │
│  │  Busca Semântica │  │ Busca BM25      │   │
│  │  (Vetor Denso)   │  │ (Vetor Esparso) │   │
│  │  top-20 chunks   │  │ top-20 chunks   │   │
│  └────────┬─────────┘  └────────┬─────────┘   │
│           │                    │             │
│           └──────┬─────────────┘             │
│                  ▼                           │
│          ┌──────────────┐                   │
│          │  RRF Fusion   │ ← Reciprocal     │
│          │  (Fusão por   │   Rank Fusion    │
│          │   Rank)       │                   │
│          └───────┬───────┘                   │
│                  ▼                           │
│          Top-5 chunks                       │
│          (re-rankados)                      │
└──────────────────────────────────────────────┘
```

#### 3.5 Reranking (Cohere rerank)
- Após RRF, rerankar os 20 candidatos para **top-5 definitivos**
- Score mínimo de threshold: **0.70** (descarta chunks irrelevantes)
- Parâmetro configurável por cliente

#### 3.6 HyDE (Hypothetical Document Embeddings)
- Se score do top-5 < 0.85, acionar HyDE como backup
- Gera documento hipotético (resposta simulada via GPT-5.1) com terminologia técnica correta
- Faz busca com o documento hipotético e compara scores
- Mantém o melhor resultado (híbrida direta vs HyDE)

#### 3.7 Web Search (Opcional)
- Habilitável por empresa via configuração
- Útil para perguntas que exigem dados atualizados em tempo real

---

### ESTÁGIO 3 — REFINARIA (Evaluation + Benchmark)

#### 3.8 Evaluation Service (Por Documento)
Para cada documento processado:
1. GPT-5.1 gera de 5 a 10 perguntas técnicas desafiadoras baseadas no conteúdo real
2. Recupera chunks do documento específico
3. LLM as Judge julga se a resposta está correta
4. Retorna **percentual de acerto** (ex: 93%, 96%, 100%)
5. Documentos com baixa nota (< 80%) são sinalizados para revisão

#### 3.9 Benchmark Service (Global — Todas as Estratégias)
Rodado após processar TODOS os documentos do cliente:
1. Seleciona aleatoriamente N documentos (padrão: 3)
2. Gera 5 a 15 perguntas-teste via GPT-5.1 (redator)
3. Executa **12 cenários**: 4 estratégias de chunk × 3 modos de retrieval
   - Modos: Standard | HyDE | Híbrida
4. Para cada cenário:
   - Indexa temporariamente no Qdrant (sandbox)
   - Insere vetores densos + esparsos
   - Executa retrieval
   - Verifica se documento correto apareceu no **top-5 com score > 0.70**
   - Calcula **Hit Rate** (taxa de acerto) e **Average Score**
5. RRF para definir combinação vencedora
6. Delete da collection temporária (limpeza)
7. Aplica estratégia vencedora a TODOS os documentos do cliente

**Critérios de vitória:**
- Maior Hit Rate (prioridade)
- Se empate → maior Average Score (confiança)
- Se empate → HyDE como decidirdor final

---

## 4. ARQUITETURA DE MICROSERVIÇOS

```
┌──────────────────────────────────────────────────────────┐
│                   FRONT-END (Multi-tenant)                │
│        Next.js + Supabase (Web Chat + Admin Panel)       │
└──────────────┬──────────────────────┬───────────────────┘
               │                      │
┌──────────────▼─────────┐  ┌────────▼─────────────────┐
│    Chat Microservice    │  │    Admin Microservice      │
│    (WebSocket/REST)    │  │    (Dashboard/Cadastro)    │
└──────────────┬─────────┘  └──────────────┬──────────────┘
               │                           │
┌──────────────▼──────────────────────────▼───────────────┐
│                    LANGGRAPH (Orchestrator)                │
│   • Router (decisão: direto / knowledge base / web)       │
│   • Memory / Cache                                         │
│   • Agent State + Company Config (multitenant)             │
└──────────────┬──────────────────────┬─────────────────────┘
               │                      │
    ┌──────────▼────┐      ┌──────────▼──────┐
    │ Search Service │      │ Audio Service   │
    │ (Qdrant)       │      │ (FasterWhisper) │
    └────────────────┘      └─────────────────┘
```

### Stack Tecnológica

| Componente | Tecnologia | Função |
|---|---|---|
| Chat Frontend | Next.js + Supabase | Interface web, multitenant |
| Admin Panel | Next.js + Supabase | Cadastro de empresas, logs |
| Storage | MinIO | Guarda arquivos e JSONs |
| Banco Vetorial | Qdrant (Cloud ou Docker) | Vetor denso + esparso |
| Reranking | Cohere (rerank-3) | Re-rank de candidatos |
| Embeddings | OpenAI `text-embedding-3-small` | Vetor denso |
| BM25 | Nativo Qdrant | Vetor esparso |
| Orquestração | LangGraph | Fluxo do agente, memória |
| LLM Principal | GPT-5.1 / GPT-4o / Claude | Resposta do agente |
| LLM Judge | GPT-4o-mini | Avaliação de perguntas |
| Chunking Agentic | GPT-4o-mini | Chunking inteligente |
| Transcrição | FasterWhisper | Áudio → texto |
| Framework | Python 3.12+ (FastAPI) | Backend dos serviços |

---

## 5. FLUXO COMPLETO DE UM PROJETO CLIENTE

```
1. Briefing do cliente
   → Entrevista: quais perguntas o agente deve responder?
   → Entendimento profundo do negócio e documentação
   → Definição: atendimento, suporte, onboarding, interno?

2. Upload da documentação
   → Document Service extrai texto e salva em JSON (MinIO)

3. Processamento em paralelo
   → Roda as 4 estratégias de chunking simultaneamente
   → Gera vetores densos (OpenAI) + esparsos (BM25) no Qdrant

4. Evaluation Service
   → Por documento: gera perguntas, testa, pontua
   → Documentos ruins são sinalizados

5. Benchmark Service
   → Roda 12 cenários (4 chunkings × 3 retrievals)
   → Define estratégia vencedora para aquele cliente

6. Configuração do Agente
   → Prompt do cliente (empresa) + System Prompt (aplicação)
   → Fusionados para cada interação

7. Chat em Produção
   → Usuário pergunta → Router → Search Service (híbrida → rerank)
   → Se score < 0.85 → HyDE como fallback
   → Se configuração web enabled → busca internet
   → Log de todas as conversas + scores dos chunks

8. Monitoramento contínuo
   → Logs de conversation (perguntas, respostas, chunks usados, scores)
   → Métricas de Hit Rate por período
```

---

## 6. CONFIGURAÇÕES POR EMPRESA (Multitenant)

```python
CompanyConfig:
  - company_id
  - company_name (white label)
  - llm_model: "gpt-5.1" | "gpt-4o" | "claude-3-5-sonnet"
  - temperature: 0.0 - 1.0
  - system_prompt: str
  - company_prompt: str  # fundido com system
  - web_search_enabled: bool
  - audio_enabled: bool
  - chunking_strategy: "recursive" | "semantic" | "page" | "agentic"
  - retrieval_mode: "standard" | "híbrida" | "híbrida+hide"
  - top_k: int (qtd de chunks)
  - min_score_threshold: float (0.0 - 1.0)
```

---

## 7. ESTRATÉGIAS DE CHUNKING — PROFUNDIDADE

### 7.1 Recursive Chunking
```
chunk_size: 1000 caracteres
chunk_overlap: 200 caracteres
保留 palavras inteiras (não corta no meio)
```

### 7.2 Semantic Chunking (LangGraph)
```
Usa biblioteca experimental do LangGraph
Max 1900 caracteres por chunk
Baseado em distância semântica entre vetores
Mais rápido e barato que agentic
```

### 7.3 Page by Page (PDF Only)
```
1 página = 1 chunk
Mantém contexto jurídico/contratual
Não corta contratos no meio
```

### 7.4 Agentic Chunking (Ferrari)
```
1. Split do documento em janelas de 8.000 caracteres
2. Envia para GPT-4o-mini com prompt profissional:
   - "Você é especialista em arquitetura de informação"
   - "Chunk máximo: 500-1000 caracteres"
   - "Cada chunk deve fazer sentido sozinho"
   - "Jamais reescreva — copie texto exato do original"
   - "Títulos descritivos: 'Política de reembolso, prazos' não só 'Prazos'"
   - "Se tópico for longo, divida em parte 1 e parte 2"
3. Overlap de 800 caracteres entre chunks
4. Validação: fallback inteligente em caso de erro
```

---

## 8. MÉTRICAS E KPIS DE QUALIDADE

| Métrica | Meta Enterprise |
|---|---|
| Hit Rate (Benchmark) | ≥ 80% no top-5 |
| Average Score dos Chunks | ≥ 0.70 |
| Acurácia por documento (Evaluation) | ≥ 90% |
| Latência de resposta | < 8 segundos |
| Taxa de hallucinação | < 10% (julgado por LLM as Judge) |
| Tokens por resposta | Controlado via chunk threshold |

---

## 9. FASES DE IMPLEMENTAÇÃO

### Fase 1 — Foundation (Semanas 1-4)
- [ ] Document Service (upload, extração, conversão JSON)
- [ ] MinIO storage setup
- [ ] Qdrant local (Docker)
- [ ] 4 estratégias de chunking implementadas
- [ ] Geração de vetores (denso + esparso)

### Fase 2 — Retrieval (Semanas 5-8)
- [ ] Busca híbrida (RRF Fusion)
- [ ] Reranking (Cohere)
- [ ] HyDE implementation
- [ ] Search Service completo
- [ ] Limiar configurável de chunks/scores

### Fase 3 — Evaluation (Semanas 9-12)
- [ ] Evaluation Service por documento
- [ ] Benchmark Service global
- [ ] LLM as Judge integration
- [ ] Dashboard de métricas de qualidade

### Fase 4 — Agent + Chat (Semanas 13-16)
- [ ] LangGraph orchestrator
- [ ] Router (direto / KB / web)
- [ ] Memory + Cache
- [ ] Frontend Next.js (chat + admin)
- [ ] Logs de conversão completos
- [ ] Audio service (FasterWhisper)

### Fase 5 — Multitenant + White Label (Semanas 17-20)
- [ ] Sistema de empresas (cadastro, config)
- [ ] White label do chat (nome, branding)
- [ ] Prompt fusionado por empresa
- [ ] Sistema de permissões e aprovações

---

## 10. PREÇOS E CONTRATAÇÃO (Referência de Mercado)

### Modelo de Monetização

| Plano | Valor Mensal | Escopo |
|---|---|---|
| **Starter** | R$ 2.000 - R$ 4.000/mês | Até 3 empresas, 5.000 docs, 10k conversas/mês |
| **Professional** | R$ 5.000 - R$ 10.000/mês | Até 10 empresas, docs ilimitados, 50k conversas |
| **Premium Enterprise** | R$ 15.000 - R$ 30.000/mês | Multitenant completo, docs ilimitados, conversas ilimitadas, SLA 99.9% |
| **Custom** | Sob consulta | Infraestrutura dedicada, integração ERP/CRM, modelos próprios |

### O que está incluso no Premium Enterprise
- Implementação completa do framework
- Treinamento da equipe do cliente
- Suporte prioritário
- Atualizações de versão
- Consultoria trimestral de otimização
- White label completo
- SLA de disponibilidade
- Monitoramento avançado de качество

### Custos deInfraestrutura (estimativa AWS/GCP)
- Qdrant Cloud (3 replicas): ~R$ 1.500/mês
- MinIO (S3): ~R$ 500/mês
- API OpenAI (embeddings + LLM): ~R$ 3.000-10.000/mês (variável por volume)
- Compute (FastAPI, LangGraph): ~R$ 1.000/mês
- Cohere Rerank: ~R$ 500-2.000/mês (variável)

**Custo total estimado de operação: R$ 6.500 - R$ 15.000/mês por cliente enterprise**

---

## 11. POR QUE ESSE SISTEMA VALE DINHEIRO

> "Eu scalei minha agência para R$ 45.000/mês. Um agente RAG profissional é um dos projetos que **menos entregava**, porque é difícil. Mas quando交付 — **vale muito dinheiro**. Muitos clientes vão pagar para ter uma estrutura dessas, principalmente se for rodando **localmente** dentro da máquina."

— Breno (transcrição do vídeo)

###Diferencial competitivo real:
- Não é "pega arquivo, quebra em 1000 pedaços, faz 3 perguntas" (Naive RAG)
- É sistema completo de **refinaria** com benchmark automático
- Suporta documentação complexa, gigante, vários tipos de arquivos
- HyDE + Híbrida + Reranking = acurácia > 90%
- Roda local (privacidade de dados) ou cloud
- Multitenant = vários clientes na mesma infraestrutura

---

*Documento gerado automaticamente com base na transcrição do vídeo de Breno (Lolab Academy) sobre RAG Enterprise com Smith AI Framework.*
*Transcrição: https://www.youtube.com/watch?v=HpzWrIzSpmY*
*Data: 2026-04-16*