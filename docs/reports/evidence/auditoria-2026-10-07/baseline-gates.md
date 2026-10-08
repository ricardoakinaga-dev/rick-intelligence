# Baseline selada — auditoria AUD07 (07/10/2026)

**Data/hora UTC:** 2026-10-07, execução iniciada por volta de 08:40 UTC.
**SHA:** `b52f32c` (*Record alternate Docker endpoint probe*).
**Worktree:** 892 mudanças pendentes — 234 não rastreadas (`??`), 219 modificadas não indexadas
(` M`) e **439 remoções já indexadas** (`D `) correspondentes aos três componentes legados
`cvg-master-rag-v2/` (397), `rick-professor/` (34) e `modulo-redis-locker/` (8).
**Ambiente:** Python 3.12 do sistema, Node/npm locais, venv `.runtime/venvs/cvg`.

Esta página registra o estado **antes** de qualquer correção AUD07. Os comandos abaixo são a
referência para o gate de passagem G2 do
[roadmap](../../../roadmap-auditoria-2026-10-07.md).

## Gates obrigatórios na baseline

| Gate | Comando | Exit | Causa raiz | Achado |
|---|---|---|---|---|
| Validação | `make validate` | **1** | `check_boundaries.py`: `missing preserved component` × 3 (`cvg-master-rag-v2`, `rick-professor`, `modulo-redis-locker`) | A01 |
| Lint | `make lint` | **2** | 406 erros e 5.053 warnings de eslint; **todos** os 406 erros estão sob `apps/web/.next-audit-20261006/` | A05 |
| Testes rápidos | `make test-fast` | **2** | `ModuleNotFoundError: jsonschema` na regressão Phase 1.5 + lane `CVG focused contract/security regression` → `NOT AVAILABLE (missing executable)` (caminhos legados) + boundary validator exit 1 | A08, A01 |
| Segurança de API | `make api-security` | **2** | 1 failed, 72 passed — `test_route_policy.py::test_registry_covers_all_app_routes` | A04 |
| Build | `make build` | **2** | `canonical web production build: exit 0`; falham `Professor build`, `CVG frontend production build` e `CVG Python compilation` → `NOT AVAILABLE (missing executable)` | A01 |

**Diagnóstico consolidado:** os cinco gates vermelhos reduzem-se a **três causas**: A01
(componentes legados removidos sem reconciliar consumidores), A04 (registro de rotas incompleto)
e A05 (artefato de build obsoleto). A08 (`jsonschema` fora do lock/venv) derruba `test-fast`.

## Reproduções discriminantes preservadas

Ambas as reproduções saem com **exit 0** na baseline (defeito presente) e **exit 1** quando o
defeito estiver corrigido.

### A02 — coleção arquivada continua pesquisável

```
python3 docs/reports/evidence/auditoria-2026-10-07/repro/repro_a02_archive_search.py
```

Saída registrada em [`repro/a02-baseline.json`](repro/a02-baseline.json):

| Passo | Status | Itens |
|---|---|---|
| `POST /api/v1/search` (antes) | 200 | 1 |
| `POST /api/v1/collections/rag_phase0/archive` | 200 | `status=archived` |
| `POST /api/v1/search` escopada (depois) | 200 | **1** |
| `POST /api/v1/search` global (depois) | 200 | **1** |

`still_searchable_after_archive: true`. A projeção pública de `routes/search.py` nunca consulta
autoridade de lifecycle de coleção/documento.

### A03 — idempotência cruza conversas

```
python3 docs/reports/evidence/auditoria-2026-10-07/repro/repro_a03_idempotency.py
```

Saída registrada em [`repro/a03-baseline.json`](repro/a03-baseline.json):

| Turno | `conversation_id` | `answer` | `message_id` |
|---|---|---|---|
| `ALPHA` em `conv-A` | `conv-A` | `ANSWER_FOR::ALPHA` | `msg-9fd6ef9938fd` |
| retry idêntico em `conv-A` | `conv-A` | `ANSWER_FOR::ALPHA` | `msg-9fd6ef9938fd` |
| `BETA` em `conv-B`, mesma chave | **`conv-A`** | **`ANSWER_FOR::ALPHA`** | `msg-9fd6ef9938fd` |

`cross_conversation_replay_defect: true`. `ChatApplicationService.chat` consulta
`history.get_idempotent(session=..., idempotency_key=...)`, que indexa apenas por
`(tenant_id, workspace_id, user_id, idempotency_key)` — sem `conversation_id` e sem
fingerprint do turno — e `_cached_response` devolve a resposta armazenada sem revalidar
destino.

## Regras de preservação

1. Os scripts em [`repro/`](repro/) são evidência da baseline e **não podem ser editados** para
   tornar um gate verde; a correção acontece no código e nas regressões de `apps/api/tests/`.
2. Os JSONs de saída são o "antes"; as regressões de AUD07-12 registram o "depois".
3. Nenhuma pasta de teste, threshold ou `skip` foi alterado nesta baseline.

## Limites

- Nenhum serviço externo (PostgreSQL, Redis, Qdrant, object-storage, provider) foi executado.
  Toda evidência acima é local e in-process.
- `make api-test`, `make build` e os lanes de navegador **não** faziam parte desta captura de
  baseline; foram executados em momentos anteriores e constam do
  [relatório](../../../reports/relatorio-auditoria-2026-10-07.md).
