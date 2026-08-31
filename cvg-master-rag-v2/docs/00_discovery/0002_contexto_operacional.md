# 0002 — Contexto Operacional

## Objetivo

Entender onde e como os problemas do programa vivem na prática.

---

## Onde o Problema Ocorre

### 1. Pipeline de Validação de Gates

**Localização:** Processo de decisão entre fases (F0→F1, F1→F2, F2→F3)

**Fluxo afetado:**
```
GATE F0 → GATE F1 → GATE F2 → GATE F3
  │          │          │          │
  ▼          ▼          ▼          ▼
Validação   Validar    Validar    Validar
de motor    operação   frontend   plataforma
técnico     profissional             enterprise
```

**Problema:** Sem dataset real, nenhum gate pode ser validado objetivamente.

### 2. Camada de Autenticação e Autorização

**Localização:** Backend (`src/api/`) e Frontend (`frontend/`)

**Fluxo atual problemático:**
```
Cliente envia X-Enterprise-Workspace-ID e X-Enterprise-Role
  → Backend confia nos headers
  → Não há autenticação real no servidor
  → Sessão não persiste entre reinicializações
```

**Fluxo esperado:**
```
Cliente faz login
  → Backend valida credenciais
  → Gera sessão persistente
  → Retorna token/session_id
  → Cliente envia token em cada requisição
  → Backend valida token e extrai workspace/role
```

### 3. Decisões de Features Premium

**Localização:** Pipeline de Retrieval e Chunking

**Features pendentes:**
- Reranking (Cohere rerank-3)
- HyDE (Hypothetical Document Embeddings)
- Semantic Chunking (LangGraph)

**Problema:** Decisões precisam ser tomadas sem evidência de benefício real.

### 4. Operações de Produção

**Localização:** Monitoramento, logs, alertas

**O que existe:**
- Telemetria básica (`/metrics`, `/health`)
- Logs de query em JSON Lines
- Suíte de testes principal

**O que falta:**
- request_id ponta a ponta
- Métricas por tenant
- SLI/SLO com alertas
- Dashboard executivo

---

## Etapa do Fluxo Afetada

### Etapa 1: Funding / Decisão de Investimento
- **Afetada por:** Dataset inexistente
- **Sintoma:** Não há como justificar investimento com dados objetivos

### Etapa 2: Desenvolvimento de Features
- **Afetada por:** Auth incompleto, features pendentes
- **Sintoma:** Features implementadas sem validação de benefício

### Etapa 3: QA / Validação de Gates
- **Afetada por:** Dataset, observabilidade
- **Sintoma:** Gates validados com critérios subjetivos

### Etapa 4: Operação em Produção
- **Afetada por:** Observabilidade insuficiente
- **Sintoma:** Incapacidade de garantir SLA ou debugar problemas

---

## Atores Envolvidos

### Time de Desenvolvimento
- Backend engineers (FastAPI, Qdrant, retrieval)
- Frontend engineers (Next.js 15)
- Platform engineers (observabilidade, infra)

### Time de Produto
- Product managers (decisões de roadmap)
- Product owners (priorização)

### Time de QA/Data
- QA engineers (validação de gates)
- Data engineers (dataset de avaliação)

### Time de Operações (SRE/DevOps)
- Operações (monitoramento, alertas)
- Infra (Qdrant, storage)

### Stakeholders de Negócio
- Decisores (aprovação de gates)
- Usuários operadores (uso diário)
- Administradores (gestão de tenants)

---

## Ferramentas Atuais

### Backend
- FastAPI (Python) — API REST
- Qdrant — Vector database (dense + sparse)
- OpenAI — Embeddings e LLM
- Filesystem — Armazenamento de corpus

### Frontend
- Next.js 15 (App Router)
- TypeScript
- Tailwind CSS
- Shadcn/ui

### Infraestrutura
- Python 3.x
- Node.js (frontend)
- pnpm (package manager)

### Testing
- pytest (backend)
- Playwright (frontend smoke tests)
- TypeScript compiler

---

## Processo Atual

### Upload de Documento
```
POST /documents/upload
  → Validação de tipo
  → Parse por formato (PDF/DOCX/MD/TXT)
  → Normalização JSON
  → Salvamento em disco
  → Chunking recursivo (1000/200)
  → Geração de embeddings (OpenAI)
  → Indexação no Qdrant (dense + sparse)
  → Retorno de document_id
```

### Query/RAG
```
POST /query
  → Embedding da query (OpenAI)
  → Busca híbrida (dense + sparse + RRF)
  → Seleção top-5
  → Montagem de contexto
  → Geração de resposta (GPT-4o-mini)
  → Retorno com citações e groundedness
```

### Validação de Gate
```
Audição de documento
  → Execução de suite de testes
  → Verificação manual de comportamento
  → Decisão subjetiva de aprovação
```

---

## Workaround Existente

### Dataset
- Sistema usa dataset placeholder sintético
- Hit rate reportado como 100% baseado em dataset não-real
- Gates aprovados sem validação objetiva real

### Auth
- Headers X-Enterprise-* são usados como "autenticação"
- Bootstrap de sessão anônima no frontend
- Login funcional mas não persistente no servidor

### Features Pendentes
- Documentação promete features que não existem no código
- Roadmap inclui items sem evidência de implementação
- Auditorias identificam gap entre docs e código

---

## Próximo Passo

Avançar para Mapeamento do Fluxo Atual (0003_fluxo_atual.md)