# Evidência de correção — gates M1 (AUD07-10, AUD07-11, AUD07-12)

**Data:** 2026-10-07. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = b52f32c141916a2ea3af1a6b913bd91f380606e0` (*Record alternate Docker endpoint probe*).
**Ambiente:** Python 3.12.3 (`.runtime/venvs/cvg`), Node v24.20.0 / npm 11.19.0 no host.

Esta página continua [`fix-gates-1.md`](fix-gates-1.md) (M0, AUD07-03…09). Ela cobre as duas
correções de segurança/autorização de M1 e as regressões que as tornam obrigatórias.

## 1. O que foi corrigido

### AUD07-10 — idempotência não pode cruzar conversas (A03)

**Sintoma:** a chave idempotente era indexada só por `(tenant_id, workspace_id, user_id,
idempotency_key)`; a mesma chave repetida em outra conversa devolvia a resposta armazenada
da conversa anterior.

**Decisão canônica** em `apps/api/src/services/chat_history.py`:

| Símbolo | Papel |
|---|---|
| `IdempotencyConflict` | erro de domínio que a camada de serviço converte em `409 conflict` |
| `idempotency_fingerprint(*, session, message, collection_id)` | sha256 sobre escopo + mensagem normalizada (truncada em 20000 chars) + `collection_id` |
| `require_idempotent_match(...)` | igualdade exata de todos os campos; divergência ⇒ conflito |
| `expectation_requested` / `pack_idempotent_record` / `unpack_idempotent_record` | registro plano legado ⇒ fingerprint `None` ⇒ falha fechada |

Os três stores (`in-memory`, `SQLite`, `PostgreSQL`) ganharam `conversation_id=` e
`fingerprint=` em `get_idempotent` / `append` / `record_stream_outcome`. O SQLite subiu
`SCHEMA_VERSION = 2` com `chat_turns.idempotency_fingerprint TEXT` nullable (migração
idempotente); o PostgreSQL guarda o fingerprint como campo irmão `metadata["idempotency_fingerprint"]`
(JSONB), sem DDL, e `_session()` **relança `IdempotencyConflict` antes** dos `except
PostgresChatHistoryError` / `except Exception` para não mascarar o 409.

Camada de serviço (`chat_service.py`): `_turn_fingerprint`, `_replayable_turn` (leitor com
kwargs + `IdempotencyConflict → ApiError("conflict")` + pós-verificação de `conversation_id`),
`_persisted_turn` e `_record_stream_outcome` (escada de 3 passos com fallback por assinatura).
Duas barreiras ativas: a camada de serviço (essencial) e a do store (ativa só quando há
expectativa explícita).

### AUD07-11 — busca em coleção arquivada (A02)

**Sintoma:** `routes/search.py` nunca consultava o lifecycle da coleção/documento;
`archive → search` continuava devolvendo itens.

**Decisão canônica:** a autoridade de lifecycle fica em
`apps/api/src/services/knowledge_service.py` — o mesmo store que catálogo e
`professor_backend.py` já consultam (`get_collection(workspace_id, collection_id, *,
tenant_id)`, `get_document(document_id, *, tenant_id=None, workspace_id=None)`, assinaturas
idênticas nos três stores):

| Símbolo | Papel |
|---|---|
| `LifecycleAuthorityError` | autoridade **indisponível** ou que **lançou** ⇒ quem chama nega, nunca ignora |
| `resolve_collection_state(...) -> "active" \| "inactive"` | `None`/escopo divergente/status ≠ `active` ⇒ `inactive` |
| `resolve_document_state(...) -> "published" \| "inactive"` | idem para `status == "published"` |

`apps/api/src/services/retrieval_service.py` aplica a autoridade em **dois** pontos:

- **admissão** (`_admitted`): grants concretos são resolvidos *antes* de tocar o índice;
  uma consulta sem nenhum grant ativo devolve `_lifecycle_denied` sem custo.
  `["*"]` não pode ser resolvido na admissão e passa adiante.
- **projeção** (`_projectable`): cada item resolve `collection_id`/`document_id` próprios;
  o wildcard é resolvido por item, então uma coleção arquivada some mesmo sob grant global.

Cache de lifecycle é **por consulta** (dict dentro de `retrieve()`), deliberadamente sem
cache entre requisições: um índice quente não pode continuar servindo coleção arquivada.
Sem `tenant_id`/`workspace_id`/`collection_id`/`document_id` concretos na evidência ⇒ a
evidência não é projetável (falha fechada).

`routes/search.py` não precisou mudar: seu `except Exception → ApiError("retrieval_failed")`
(500) captura `LifecycleAuthorityError`, e `core/errors.py` registra
`unhandled_exception_handler` para `Exception` como rede de segurança.

### AUD07-12 — regressões públicas e discriminantes

| Suite | Lane | Conteúdo |
|---|---|---|
| `apps/api/tests/test_idempotency_scope.py` | `apps/api` | replay idêntico, conflito em outra conversa/mensagem/coleção, stream e HTTP 409 (memória + SQLite) |
| `apps/api/tests/test_search_lifecycle.py` (nova) | `apps/api` | 8 casos: ranking ativo preservado; arquivada em índice **quente** e **frio**; documento não publicado; autoridade indisponível; backend remoto; HTTP escopado/global; restart SQLite |
| `packages/knowledge/tests/test_lifecycle_authority_contract.py` (nova) | `packages/knowledge` | 7 casos: arquivo persiste para um leitor posterior (memória/SQLite), segundo handle sobre o mesmo arquivo, escopo nunca é cruzado, status de documento visível ao próximo leitor |
| `packages/retrieval/tests/test_evidence_lifecycle_keys.py` (nova) | `packages/retrieval` | 2 casos: as quatro chaves que o gate da API lê sobem em toda evidência; candidatos de escopo estranho nunca chegam à projeção |

Ajustes de regressões existentes (não enfraquecidos — o critério foi tornado explícito):
`test_aud03_retrieval_admission.py` agora usa um store com coleção `allowed` **ativa** e
asserção `authorization != "lifecycle_denied"`; `test_phase16_retrieval.py` ganhou
`_active_store()` + documento `doc-phase16-beta`, coleção ativa no teste de *refresh* e a
asserção reforçada `assert "doc-live" in {...}`.

## 2. Discriminação (o teste falha quando o fix é revertido)

Os dois fixes foram revertidos **por anexação de overrides no fim do módulo** (nada de
edição frágil), a suíte completa `apps/api/tests` foi executada, e os arquivos foram
restaurados a partir de cópia com **hash verificado**.

| Experimento | Mutação | Resultado | Artefato |
|---|---|---|---|
| `exp-a02` | `knowledge_service.resolve_collection_state` ⇒ sempre `"active"`; `resolve_document_state` ⇒ sempre `"published"` | **exit 1 — 7 failed, 1590 passed, 18 skipped** | [`discrimination/exp-a02.txt`](discrimination/exp-a02.txt) |
| `exp-a03` | `ChatApplicationService._replayable_turn` reescrito no modo pré-fix (leitura sem `conversation_id`/`fingerprint`, sem pós-verificação) | **exit 1 — 8 failed, 1589 passed, 18 skipped** | [`discrimination/exp-a03.txt`](discrimination/exp-a03.txt) |
| `control` | nenhum, logo após o `restore` | **exit 0** (suíte inteira verde) | [`discrimination/control.txt`](discrimination/control.txt) |

Os 7 falhos do `exp-a02` são exatamente os 7 negativos de `test_search_lifecycle.py`
(o oitavo caso, o positivo, continua passando). Os 8 falhos do `exp-a03` estão todos em
`test_idempotency_scope.py` (replay idêntico, mensagem/coleção trocada, stream, HTTP —
memória e SQLite).

Hashes conferidos após o `restore`:

```
844fd14e7d8a457639aaffe121d99c95ec310f2a225f1eb37dba824c61546aa2  apps/api/src/services/chat_service.py
021dd0a353fb4e6a14cbf8851b9508de95836720bf7f3d71b8490cf7100d55ca  apps/api/src/services/knowledge_service.py
```

Cópias de segurança e logs íntegros ficaram em `/tmp/opencode/discrimination/` — caminho
**fora do repositório**, portanto não reproduzível por terceiros; o que é reproduzível é a
mutação descrita acima (uma única `cat >>` por arquivo) e o comando de suíte.

## 3. Reproduções da baseline agora fechadas

Ambas saem **exit 1** (defeito ausente), com o mesmo harness da baseline:

| Reprodução | Saída | Artefato |
|---|---|---|
| `repro_a02_archive_search.py` | `search_before [200,1]` → `archive [200,"archived"]` → `search_after_scoped [200,0]` → `search_after_global [200,0]`; `still_searchable_after_archive: false` | [`discrimination/post-fix-a02.out`](discrimination/post-fix-a02.out) |
| `repro_a03_idempotency.py` | replay idêntico `200` na mesma conversa; outra conversa `409`; `cross_conversation_replay_defect: false` | [`discrimination/post-fix-a03.out`](discrimination/post-fix-a03.out) |

```sh
PYTHONPATH=<canonical> .runtime/venvs/cvg/bin/python \
  docs/reports/evidence/auditoria-2026-10-07/repro/repro_a02_archive_search.py   # exit 1
PYTHONPATH=<canonical> .runtime/venvs/cvg/bin/python \
  docs/reports/evidence/auditoria-2026-10-07/repro/repro_a03_idempotency.py      # exit 1
```

Os arquivos `a02-baseline.json` / `a03-baseline.json` e seus `.stderr` **não foram tocados** —
eles registram o estado pré-fix (exit 0, defeito presente).

## 4. Duas correções de lane encontradas ao reexecutar os gates

| O que quebrou | Causa | Correção |
|---|---|---|
| `make test` → **exit 2**: `ERROR collecting apps/worker/tests/test_provider_rework3_lifecycle.py` (`ModuleNotFoundError: No module named 'worker'`) | a suíte de worker adicionada em AUD07-03 importa `worker.tests.<módulo>`, que só resolve com o diretório **pai** (`apps/`) no `PYTHONPATH`; `canonical_env()` só tem `apps/*/src` + `packages/*/src` | `scripts/phase11/runner.py::worker_suite_env()`: `apps` é prefixado **só** naquele caso — o contrato `PYTHONPATH` de todos os outros suites fica intacto. Rotulado como regressão **nossa**, não pré-existente: em `HEAD` o `mode_test` ainda rodava as lanes legadas CVG/Professor/Locker |
| `make api16-full` → **exit 2**: `ModuleNotFoundError: No module named 'rick_authorization'` em `scripts/phase16/benchmark.py:34` | a correção do AUD07-11 passou a importar `services.knowledge_service` (que importa `rick_authorization`) a partir de `retrieval_service`; a receita `api16-benchmark` tinha um `PYTHONPATH` enxuto sem `packages/authorization/src` | `Makefile:371`: adicionado `$(ROOT)/packages/authorization/src` à receita `api16-benchmark` (a receita `api15-benchmark` já o tinha) |

Ambos são correções de contrato de import, não mudanças de comportamento: nenhum limiar foi
abaixado, nenhum gate removido, nenhum teste marcado como ignorado.

## 5. Gates no candidato (pós-AUD07-10/11/12)

| Gate | Comando | Exit | Resultado |
|---|---|---|---|
| Validação | `make validate` | **0** | control-plane + quality-bar PASS |
| Testes rápidos | `make test-fast` | **0** | 26 passed (regressões de runner/workflow) |
| **CI completo** | `make ci` | **0** | 15 casos / 17 linhas `<==`, todos 0 (ver `fix-gates-1.md` §1 para a lista) |
| **Testes completos** | `make test` | **0** | packages/API/differential `614 passed, 103 skipped` + `17 passed` + `1597 passed, 18 skipped`; worker `734 passed`; validadores/runner `472 passed` |
| Testes de API | `make api-test` | **0** | **1597 passed, 18 skipped** (baseline pós-fix 1597; 1571 antes do M1) |
| Phase 1.3.1 / 1.4 | `make api131-full` / `make api14-full` | **0** / **0** | 1597 passed |
| Phase 1.5 | `make api15-full` | **0** | contracts/provider/lock/professor/root/benchmark |
| Phase 1.6 | `make api16-full` | **0** | domain `614 passed, 103 skipped` + coverage + benchmark |
| Domain (pacotes) | `make api16-domain` | **0** | `614 passed, 103 skipped` — inclui as 9 regressões novas de pacote |
| Segurança de API | `make api-security` | **0** | 76 passed |
| Contrato de API | `make api-contract` | **0** | `openapi.json` — OpenAPI OK: 55 paths |
| Storage / jobs | `make storage-test` / `make jobs-test` | **0** / **0** | 28 passed / 44 passed |
| Estáticos | `make ops-static` / `make compose-static` | **0** / **0** | 298 passed; 16 serviços em cada topology |
| Avaliação | `make eval-retrieval` / `make security-adversarial` | **0** / **0** | `status PASS`; 8 registros adversariais |
| `pip check` | `.runtime/venvs/cvg/bin/python -m pip check` | **0** | *No broken requirements found.* |
| Reproduções A02/A03 | `repro_a02` / `repro_a03` | **1** / **1** | defeito fechado (seção 3) |

Logs completos em `/tmp/opencode/gate-*.log` (fora do repositório).

## 6. Cobertura de lanes exigida pelo aceite de AUD07-12

| Lane | Comando | Cobertura entregue |
|---|---|---|
| `apps/api` | `make api-test` → 1597 | `test_idempotency_scope.py` + `test_search_lifecycle.py` + `test_chat_history.py` + `test_postgres_chat_history.py` |
| `packages/knowledge` | `make api16-domain` → 614 | `test_lifecycle_authority_contract.py` (7) |
| `packages/retrieval` | `make api16-domain` → 614 | `test_evidence_lifecycle_keys.py` (2) |
| worker (integração) | `make test` → 734 | suíte completa segue verde após a correção de `PYTHONPATH` |

## 7. Limites desta página

- **Checkout limpo não foi reexecutado após o M1.** O procedimento e o resultado de
  AUD07-09 continuam válidos para o estado pré-M1; o candidato atual carrega alterações
  não commitadas, então o próximo `git clone --local` + `rsync` precisa ser refeito em
  AUD07-27 antes de se afirmar que a árvore limpa ainda sobe.
- `/tmp/opencode/*` (logs, `.bak`, clones) não é parte do repositório e não é reproduzível.
- `make ci` **não** executa as suítes Python canônicas, a suíte de worker nem as regressões
  de validador/runner completas — quem roda isso é `make test`. A lista de lanes de
  `fix-gates-1.md` foi corrigida justamente por isso.
- Nenhum gate de M5/M6/M7 foi tocado: dependem de serviços externos (OIDC, Qdrant/Redis
  reais, campanha RAG, proveedores pagos).
