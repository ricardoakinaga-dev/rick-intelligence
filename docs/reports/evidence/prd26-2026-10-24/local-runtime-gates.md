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
Foram provisionados o realm **`rick`**, o client confidencial **`rick-api`**
e o usuário **`reader@example.invalid`**, com mappers de `tenant_id`,
`workspace_id` e audiência `rick-api`. O discovery
`/realms/rick/.well-known/openid-configuration` responde e o **password grant**
retorna access/refresh token. O `OIDCVerifier` validou a assinatura RS256, o
issuer e a audiência reais; o `OIDCIdentityProvider` resolveu uma sessão
autoritativa `VETERINARIAN` com tenant `tenant-a`, workspace `workspace-a`,
7 permissões e coleção `col-a`.

**Integração com a API:** um `TestClient` do `create_app` canônico, com
`OIDCIdentityProvider` e o token real do Keycloak, respondeu
`GET /api/v1/auth/me` com **200**, `tenant-a`, `workspace-a`, papel
`VETERINARIAN` e 7 permissões. Chat/auditoria/histórico foram in-memory nesse
probe.

**Limite:** o membership resolver foi estático; não há store de membership,
usuários A/B, revogação/logout, cookies de sessão, multi-réplica ou composição
externa completa. É prova de autenticação OIDC real na borda da API, não de
isolamento multi-tenant completo.

**Achado de infraestrutura:** o `compose.integration.yml` usa `internal: true`,
e o Docker 29 não publica portas de host nessa rede. Para acesso do host foi
usado um override revisado com `internal: false` (porta 18080); isso habilita
egress e deve ser tratado como escolha de laboratório, não como padrão.

## 5. Composição externa local da API

Foi construído `build_external_providers` com clientes reais: PostgreSQL,
Redis, Qdrant, MinIO, Keycloak/OIDC e o provider fixture. O `create_app`
canônico foi criado com essa composição e respondeu:

- `GET /api/v1/auth/me` com token real do Keycloak: **200**, `VETERINARIAN`;
- `GET /health/ready`: **503** fail-closed, com 14 checks `true` e 3 `false`.

Os checks falsos são `redis` e `lease` (capacidade local sem TLS não recebe o
mark `production_safe`) e `embedding_provider` (health check do fixture local).
PostgreSQL, Qdrant, queue, identity, chat, auditoria, histórico, job journal,
object store, retrieval, ingestion, vector store, storage e provider
responderam `true`.

**API HTTP real:** o servidor Uvicorn foi iniciado em `127.0.0.1:18000` com
`RICK_API_COMPOSITION=local_lab_composition:build` e os mesmos serviços. Resultados:
`GET /health/live` **200**; `GET /api/v1/auth/me` com token real do Keycloak
**200**, `VETERINARIAN`, tenant `tenant-a`, workspace `workspace-a`, 7 permissões;
`GET /health/ready` **503** fail-closed (14 checks `true`, 3 `false`).

**Fluxo de chat:** foram semeados tenant `tenant-a`, usuário `user-reader`,
membership `VETERINARIAN` e coleção `col-a` no PostgreSQL. `POST /api/v1/chat`
com o token real respondeu **200** com `conversation_id`/`message_id`, histórico
persistido, `evidence_status=NO_EVIDENCE`, `decision_action=ESCALATE` e resposta
segura sem citações. O caminho não inventou evidência.

**Limite:** a composição não foi admitida em `environment=production`; o 503
é o comportamento correto para Redis local sem TLS e embedding fixture. Não é
prova de readiness de produção. O chat não teve documento indexado; o golden
path de ingestão continua pendente.

## 6. Golden path parcial — achado local

O upload JSON autenticado respondeu **202** e criou um job durável `QUEUED`,
com objeto no MinIO e checksum. O worker externo reivindicou o job, mas falhou
na fase de indexação/verificação com `storage_unavailable`.

Investigação discriminante: `S3ObjectStore.get` direto com o mesmo escopo e
chave retornou os 156 bytes; o objeto e o checksum estão corretos. O job
permaneceu em retry/`QUEUED` e um job anterior virou `DEAD_LETTER`. A causa
provável está na escrita/verificação Qdrant/Knowledge, não no objeto.

**Estado:** golden path **FAIL parcial**; nenhum documento foi publicado. É um
defeito local real a corrigir antes de declarar ingestão ponta a ponta.

## 7. Limitações e próximo passo

- Containers e fixture são efêmeros e loopback; não autorizam promoção.
- O gate de provider usa um servidor OpenAI-compatible local de fixture, não um
  modelo de produção; a evidência é de contrato HTTP, não de qualidade de modelo.
- Golden path, restore, observabilidade e file-security continuam sem
  composição externa autorizada.
- Próximo passo: provisionar realm/client OIDC, manter o laboratório reproduzível,
  executar golden path e restore com composição autorizada e vincular os
  resultados ao pacote de release.

## 8. Artefatos locais

`.runtime/phase-2/postgres-runtime-gate.json`,
`.runtime/phase-3/multi-worker-runtime-gate.json`,
`.runtime/phase-2/redis-runtime-gate.json`,
`.runtime/phase-2/object-qdrant-runtime-gate.json`,
`.runtime/phase-3/provider-runtime-gate.json`. Composição reproduzível:
`scripts/phase11/local_lab_composition.py`; o servidor local usa
`RICK_API_COMPOSITION=local_lab_composition:build`.
