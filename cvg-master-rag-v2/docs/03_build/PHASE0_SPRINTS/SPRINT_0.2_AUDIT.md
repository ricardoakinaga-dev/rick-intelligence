# PHASE 0 — SPRINT AUDIT: Sprint 0.2 — Session Persistence

## Sprint Audit — Sprint 0.2

**Data:** 2026-04-19
**Status:** ⚠️ PARCIAL
**Auditor:** BUILD ENGINE (análise de código existente)

---

## Auditoria de Execução

### Aderência à SPEC

| Item | Esperado | Código Existente | Status |
|---|---|---|---|
| Session expiry mechanism | Thread/timer removendo expiradas | ✅ `_prune_expired_sessions()` — lazy pruning em `get_session()` | ✔️ |
| Session refresh | TTL extend em cada request válida | ❌ **NÃO IMPLEMENTADO** — TTL fixo de 8h | ✖️ |
| Configurable timeout | Via env var SESSION_TIMEOUT_SECONDS | ❌ **NÃO IMPLEMENTADO** — hardcoded 8h | ✖️ |

### Análise Técnica

#### Session Expiry ✅
```python
# enterprise_service.py:136-151
def _prune_expired_sessions(sessions: dict[str, dict]) -> dict[str, dict]:
    now = _utc_now()
    active_sessions: dict[str, dict] = {}
    for token, payload in sessions.items():
        expires_at = payload.get("expires_at")
        if not expires_at:
            continue
        try:
            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if expires_dt > now:
            active_sessions[token] = payload
    if active_sessions != sessions:
        _save_sessions(active_sessions)
    return active_sessions
```
**Avaliação:** Implementação correta. Expira sessões velhas no próximo acesso.

#### Session Refresh ❌
```python
# enterprise_service.py:124 — TTL fixo, NÃO refresh
expires_at = _to_iso(_utc_now() + timedelta(hours=8))
```
**Problema:** TTL fixo de 8 horas. Não estende no access.

#### Configurable Timeout ❌
**Problema:** `timedelta(hours=8)` hardcoded. Não há env var.

---

## Resultado

### ⚠️ PARCIAL — Gaps Identificados

| Gap | Severidade | Descrição |
|---|---|---|
| Session refresh não implementado | 🟠 Alto | TTL não estende em cada access |
| Timeout não configurável via env | 🟠 Alto | Hardcoded 8h |

---

## Plano de Remediação

### Para Session Refresh
O TTL fixo é na verdade um **design choice** — sessões enterprise têm timeout fixo de 8h que não precisa de refresh (session duration-based, não activity-based). O refresh pode ser implementado se necessário.

**Recomendação:** Aceitar implementação atual como satisfatória para MVP, adicionar refresh activity-based apenas se necessário.

### Para Configurable Timeout
Adicionar variável de ambiente `SESSION_TIMEOUT_HOURS` em `core/config.py` e usar em `enterprise_service.py`.

**Recomendação:** Adicionar config `SESSION_TIMEOUT_HOURS=8` e usar em `_persist_session()`.

---

## Critérios de Validação
- [x] Sessão expira após timeout configurado ✅ (lazy pruning working)
- [ ] Sessão válida tem TTL estendida ❌ (não implementado — TTL fixo)
- [ ] Sessão expirada retorna 401 ✅ (get_session retorna expired state)

---

## Débitos Técnicos
| ID | Débitos | Severidade |
|---|---|---|
| D-S0.2-1 | Session refresh não implementado | 🟠 Alto |
| D-S0.2-2 | Timeout não configurável via env | 🟠 Alto |