# Execução do planejamento — 08/09/2026

## Resultado

O plano foi implementado até o limite que pode ser verificado nesta sessão. A
base do produto, os contratos, os adapters duráveis, o worker externo, o
workspace conversacional, o console administrativo, o módulo de casos
controlado e a matriz web estão implementados e cobertos por gates locais. O
programa completo ainda não pode ser aceito como produção: o daemon Docker não
está acessível, nenhum serviço externo foi exercitado, não há corpus/provider
aprovado para chamada real e as decisões D01–D05 continuam abertas.

O candidato é o checkout local sujo em `main`, HEAD
`66781cbe96c10786bbf9b9150ee4798df62fdba6`. O snapshot vinculante atual está
em [rec-source-snapshot-2026-09-08-v15.json](rec-source-snapshot-2026-09-08-v15.json);
o v13 e o v14 permanecem históricos: v13 refletiu o alinhamento de dois testes
de identidade e v14 precedeu a correção de shutdown bounded. O build web usado
foi `xn_XDhfG2Cx4zXlDfVo8i`.
Nenhum volume, banco,
credencial, provider pago ou ambiente de produção foi alterado.

## O que foi entregue

| Frente | Estado verificável | Limite atual |
|---|---|---|
| REC-01–04 | Harness próprio, matriz de personas, configuração efetiva, diagnóstico protegido e UI guiada por permissões | aceite local; sem CI/deploy externo |
| REC-05 | Compose privado, launcher fail-closed e configuração estática validada | preflight real bloqueado por acesso ao daemon; serviços reais NOT_RUN |
| REC-06–09 | Migrações aditivas, stores Postgres/OIDC, auditoria scoped e política fail-closed nas mutações sensíveis | checksums verificados; execução Postgres e auditoria distribuída NOT_RUN |
| REC-10–14 | CRUD administrativo, sessões, recuperação com token single-use/TTL e delivery port injetável, coleções/grants e UI | IdP externo, tenant cruzado e delivery real NOT_RUN; Argon2id/D02 pendente |
| REC-15–20 | S3-compatible, fila Postgres, worker com timeout, lease Redis, Qdrant, composição externa e readiness | nenhuma dependência externa exercitada; duas réplicas NOT_RUN |
| REC-21–22 | Caminho Professor/provider, contratos de evidência e pack sintético offline com métricas por caso/modelo/corpus e negativos | provider/corpus aprovados, golden set clínico, thresholds D04 e orçamento NOT_RUN; pack local não é aceite semântico de produção |
| REC-23–26 | Histórico SQLite/Postgres, paginação por cursor, contratos HTTP/SSE, contexto scoped, ACL revalidada, idempotência, streaming/cancelamento e workspace conversacional | paginação/total real, detalhe sem limite global, contratos canônicos, retry sem duplicação, contexto limitado após filtros, ACL de fontes e texto provisório verificados localmente; runtime externo NOT_RUN |
| REC-27 | Contratos estritos, store InMemory/SQLite, gate D04 duplo, isolamento tenant/workspace/owner, catálogo autorizado, auditoria de intenção antes da escrita, idempotência por chave estável e UI de registro/revisão/feedback | decisão D04, dados permitidos, responsável de domínio e aceite clínico continuam NOT_RUN; nenhum agente/modelo é invocado |
| REC-28 | Jornadas locais, teclado, foco, reduced motion, reflow e três viewports | revisão de release independente e jornadas externas NOT_RUN |
| REC-29–33 | Telemetria/readiness bounded, reconciliação semântica de backup, rate limit distribuído injetável, benchmark local e artefatos de release/compose | collector/alert delivery, restore live, Redis multi-réplica, carga/custo, build/scan de imagem, canary e rollout NOT_RUN |
| REC-34–35 | REC-34 aprovado localmente no snapshot v15; REC-35 permanece NO-GO | runtime externo e Go/No-Go humano ainda não foram executados; não houve promoção |

## Evidência executada

| Comando | Resultado observado |
|---|---|
| `make api15-full` | boundaries PASS; contracts 5; providers 47; locking 36; Professor 15; API **418**; benchmark local PASS |
| `make api16-full` | control-plane PASS; domínio 107; worker/health 45; API **418**; benchmark local PASS |
| foco REC-23–25 | testes de histórico/stream/Postgres: 15 PASS; paginação, contratos, ACL, contexto, retry idempotente, conclusão, erro após delta, cancelamento, escopo e reinício verificados |
| `make api-contract` | OpenAPI regenerado e validado com **49 paths**, incluindo REC-27 |
| `make api-security` | route policy, negativos, import boundary e HTTP contract: 25 PASS |
| `make storage-test ops-static ops-backup-test` | storage 24; três checksums de migration PASS com execução NOT_RUN; backup **6**; sintaxe operacional PASS |
| `make eval-retrieval-pack` | REC-22 pack sintético offline PASS; thresholds, negativos, ACL/citações e métricas por modelo/corpus; provider/rede NOT_RUN |
| `make web-lint web-typecheck web-build` | lint, TypeScript e build Next 15.5.25 PASS; rota `/app/cases` gerada |
| `make web-e2e` | **294/294 PASS** em 375/768/1440, zero skips, 4,8 min; inclui 6 cenários de REC-27 |
| resumo Playwright de performance | 18/18 casos; LCP máximo **1072 ms**; CLS máximo 0,0787; reduced motion registrado |
| Docker/benchmarks focados | 10 testes Docker/release e 6 testes de benchmark PASS; Docker daemon/build/scan NOT_RUN |
| `docker compose config --quiet` com secrets efêmeras | configuração estática do laboratório PASS; `integration_lab.py preflight` bloqueado pelo socket local |
| rebinding dos gates locais V6/V8 | observabilidade: 10 + API/worker 122; lifecycle/root 69; identidade/ingestão/knowledge 45; todos os hashes e snapshots dos candidatos atuais conferidos |
| `git diff --check` | PASS |

Os testes web combinam jornadas contra a API local com estados sintéticos
explicitamente interceptados. Isso valida o contrato e a superfície visual,
mas não prova latência de provider, banco, rede ou produção. Os avisos de
depreciação Starlette/httpx não falharam os gates.

## Situação dos 35 itens

`DONE_LOCAL` significa implementação e regressão local observadas. `PREPARED`
significa que a composição e os testes existem, mas o aceite depende de uma
dependência externa. `PARTIAL` significa que há uma fatia útil, mas falta um
requisito explícito do backlog. `NOT_RUN` mantém o item aberto sem converter
mock, adapter ou documentação em aceite.

| IDs | Situação atual |
|---|---|
| REC-01, REC-02, REC-03, REC-04 | `DONE_LOCAL` |
| REC-05 | `PREPARED / BLOCKED_EXTERNAL` |
| REC-06, REC-07 | `IMPLEMENTED_LOCAL / PENDING_EXTERNAL` |
| REC-08, REC-09, REC-10, REC-11, REC-12, REC-13, REC-14 | `IMPLEMENTED_LOCAL / PENDING_EXTERNAL` |
| REC-15, REC-16, REC-17, REC-18, REC-19, REC-20 | `IMPLEMENTED_LOCAL / PENDING_EXTERNAL` |
| REC-21 | `IMPLEMENTED_LOCAL / PENDING_D03_EXTERNAL` |
| REC-22 | `IMPLEMENTED_LOCAL / PENDING_D04_EXTERNAL`: pack versionado sintético, thresholds explícitos, negativos, ACL/citações e relatório por modelo/corpus; sem corpus clínico ou provider real |
| REC-27 | `IMPLEMENTED_LOCAL / PENDING_D04_EXTERNAL`: registro humano, hipóteses/evidências estruturadas, revisão, feedback, catálogo e UI; gate duplo desligado por padrão e sem geração clínica |
| REC-23, REC-24 | `IMPLEMENTED_LOCAL / PENDING_EXTERNAL` |
| REC-25 | `IMPLEMENTED_LOCAL / PENDING_EXTERNAL`: turnos `complete`, `partial`, `error` e `cancelled` persistem com escopo; retry substitui outcome incompleto pela mesma chave; contexto exclui terminais incompletos e fontes revogadas; telemetria local mede TTFT e duração bounded; SSE/UI marcam texto em curso como provisório |
| REC-26, REC-28 | `DONE_LOCAL / PENDING_EXTERNAL` |
| REC-29 | `IMPLEMENTED_LOCAL / PENDING_D05_EXTERNAL`: métricas bounded de readiness, worker, provider, retrieval, HTTP e regras alinhadas; collector/alert delivery NOT_RUN |
| REC-30 | `IMPLEMENTED_LOCAL / PENDING_D05_EXTERNAL`: manifest semanticamente validável, contagens/escopo/checksums e reconciliação fail-closed; restore live e RPO/RTO NOT_RUN |
| REC-31 | `IMPLEMENTED_LOCAL / PENDING_EXTERNAL`: adapter distribuído fail-closed sobre backend atômico injetável, conectado ao login e coberto por negativos locais; Redis/multi-réplica/browser real NOT_RUN |
| REC-32 | `PREPARED / PENDING_D05_EXTERNAL`: p50/p95/p99, TTFT/conclusão, RSS, falhas determinísticas e soak local; carga distribuída, custo e dependency-down externos NOT_RUN |
| REC-33 | `PREPARED / PENDING_EXTERNAL`: Dockerfiles, launcher worker fail-closed, compose healthcheck, checker, manifest e rollout policy; build/scan/canary/rollback NOT_RUN |
| REC-34 | `APPROVED_LOCAL`: Final Critic independente aprovou o escopo de integração local do snapshot v15 |
| REC-35 | `NO-GO`: não há decisão humana de promoção nem autorização de rollout |

## Bloqueios e decisões pendentes

- `docker` e Compose estão instalados, mas o socket local continua negando
  acesso dentro e fora da sessão; `sudo -n` exige autenticação do usuário.
  Nenhum container foi iniciado.
- D01 precisa fechar o modelo de integração/ownership; D02, a política de
  identidade e credenciais; D03, provider/modelo/orçamento; D04, corpus,
  golden set, thresholds e responsável clínico; D05, SLO/RPO/RTO, retenção,
  alertas e carga.
- Não foram executadas migrations contra Postgres, login OIDC, fila/worker
  separado, S3, Qdrant, Redis/Locker, provider pago, restore, collector,
  alerta, soak, scan de imagem, canary ou rollback.
- O fluxo de recovery agora exige, na composição externa, um
  `password_reset_delivery` explícito. A API permanece neutra e nunca devolve
  o token; o adapter real ainda precisa ser fornecido pelo ambiente aprovado.
- A composição externa e as stores recusam chamadas sem tenant/workspace nos
  caminhos protegidos. Fixtures legadas continuam existindo apenas nos testes
  locais que declaram a compatibilidade.

## Revisão e rastreabilidade

Os pareceres históricos, rejeições e tentativas interrompidas permanecem nos
ledgers e em `.gauntlet-state-of-art/`; nenhum PASS histórico foi reescrito.
A revisão independente anterior encontrou lacunas locais em REC-23–25; elas
foram corrigidas e regressadas. A revisão pós-correção do snapshot v8 não
retornou parecer dentro das janelas limitadas e foi registrada como `NOT_RUN`;
nenhum critério foi aprovado por silêncio ou encerramento. A revisão
independente do snapshot v9 encontrou quatro falhas locais de integração; as
correções passaram os gates v10. A revisão independente do snapshot v10 encontrou
uma falha High no checker de release preparado: cinco campos ainda aceitavam
`PASS` sem evidência externa. O checker foi corrigido, o teste agora percorre
todos os estados externos e o candidato foi refeito como snapshot v11. A
reexecução dos gates API15/API16 atualizou os dois artefatos de performance;
por isso v11 foi marcado stale e o candidato foi rebindingado como snapshot v12.
O Final Critic aprovou o escopo local do v12 sem achados impeditivos, mas uma
verificação posterior regenerou os dois artefatos de performance rastreados;
v12 foi marcado stale e o candidato foi rebindingado como snapshot v13. A
crítica read-only substituta aprovou REC-34 para o escopo local, sem achados
impeditivos. Depois, os testes de identidade `test_oidc.py` e `test_provider.py`
foram ajustados para refletir a política atual de sete permissões da persona
veterinária; isso tornou v13 stale e produziu o rebinding exato v14, com
546/546 hashes válidos. O Final Critic aprovou v14 para o escopo local, mas a
correção posterior do shutdown bounded mudou o serviço e sua regressão, então
v14 também foi marcado stale e o candidato foi rebindingado como v15, novamente
com 546/546 hashes válidos. As revisões independentes dos candidatos V3/V5 e
V6/V7 de observabilidade e lifecycle foram preservadas como `NOT_APPROVED`; os
candidatos correntes V6 e V8 receberam aprovação I1 no escopo local, sem
achados Critical/High/Medium. A primeira revisão global do v15 foi interrompida
e registrada como `NOT_RUN`; a revisão final independente de Erdos completou a
inspeção do v15, aprovou REC-34 para o escopo local e não encontrou achados
Critical/High/Medium/Low. REC-35 continua `NO-GO` enquanto faltarem runtime
externo, decisões D01–D05 e autorização humana de promoção.

O plano vivo é [.agent/plans/rec-implementation.md](../../.agent/plans/rec-implementation.md).
As evidências locais atuais incluem
`.gauntlet-state-of-art/evidence/visual-cycle5-current/`,
`.gauntlet-state-of-art/evidence/observability-local-current/` com o candidato
V6 e `.gauntlet-state-of-art/evidence/ingestion-lifecycle-current/` com o
candidato V8,
`docs/architecture/clinical-case-boundary.md`,
`docs/operations/backup-restore-reconciliation.md` e os registros
append-only em `.agent/verification.jsonl` e `.agent/execution-log.jsonl`.

## Próximo passo seguro

O próximo passo é operacional: o responsável pelo host deve conceder acesso
controlado ao daemon sob a política local e fornecer somente secrets
descartáveis do [runbook de integração](../../infrastructure/compose/INTEGRATION.md).
Depois disso, executar o preflight e os aceites REC-05–09 antes de qualquer
provider/corpus real. Para REC-22/27, D04 deve fornecer corpus/casos permitidos,
thresholds, responsável de domínio e aceite clínico. A promoção só pode ocorrer
depois de REC-22, REC-27, REC-29–34 e da decisão REC-35 sobre um snapshot
concreto. A revisão corrente deve usar o snapshot v15 e manter v13/v14 apenas
como decisões históricas.
