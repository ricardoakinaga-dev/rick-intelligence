# Implementação AUD15 — resultado parcial e evidências

**15/10/2026 · America/Sao_Paulo · verificações e crítica independente locais concluídas.** Perfil selecionado `postgres-local-v1`; BUILD/VERIFY, preparação local reversível. **Não é conclusão integral dos planos nem autorização de produção.** O [backlog canônico](<../../.agent/backlog.json>) é a única fonte de status/aceite; esta página descreve observações, não cria outro controlador. A [auditoria original](<relatorio-auditoria-2026-10-15.md>) e sua nota histórica não foram reescritas.

## Gauntlet Result

**Goal**

Implementar o [backlog AUD15](<../backlog-auditoria-2026-10-15.md>) e o [roadmap](<../roadmap-auditoria-2026-10-15.md>), preservar patches anteriores e continuar PROD12 sem inventar autoridade, evidência externa ou aceite.

**Quality Bar**

A [barra B01–B17 v1](<evidence/aud15-implementation-20261015/quality-bar.md>) permanece congelada. **B01 falha; B16 não satisfeito; B14/B17 conservam bloqueios externos.** Melhoria local não converte o objetivo completo em PASS. Os 24 contratos estão adotados, sem fechamento automático; os 92 itens anteriores e seus aceites não foram substituídos. O umbrella de preparação não satisfaz predecessores AND.

| Critério | Observação e validade |
|---|---|
| B01 | **FAIL:** logout com sink síncrono bloqueado pode persistir `completed` depois de HTTP503. Teste genuíno continua falhando, sem skip/xfail. |
| B02 | Regressões locais de quota antes de KDF/consume e single-use exercitadas; stores reais continuam separados. |
| B03–B04 | Pergunta/idempotência e revisões de drafts preservadas; abort de mutação mantém aviso de resultado indeterminado, não afirma rollback. Matriz browser final local passou. |
| B05 | Protocolo v2 com marcadores independentes, bootstrap, stamp e leases. Eventos legados observados são conservadores; rolling mixed-version não validado. |
| B06–B07 | Falha de autoridade não vira anonimato; limites/deadline incluem quota síncrona/assíncrona e inicialização lazy, com cancelamento retendo admissão até término real. Não é prova de capacidade distribuída. |
| B08 | Inventário contempla manifesto ativo e somente o archive histórico exato/provado; desconhecidos ou bytes divergentes falham. |
| B09–B12 | Paginação além de 50, revalidação pós-403, mesmo job e envelopes runtime implementados/testados localmente; regressão browser final local passou. |
| B13 | Matriz attach/detach/corpo preserva resultado/exceção original; telemetria distribuída não executada. |
| B14 | Toolchain correta executada; diagnóstico VPS recusado pela política original e 221 skips classificados. Lane real não aprovada. |
| B15 | Cobertura/tipos têm denominadores explícitos abaixo; não há certificado WCAG global, tipagem de todo monorepo ou cobertura global inferida. |
| B16 | **Não satisfeito:** regressão B01 aberta e VPS sem executor compatível, apesar de CI/build e verificações web locais verdes. |
| B17 | **NOT_RUN/BLOCKED_EXTERNAL:** runtime/providers/DR/carga/soak/release não substituídos por mocks. |

**Rounds**

1. Preservação/adopção e implementação por fronteiras de identidade/web/integração.
2. Críticas independentes expuseram quota fora da admissão, perda de estado e guards incompletos; correções e novos negativos.
3. Integração encontrou abort de casos, incompatibilidade de adapters delegados, múltiplos produtores de sessão e saúde legítima com `detail:null`; reproduções RED preservadas.
4. CI/build, instalação limpa e360 cenários locais passaram no candidato759/8bc. Critic independente rejeitou B01, lookup de reset fora do offload, falta de browser offline durante envio e tipagem parcial.
5. Lookup/consume/conversão de reset e checkpoint pós-lookup corrigidos; teste browser nativo durante POST passa nos três viewports;27 erros de tipagem resolvidos e quatro novas fronteiras adotadas com limite zero. Candidato760/6d056 congelado: CI/build e363 cenários passaram; coorte Python ampliada permanece vermelha por B01/277VPS. Fonte/denominadores estáveis após as duas invocações; Critic final novo/read-only concluiu **REJECT** por B01 e gates VPS/externos; confirmou remediações locais B03/B07 e escopos de tipagem sem declarar aceite canônico.

**Major gaps discovered**

1. **Decisão material pendente sobre logout/auditoria.** Uma verificação antes de `emit()` não cancela persistência síncrona já aceita. Revogação pode ter ocorrido, mas HTTP503 não confirma a conclusão. É preciso ratificar capacidade transacional/fencing exigida do sink ou semântica explícita de resultado indeterminado. Não removi o teste nem alterei B01 para aprovar o código. [Regressão](<../../apps/api/tests/test_aud15_identity.py>) · [resultado Python atual](<../../.runtime/implementation-aud15-20261015/lead/python-full-3.log>).
2. **Executor VPS incompatível:** captura real recusada por `unprotected input parent`; No namespace observado: UID/GID1000, raiz com ownership65534 não mapeado e `/tmp` sticky pertencente a1000; isso não determina privilégios/ownership do host. Não foram alterados DAC/ownership/namespace. Os 277 resultados da lane não provam 277 defeitos independentes nem aprovação futura em outro host. [Diagnóstico](<../../.runtime/implementation-aud15-20261015/lead/vps-preflight.json>) · [procedimento](<../operations/vps-github-images.md>).
3. **221 corpos de testes não executados:** 215 dependem de PostgreSQL descartável autorizado, cinco de Qdrant e um de DAC multi-UID representativo. Cada nó tem motivo, fixture, obrigação, autoridade e owner **proposto**, não designado. [Primeira observação](<evidence/aud15-implementation-20261015/test-outcomes-first-run.json>) · [segunda observação integral](<evidence/aud15-implementation-20261015/test-outcomes-second-run.json>) · [terceira observação integral](<evidence/aud15-implementation-20261015/test-outcomes-third-run.json>).
4. **Compatibilidade de sessão:** bootstrap multi-produtor protege escritores v2 cooperantes. O protocolo legado não permite reconstruir uma operação já sobrescrita antes do boot. Cutover/reload e coexistência de bundles exigem política humana antes de produção; não impus bloqueio retroativo arbitrário. Mesmo em v2, operação órfã/armazenamento instável fica fail-closed e requer resolução pelo writer/suporte; não há limpeza automática de marcadores desconhecidos. Isso protege segurança, não garante disponibilidade de recuperação sem política operacional. [Limite documentado](<../../apps/web/README.md#L55-L72>).

**Major improvements**

- Identidade: logout OIDC não finge revogação; outage difere de credencial inválida; reset limitado antes de custo/consumo; offload compartilhado de40 operações, fila zero e deadline absoluto por request. Sync/async/lazy quota usam a mesma admissão; threads/corrotinas abandonadas continuam contadas até término real. Adapters delegados continuam suportados sem executar descoberta potencialmente bloqueante fora do worker. [Offload](<../../apps/api/src/services/identity_offload.py>) · [auth](<../../apps/api/src/routes/auth.py>) · [quota](<../../apps/api/src/core/rate_limit.py>).
- Sessão/web: árvore anterior retida apenas em memória, oculta/inert durante revalidação; mesma autoridade restaura draft/foco, outra descarta. JSON/FormData/SSE têm leases, abort e fences de callbacks/corpos. Marcadores opacos por operação impedem settled B liberar C; armazenamento indisponível/instável falha fechado, sem timer que invente autoridade. [Provider](<../../apps/web/components/session-provider.tsx>) · [coordenação](<../../apps/web/lib/session-coordination.ts>) · [leases](<../../apps/web/lib/client-authority.ts>).
- Casos: revisões monotônicas, exclusão de submit duplicado, preservação de edição B após A e aviso honesto no abort; paginação/dedup/contagens/erro de próxima página e callback de escopo antigo. [Workspace](<../../apps/web/components/cases/case-workspace.tsx>).
- Documentos: observação limitada a9.600ms e backoff; pausa/retomada e consulta manual do mesmo job, sem segundo upload/retry implícito, sem persistir fonte/ID no browser. Retry explícito pode retornar sucessor novo, GET/cancel não. [Página](<../../apps/web/app/app/documents/page.tsx>) · [observador](<../../apps/web/lib/job-tracking.ts>).
- HTTP: respostas HTML/JSON inválido/campos/tipos/booleans/IDs inconsistentes rejeitadas antes de sucesso. `detail:null` real da saúde agora é aceito como definido pela API; tipos incompatíveis continuam rejeitados. Fixtures inválidas não motivaram permissividade genérica. [Guards](<../../apps/web/lib/response-contract.ts>) · [regressões](<../../apps/web/tests/unit/aud15-api.test.ts>).
- OTel: somente um yield, falhas de attach/detach separadas do corpo e exceção de negócio preservada. [Implementação](<../../apps/api/src/core/otel.py>) · [testes](<../../apps/api/tests/test_otel.py>).
- Supply: classificação histórica restrita por caminho, hashes e proveniência; não foi aplicado filtro amplo a runtime, nem excluído archive de varredura de segredos. [Inventário](<../../scripts/phase11/frontend_supply_runtime_gate.py>) · [política](<../local-runtime-archive-20261011.md>).

**Verification performed**

| Verificação | Resultado observado | Limite |
|---|---|---|
| Python ampliado, terceira execução | **7.749 passed,278 failed,221 skipped,88 subtests passed**, exit1,765,46s |277 lane VPS +1 B01, nenhuma outra falha local. [Log](<../../.runtime/implementation-aud15-20261015/lead/python-full-3.log>) · [inventário por nó](<evidence/aud15-implementation-20261015/test-outcomes-third-run.json>) |
| Complemento controlador, disjunto | **15PASS +11 subtests**,exit0 | O testpaths padrão não inclui docs/ci; invocação explícita recompõe a fronteira anterior, sem apagar testes. União de duas invocações:7.764PASS/278FAIL/221SKIP/99subtests, **não** stdout de uma invocação única. [Log](<../../.runtime/implementation-aud15-20261015/lead/python-full-3-control-complement.log>) · [prova de disjunção/coorte](<../../.runtime/implementation-aud15-20261015/lead/python-final-cohort.json>) |
| API — produção | **79,92%**,10.216/12.782 statements,57 arquivos; floor75 preservado | Medição da terceira suite ampliada, não só alvo estreito CI; B01 continua falhando. [Resumo final](<../../.runtime/implementation-aud15-20261015/lead/api-coverage-final-summary.json>) |
| Worker — produção | **80,98%**,3.628/4.480 linhas executáveis,11 arquivos; floor74 preservado | Testes excluídos pelo config canônico; não mede pacotes compartilhados/serviços reais. [Resumo final](<../../.runtime/implementation-aud15-20261015/lead/worker-coverage-final-summary.json>) |
| Web — Node22.19.0/npm10.9.3 | **258 testes PASS,90,65% linhas,19 arquivos**, floor85 preservado | Original10 +9 superfícies; não todo frontend. [Resumo](<../../.runtime/implementation-aud15-20261015/lead/web-protocol-node22-summary.json>) · [log](<../../.runtime/implementation-aud15-20261015/lead/web-protocol-node22.log>) |
| Tipagem Python canônica | **13 originais +8 fronteiras=21 arquivos**, todos limites0; seis fronteiras sem defs não tipadas |27 erros/quatro arquivos corrigidos antes da adoção, sem aceitar dívida ou ignorar imports ausentes. Imports fora do denominador seguem interfaces; não é todo monorepo. [Log integrado](<../../.runtime/implementation-aud15-20261015/lead/mypy-final-expanded-strict.log>) · [config](<../../mypy.ini>) · [baseline](<../baselines/mypy-baseline.txt>) |
| CI canônico | **Quarta execução exit0**, candidato760/6d056 | Primeira exit1 por inventário não citado, corrigido por citação funcional, sem alterar política. [Falha preservada](<../../.runtime/implementation-aud15-20261015/lead/ci-final-node22.log>) · [CI final](<../../.runtime/implementation-aud15-20261015/lead/ci-final-node22-4.log>) |
| Build/TypeScript Node22 atual | **exit0 / exit0** | Build final usa API loopback18101, não deploy; CI final inclui os tipos. [Build servido](<../../.runtime/implementation-aud15-20261015/lead/web-build-final-matrix-4.log>) · [tipos explícitos](<../../.runtime/implementation-aud15-20261015/lead/web-types-protocol-node22.log>) |
| Bootstrap final, diretório novo | **Instalação limpa exit0 e build exit0**, Node22/npm10 | Lock intacto; precede as últimas fixtures browser e mudanças API/tipos. **Código de produção web/config/lock** byte-idêntico desde essa cópia; não é bootstrap do backend nem da árvore final inteira. [Fonte](<../../.runtime/implementation-aud15-20261015/lead/bootstrap-final-source.json>) · [instalação](<../../.runtime/implementation-aud15-20261015/lead/bootstrap-final-install-node22.log>) · [build](<../../.runtime/implementation-aud15-20261015/lead/bootstrap-final-build-node22.log>) |
| Browser completo, primeira execução |336PASS/21FAIL,357 cenários em375/768/1440 | Uma incompatibilidade real de saúde, cinco fixtures/harness e um seletor ambíguo. [Log inicial](<../../.runtime/implementation-aud15-20261015/lead/browser-production-1.log>) |
| Browser completo, segunda execução |**358PASS/2FAIL**,360 cenários,6,2min | Os sete grupos anteriores passaram; mobile/tablet expuseram outro harness: histórico real401 concorria com identidade mockada. Trace confirmou a causa; fixture agora403 canônico coerente com falta de history.read, sem relaxar autoridade. [Log](<../../.runtime/implementation-aud15-20261015/lead/browser-production-2.log>) |
| Fronteiras Python após19ª fonte web |**80PASS**,1,15s,exit0 | Resumo/denominadores, inventário, ratchet de tipos e diagnóstico VPS; não executa lane DAC real. [Log](<../../.runtime/implementation-aud15-20261015/lead/python-final-frontiers.log>) |
| Browser completo, candidato anterior759/8bc | **360PASS,0FAIL/0SKIP**,5,4min,exit0 |375/768/1440; inclui nove execuções multiaba v2 e três do teste de recuperação corrigido. Build de produção local/backend sintético não prova stores/IdP reais. [Log](<../../.runtime/implementation-aud15-20261015/lead/browser-production-3.log>) · [fonte idêntica antes/depois](<../../.runtime/implementation-aud15-20261015/lead/candidate-after-final-gates.json>) |

**Matriz browser final:** **363PASS,0FAIL/0SKIP**,5,0min,exit0, nos três viewports. [Log](<../../.runtime/implementation-aud15-20261015/lead/browser-production-4.log>) · [vinculação760/6d056 e prova de reuso unitário web](<../../.runtime/implementation-aud15-20261015/lead/candidate-after-browser-round5.json>). As258 unidades/19 fontes permanecem byte-idênticas; não se reaproveita por isso a aprovação de backend ou da árvore inteira. O novo teste retém o primeiro POST, usa a transição de rede do browser, exige ação explícita para retry com payload/key idênticos e conclui a resposta antiga após a recuperação. A proteção contra transporte que ignora abort também tem negativos jsdom; a prova browser usa cancelamento nativo, não certifica dedup servidor.

Candidato executável/config explícito atual: **760 arquivos**, fingerprint `6d0562090d560f2c6a68b9ac1765f2988134180ecb1d693c0414b6a95a08645e`, HEAD `48e383c25ca4af32aa7ffe7e2367360ca9742c58`. O [manifesto atual](<../../.runtime/implementation-aud15-20261015/lead/candidate-before-final-round-5.json>) registra dez fontes/configs alteradas e um novo módulo de testes frente ao [candidato759/8bc](<../../.runtime/implementation-aud15-20261015/lead/candidate-before-browser-final.json>), além de vincular separadamente baseline de tipos e barra congelada. O escopo não é hash integral da árvore nem incorpora automaticamente controle/docs/runtime. A [baseline inicial](<../../.runtime/implementation-aud15-20261015/entry/manifest.json>) preserva1.507 hashes e o patch anterior. Arquivos Next gerados foram comparados/restaurados aos bytes de entrada, não ao HEAD.

Cobertura web adicional: statements86,30% (1.954/2.264), branches79,98% (1.690/2.113), funções87,33% (393/450), skipped0 no relatórioV8. O chat workspace isolado tem77,52% linhas/66,61% branches: o agregado não significa que todo módulo ou ramo passou de85%. O floor85 é de **linhas**, não foi trocado por outro numerador. Python mediu linhas/statements executáveis, **sem branch coverage**;66 linhas API e88 worker excluídas pelas regras efetivas. A contagem API era47 antes dos novos protocolos/TYPE_CHECKING; **não houve nova regra de exclusão nem redução de escopo** para obter verde. Os relatórios particionados preservam os resumos por arquivo e o SHA do JSON bruto.

A **segunda** execução Python precedeu a19ª fonte web; os80 testes suplementares revalidaram os metadados então vigentes. A terceira execução já inclui19 fontes web e21 fontes MyPy. A coorte final mantém todos os labels anteriores salvo o teste de declaração18 renomeado para19, acrescentando44 casos líquidos; os15 testes docs/ci ausentes do testpaths padrão foram executados separadamente, não removidos. Não se somam esses testes aos7.720 para fabricar uma suite integral nova. A [comparação das duas coletas](<../../.runtime/implementation-aud15-20261015/lead/python-run-comparison.json>) registra9 labels adicionados,1 renomeado/removido e3 falhas que passaram (dois adapters delegados e igualdade do denominador): saldo+8 casos,+11PASS/−3FAIL. Os99 subtests aparecem no total da suite/stdout, não como linhas individuais de testcase no XML. Amostragem visual direta: [chat mobile](<../../.runtime/implementation-aud15-20261015/lead/visual-production-2/chat-mobile.png>) e [modal/foco desktop](<../../.runtime/implementation-aud15-20261015/lead/visual-production-2/keyboard-confirmation-desktop.png>), produto web byte-a-byte inalterado desde essa captura; não é certificação assistiva/WCAG global.

### Correspondência dos 24 contratos — não é ledger de aceite

| Contrato | Preparação/entrega observada e limitação |
|---|---|
| T001 | Baseline/cópia/patch e adoção preservados. Prova final:92 itens anteriores e116 não-umbrella exatos,24TODO/unaccepted,117 statuses/deps/aceites intactos; prefixos421/416, originais416/414 e84 hashes preservados. [Prova](<../../.runtime/implementation-aud15-20261015/control/final-checkpoint/final-integrity-proof.json>). |
| T002 | Node/npm declarados executados, bootstrap limpo e build; não só versão do host. |
| T003 | Diagnóstico real e cinco testes do diagnóstico; executor representativo ainda necessário. |
| T004 |221 skips enumerados com fixture/owner proposto/autoridade/gate, sem converter em PASS. |
| T005 | Inventário ativo/archive corrigido e negativos. |
| T006 | Logout efeito/resultado corrigido; **B01 ainda aberto**, IdP real não exercitado. |
| T007 | Outage versus ausência discriminados localmente. |
| T008 | Quota pré-KDF/consume e corrida/single-use locais. |
| T009 | Admissão/deadline/drain e quotas/lazy/async locais; reset hot lookup/conversão agora no worker.9 testes focados passam; retirar checkpoint pós-lookup gera duas falhas discriminantes. [Evidência](<../../.runtime/implementation-aud15-20261015/identity/reset-lookup-result.md>). Capacidade real não medida. |
| T010 | Revalidação/leases/multi-produtor v2; mixed-version exige decisão separada. |
| T011 | Pergunta/retry estável e callbacks de sessão antiga. Novo cenário browser usa offline nativo **após POST**, sem submit automático, mesma key/payload no retry e resposta antiga após recuperação; três viewports passam no diagnóstico. [Teste](<../../apps/web/tests/chat-workspace.spec.ts>) · [log](<../../.runtime/implementation-aud15-20261015/lead/browser-offline-during-send-diagnostic.log>). Matriz nova completa:363PASS. |
| T012 | Create/review/feedback conservam revisões e incerteza após abort. |
| T013 | Página51, dedup, total/cursor e recuperação. |
| T014 |403 sem retry cego, restauração por autoridade legítima; browser local final passou. |
| T015 | Runtime guards e sucesso/no-body legítimos; saúde nullable corrigida a partir de payload real. |
| T016 | Mesmo job após budget/outage, consulta manual; sem promessa de recuperação sem fonte. |
| T017 | OTel preserve erro/resultado; traces distribuídos ainda não demonstrados. |
| T018 | Drawer/foco/modal/árvore oculta testados localmente; assistiva e WCAG global não aprovadas. |
| T019 |27 erros/quatro arquivos corrigidos;21 fontes canônicas sem erros, sem inflar baseline; cursor/tracer/decoder tipados, casts só em fronteiras específicas.33 novos casos de coerção/negativos/exporter opcional,200PASS focados. [Tipos](<../../.runtime/implementation-aud15-20261015/lead/mypy-canonical-21-files.log>) · [regressões](<../../.runtime/implementation-aud15-20261015/typing/focused-tests-verified.log>). Corpos importados fora dos roots não viram cobertura implícita. |
| T020 | Cobertura API/worker/web medida e negativos ampliados; não cobertura global. |
| T021 | Docs/frontend/identidade/inventário/VPS e adoção atualizados; controle/derivadas/arquivos/Gauntlet/control-inputs/make validate/diff finais exit0, sem substituir validação de produto. [Resultados selados](<../../.runtime/implementation-aud15-20261015/control/final-checkpoint/sealed-validation-results.json>). |
| T022 | CI/build exit0 e363 cenários browser locais PASS, incluindo offline durante envio; não substitui golden path real PROD12-041. |
| T023 | **Não fechado:** B01, VPS e obrigações externas pendentes; revisão independente final REJECT, sem promover GO. |
| T024 | Mapa PROD12 preservado, classes de recursos/owners propostos e decisões pendentes explícitos; nenhuma execução externa autorizada por isso. |

- **Final Critic:** **REJECT**, agente novo `48b3a38f-f627-4ea4-8787-3ebeb2d70e68`, read-only imposto pelo runtime, sem rationale de builders/verdicts anteriores;760 hashes/bindings conferidos antes/depois. Confiança alta/severidade alta em B01/B16. Reproduziu pessoalmente39PASS/1FAIL no módulo de identidade e48PASS em OTel/typing; confirmou fonte/partições/coorte e renders. Não executou externos nem certificou WCAG. [Resultado preservado, tabela B01–B17 e comando](<../../.runtime/implementation-aud15-20261015/lead/final-critic.md>). A [crítica anterior](<../../.runtime/implementation-aud15-20261015/lead/critic-1.md>) preserva os gaps B07/browser/tipagem que motivaram a quinta rodada, não aprova alterações posteriores.

Checkpoint canônico final: revisão391, BUILD/VERIFY, IN_PROGRESS/PARTIAL/NO-GO; próxima ação `AUD15-LOCAL-PREPARATION:DECIDE-B01-RESULT-CONTRACT`. Somente ação/evidências do umbrella e narrativa atual foram atualizadas; nada foi aceito/DONE ou promovido a VERIFIED de produto. O gerador original e validadores passaram; fontes760 e configurações adicionais permaneceram iguais. A falha transitória de dupla ação do plano foi preservada e corrigida movendo o texto histórico integral para sua seção, sem normalizar eventos antigos nem afrouxar checker. [Estado](<../../.agent/state.json>) · [handoff](<../../.runtime/implementation-aud15-20261015/control/final-checkpoint/HANDOFF.md>) · [logs/hash/provas](<../../.runtime/implementation-aud15-20261015/control/final-checkpoint/evidence-sha256.json>).

A [vinculação final da entrega](<../../.runtime/implementation-aud15-20261015/lead/final-delivery-manifest.json>) associa esta página, fontes/configurações delimitadas, rawlogs/coorte/cobertura, crítica e checkpoint por SHA-256. Não é assinatura de release nem hash integral do workspace.

**Remaining limitations**

- Recursos/autoridades reais continuam os do [mapa externo canônico](<../backlog-auditoria-2026-10-15.md#5-backlog-externo-mantido-por-referência-sem-duplicação-de-ids>) e [PROD12](<../backlog-producao-2026-10-12.md>): imagens/lab, PostgreSQL/Redis/S3/Qdrant, providers/budgets, dados/corpus/direitos/labels, tenant/worker, auditoria/traces, restore/RPO/RTO, carga/chaos/soak, operação, assinatura/release/canary. Owners permanecem propostos e D01–05/07 não são inventados. Perfil local selecionado não é prova desses serviços.
- Não houve deploy, commit/push, DDL real, mudança de permissões do host ou consumo de provider pago. Servidores de teste usam13110/18101; a GUI35117 não foi substituída.
- Evidência ignorada em runtime é local e não fornece retenção externa aprovada. Logs falhos, casos negativos e resultados históricos foram preservados; nenhum timestamp histórico foi atualizado para parecer execução nova.

**Final verdict**

**FAIL para o objetivo integral; progresso local substancial, produção NO-GO.** B01 obrigatório ainda falha e provas externas permanecem ausentes. Próxima ação material: ratificar o contrato auditável de logout (capacidade transacional/fencing ou resultado explicitamente indeterminado) sem alegar rollback de revogação já realizada. Até essa decisão, não enfraquecer a barra nem declarar o plano completo.
