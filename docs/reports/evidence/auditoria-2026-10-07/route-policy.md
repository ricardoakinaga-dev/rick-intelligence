# Evidência de correção — política default-deny de rotas (AUD07-13)

**Data:** 2026-10-07. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = b52f32c141916a2ea3af1a6b913bd91f380606e0` (*Record alternate Docker endpoint probe*).
**Ambiente:** Python 3.12.3 (`.runtime/venvs/cvg`), Node v24.20.0 / npm 11.19.0 no host.
**Achado de origem:** A04. **Continuação:** [`fix-gates-1.md`](fix-gates-1.md) (M0) e
[`fix-gates-2.md`](fix-gates-2.md) (AUD07-10…12).

## 1. Problema

A política default-deny de rotas era **estruturalmente incompleta**:

1. **Permissão fabricada.** Cinco rotas declaravam `permission: "session:self"`, um id que
   não existe em `rick_authorization.CANONICAL_PERMISSION_IDS` e que nenhum papel do
   motor de autorização concede. Declarar `authenticated` **não** é declarar a política
   que o handler aplica — o teste antigo não cobria isso porque só checava a *forma* da
   entrada, não a *semântica*.
2. **Política documentada ≠ política imposta.** `POST /api/v1/conversations` exige de fato
   `history.read` **e** `chat.query` no handler; `POST /api/v1/audit/operations/{id}/reconcile`
   exige `audit.read` **e** `users.manage`. O registro nomeava apenas uma das duas.
3. **Escopo implícito.** `GET /api/v1/audit/operations` e `GET .../{operation_id}` são
   auto-restritas por design (`operator = has_permission(...)`), mas o registro dizia
   "precisa de permissão" sem nomear o que; hoje o escopo é uma decisão explícita.
4. **Teste de paridade vazio.** `test_registry_covers_all_app_routes` percorria
   `app.routes` — em FastAPI 0.141 os roteadores aparecem como `_IncludedRouter` (sem
   `.path`, sem `.endpoint`), logo o laço **nunca encontrava nenhuma rota** e comparava um
   conjunto vazio com outro. O teste passava sem verificar nada, e
   `test_protected_route_payloads_match_endpoint_contracts` tinha o mesmo defeito.
5. **Sem prova de imposição.** Nenhum teste enviava uma requisição como sessão que
   *não* detém a permissão declarada e esperava `403`.

## 2. O que mudou

### `apps/api/src/routes/__init__.py` (registro e contrato de declaração)

| Símbolo | Papel |
|---|---|
| `permission_set(entry) -> frozenset[str]` | normaliza `str \| list \| None` para o conjunto declarado (única forma de leitura usada por testes e docs) |
| `SELF_SCOPED_PATHS` | allowlist explícita dos 7 caminhos auto-restritos; pertencer a ela é decisão de política, nunca padrão |
| `permission: None, scope: "self"` | substitui a permissão fabricada nas 5 rotas de sessão/operador e declara o escopo de `GET /api/v1/audit/operations{,/{id}}` |
| `permission: ["history.read", "chat.query"]` | `POST /api/v1/conversations` passa a nomear as duas permissões que o handler nega |
| `permission: ["audit.read", "users.manage"]` | `POST /api/v1/audit/operations/{id}/reconcile` idem |

Nenhuma rota declara `permission` e `scope` ao mesmo tempo; um conjunto vazio implica
necessariamente `scope == "self"` **e** presença em `SELF_SCOPED_PATHS`.

### `apps/api/tests/test_route_policy.py` (três checagens independentes)

| Teste | O que prova |
|---|---|
| `_mounted_handlers(app)` | paridade resolvida via `routes.ROUTERS`; falha se `create_app` montar exatamente os roteadores do registro (ids por `id()` — `APIRouter` é inconstante) |
| `test_registry_covers_all_app_routes` | paridade **bijetiva**: entrada sem handler e handler sem entrada falham nos dois sentidos |
| `test_every_non_public_route_has_policy` | autenticação de sessão, catálogo de permissões, proibição de misturar `permission`+`scope`, escopo vazio ⇒ `SELF_SCOPED_PATHS` |
| `test_declared_permission_is_what_the_handler_enforces` (51 casos) | caminhada estática (`ast`) de `has_permission`/`require_permission` no endpoint **mais** os alvos delegados (`_DELEGATED_ENFORCEMENT`: `chat` → `ChatApplicationService.chat`/`.stream_events`; `reconcile` → `services.audit_operations.reconcile_operation`) é **igual** ao conjunto declarado |
| `test_session_route_denies_a_session_without_its_permission` (51 casos) | prova viva: sessão VET (`GET /api/v1/auth/me`) não detém `declared - held` ⇒ `403`; detém ⇒ resposta ≠ `403` |
| `test_self_scoped_routes_serve_the_caller_and_refuse_foreign_targets` | as 5 rotas auto-restritas respondem ao próprio chamador; `revoke` de `session_id`/`user_id` estrangeiro ⇒ `403` (limite de escopo, não lacuna de papel) |
| `test_self_service_session_routes_work_for_the_caller` | `revoke` da própria sessão ⇒ `200`, `logout` ⇒ `200` e sessão revogada ⇒ `401` |
| `test_protected_route_payloads_match_endpoint_contracts` | agora percorre os handlers reais (antes: laço sobre `app.routes`, nunca executado) |

`POST /api/v1/auth/logout` continua fora de `_PROTECTED_ROUTES` (invalida a sessão) e é
cuberto pelo teste estrutural + `test_self_service_session_routes_work_for_the_caller`.

### `docs/architecture/api-security.md`

A seção *Default-deny + allowlist* passa a documentar o modelo de declaração
(`permission` escalar/lista, `scope: "self"` + `SELF_SCOPED_PATHS`, paridade via
`ROUTERS`, dupla prova de imposição) e o tópico de cobertura ganha o limite de escopo.

## 3. Discriminação (a nova checagem falha sem a correção)

Script: `/tmp/opencode/discriminate_a04.sh` — aplica a regressão, roda
`apps/api/tests/test_route_policy.py`, restaura e verifica o sha256 de
`apps/api/src/routes/__init__.py`.

| Experimento | Mudança | exit | Resultado |
|---|---|---|---|
| [`exp-a04.txt`](discrimination/exp-a04.txt) | restaura `session:self` e as permissões únicas antigas | 1 | **15 falharam**, 145 passaram — catálogo, declarado≠imposto (10 rotas) e prova viva (6 rotas) |
| [`exp-parity.txt`](discrimination/exp-parity.txt) | remove a entrada `POST /api/v1/search` do registro | 1 | **2 falharam** — paridade e conjunto esperado de corpos |
| [`control-a04.txt`](discrimination/control-a04.txt) | restauração verificada por hash | 0 | **160 passaram**, 0 falharam |

Regressões de reprodução (`repro`, os dois bugs de segurança fechados em M1):
`repro_a02`/`repro_a03` permanecem `exit 1` sem a correção e `exit 0` com ela.

## 4. Gates

Comandos executados com `PYTHONPATH` canônico
(`apps/api/src`, `apps/worker`, `packages/*/src`):

| Gate | exit | Resultado |
|---|---|---|
| `make api-test` | 0 | **1702 passed, 18 skipped** (era 1597 → +105) |
| `make api-security` | 0 | **181 passed** (era 76 → +105) |
| `make ci` | 0 | 17 linhas `<==` |
| `make test` | 0 | 7 linhas `<==` — pacotes/API/diferencial, worker **734**, validadores/runner **472** |
| `make validate` | 0 | — |
| `make ops-static` | 0 | 298 passed |
| `make api-contract` | 0 | OpenAPI (55 paths) |
| `make compose-static` | 0 | 16 serviços ×2 |
| `make lint` | 0 | web ESLint + compilação `scripts`/`packages` |
| `make typecheck` | 0 | web `tsc --noEmit` |

Nenhuma suíte foi reduzida, nenhum teste marcado como ignorado para passar.

## 5. Cobertura final do registro

- **61** entradas; **7** públicas, **2** compat (`/v1/*` com API key), **1** fora da
  varredura comportamental (`logout`), **51** rotas protegidas testadas de 3 formas.
- **7** rotas com `scope: "self"` = exatamente `SELF_SCOPED_PATHS`.
- **2** rotas com permissão múltipla; **24** ids no catálogo canônico.
- Contagens conferidas em runtime contra `routes.ROUTE_REGISTRY` e
  `core.security.{PUBLIC_ALLOWLIST,COMPAT_API_KEY_PATHS}`.

## 6. Limites

- A igualdade declarado↔imposto é estática: delegação para além de
  `_DELEGATED_ENFORCEMENT` (ex. `chat` → `chat_service`) precisa ser **declarada** ali
  para ser comparada; esquecer de declarar gera `declared ≠ enforced` (falha fechada).
  A prova viva cobre o resto: qualquer permissão exigida de verdade e não declarada
  nega a sessão de teste e derruba o caso correspondente.
- `GET /metrics` é público no registro atual (já era assim); está fora de
  `apps/api` e não é escopo de A04.
- Fora do escopo: A18/rotas públicas de infraestrutura e a comparação de payloads de
  corpo com OpenAPI — o segundo hoje usa apenas os modelos Pydantic declarados no
  teste, não o documento OpenAPI.
