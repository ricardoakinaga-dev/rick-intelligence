# 0004 — Fluxo Atual

## Resumo do Fluxo Atual

Consulte `/docs/00_discovery/0003_fluxo_atual.md` para detalhamento completo.

---

## Pipeline Principal

### 1. Ingestão
```
Upload → Validação → Parse → Normalização → Chunking → Indexação → Retorno
```

### 2. Retrieval
```
Query → Embedding → Busca Densa → Busca Esparsa → RRF → Filtragem → Retorno
```

### 3. Query (RAG)
```
Query → Retrieval → Low Confidence Check → Contexto → LLM → Resposta → Logging
```

---

## Fluxo de Autenticação (Atual)

```
Cliente envia X-Enterprise-Workspace-ID e X-Enterprise-Role
  → Backend confia nos headers
  → Não há autenticação real no servidor
  → Sessão não persiste entre reinicializações
```

---

## Fluxo de Autenticação (Esperado)

```
Cliente faz login
  → Backend valida credenciais
  → Gera sessão persistente
  → Retorna token/session_id
  → Cliente envia token em cada requisição
  → Backend valida token e extrai workspace/role
```

---

## Próximo Passo

Avançar para 0005_riscos_hipoteses.md