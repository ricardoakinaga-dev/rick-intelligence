# AUD24 — laboratório Docker descartável (M5 parcial)

**Data:** 24/10/2026. **Autoridade:** pedido humano “lab completo + migrations” nesta sessão. **Escopo:** containers loopback descartáveis; nenhuma produção, nenhum segredo real.
**Status:** evidência local de runtime; **não** é promoção, restore, carga ou GO.

## 1. Ambiente efêmero

| Serviço | Imagem | Porta local | Resultado |
|---|---|---|---|
| PostgreSQL | `postgres:16.4-alpine` | 55432 | pronto; 11 migrations aplicadas |
| Redis | `redis:7.4-alpine` (auth) | 56379 | pronto |
| Qdrant | `qdrant/qdrant:v1.12.5` | 56333 | pronto |
| MinIO | `quay.io/minio/minio:latest` | 59010 | pronto; bucket `rick-test` |

Nenhum container existente do host foi alterado; todos foram criados com prefixo `rick-aud24-*` e serão removidos ao fim do lab.

## 2. PostgreSQL

Comando: `make postgres-runtime` com DSN loopback e `PYTHON=.runtime/venvs/cvg/bin/python`.

**Ajustes de gate necessários e aplicados:**
- `EXPECTED_MIGRATIONS` era fixo em 0001–0006; agora deriva dos arquivos numerados reais (0001–0011).
- o fixture de lease expirado violava `lease_until > lease_acquired_at`; agora recua ambos os timestamps preservando a invariante.

**Resultados:** migrations **PASS**; migration-history 11 **PASS**; constraints **PASS**; indexes **PASS**; 6 query plans **PASS**; claim concorrente, enqueue idempotente, fencing de lease, dead-letter, replay, ack transaction, rollback e retention **PASS**; health **PASS**.
**Residual:** `crash-before-commit` e `crash-after-commit` `BLOCKED_EXTERNAL` — exigem harness de crash real, não inferido. Status do gate: `BLOCKED_EXTERNAL`, sem FAIL.

## 3. Redis

Comando: `make redis-runtime` com `redis://default:***@127.0.0.1:56379/0`.

**Resultados:** health, isolamento de namespace, heartbeat, fencing de owner, rate-limit atômico/replay e reconnect **PASS**.
**Residual:** `circuit-breaker-recovery` `BLOCKED_EXTERNAL` (fault endpoint real); capability de produção `PARTIAL` por ausência de TLS. Nenhum FAIL.

## 4. S3 e Qdrant

Comando: `make object-qdrant-runtime` com endpoint/bucket/região/credenciais loopback.

**S3 (MinIO):** health, PUT streaming/idempotente, HEAD checksum/content-length, GET integridade, limites, acesso privado, isolamento tenant/workspace, delete/idempotência, restore-negative e cleanup — **todos PASS**.
**Qdrant:** health, collection preflight/schema/indexes, upsert, state, filtros tenant/workspace/collection, cross-scope negativo, delete/idempotência, restore-negative, alias create/read/swap, rebuild/reindex, partial-failure e cleanup — **todos PASS**.
**Residual:** `retry-circuit` e `timeout` exigem fault endpoint real (`BLOCKED_EXTERNAL`). Nenhum FAIL.

## 5. Limites

- Não executei golden ingestion E2E, restore integrado, provider real, observabilidade distribuída, carga/chaos/soak ou release.
- Containers são efêmeros e loopback; não são prova de topologia de produção.
- O lab não autoriza promoção; `NO-GO` permanece.
