# Roadmap — fechamento da auditoria AUD15 e continuidade de produção

**Data:** 15/10/2026 (America/Sao_Paulo). **Estado de publicação:** PLANEJAMENTO PROPOSTO; posteriormente, os 24 contratos foram adotados no [controlador canônico](<../.agent/backlog.json>) e o pedido humano de implementação iniciou preparação/integração local. **Produção: NO-GO.** Este roadmap não é ledger de execução nem autorização para serviços externos, mudanças irreversíveis ou deploy; consulte o [plano ativo](<../.agent/plans/producao-2026-10-12.md>) para o escopo local atual.

## 1. Objetivo e ponto de partida

Converter os **13 achados** da [auditoria AUD15](<reports/relatorio-auditoria-2026-10-15.md>) em correções demonstráveis, recuperar uma cadeia local reproduzível e cumprir as provas externas já especificadas antes de qualquer decisão de promoção.

**Base histórica, sem reexecução nesta elaboração:** nota geral 74,6/100; validação estática, lint, TypeScript, build, 115 testes web e 215 regressões focadas aprovados. Python ampliado: 7.658 passes, **278 falhas**, 221 skips. As 277 falhas VPS têm barreiras ambientais diagnosticadas, mas não estão automaticamente resolvidas; o inventário Node falhou também isoladamente. Serviços reais, browser E2E atual, carga e restore integrado não foram executados nessa auditoria.

O [backlog desta rodada](<backlog-auditoria-2026-10-15.md>) contém **24 contratos novos de planejamento**, com donos sugeridos, dependências e aceites. O [backlog PROD12](<backlog-producao-2026-10-12.md>) conserva os contratos de runtime/release; seus 56 IDs já foram registrados anteriormente em TODO no [controlador](<../.agent/backlog.json>), não aceitos por isso. Não duplicar execuções, apagar IDs ou substituir status por checklists neste roadmap.

**Princípio:** corrigir o que falha, preservar o que já tem prova e obter o que ainda não foi executado. Não é proposta de reescrita arquitetural, troca de provedor ou aumento artificial de nota.

## 2. Roadmap por marcos e gates

Os IDs Tnnn nesta tabela usam prefixo AUD15-. IDs PROD12 mantêm seu prefixo original. **As dependências completas e AND do backlog prevalecem sobre este resumo.**

| Marco | Resultado verificável | Escopo principal | Gate de saída |
|---|---|---|---|
| **M0 — Base confiável e plano de provas** | Candidato/evidências preservados, toolchain efetiva, falhas/skips classificados, inventário coerente e recursos/autoridades mapeados | T001–005,024 | **G0:** baseline vinculada; inventário corrigido; toolchain/executor compatíveis comprovados para os testes locais; matriz de skips e bloqueios externos explícita. Nenhum resultado histórico tratado como novo PASS. |
| **M1 — Segurança e perda de dados** | Logout e outage OIDC honestos, reset limitado, drafts preservados e autoridade entre abas | T006–008,010–012 | **G1:** cinco achados altos com negativos discriminantes aprovados e review independente; AUD15-06 tratado junto do logout. T010 inclui prova browser direcionada multiaba, não apenas teste mockado; T022 revalida na matriz integrada em G3. |
| **M2 — Robustez e contratos** | Event loop protegido, paginação/403/job recuperáveis, schemas runtime, OTel correto, foco/tipos/cobertura/docs coerentes | T009,013–021 | **G2:** demais achados reproduzidos e corrigidos ou disposição técnica demonstrada; cobertura/tipagem com denominadores explícitos e sem redução de gates; UI falha com honestidade. |
| **M3 — Candidato local integrado** | E2E local atual, suites/lane VPS em executor adequado e crítica independente no mesmo candidato | T022–023; vínculo a PROD12-026 | **G3:** todos os gates locais obrigatórios aprovados; 278 falhas reconciliadas por evidência, não por supressão; skips obrigatórios externos encaminhados, sem alegar que foram executados. **Local pronto ≠ produção pronta.** |
| **M4 — Integração externa real** | Imagens/lab/stores/providers/golden path/tenant/worker/corpus/browser real comprovados | PROD12-027–042, com predecessores vigentes e reconciliação T024 | **G4:** provas production-shaped autorizadas, inclusive negativos, candidato/config/digests exatos e perfil/corpus aprovados. Testes com fixtures controladas não substituem IdP/stores reais aplicáveis. |
| **M5 — Operação, recuperação e capacidade** | Tracing/audit/alertas, restore, rollback, carga/chaos/soak e operação humana demonstrados | PROD12-043–049 | **G5:** recuperação e capacidade medidas nos budgets aprovados; perda/duplicação/tenant pós-restore verificadas; falhas e sinais reais exercitados com aborto e teardown seguros. |
| **M6 — Decisão de release** | Candidato único, gates/reviews/packet/trust válidos e decisão humana independente | PROD12-050–053 | **G6:** todos os critérios mandatórios vigentes satisfeitos, evidência fresca/vinculada, risco alto não pendente e Go explícito para o artefato exato. Caso contrário, permanece NO-GO. |
| **M7 — Canary e operação acompanhada** | Entrada limitada, reversão disponível, expansão/handoff e janela real de SLIs | PROD12-054–056 | **G7:** canary atende policy para expandir, operadores recebem ownership e acompanhamento real produz resultados. Não afirmar 30 dias de SLO antes de observá-los. |

### Marcos não são barreiras artificiais à preparação

- Após T001, correções de M1 podem avançar enquanto plataforma trabalha em executor/toolchain/inventário de M0. Não esperar recursos externos para corrigir perda de draft local.
- T024 inicia cedo: descobrir owners, custos, corpus e permissões pode controlar o prazo mais que os fixes.
- T022 pode ser preparado durante M1/M2. Seu **aceite integrado** exige predecessores funcionais da tabela; a prova multiaba focada de G1 já ocorre em T010 e é repetida aqui. O pertencimento a M3 não obriga adiar a reprodução inicial.
- Read-only investigação, desenho de fixtures e revisão de runbook não autorizam iniciar lab, gastar provider, aplicar DDL, publicar imagem ou modificar o host.
- Preparação de M4/M5 pode ocorrer cedo; execução e aceite respeitam autorização e predecessores canônicos. O [estado ativo](<../.agent/state.json>) registra obrigações do lab PH3-2 que este roadmap **não remove**.

## 3. Sequência prática e caminho crítico

```text
T001 — baseline, evidência e reconciliação
  ├─ T002 / T003 / T004 / T005 — toolchain, VPS, skips, inventário
  ├─ T006 → T007 + T008 → T009 — identidade, reset, scheduling
  ├─ T010 + T011 → T014 — sessão entre abas, offline, recuperação 403
  │    └─ T015 → T016 — contratos HTTP e retomada de job
  ├─ T012 → T013 — create e paginação de casos
  ├─ T017 — utilitário OTel
  └─ T024 — perfil, recursos, autoridade e vínculos externos (preparação cedo)

Correções UI → T018 + fronteiras tipadas T019 → T020 → T021
Predecessores de browser → T022
Todos os predecessores locais obrigatórios → T023 [G3]
  → PROD12-026 reconciliado e aceito sob seus próprios contratos
  → PROD12-027–042 [G4]
  → PROD12-043–049 [G5]
  → PROD12-050–053 [G6: Go ou No-Go]
  → PROD12-054–056 [G7, somente após Go/autorização]
```

Diagrama é resumo, não scheduler: por exemplo, T009 exige T006, T007 **e** T008, e T014 exige T010 **e** T011. T023 não fecha automaticamente PROD12-026; históricos/aceites pendentes e dependências anteriores precisam ser reconciliados. A dependência T023 antes da candidatura externa/release deve ser proposta no controlador em T001/T024, não presumida como já instalada.

**Caminho crítico provável:** executor VPS + identidade/autoridade → candidato local integrado → lab/stores → fronteiras reais → restore/capacidade/soak → reviews/packet/decisão. O caminho real só será conhecido após disponibilidade da equipe, ambientes e decisões. Não prometer data baseada na contagem de tarefas.

### Primeira onda de execução proposta, após autorização própria

1. **T001:** preservar candidato e evidências, reconciliar sobreposições com PROD12.
2. **Identidade/API:** T006 → T007 e T008; coordenar o mesmo owner nos trechos de auth; depois T009.
3. **Web:** T010 (sessão), T011 (offline) e T012 (caso) com ownership disjunto; estabilizar a interface de invalidação antes de integrar wrapper/chat.
4. **Plataforma/QA:** T002, T003, T004 e T005; não confundir identificação da causa VPS com prova de correção de cada teste.
5. **Lead/SRE/produto:** T024 paralelamente, sem executar serviços antes dos gates/autorização.

## 4. Organização do trabalho e limites de paralelismo

| Frente | Responsabilidade | Controle de colisão |
|---|---|---|
| Identidade/API | Logout, indisponibilidade, reset, offload | Mesmo owner ou sequência para auth/provider/dependência; quotas e contrato de revogação primeiro |
| Web/sessão | Multiaba, 401, invalidação e wrapper HTTP | Um owner de provider/transporte; contrato de eventos/revalidação sem dados sensíveis |
| Web/chat | Offline, idempotência, 403 e foco | T011/T014 coordenados; não dois writers no mesmo workspace |
| Web/casos/documentos | Draft/paginação e acompanhamento do job | Casos e documentos podem ser independentes; mudanças do wrapper integradas por seu owner |
| Plataforma/CI | Toolchain, VPS, inventário, coleta de skips | Um owner de locks/workflows/Make; sem alterar DAC do host como atalho |
| QA/observabilidade | Probes discriminantes, OTel, E2E, cobertura e crítica | Não editar testes/artefatos do writer simultaneamente; review sensível independente do autor |
| Runtime/release | Lab/stores/provider/corpus/DR/carga/promoção | Namespaces e dados isolados; ensaios destrutivos/carga serializados quando compartilharem recursos; operador e signer identificados |

**WIP proposto:** uma escrita ativa por recurso compartilhado. Não abrir todas as tarefas ao mesmo tempo nem usar paralelismo para contornar dependência. Uma correção material termina com teste focado, regressão relevante, revisão e evidência vinculada, antes de adoção de resultado pelo owner de status.

## 5. Portões externos: o que falta provar

O detalhamento permanece no [backlog PROD12](<backlog-producao-2026-10-12.md>) e na sua [seção de autoridades](<roadmap-producao-2026-10-12.md#4-decisões-recursos-e-responsáveis>). Não há nova autorização implícita.

- **Infraestrutura e dados:** destinos descartáveis, namespaces, owners, segredos via mecanismo aprovado, TLS, volumes, migrações e rollback/roll-forward. Linux representativo; não simular ownership como prova de segurança do host.
- **Identidade:** perfil postgres-local-v1 existente deve ser preservado até decisão contrária; corrigir OIDC injetável não significa escolher IdP de produção. Se OIDC fizer parte do perfil, provar broker/revogação/membership e outage reais.
- **Provider/RAG/domínio:** conta/endpoints/modelo/dimensão, teto de custo, direitos/classificação do corpus, estratos/rótulos, thresholds e revisão humana. Pack offline de 2 positivos/3 negativos não demonstra qualidade real de IA.
- **Browser/E2E:** diferenciar componente/jsdom, browser com mocks, browser com API real e serviços/autoridade externos. Provar estados de rede/403/401 e sessão multiaba na classe exigida por cada gate.
- **Restore:** definir RPO/RTO antes do ensaio, restaurar conjunto consistente de stores/conversas/audit, conferir contagem/checksum/ACL/tenant e funcionalidade pós-restore. Arquivo de backup sozinho não é prova de recuperação.
- **Carga e resiliência:** workload e amostra aprovados, concorrência/throughput/latências de cauda/erros/CPU/memória/filas/custo; ensaios de crash/queda/timeout e soak em janela combinada. Budgets e limites de aborto precisam existir antes, não ser escolhidos após olhar resultado.
- **Autoridade:** D01–D05/D07 e pendências do plano ativo continuam delimitando dados, infraestrutura, provider, política clínica, SLO/DR e promoção. Confirmar disponibilidade não equivale a obter permissão para usar.

## 6. Política de evidência e definição de pronto

### Pronto localmente — G3

- Mesmo candidato, configurações identificadas, toolchain efetiva compatível e executor VPS adequado.
- Gates estáticos, inventário, lint/tipos/build, regressões e E2E local obrigatórios aprovados; os defeitos antigos devem ser rejeitados pelos novos testes.
- As 278 falhas têm fechamento verificável e nova coleta registrada. Não estipular que a suite futura deva ter exatamente 7.658 passes ou 221 skips.
- Skips obrigatórios de produção podem permanecer não executados no marco local **somente explicitamente vinculados aos gates externos**. Isso não permite G6.
- Crítica independente e ausência de gaps altos locais sem disposição legítima. Resultado de plano/tarefa não aceita risco pelo usuário.

### Pronto para decisão de produção — G6

Aplicam-se a [integridade de release](<architecture/release-integrity.md>), a [autoridade de promoção](<architecture/promotion-authority.md>) e a barra congelada vigente; este documento não cria thresholds menores ou uma aprovação pela média 75/100.

- Todos os gates mandatórios do perfil satisfeitos com provas atuais, mesmo artefato/config/digests, sem FAIL/NOT_RUN/STALE/skip obrigatório oculto.
- Stores/identidade/providers reais aplicáveis, tenant/worker negativos, segurança, qualidade de domínio e observabilidade demonstrados.
- Restore e capacidade/resiliência medidos, operação/runbooks/owners e estratégia de reversão disponíveis.
- Supply chain/scans/reviews/scorecard exigidos pelo contrato vigente, pacote/trust íntegros e decisão humana independente D07; nenhum builder aprova sozinho o release.
- Mudança de código/config/topologia após teste invalida provas afetadas; repetir os gates pertinentes. Não rejuvenecer timestamps nem reconstruir imagem nova e reutilizar evidência de outra.
- Canary e acompanhamento são **pós-decisão**, não pré-condições circulares do primeiro Go. A [política de rollout](<../infrastructure/docker/rollout-policy.json>) controla aborto/expansão; SLO exige sua janela real.

## 7. Horizonte, estimativas e próxima decisão

| Horizonte | Grau de detalhe | Condição para agendar |
|---|---|---|
| Próxima onda | T001 e cinco achados altos, mais toolchain/VPS/inventário | Autorizar escopo local, designar owners e preservar baseline |
| Seguinte | Demais achados, tipos/cobertura/docs e E2E integrado | Contratos compartilhados estabilizados e executor disponível |
| Externo condicionado | Stores/provider/corpus/browser real/restore/carga | Autoridade, custos, recursos e fixtures aprovados; gates predecessores íntegros |
| Release e operação | Reviews/packet/Go/canary/expansão/SLIs | Todos os gates aplicáveis e autoridade humana, sem data prometida por planejamento |

**Sem cronograma em dias ou data de produção:** não foram informadas capacidade da equipe, disponibilidade de infraestrutura/providers/dados nem janelas dos reviewers. Após T001/T024, estimar por owner, decompor itens G e agendar reruns/review/frescor com buffers. Não prometer 90/95/100 pontos ou GO como consequência de concluir uma quantidade de tarefas.

**Validação deste planejamento:** conferência estrutural aprovou 24 contratos, dependências AND sem ciclos, cobertura dos 13 achados e oito marcos. `make docs-check` aprovou 941 links locais/zero erros; `git diff --check` passou. São verificações documentais, não nova execução dos testes de produto.

**Próxima decisão recomendada:** aprovar uma rodada delimitada de remediação local, começando por T001 e pelos cinco achados altos. Esta elaboração entregou somente backlog/roadmap; não executou novamente os testes de produto e não alterou seu estado de promoção.
