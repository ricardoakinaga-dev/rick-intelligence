# 0105 — Máquina de Estados e Fluxos

## Estados do Documento

### Estado: Parsing

```
[Upload] → PARSING → [Sucesso] → PARSED
                      → [Falha] → FAILED
                      → [Parcial] → PARTIAL
```

**Transições:**
- UPLOAD → PARSING (início do parse)
- PARSING → PARSED (parse bem sucedido)
- PARSING → FAILED (parse falhou completamente)
- PARSING → PARTIAL (parse parcialmente bem)

**Ações válidas em PARSING:**
- Nenhuma (estado transitório)

---

### Estado: Parsed

```
[Parsed] → CHUNKING → [Sucesso] → INDEXED
                       → [Falha] → PARTIAL (retry possible)
```

**Transições:**
- PARSED → CHUNKING (início do chunking)
- PARSED → PARTIAL (chunking falhou, pode retry)

**Ações válidas em PARSED:**
- Iniciar chunking
- Cancelar (soft delete)

---

### Estado: Indexed

```
[Indexed] ← [Chunks indexados no Qdrant]
```

**Transições:**
- INDEXED é estado final de sucesso
- Pode voltar para PARSED se reindex for necessário

**Ações válidas em INDEXED:**
- Fazer queries
- Deletar (soft delete → archive)

---

### Estado: Failed

```
[Failed] → [Motivo registrado]
```

**Transições:**
- FAILED é estado terminal de falha
- Não pode ir para INDEXED automaticamente

**Ações válidas em FAILED:**
- Ver motivo da falha
- Upload novo documento

---

## Estados da Sessão

### Estado: New → Valid

```
[Login] → NEW_SESSION → [Credenciais válidas] → SESSION_VALID
                        → [Inválidas] → REJECTED
```

**Transições:**
- NEW_SESSION → SESSION_VALID (sucesso)
- NEW_SESSION → REJECTED (falha)

**Ações em SESSION_VALID:**
- Acessar endpoints protegidos
- Executar queries

---

### Estado: Valid → Expired

```
[SESSION_VALID] → [Timeout ou Logout] → EXPIRED
```

**Transições:**
- SESSION_VALID → EXPIRED (timeout ou logout)

**Ações em EXPIRED:**
- Redirect para login
- Não pode acessar endpoints

---

## Estados do Tenant

### Estado: Active / Inactive

```
[Tenant] → ACTIVE ↔ INACTIVE
```

**Transições:**
- ACTIVE → INACTIVE (desativado por admin)
- INACTIVE → ACTIVE (reativado por admin)

**Ações em ACTIVE:**
- CRUD operations
- Users can login

**Ações em INACTIVE:**
- Login bloqueado
- Dados mantidos

---

## Estados do Retrieval

### Fluxo de Retrieval

```
[Query Received]
       ↓
[Check Threshold]
       ↓
 score >= threshold? → YES → [Montar contexto] → [LLM] → [Response]
       ↓ NO
[Low Confidence] → [Response "não sei"]
```

**Transições:**
- QUERY → LOW_CONFIDENCE (score < threshold)
- QUERY → RESPONSE (score >= threshold, LLM called)

**Exceções:**
- Qdrant Offline → Error 500
- LLM Timeout → Error 504
- Query Empty → Error 400

---

## Estados de Audit

### Log de Evento

```
[Admin Action] → AUDIT_LOG → [Armazenado]
```

**Informações em AUDIT_LOG:**
- request_id
- timestamp
- user_id
- action
- target (tenant/user)
- result (success/failure)

---

## Transições Proibidas

1. FAILED → INDEXED (não pode pular para sucesso)
2. EXPIRED → SESSION_VALID (precisa re-login)
3. INACTIVE Tenant → Admin operations (bloqueado)

---

## Falhas e Recuperação

### Falha de Parse
- Registrar motivo
- Document status = failed
- Retornar erro 413 com reason

### Falha de Indexação
- Chunking feito, mas vetores não indexados
- Status = partial
- Retry via reindex script

### Falha de Qdrant
- Health check retorna degraded
- Queries retornam erro 500
- Recovery: restart Qdrant, reindex

---

## Próximo Passo

Avançar para 0106_contratos_de_aplicacao.md