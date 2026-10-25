# PRD26 — gates de runtime local (loopback)

**Data:** 24/10/2026, 23:35 America/Sao_Paulo · **UTC:** 25/10/2026, 02:35
**HEAD:** `dc79ec6f829b5690c6206b6ccba67021a78fcf35` · **Branch:** `archive/local-runtime-20261011`
**Worktree:** 15 entradas (documentos PRD26/AVAL24, evidência, correções locais).
**Status:** `VERIFY` local — **não é `DONE`**, não é produção, não há aceite formal nem release.

## 1. Laboratório loopback descartável

| Serviço | Imagem | Endpoint local | Resultado |
|---|---|---|---|
| PostgreSQL | `postgres:16.4-alpine` | `127.0.0.1:55432` | 11 migrations e gates de fila |
| Redis | `redis:7.4-alpine` | `127.0.0.1:56379` | lease, rate limit, fencing e fault recovery |
| Qdrant | `qdrant/qdrant:v1.12.5` | `127.0.0.1:56333` | coleção, filtros ACL, alias/rebuild |
| MinIO | `quay.io/minio/minio:latest` | `127.0.0.1:59010` | bucket `rick-test`, PUT/HEAD/GET/delete |
| Qdrant fault endpoints | script local | `127.0.0.1:56334/56335` | 500 real e timeout real |
| Provider fixture | handler OpenAI-compatible local | `127.0.0.1:58000/v1` | chat, stream, tools, JSON, embeddings |
| Keycloak IdP | `quay.io/keycloak/keycloak:26.7.3` | `127.0.0.1:18080` | realm master responde 200; dev mode |

Credenciais e DSNs usam valores descartáveis de laboratório; não são secrets de
produção e não são reproduzidos neste documento.

## 2. Gates executados

| Gate | Comando | Exit | Resultado |
|---|---|---:|---|
| PostgreSQL | `make postgres-runtime` | 0 | **PASS** — migrations, constraints, índices, 6 planos, claim concorrente, idempotência, fencing, DLQ/replay, rollback, retention, crash before/after commit |
| Multi-worker | `make multi-worker-runtime` | 0 | **PASS** — matriz de crash **8/8** |
| Redis | `make redis-runtime` | 0 | **PASS** — health, namespace, heartbeat, fencing, rate limit atômico/replay, reconnect, fault recovery; `production_safe=false` por ausência de TLS |
| Objeto + Qdrant | `make object-qdrant-runtime` | 0 | **PASS** — S3 e vetor, isolamento tenant/workspace, ACL negativa, alias/rebuild, retry/timeout reais |
| Provider | `make provider-runtime` | 0 | **PASS** local — saúde, chat, streaming, JSON, tool call, embeddings; `production_safe=false` por HTTP/local sem TLS |
| CI local | `make ci` | 0 | **PASS** — validate, fast tests, lint, typecheck e build de produção |

## 3. O que isso prova — e o que não prova

**Prova:** os adaptadores canônicos funcionam contra serviços reais de rede
loopback, com migrations reais, concorrência entre processos, falhas reais de
rede e isolamento de escopo. Não é mock de transporte nem teste hermético.

**Não prova:** topologia de produção, TLS/auth de produção, IdP externo,
provider comercial, golden path completo de ingestão, restore/DR integrado,
observabilidade distribuída, performance/chaos/soak, CI remoto, scans,
assinatura, release packet ou decisão humana. `production_safe=false` é
explícito em Redis, objeto/vetor e provider.

## 4. IdP local (Keycloak)

O Keycloak **26.7.3** foi instalado e iniciado em modo dev, com admin local
descartável. `GET /realms/master` responde **200** em `127.0.0.1:18080`.
O realm, client OIDC, memberships e usuários sintéticos A/B **não** foram
provisionados; a aplicação ainda não foi apontada para este IdP. É instalação
local, não prova de login/revogação.

**Achado de infraestrutura:** o `compose.integration.yml` usa `internal: true`,
e o Docker 29 não publica portas de host nessa rede. Para acesso do host foi
usado um override revisado com `internal: false` (porta 18080); isso habilita
egress e deve ser tratado como escolha de laboratório, não como padrão.

## 5. Limitações e próximo passo

- Containers e fixture são efêmeros e loopback; não autorizam promoção.
- O gate de provider usa um servidor OpenAI-compatible local de fixture, não um
  modelo de produção; a evidência é de contrato HTTP, não de qualidade de modelo.
- Golden path, restore, observabilidade e file-security continuam sem
  composição externa autorizada.
- Próximo passo: provisionar realm/client OIDC, manter o laboratório reproduzível,
  executar golden path e restore com composição autorizada e vincular os
  resultados ao pacote de release.

## 6. Artefatos locais

`.runtime/phase-2/postgres-runtime-gate.json`,
`.runtime/phase-3/multi-worker-runtime-gate.json`,
`.runtime/phase-2/redis-runtime-gate.json`,
`.runtime/phase-2/object-qdrant-runtime-gate.json`,
`.runtime/phase-3/provider-runtime-gate.json`.
