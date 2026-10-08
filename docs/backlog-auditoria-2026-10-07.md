# Backlog de remediação RICK Intelligence

**Data:** 07/10/2026. **Estado:** 42 tarefas propostas; **AUD07-01–15, AUD07-17, AUD07-18 e
AUD07-19 concluídas e evidenciadas** (**M0 e M1 completos** + M2 em curso: A02/A03, A04, A16, A10, A09 e
A11 tratados), AUD07-16 e AUD07-20–27 pendentes, AUD07-28–42 com dependência externa. **Origem:** auditoria de 07/10/2026, 64,2/100 em
26 áreas, 20 achados (A01–A20) e prontidão `NO-GO`.

Este backlog traduz os achados A01–A20 em correções verificáveis e acrescenta o trabalho de
integração, operação e promoção ainda sem prova. O [roadmap](roadmap-auditoria-2026-10-07.md)
define a sequência dos marcos M0–M7. O
[relatório de origem](reports/relatorio-auditoria-2026-10-07.md) preserva comandos, exit codes,
notas e limites.

Os IDs AUD07 pertencem a este planejamento. Eles não encerram nem substituem tarefas
Q17/Q24/R27/AUD26/AUD03, os ledgers em `.agent/` ou gates de promoção. Conclusão local e
validação externa terão registros distintos.

## Convenções de execução

- **P0:** gate obrigatório vermelho, defeito de integridade/autorização reproduzido, ou
  impedimento essencial à candidatura a produção.
- **P1:** confiabilidade, reprodutibilidade, testes ou prova operacional necessária para o
  respectivo gate.
- **P2:** documentação e manutenção sem alteração de comportamento.
- **Tamanho P:** alteração delimitada e teste focado. **M:** vários componentes ou contratos.
  **G:** concorrência, compatibilidade de dados ou execução distribuída.
- **Planejada:** trabalho local ainda não iniciado. **Dependência externa:** execução depende de
  ambiente, dados, política ou autoridade descrita; reconferir disponibilidade antes de executar.
- Os responsáveis são papéis sugeridos, não designações de pessoas.

Uma tarefa só recebe aceite quando cumprir os critérios, preservar o primeiro resultado da
baseline e apresentar candidato/hash, comando completo, exit code, resultado, artefatos e
limites. Criar regressões que rejeitem o comportamento incorreto. Não enfraquecer thresholds,
repor Actions por tag mutável, remover gates ou marcar casos como ignorados para obter sucesso.

## Fila de tarefas

| ID | Marco | Pri | Entrega | Tam | Dependências | Estado |
|---|---|---|---|---|---|---|
| AUD07-01 | M0 | P0 | Selar baseline e preservar reproduções A02/A03 | M | — | Concluída |
| AUD07-02 | M0 | P0 | Decidir preservação ou retirada dos três legados | M | 01 | Concluída (retirada) |
| AUD07-03 | M0 | P0 | Reconciliar validador de fronteiras e Makefile | M | 02 | Concluída |
| AUD07-04 | M0 | P0 | Reconciliar 58 referências legadas nos workflows | M | 02 | Concluída |
| AUD07-05 | M0 | P0 | Remover artefato `.next-audit-*` e generalizar ignores | P | 01 | Concluída |
| AUD07-06 | M0 | P0 | Corrigir testes apontando para caminhos legados | P | 02 | Concluída |
| AUD07-07 | M0 | P0 | Registrar 3 rotas de auditoria em `ROUTE_REGISTRY` | P | 01 | Concluída |
| AUD07-08 | M0 | P0 | Bootstrap reproduzível a partir dos locks | M | 01 | Concluída |
| AUD07-09 | M0 | P0 | `make ci` verde em checkout limpo | G | 03–08 | Concluída |
| AUD07-10 | M1 | P0 | Corrigir idempotência cruzando conversas (A03) | M | 01 | Concluída |
| AUD07-11 | M1 | P0 | Corrigir busca em coleção arquivada (A02) | M | 01 | Concluída |
| AUD07-12 | M1 | P0 | Regressões públicas e discriminantes para A02/A03 | M | 10, 11 | Concluída |
| AUD07-13 | M1 | P1 | Ampliar cobertura da política default-deny de rotas | P | 07 | Concluída |
| AUD07-14 | M1 | P1 | Fail-closed em port sem probe no wrapper de resiliência | M | 01 | Concluída |
| AUD07-15 | M2 | P1 | Eliminar as 2 vulnerabilidades HIGH do npm | P | 01 | Concluída |
| AUD07-16 | M2 | P1 | Eliminar basenames de teste duplicados entre pacotes | P | 01 | Planejada |
| AUD07-17 | M2 | P1 | Introduzir type-checker Python em modo gradual | G | 09 | Concluída |
| AUD07-18 | M2 | P1 | Dar destino versionável à evidência de 1,86 GB | M | 01 | Concluída |
| AUD07-19 | M2 | P1 | Política de artefatos não rastreados e limpeza da árvore | M | 18 | Concluída |
| AUD07-20 | M2 | P1 | Classificar os 216 testes pulados por motivo e gate | M | 09 | Planejada |
| AUD07-21 | M2 | P1 | Descobrir `PYTHONPATH` sem export manual | P | 08 | Planejada |
| AUD07-22 | M3 | P1 | Reescrever README para o checkout real | M | 02 | Planejada |
| AUD07-23 | M3 | P1 | Reconciliar os 48 documentos que citam os legados | M | 02 | Planejada |
| AUD07-24 | M3 | P2 | Corrigir link quebrado e adotar verificação de links | P | 23 | Planejada |
| AUD07-25 | M3 | P2 | Materializar as lanes raiz de `tests/` ou corrigir a descrição | M | 02 | Planejada |
| AUD07-26 | M3 | P2 | Publicar cobertura com denominador e exclusões explícitos | M | 20 | Planejada |
| AUD07-27 | M4 | P0 | Validar candidato integrado local | G | 09–26 | Planejada |
| AUD07-28 | M5 | P0 | Provar golden path com serviços reais | G | 27 | Dependência externa |
| AUD07-29 | M5 | P0 | Provar isolamento multi-tenant e revogação reais | G | 28 | Dependência externa |
| AUD07-30 | M5 | P1 | Provar IdP/OIDC e comportamento com réplicas | G | 28 | Dependência externa |
| AUD07-31 | M5 | P1 | Executar campanha RAG representativa | G | 28 | Dependência externa |
| AUD07-32 | M5 | P1 | Provar fencing com múltiplos workers reais | G | 28 | Dependência externa |
| AUD07-33 | M5 | P1 | Executar corpus hostil de arquivos em worker isolado | G | 28 | Dependência externa |
| AUD07-34 | M6 | P1 | Provar collector, alertas e tracing distribuído | G | 28 | Dependência externa |
| AUD07-35 | M6 | P0 | Medir backup/restore, RPO e RTO | G | 28 | Dependência externa |
| AUD07-36 | M6 | P1 | Medir capacidade e latência representativas | G | 28, 34 | Dependência externa |
| AUD07-37 | M6 | P1 | Ensaiar falhas e recuperação controladas | G | 28, 34, 35 | Dependência externa |
| AUD07-38 | M6 | P1 | Executar soak com limites de recursos | G | 36, 37 | Dependência externa |
| AUD07-39 | M7 | P0 | Gerar evidência de release e imagens rastreáveis | G | 27 | Dependência externa |
| AUD07-40 | M7 | P0 | Selecionar pacote de promoção vinculado ao candidato | G | 39 | Dependência externa |
| AUD07-41 | M7 | P1 | Reauditar as 26 áreas sobre o candidato exato | G | 40 | Dependência externa |
| AUD07-42 | M7 | P0 | Decisão Go/No-Go explícita com riscos residuais | G | 41 | Dependência externa |

As dependências abreviadas usam o prefixo AUD07. Intervalos incluem todos os IDs indicados.

## Aceite comum

1. A reprodução relevante distingue baseline incorreta e candidato correto; os resultados
   originais ficam preservados.
2. O caso positivo continua funcionando, com compatibilidade e escopo explícitos.
3. Testes negativos incluem revogação, exceção, cancelamento, estado vazio e concorrência quando
   aplicáveis.
4. Não há escrita fora do escopo autorizado nem alteração de histories/checksums para encobrir
   divergência.
5. Evidências identificam a árvore exata. `NOT_RUN`, `BLOCKED_EXTERNAL`, `STALE` e falha não
   contam como aprovação.
6. Revisão separada confere os P0 e mudanças de identidade, dados, auditoria ou promoção.

---

## M0 — Baseline selada e gates verdes locais

### AUD07-01 Selar baseline e preservar reproduções A02/A03

**Responsável sugerido:** integração e qualidade. **Origem:** corte completo da auditoria.

Registrar HEAD, diff, hashes dos 889 arquivos alterados e o estado do worktree. Preservar os
scripts de reprodução de A02 (archive→search) e A03 (idempotência cruzando conversas), incluindo
o harness in-process, entradas e saídas, antes de alterar qualquer código. Sanitizar dados e
registrar ambiente (Python, Node, venv, `PYTHONPATH`).

**Aceite:** cada A01–A20 possui fonte e procedimento recuperável; as duas reproduções são
reexecutáveis e falham na baseline; a árvore do usuário está preservada; evidências novas têm
destino durável sob `docs/reports/evidence/` ou referência CI recuperável.

### AUD07-02 Decidir preservação ou retirada dos três legados

**Responsável sugerido:** arquitetura e dono do produto. **Origem:** A01.

Levantar o que ainda consome `cvg-master-rag-v2/`, `rick-professor/` e `modulo-redis-locker/`
(validador, Makefile, workflows, testes, documentação) e o que é apenas texto histórico.
Decidir entre restaurar os diretórios, retirá-los formalmente com ajuste de todos os consumidores,
ou isolar os consumidores obsoletos atrás de flag explícita.

**Aceite:** decisão registrada com justificativa e responsável; a escolha cobre os 58 pontos de
referência de CI, o validador, o Makefile e os 48 documentos; nenhuma das três opções é feita
parcialmente. Enquanto a decisão não existir, nenhum outro trabalho de A01 avança.

### AUD07-03 Reconciliar validador de fronteiras e Makefile

**Responsável sugerido:** arquitetura e toolchain. **Origem:** A01. **Fontes:**
`scripts/phase15/check_boundaries.py`, `Makefile`.

Alinhar a regra de "preserved component" ao resultado de AUD07-02 e remover dos alvos
`validate`, `lint`, `test-fast`, `build`, `api15-full` e `api16-full` as lanes que deixaram de
existir, sem afrouxar a verificação de imports proibidos entre `apps` e `packages`.

**Aceite:** `make validate` retorna 0 no candidato; a checagem de dependência continua falhando
quando um import proibido é introduzido (fixture negativa); nenhum alvo obrigatório é removido
apenas para ficar verde.

### AUD07-04 Reconciliar 58 referências legadas nos workflows

**Responsável sugerido:** CI e release. **Origem:** A01. **Fonte:** `.github/workflows/`
(40 em `phase-0.6.yml`, 8 em `quality.yml`, 8 em `phase-1.1.yml`, 1 cada em `phase-1.5.yml` e
`phase-1.6.yml`).

Ajustar a lane `supply-chain` (hoje executa `pip-audit` e `npm ci/audit` sobre os três caminhos
apagados) e os demais workflows conforme AUD07-02, preservando pinagem por SHA,
`--require-hashes` e a relação `needs:` entre `supply-chain` e `release`.

**Aceite:** nenhuma step referencia caminho inexistente; `release` continua dependendo de
`supply-chain`; Actions seguem pinadas por SHA e installs com hashes; workflow de validação
estática confere que comentário não satisfaz a regra.

### AUD07-05 Remover artefato `.next-audit-*` e generalizar ignores

**Responsável sugerido:** frontend e higiene do repositório. **Origem:** A05.

Remover `apps/web/.next-audit-20261006/` (90 MB, não rastreado), generalizar `.gitignore`
(`**/.next/`, `**/.next-phase3-*/` → padrão que cubra qualquer `.next-*`) e o `ignores` do
`apps/web/eslint.config.mjs`.

**Aceite:** `make lint` retorna 0 num checkout limpo; `npx eslint app components lib
middleware.ts --max-warnings=0` permanece 0; criar um `.next-qualquer` não reintroduz erro; o
artefato não volta a ser gerado fora de diretórios ignorados.

### AUD07-06 Corrigir testes apontando para caminhos legados

**Responsável sugerido:** qualidade e migração. **Origem:** A06. **Fontes:**
`apps/api/tests/test_differential_auth.py`, `packages/retrieval/tests/test_differential.py`,
`packages/retrieval/tests/test_shadow_quality.py`.

Reescrever ou remover os testes de paridade legado↔raiz, preservando a intenção de verificação
como regressão da contratualidade atual (ex.: comparar contra fixture versionada em vez de
arquivo legado).

**Aceite:** `pytest apps/api/tests` e `pytest packages/retrieval/tests` coletam sem erro e
retornam 0; a intenção de verificação de paridade continua coberta por ao menos um teste que
falha se a implementação raiz divergir do contrato registrado.

### AUD07-07 Registrar três rotas de auditoria em `ROUTE_REGISTRY`

**Responsável sugerido:** API e autorização. **Origem:** A04. **Fontes:**
`apps/api/src/routes/__init__.py`, `apps/api/src/routes/knowledge.py#L38-L54`.

Adicionar entradas com `auth` e `permission` explícitos para
`GET /api/v1/audit/operations`, `GET /api/v1/audit/operations/{operation_id}` e
`POST /api/v1/audit/operations/{operation_id}/reconcile`.

**Aceite:** `make api-security` retorna 0; a permissão escolhida é a mais restritiva que
sustenta o caso de uso; rota montada sem registro continua fazendo `test_registry_covers_all_app_routes`
falhar.

### AUD07-08 Bootstrap reproduzível a partir dos locks

**Responsável sugerido:** toolchain. **Origem:** A08.

Fazer `make bootstrap` criar/atualizar um venv raiz a partir de `requirements/test.lock` com
`--require-hashes`, reparar ou aposentar `.runtime/venvs/cvg` vazio e declarar as dependências
de runtime que hoje só existem no CI. Remover a dependência de pacotes instalados
globalmente no host (`jsonschema` ausente no sistema).

**Aceite:** em máquina nova, `make bootstrap && make api-test` passa sem instalação manual;
`pip check` retorna 0; fixture que remove uma dependência do lock faz a lane correspondente
falhar explicitamente.

### AUD07-09 `make ci` verde em checkout limpo

**Responsável sugerido:** integração. **Origem:** consolidação de M0.

Integrar AUD07-03 a AUD07-08 num único candidato identificado e executar a cadeia completa
(`validate`, `test-fast`, `lint`, `typecheck`, `build`) em checkout limpo, com dependências só
dos locks.

**Aceite:** `make ci` retorna 0; nenhuma exclusão ad hoc, nenhum diretório local prévio como
pré-condição; reproduções A02/A03 ainda falham (ainda não corrigidas) e estão arquivadas;
comando completo, exit code e artefatos registrados.

**Estado:** Concluída. **Evidência:**
[`fix-gates-1.md`](reports/evidence/auditoria-2026-10-07/fix-gates-1.md) — `make bootstrap`
e `make ci` em `git clone --local` + `rsync`, ambos exit 0.

---

## M1 — Defeitos de integridade e autorização

### AUD07-10 Corrigir idempotência cruzando conversas (A03)

**Responsável sugerido:** API e contratos de chat. **Origem:** A03. **Fontes:**
`apps/api/src/services/chat_service.py#L285-L345`,
`apps/api/src/services/chat_history.py` (`get_idempotent`, `append`),
`apps/api/src/services/postgres_chat_history.py`.

Persistir junto ao registro idempotente o `conversation_id` e um fingerprint canônico do turno
(mensagem normalizada + escopo + coleção). Devolver o resultado armazenado apenas quando ambos
coincidirem; reuso incompatível responde `409` (código `conflict`) sem executar nova geração.

**Aceite:** a reprodução da baseline (chave K em conv-B devolvendo resposta de conv-A) é
rejeitada; repetição idêntica devolve byte a byte o mesmo resultado; cobre JSON, SSE e os três
stores (in-memory, SQLite, PostgreSQL); não há vazamento entre usuários (chave já escopada por
sessão).

**Estado:** Concluída. `repro_a03` → exit 1 (`cross_conversation_replay_defect: false`);
`make api-test` 1597 passed. **Evidência:**
[`fix-gates-2.md`](reports/evidence/auditoria-2026-10-07/fix-gates-2.md) §1, §3.

### AUD07-11 Corrigir busca em coleção arquivada (A02)

**Responsável sugerido:** retrieval e knowledge. **Origem:** A02. **Fontes:**
`apps/api/src/routes/search.py#L141-L182`, `apps/api/src/services/retrieval_service.py`,
`apps/api/src/services/knowledge_service.py`.

Revalidar a autoridade de lifecycle (coleção, documento e fontes) na admissão da consulta e na
projeção da resposta, usando a mesma autoridade que o catálogo e o Professor já consultam.

**Aceite:** `archive → search` retorna zero itens, escopada e globalmente, com cache quente e
frio, em SQLite e no backend remoto autorizado; coleção ativa preserva ranking e proveniência;
falha da autoridade de lifecycle fecha em negação, não em bypass.

**Estado:** Concluída. `repro_a02` → exit 1 (`still_searchable_after_archive: false`);
`make api-test` 1597 passed. **Evidência:**
[`fix-gates-2.md`](reports/evidence/auditoria-2026-10-07/fix-gates-2.md) §1, §3.

### AUD07-12 Regressões públicas e discriminantes para A02/A03

**Responsável sugerido:** qualidade. **Origem:** A02, A03.

Transformar as duas reproduções em testes de suíte que rodam no CI, cobrindo variantes (stream,
diferentes stores, escopos de grants, restart) e garantindo que a remoção de qualquer fix faz o
teste falhar.

**Aceite:** testes falham quando os fixes de AUD07-10/11 são revertidos e passam com eles;
rodar em todos os lanes afetados (`apps/api`, `packages/retrieval`, `packages/knowledge`);
resultado registrado no candidato de AUD07-27.

**Estado:** Concluída. Reversão de AUD07-11 ⇒ **7 failed** (`test_search_lifecycle.py`);
reversão da camada de serviço de AUD07-10 ⇒ **8 failed** (`test_idempotency_scope.py`);
controle após restauração ⇒ exit 0. Lanes: `make api-test` 1597, `make api16-domain` 614,
`make test` completo exit 0. **Evidência:**
[`fix-gates-2.md`](reports/evidence/auditoria-2026-10-07/fix-gates-2.md) §2, §5, §6.

### AUD07-13 Ampliar cobertura da política default-deny de rotas

**Responsável sugerido:** segurança e API. **Origem:** A04.

Além das três rotas de AUD07-07, verificar se toda rota montada tem permissão atribuída e se a
permissão declarada corresponde à efetivamente exigida no handler (não apenas `authenticated`).

**Aceite:** teste compara `ROUTE_REGISTRY` com as dependências reais dos handlers e falha em
divergência; documentação da política de rotas atualizada; nenhuma rota pública nova é criada
sem decisão explícita.

**Estado:** Concluída. Registro corrigido (`session:self` removido, `scope: "self"` explícito em
7 rotas, permissões múltiplas em `POST /api/v1/conversations` e em
`POST /api/v1/audit/operations/{id}/reconcile`); paridade bijetiva resolvida via `routes.ROUTERS`
(FastAPI 0.141 não achata `app.routes`, o teste antigo era vazio); imposição provada de 3 formas
(declarado == estático+delegado, 51 casos; sessão sem a permissão ⇒ 403, 51 casos; limite de
escopo próprio vs. estrangeiro). Reversão do registro ⇒ **15 failed**; remoção de uma entrada
⇒ **2 failed**; controle ⇒ exit 0 (**160 passed**). Gates: `api-test` **1702**, `api-security`
**181**, `ci`/`test`/`validate`/`ops-static` (298)/`api-contract`/`compose-static`/`lint`/`typecheck`
todos exit 0. **Evidência:**
[`route-policy.md`](reports/evidence/auditoria-2026-10-07/route-policy.md) e
[`discrimination/`](reports/evidence/auditoria-2026-10-07/discrimination/).

### AUD07-14 Fail-closed em port sem probe no wrapper de resiliência

**Responsável sugerido:** providers. **Origem:** A16. **Fonte:**
`packages/providers/src/rick_providers/resilience.py#L80-L125`.

Exigir probe ou marca explícita de produção para que um port seja classificado
`production_safe=True`; quando `health_check` não estiver disponível, reportar não-saudável em
vez de cair para o estado local do circuito.

**Aceite:** port sintético sem probe resulta `production_safe=False` e `health_check` falso;
composição oficial com probes próprios continua verde; teste de admissão cobre a composição, não
só o wrapper.

**Estado:** Concluída. Regra canônica em `ResilientProvider._production_safe`
(teste ⇒ `False`; declaração explícita vence; sem declaração ⇒ só com `health_check` chamável) e
`health_check()` sem probe ⇒ `False` (era `readiness_check()`). Testes novos no wrapper (3) e na
composição (2): `SyntheticPort` sem probe ⇒ `production_safe` False **e** `health_checks["provider"]()`
False; cliente oficial com `/models` vivo ⇒ ambos True. Reversão ⇒ **3 failed**; controle ⇒ exit 0
(**23 passed**). Gates: `make test`, `api-test` **1704**, `ci`, `validate`, `test-fast`,
`api-security` **181**, `ops-static` **298**, `api-contract`, `compose-static`, `lint`,
`typecheck` — todos exit 0. **Evidência:**
[`resilience-fail-closed.md`](reports/evidence/auditoria-2026-10-07/resilience-fail-closed.md).

---

## M2 — Confiabilidade da toolchain

### AUD07-15 Eliminar as 2 vulnerabilidades HIGH do npm

**Responsável sugerido:** frontend e supply chain. **Origem:** A10.

Atualizar `sharp` (≥ 0.35.5) e `source-map-js` (≥ 1.2.2), regenerar `package-lock.json` e
revalidar build, unit e E2E.

**Aceite:** `npm audit --audit-level=high` retorna 0 em `apps/web`; `make web-build` e
`make web-e2e` continuam verdes; `pip-audit -r requirements/runtime.lock --strict` permanece
limpo.

**Estado:** Concluída. `overrides` explícitos `sharp: 0.35.5` e `source-map-js: 1.2.2` em
`apps/web/package.json` + lock regenerado (drift pré-existente do lock preservado). Gates:
`npm audit --audit-level=high` **0 vulnerabilidades** (era 2 high), `web-lint`, `web-typecheck`,
`web-build`, `web-e2e` **339 passed**, `pip-audit --strict` limpo, `make validate` — todos exit 0.
**Evidência:**
[`npm-supply-chain.md`](reports/evidence/auditoria-2026-10-07/npm-supply-chain.md).

### AUD07-16 Eliminar basenames de teste duplicados entre pacotes

**Responsável sugerido:** qualidade. **Origem:** A07.

Resolver `import file mismatch` entre `packages/identity/tests/` e `packages/{knowledge,providers}/tests/`
(`test_aud03_postgres_live.py`, `test_provider.py`) via `__init__.py`, renomeação ou modo de
import único.

**Aceite:** `pytest packages` em invocação única coleta e executa sem erro; a execução por
pacote usada no CI continua funcionando; nenhuma suíte é silenciosamente excluída.

**Estado:** Planejada — diagnóstico pronto, correção revertida (ver
[`test-import-uniqueness.md`](reports/evidence/auditoria-2026-10-07/test-import-uniqueness.md)).
A renomeação dos dois arquivos `identity` resolve a colisão, mas quebra
`make validate`: o control-plane exige que cada `evidence_refs`/`artifacts` de
`.agent/backlog.json` e `.agent/verification.jsonl` resolva no worktree (7 refs históricos para
`packages/identity/tests/test_provider.py`), e editar esses artefatos de histórico violaria o
contrato append-only. Próxima rota: `--import-mode=importlib` (escopado, testado lane a lane) ou
cadeia de `__init__.py` até `packages/`.

### AUD07-17 Introduzir type-checker Python em modo gradual

**Responsável sugerido:** arquitetura e qualidade. **Origem:** A09.

Adicionar `mypy` (ou `pyright`) com baseline versionada, começando pelos pacotes de contratos e
autorização, e registrar o floor de erros no CI sem regressão.

**Aceite:** `make typecheck` passa a incluir a verificação Python; baseline versionada e
comentada; introduzir um erro tipado novo em pacote já coberto faz o CI falhar; a cobertura
cresce por decisão explícita, não por exclusão.

**Estado:** Concluída. `mypy==2.4.0` fixado em `requirements/test.in`/`test.lock` (5 pacotes
novos, nenhum pin existente alterado, `pip install --require-hashes --dry-run` exit 0);
`mypy.ini` declara a cobertura (`files`) e `docs/baselines/mypy-baseline.txt` registra o limite
(0/0) com regras comentadas; `scripts/phase11/typecheck_baseline.py` + 8 testes rodam no
`make typecheck` (e no `make ci`) e falham acima do limite/avisam abaixo. Baseline nasceu em 0
após corrigir 13 `Literal[CONST]`, ampliar `permissions_for_role` para `Mapping` e remover um
`# type: ignore` obsoleto. Discriminação: erro tipado novo em `packages/contracts` ⇒
`make typecheck` exit 2; removido ⇒ exit 0. **Evidência:**
[`python-typecheck.md`](reports/evidence/auditoria-2026-10-07/python-typecheck.md).

### AUD07-18 Dar destino versionável à evidência de 1,86 GB

**Responsável sugerido:** integração e operação. **Origem:** A11.

Definir política: versionar sumários/manifests com hash e proveniência, e publicar o restante
como artefato de CI ou armazenamento externo com referência imutável.

**Aceite:** política documentada e aplicada; `docs/reports/evidence/` deixa de ser 1,86 GB
untracked; cada evidência citada em relatório continua recuperável por hash; nada é apagado sem
substituto verificável.

**Estado:** Concluída com incidente documentado. Política única em
[`evidence/README.md`](reports/evidence/README.md) aplicada por
`scripts/phase11/evidence_store.py` (`apply`, `relink`, `check`, `verify`, `restore`, `stat`);
`check` ligado ao `make validate` (Makefile) e ao `make ci` (`mode_validate`), com 14 testes em
`scripts/phase11/test_evidence_store.py`. Árvore: 50 351 ficheiros / 1,86 GB → **411 ficheiros
/ 3 625 941 bytes (≈3,5 MB)**, não ignorada pelo git; 34 117 *blobs* / 1,32 GB na bolsa,
manifesto de 35 843 linhas ancorado por `manifest_sha256` no `STORE-SUMMARY.json` versionado.
Disciplina: material bruto reinserido ⇒ `check` exit 1 (removido ⇒ 0), manifesto alterado ⇒ 1
(repsto ⇒ 0), *blob* corrompido ⇒ `verify` 1 (repsto ⇒ 0) — sondas reexecutadas depois da
alteração ao detetor, mesmo resultado. **Incidente:** o primeiro `apply` parou por diretório
só-leitura antes de gravar o manifesto — conteúdo preservado, mas 30 200 linhas ficaram sem
caminho (corrigido: permissão, manifesto crash-safe e `relink`, que recuperou 1 594 caminhos).
As **45 citações relativas** afetadas foram repostas com hash verificado (39 nesta fase: 32 de
uma cópia local de referência, 1 pela hash registada em `archive-manifest.json`, 6 irmãos de um
pacote de revisão; 6 antes, via `restore`) e o detetor passou a contar links de ficheiros já
mantidos dentro da pasta, para o pacote ficar completo; restam **738** citações relativas a
material histórico (aviso, não falham o gate) e 0 links de evidência quebrados. Os 411
mantidos estão **staged**, incluindo 248 `*.log` que a regra `*.log` do `.gitignore` escondia:
exceção `!docs/reports/evidence/**/*.log` no `.gitignore` + teste no `check`
(`git check-ignore --no-index` ⇒ `evidência mantida ignorada pelo git`, sonda D). A linha nova do
`Makefile` exigiu incluir `scripts/phase11/evidence_store.py` no fixture de
`test_check_canonical_ci.py`. Gates: `make validate` 0, `make test` 0 (494 = +14),
`make ci` 0. **Evidência:**
[`evidence-destination.md`](reports/evidence/auditoria-2026-10-07/evidence-destination.md).

### AUD07-19 Política de artefatos não rastreados e limpeza da árvore

**Responsável sugerido:** higiene do repositório. **Origem:** A11.

Generalizar `.gitignore` para `.next*`, cobrir `.coverage`, `tsbuildinfo`, `test-results` e
demais saídas; remover conteúdo óbvio não rastreado; revisar `.runtime/` (1,3 GB) e
`artifacts/` (112 MB).

**Aceite:** `git status --porcelain` em checkout limpo mostra apenas mudanças intencionais; a
árvore não cresce por execução de teste; `git check-ignore` cobre os padrões generalizados.

**Estado (08/10/2026): PASS.** As 12 provas + 5 negativas de `git check-ignore` estão
versionadas em `scripts/phase11/test_untracked_hygiene.py` (roda em `mode_test_fast`, logo em
`make ci`); checkout limpo = 0 linhas; `make ci` e `make test` = 0 linhas de crescimento no
`git status -uall`. `.gitignore` ganhou `.opencode/` (64 MB) e `.agent/*.lock`; a 3.ª regra
(`uv.lock`) foi **revertida** porque os registos `VER-Q24-03-*` de `.agent/verification.jsonl`
nomeiam `apps/api/uv.lock`, que hoje está staged (90 KB) e é prova negativa na regressão.
238 `??` restantes são trabalho intencionais (155 `.py`/58 `.md`) — nada apagado.
**Achado medido:** um checkout novo tem `status` vazio mas `make validate` = exit 2 (734 FAIL),
porque `docs/ci/restore_control_inputs.py` + `docs/ci/control-inputs/**` (29 MB, 1 293 ficheiros
com 749 de `.gauntlet-state-of-art`) e `requirements/*.lock` nunca foram trackeados. O
experimento **E4** prova que trackear esses inputs + commitar staged/unstaged/não-rastreados
dá `control-inputs-restore` 0 e `make validate` 0 (`RESULT PASS 12/0/0`); opções A/B/C e custo
(+~30 MB num pack de 1,38 MiB) em
[`untracked-hygiene.md`](reports/evidence/auditoria-2026-10-07/untracked-hygiene.md) — decisão
de commit pendente do utilizador.

### AUD07-20 Classificar os 216 testes pulados por motivo e gate

**Responsável sugerido:** qualidade. **Origem:** A17.

Inventariar os skips observados (98 em `knowledge`, 84 em `infrastructure`, 18 em `apps/api`,
16 em `identity`) com motivo, dependência externa e gate ao qual pertencem.

**Aceite:** relatório de skips versionado; os obrigatórios para produção estão executando ou
marcados `BLOCKED_EXTERNAL` com justificativa; nenhum skip é removido apenas para inflar número.

### AUD07-21 Descobrir `PYTHONPATH` sem export manual

**Responsável sugerido:** toolchain. **Origem:** A08.

Mover as 16 entradas de `PYTHONPATH` do workflow para um mecanismo local (`conftest.py` raiz,
arquivo `.pth` gerado pelo bootstrap ou alvo Make), para que `pytest` funcione sem export.

**Aceite:** `pytest apps/api/tests packages apps/worker` roda a partir de qualquer diretório
sem variável de ambiente manual; o CI e o local convergem para a mesma descoberta; documentação
de comandos é atualizada.

**Nota de AUD07-19 (08/10):** um checkout limpo do `HEAD` roda `git status` vazio mas falha
`make validate` (`exit 2`, 734 FAIL) — além do `PYTHONPATH`, os inputs de CI
`docs/ci/restore_control_inputs.py`, `docs/ci/control-inputs/**` e `requirements/*.lock` nunca
foram trackeados. O experimento E4 mostrou que, com esses inputs trackeados, o
`make control-inputs-restore` materializa os diretórios ignorados por desenho
(`.gauntlet-state-of-art/**`, `.agent/legacy-v1/`, `.review-control-history/`, `.runtime/phase-3`,
`artifacts/rec-m0-v3|v4`) e `make validate` passa a 0 — ou seja, a parte do checkout novo
desta tarefa depende da decisão de trackear/commitar (opção A de
[`untracked-hygiene.md`](reports/evidence/auditoria-2026-10-07/untracked-hygiene.md)), não de
mudar o `PYTHONPATH`.

---

## M3 — Documentação e testes coerentes

### AUD07-22 Reescrever README para o checkout real

**Responsável sugerido:** documentação. **Origem:** A13.

Atualizar o parágrafo de consolidação, o bloco "Repository layout" e a tabela de comandos para
refletir a decisão de AUD07-02 e o estado efetivo dos alvos.

**Aceite:** nenhuma afirmação do README contradiz o checkout; todo comando da tabela existe e
sua descrição corresponde ao comportamento observado; a classificação honesta (`NO-GO`) é
mantida.

### AUD07-23 Reconciliar os 48 documentos que citam os legados

**Responsável sugerido:** documentação. **Origem:** A13.

Classificar cada documento como `CURRENT` ou `HISTORICAL`, ajustando os atuais e preservando os
históricos sem reescrever decisões antigas; atualizar o [índice](INDEX.md) com a data e a nota
da nova rodada.

**Aceite:** nenhum documento `CURRENT` descreve os legados como existentes; o índice aponta para
o pacote vigente; documentos históricos têm marcador de estado.

### AUD07-24 Corrigir link quebrado e adotar verificação de links

**Responsável sugerido:** documentação e CI. **Origem:** A13.

Corrigir o link quebrado em `docs/reports/relatorio-auditoria-funcionamento-2026-09-08.md` e
adicionar checagem de links locais aos gates de documentação.

**Aceite:** 0 links quebrados em primário, `docs/plans/` e `docs/reports/*.md`; a checagem roda
no CI e falha ao introduzir link inválido; cópias históricas em `evidence/` ficam fora do escopo
por decisão explícita.

### AUD07-25 Materializar as lanes raiz de `tests/` ou corrigir a descrição

**Responsável sugerido:** qualidade e documentação. **Origem:** A20.

Decidir se `tests/{contract,integration,regression,security,performance,concurrency,e2e}`
passam a conter as verificações que o README descreve, ou se a descrição passa a apontar para
os locais reais (suites por pacote, `scripts/phase11/*_gate.py`).

**Aceite:** não há descrição de lane sem implementação correspondente; se as lanes forem
materializadas, cada uma roda por alvo Make dedicado e retorna exit code distinto para falha e
para bloqueio externo.

### AUD07-26 Publicar cobertura com denominador e exclusões explícitos

**Responsável sugerido:** qualidade. **Origem:** A26/A17.

Consolidar cobertura web (92,14% linhas) e Python num sumário único, com denominador, exclusões
e relação com os skips de AUD07-20.

**Aceite:** sumário versionado informa o que está e o que não está no denominador; floors de
cobertura são verificados no CI; nenhuma pasta de teste é excluída silenciosamente.

---

## M4 — Candidato integrado local

### AUD07-27 Validar candidato integrado local

**Responsável sugerido:** integração e revisão independente. **Origem:** todos os defeitos
locais corrigidos.

Integrar AUD07-01 a AUD07-26, identificar candidato limpo e repetir: `make ci`, `make api-test`,
`make api-contract`, `make api-security`, `make api14-acl`, `make api16-full`,
`make compose-static`, `make eval-retrieval-pack`, `make security-adversarial`,
`make storage-test`, `make ops-static`, `make web-validate` (lint + typecheck + cobertura +
build + 339 E2E).

**Aceite:** nenhum P0 local pendente; todos os gates obrigatórios verdes no mesmo SHA; as
reproduções A02/A03 agora passam por terem regressão, não por terem sido removidas; revisão
separada confere os P0; comandos, exit codes e artefatos registrados.

---

## M5 — Integração com serviços reais

### AUD07-28 Provar golden path com serviços reais

**Responsável sugerido:** runtime, ingestão e qualidade. **Origem:** A15.

Executar API → objeto → fila → worker → vetores → retrieval → evidência → resposta com
PostgreSQL, Redis, Qdrant, object-storage e provider em ambiente identificado, com teardown
declarado antes do início.

**Aceite:** uma publicação válida por operação; estados, checksums e referências coerentes após
falha e reinício; audit obrigatório persistido; artefatos, limites e teardown vinculados ao
candidato; mocks não substituem a prova.

### AUD07-29 Provar isolamento multi-tenant e revogação reais

**Responsável sugerido:** segurança e runtime. **Origem:** A15.

Exercer tenant A/B cruzando objeto, job, catálogo, vetor, evidência, histórico e browser;
retirar grants e revogar sessões entre réplicas.

**Aceite:** operações posteriores à revogação são negadas de forma consistente; scopes cruzados
não retornam conteúdo nem metadados; conteúdo privado pendente não reaparece na UI.

### AUD07-30 Provar IdP/OIDC e comportamento com réplicas

**Responsável sugerido:** identidade e runtime. **Origem:** A15.

Validar membership desativada/incompleta, troca de workspace e buckets de rate limit em mais de
uma instância, com o resolver documentado.

**Aceite:** o contrato de cada adapter está documentado e testado; membership inválida é
negada; caches e janelas de revogação estão identificados.

### AUD07-31 Executar campanha RAG representativa

**Responsável sugerido:** retrieval, avaliação e domínio. **Origem:** A14.

Usar corpus autorizado e representativo, splits de treino/calibração/reserva e adjudicação
aprovada antes de medir; estratificar por dificuldade, ambiguidade e risco.

**Aceite:** métricas de ranking, vazamento ACL, suporte/completude de citações, unsupported
claims e faithfulness com incerteza e proveniência; os **5 fixtures sintéticos** atuais não
substituem esta tarefa; corpus insuficiente mantém a campanha `BLOCKED_EXTERNAL`.

### AUD07-32 Provar fencing com múltiplos workers reais

**Responsável sugerido:** worker e runtime. **Origem:** A15.

Executar o gate de dois processos com PostgreSQL real, perda de lease e retry concorrente.

**Aceite:** nenhuma dupla publicação nem corrupção; transições de estado coerentes após perda de
lease; resultado registrado para o candidato.

### AUD07-33 Executar corpus hostil de arquivos em worker isolado

**Responsável sugerido:** ingestão e segurança. **Origem:** A15.

Rodar `make file-security-runtime` com limites de tempo, memória, CPU, saída e redação
declarados previamente.

**Aceite:** os dez casos hostis são contidos e redigidos; excedente de recurso falha fechado;
artefato vinculado ao candidato.

---

## M6 — Operação, performance e recuperação

### AUD07-34 Provar collector, alertas e tracing distribuído

**Responsável sugerido:** observabilidade e operação. **Origem:** A18.

Observar tracing, métricas e alert routing no runtime real; exercitar collector indisponível e
ausência de amostras.

**Aceite:** trace relaciona request/job/provider; labels e payloads redigidos e limitados;
alertas chegam ao destino; ausência de coleta produz `no_data`/alarme e não vira `PASS`.

### AUD07-35 Medir backup/restore, RPO e RTO

**Responsável sugerido:** dados e operação. **Origem:** A18.

Executar `seed → backup → destroy → restore → rebuild → verify` somente em ambiente descartável,
com budgets de RPO/RTO definidos **antes** do ensaio.

**Aceite:** checksums, contagens e relações reconciliados; isolamento preservado; RPO/RTO dentro
dos budgets ou limitação explícita; dump íntegro sozinho não aprova restore.

### AUD07-36 Medir capacidade e latência representativas

**Responsável sugerido:** performance e operação. **Origem:** A18.

Definir workload, concorrência, limites, topologia e critérios antes de medir API/worker/web/
provider; separar latência local de custo de provider.

**Aceite:** p50/p95/p99, throughput, erros, CPU/memória, filas e custo por cenário; budgets
aprovados cumpridos ou limitação explícita; amostra, warm/cold, recursos e versão registrados.

### AUD07-37 Ensaiar falhas e recuperação controladas

**Responsável sugerido:** runtime e operação. **Origem:** A18.

Planejar quedas, timeout/429, particionamento, reconexão e reinícios dentro dos limites
acordados, com interrupção e recuperação definidas antes da injeção.

**Aceite:** retries permanecem bounded; não há dupla publicação, corrupção ou retry storm;
indisponibilidade aparece como erro/degradação correta; replay preserva idempotência e tenant
scope.

### AUD07-38 Executar soak com limites de recursos

**Responsável sugerido:** confiabilidade e operação. **Origem:** A18.

Após carga e falhas, sustentar o workload pela janela aprovada acompanhando memória, threads,
conexões, filas, storage, redação e retenção.

**Aceite:** sem crescimento indevido além dos budgets; erros e latência aceitáveis; dados
íntegros ao fim; processo curto sem carga não é soak.

---

## M7 — Evidência, reauditoria e promoção

### AUD07-39 Gerar evidência de release e imagens rastreáveis

**Responsável sugerido:** release e supply chain. **Origem:** A19.

Executar `make release-evidence` e construir/escanear/SBOM/assinar as imagens no candidato
exato, com inputs por digest e proveniência.

**Aceite:** manifesto commit-bound gerado; scans sem HIGH/CRITICAL; assinaturas verificáveis;
nenhuma imagem promovida sem pertencer ao candidato identificado.

### AUD07-40 Selecionar pacote de promoção vinculado ao candidato

**Responsável sugerido:** release. **Origem:** A19.

Compor o pacote com CI, evidências de runtime, imagens/digests, scans, assinaturas e pareceres
todos apontando para o mesmo SHA; selar com referência imutável.

**Aceite:** o pacote não pode ser autopromovido por declaração; qualquer gate `NOT_RUN`,
`BLOCKED_EXTERNAL`, `STALE` ou falho mantém o pacote em `NO-GO`.

### AUD07-41 Reauditar as 26 áreas sobre o candidato exato

**Responsável sugerido:** revisão independente. **Origem:** A19.

Repetir a metodologia da auditoria de 07/10/2026 sobre o candidato selecionado, recalculando as
26 notas e reavaliando A01–A20.

**Aceite:** notas, comandos, exit codes e limites publicados com data/hora UTC, SHA e estado do
worktree; achados fechados são provados por regressão, não por declaração.

### AUD07-42 Decisão Go/No-Go explícita com riscos residuais

**Responsável sugerido:** autoridade de release. **Origem:** A19.

Registrar a decisão com escopo, riscos residuais aceitos, responsável por recuperação e
condições de rollback, conforme o [runbook de release](operations/release-readiness.md).

**Aceite:** a decisão é explícita e atribuída; um gate obrigatório falho/ausente mantém
`NO-GO` **independentemente da nota média**; canary e rollback estão preparados e testados.

---

## Rastreabilidade dos achados

| Achado | Tarefa de correção |
|---|---|
| A01 Remoção dos legados não reconciliada | AUD07-02 → 03, 04, 06, 22, 23, 25 |
| A02 Coleção arquivada continua pesquisável | AUD07-11, 12 |
| A03 Idempotência cruza conversas | AUD07-10, 12 |
| A04 Três rotas fora do `ROUTE_REGISTRY` | AUD07-07, 13 |
| A05 Artefato `.next-audit-*` quebra o lint | AUD07-05 |
| A06 Testes apontam para caminhos legados | AUD07-06 |
| A07 Basenames duplicados entre pacotes | AUD07-16 |
| A08 Bootstrap irreproduzível | AUD07-08, 21 |
| A09 Sem type-checker Python | AUD07-17 |
| A10 Duas vulnerabilidades HIGH no npm | AUD07-15 |
| A11 2 GB não versionado / árvore de 5,1 GB | AUD07-18, 19 |
| A12 Baseline não selada | AUD07-01 |
| A13 Documentação contradiz o checkout | AUD07-22, 23, 24 |
| A14 Evidência de qualidade de IA insuficiente | AUD07-31 |
| A15 Nenhuma evidência de runtime real | AUD07-28–33 |
| A16 `production_safe` sem probe | AUD07-14 |
| A17 Skips não classificados | AUD07-20, 26 |
| A18 Performance/chaos/soak não executados | AUD07-34–38 |
| A19 Pacote de promoção não gerável | AUD07-09, 27, 39, 40, 41, 42 |
| A20 Lanes raiz de `tests/` são placeholders | AUD07-25 |

AUD07-01 preserva a baseline; AUD07-09 e AUD07-27 integram os gates locais; AUD07-28–38 tratam
as lacunas externas; AUD07-39–42 tratam a promoção. Este roteiro não promove disponibilidade
dos recursos externos nem execução por meio deste documento.
