# ExecPlan — Implementação do roadmap AUD26

**Início:** 2026-10-01. **Owner:** lead integrator desta sessão. **Autorização:** usuário pediu executar todas as melhorias do roadmap local. **Estado:** BUILD em progresso; roteiro complementar ao plano canônico `.agent/plans/phase-3-runtime-evidence-production-promotion.md`, sem alterar seus pointers, gates ou ledgers.

## Objetivo

Fechar as melhorias locais AUD26-01 a AUD26-07 com mudanças pequenas, regressões que rejeitem casos conhecidos e revisão independente. Preparar, mas não alegar concluídos, AUD26-08 a AUD26-11 enquanto dependerem de D01–D07, serviços/dados autorizados, operações ou decisão de promoção.

## Contexto e restrições

- Repositório brownfield na branch `main`, HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`; origem sincronizada. O worktree já tem muitas alterações/untracked de outras atividades. Editar somente superfícies atribuídas, sem limpar, reverter, formatar globalmente ou assumir autoria de alterações preexistentes.
- `.agent/` contém o trabalho canônico ativo Q17-01.A, cuja única ação continua sendo o inventário read-only de migrations implantadas sujeito a D02. Não o alterar nesta execução. O Gauntlet existente foi retomado com seu objetivo original e seus 14 critérios preservados; o bar não será enfraquecido nem substituído.
- `cvg-master-rag-v2/AGENTS.md` rege aquele repositório filho; nenhum arquivo do filho, de `rick-professor/` ou de `modulo-redis-locker/` está na ownership desta execução.
- Não consultar `.env`, tokens, bancos instalados, corpus/provider reais nem o conteúdo do benchmark visual protegido. Não executar migration em banco, Docker/Compose, deploy, restore, carga, chaos, soak, assinatura ou promoção. A execução web autorizada deve isolar os artefatos de saída para não sobrescrever a evidência anterior.
- O primeiro critic de baseline retornou `BLOCKED` depois de um grep fora do escopo, embora o mutation sentinel `repository+state` tenha permanecido idêntico. Não usar esse parecer como aceite; críticas pós-implementação usarão escopos menores e sentinels novos.

## Bar e aceite complementar

O bar full-product imutável está em `.gauntlet/bar.json`, versão `state-of-art-aaa-v1-schema-recovery`, SHA-256 `1aa41cbe372a5dc907feb50dcf24875740c6ec122e7d1f14906e20e1927f070b`. O trabalho abaixo mapeia para SA-SECURITY, SA-API, SA-DURABILITY, SA-OPERATIONS, SA-REGRESSION, SA-WEB, SA-VISUAL e SA-REVIEW sem declarar esses critérios de produto inteiro satisfeitos por testes locais.

| Critério local | Aceite observável | Prova que pode rejeitar caso ruim |
|---|---|---|
| AUD26-01a — login | Login tenant-only tem sucesso somente com uma membership ativa elegível; ambiguidade não cria sessão nem revela workspaces. Sessões e grants permanecem amarrados à membership escolhida. O contrato atual sem `workspace_id` permanece compatível. | Testes provider/store para 0/1/2 memberships, estados ativo/desabilitado, grants distintos e ausência de sessão em ambiguidade; API auth regressions. |
| AUD26-01b — refresh/recovery | Refresh de authorization-context exige user, tenant e workspace exatos e nunca projeta grants de uma membership irmã. Emissão de recovery só usa membership única ativa; erros de lookup/token-store e delivery não diferenciam a resposta pública entre conta resolvida, ambígua ou desconhecida. Erros logam somente request ID e tipo. Escopo ausente ou membership revogada falha fechado. | Testes memory e PostgreSQL-store fake com memberships irmãs de papéis/grants diferentes; endpoints recovery comparados sob lookup-error, delivery-error e token resolvido/ausente; nenhum segredo/PII em logs. |
| AUD26-02 — migration 0008 | Nomes de constraints já presentes só são aceitos quando tabela, tipo, colunas/origem, referências, ações e `convalidated` atendem o contrato. Constraint errada ou `NOT VALID` aborta a migration e não avança o ledger. Não alterar migrations/checksums anteriores, não reparar dados automaticamente. | Regressões SQL opt-in no fixture descartável para CHECK homônima, FK errada/não validada e pré-requisitos 0004 incompatíveis; testes estáticos conhecidos-bons/ruins. Até obter D02, executar somente testes offline/static. |
| AUD26-03 — CI coverage | A lane quality executa suites root de jobs, storage e migrations offline; testes Docker/PostgreSQL opt-in continuam desabilitados. | Inspeção/teste estático que falha se chamadas/lock forem removidos; as suites command-level locais rodam sem `RICK_MIGRATION_POSTGRES_TESTS`. |
| AUD26-04 — lock hashes | Instalações de runtime/test/scanner/evaluator usadas pelas lanes canônicas vêm de locks gerados com hashes e são instaladas por `--require-hashes`; workflows históricos dos três repositórios filhos ficam fora desta mudança. | Checker estático falha em pip install direto/pins sem hash nas workflows canônicas; lock reproduzível e `pip check`. |
| AUD26-05 — evento ingestion | Com sink saudável e isolado, os três eventos lifecycle são observados uma vez e em ordem. Se callback `enqueued` exceder o deadline bounded, a ingestão continua; o teste não confunde callback terminal com conclusão dos anteriores e não exige ordenação pós-timeout. Nenhum dado sensível entra em eventos. | Teste determinístico com lane própria: drenar antes do snapshot; segundo caso segura `enqueued`, verifica timeout e publicação do job, depois libera e faz teardown. Repetir sem sleeps arbitrários; inspecionar contadores timeout/drop. |
| AUD26-06 — web | Build atualizado e matriz Playwright configurada por benchmark termina integralmente, incluindo 375/768/1440, sem alterar benchmark ou relatórios anteriores; capturas novas ficam em diretório único. | `make web-validate` com caminhos de evidência isolados, contagem final do runner, resultados/artefatos e inspeção de screenshots/console/axe disponíveis. Não declarar que o conteúdo do benchmark foi revisado. |
| AUD26-07 — toolchain docs | README distingue Qdrant 1.12.5/Redis 7.4 atuais de imagens Phase 0.6 históricas 1.7.4/7.0.15 e aponta para `toolchain.json`. Índice, relatório, roadmap e backlog descrevem o resultado e bloqueios atuais. | `scripts/phase11/check_toolchain.py`, `make validate`, validação de links/diff e leitura dos documentos atualizados. |
| AUD26-08..11 — externos | Nenhuma execução externa é necessária para os sete itens locais; gates D02 (inventário live), D01–D04 (runtime/dados/provider/corpus), D05 (SLO/DR/carga) e D07 (promoção) continuam `BLOCKED`/`NOT_RUN` até autoridade explícita. | Conferir status sem contatar/alterar os sistemas protegidos e manter a decisão de produto `NO-GO`. |

## Change surface e contratos

| Lane | Ownership | Não editar |
|---|---|---|
| Identity | `packages/identity/{src,tests}`, `apps/api/src/services/{identity_service,postgres_identity}.py`, testes específicos de identity/auth/authorization context | API request/OpenAPI/web, migration/CI, `.agent/`, `.gauntlet/bar.json`, repositórios filhos |
| Migration | `infrastructure/migrations/0008_composite_scope_constraints.sql`, `infrastructure/scripts/tests/test_composite_scope_migration_static.py`, casos novos no `test_migrate.py` | SQL/checksums 0001–0007/repair 0004, Makefile/workflows, executar Docker/DB |
| CI/locks | `Makefile`, `.github/workflows/quality.yml`, `.github/workflows/state-of-art-quality.yml`, lock inputs/outputs sob `requirements/`, checker estático novo/adjacente | código identity/migration/telemetry/web, workflows históricos Phase 0.x/1.x e manifests dos filhos |
| Ingestion-test harness | `apps/api/tests/test_phase16_root.py`, testes mínimos em `packages/observability/tests` se necessários | semântica de entrega do sink salvo reprodução que demonstre violação do contrato, CI/identity/migration |
| Docs + web verification | `README.md`, este ExecPlan, relatório/roadmap/backlog/index AUD26, `apps/web/playwright.config.ts` test discovery e execução da matriz | benchmark protegido (somente lido pelo Playwright autorizado), evidência anterior, artefatos de `.gauntlet-state-of-art/evidence` existentes, arquivos de `.agent/` |

Contratos congelados: nenhuma alteração à API de login/OpenAPI é necessária para a opção fail-closed de membership ambígua; continuação `tenant_id` só funciona se houver uma membership ativa única. Injeções externas de `IdentityProvider` permanecem atrás do contrato existente. Migration 0008 pode ser corrigida antes de qualquer aplicação; não tocar em checksum aplicado nem executar SQL live. Testes de CI para runtime PostgreSQL devem remover explicitamente a variável opt-in.

## Riscos e decisões

- **HIGH — autorização/workspace:** uma query tenant-only pode escolher role/grants de membership irmã; reduzir com resolução única para login e workspace exato no refresh, sem listar workspaces para não autenticados.
- **HIGH — integridade persistente:** handler genérico `duplicate_object` pode aceitar constraint incompatível; verificar catálogo e abortar transacionalmente; não “consertar” dado ou histórico.
- **MEDIUM — supply chain/CI:** workflow pode passar com instalações sem hashes ou sem executar suites; fechar pelo lock canônico sem mexer no pipeline dos três filhos.
- **MEDIUM — telemetria/testes:** o sink assíncrono é bounded/best-effort. O teste deve aguardar o critério observável; não mudar o produto para prometer entrega/order que o contrato não tem.
- **MEDIUM — UI/evidência:** Playwright escreve screenshots e build cache; usar destino novo e registrar artefatos pós-build. Reexecução de suite preserva o benchmark de entrada.
- **EXTERNAL — produto/produção:** Docker/DB, corpus/provider, SLO/restore, deploy e promotion continuam bloqueados por D01–D07; não inferir aceitação.

## Sequência e recuperação

1. Baseline já observada: identity/provider/Postgres-store/API auth 41 passed/9 avisos com `PYTHONPATH` completo; migration static 2 passed; checksum check 8 migrations passed/execução `NOT_RUN`; API event test 20/20 repetições passou. A primeira execução de identity falhou na coleta por `PYTHONPATH` incompleto (faltou `apps/api/src`); preservar essa falha de harness.
2. Implementar três lanes sem sobreposição (identity, migration, CI/locks) em paralelo, cada uma retornando diff, causa confirmada, comandos e limitações; nenhum descendente.
3. Integrar e conferir ownership/diff; Critic independente por lane com pacote fechado e mutation sentinel; corrigir achados, retestar e registrar resultado.
4. Corrigir o teste de evento com a reprodução de callback anterior atrasado, preservar o primeiro caso vermelho, repetir a lane saudável e o caso de timeout em execução serial e sob concorrência local.
5. Corrigir README e rerodar a matriz web com output isolado; preservar `benchmark.json` e diretórios de evidência históricos.
6. Executar regressão API/domain/worker/identity, migrations offline, jobs/storage, `make validate`, static/lock checks e `git diff --check`; criticar integração e depois obter Final Critic fresco.
7. Atualizar documentos AUD26 como proposta/evidência, sem promover os itens 08–11. Não modificar o active action Q17-01.A ou os ledgers `.agent/`.

Cada rodada conserva primeira falha, fingerprint e comandos. Se uma lane precisar de arquivo externo à ownership, pausar e integrar sequencialmente. Para retomar: ler este plano, `docs/backlog-auditoria-2026-10-01.md`, estado atual do Gauntlet (bar original preservado), hashes de evidência e worktree; não repetir D02.

## Progresso

- **Concluído:** recuperação e instruções; três scouts read-only; Gauntlet full AAA retomado com os 14 critérios originais; baseline focused executada; builders identity, migration e CI retornaram implementações; CI critic aprovou somente wiring/configuração estática AUD26-03/04; mutation sentinel do review pós-build bateu.
- **Falhas/limites preservados:** a primeira chamada identity omitiu `apps/api/src` de `PYTHONPATH` e falhou na coleta; rerun 41/41 passou. O primeiro Critic de baseline foi `BLOCKED` por grep fora do pacote fechado; o segundo critic válido rejeitou os gaps locais. Após build, o critic identity detectou diferença de recovery delivery; migration critic ficou `BLOCKED` por falta de prova de bytes antigos/live PostgreSQL; CI critic aprovou apenas wiring/configuração estática, não runner remoto. A primeira versão do novo teste de delivery falhou porque alterou o objeto fixture antes do app shallow-copy; corrigida para configurar `client.app.state.providers`; rerun focused 2/2 passou.
- **Reprodução AUD26-05:** com callback `enqueued` bloqueado além do timeout, o sink publicou `started,published` enquanto `enqueued` ainda aguardava; resultado anterior ao fix/teste `sha256=1159f0eef9b193c794c74e560db30c0d66507d359c925ac10fa77ef9a7ee83c2`. Isso confirma a lacuna no snapshot após evento terminal, não uma falha do estado de ingestão.
- **Concluído nesta correção:** recovery lookup/token-store e delivery failures agora preservam resposta neutra e logam somente request ID/tipo. O teste route cobre token existente, membership ambígua, endereço desconhecido, exceção de emissão e falha de delivery nos dois endpoints; focused passou 2/2. Os dois testes de evento passaram 2/2; o fixture saudável drena sua lane isolada, e o teste lento confirma publicação do job com timeout de telemetria.
- **Ativo:** obter crítica fresh da recuperação-neutralidade, verificar hashes históricos, repetir eventos/API e executar a matriz web em diretório isolado.
- **Próxima ação executável:** rodar toda a suíte `apps/api/tests/test_auth.py` e a repetição de evento sob runner isolado; em seguida executar `make web-lint web-typecheck web-build web-e2e` com `WEB_CURRENT_EVIDENCE_DIR` em `.runtime/aud26/...`, preservando cobertura anterior em `.runtime/qa/`.
