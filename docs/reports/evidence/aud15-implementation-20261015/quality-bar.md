# AUD15 — contrato de implementação e quality bar v1

**Congelado antes de mudanças funcionais:** 2026-10-15, após pedido humano “implementa todo o conteudo dos planos”. Objetivo: implementar os contratos do [backlog AUD15](<../../../backlog-auditoria-2026-10-15.md>) e continuar o [programa PROD12](<../../../backlog-producao-2026-10-12.md>), sem aceitar risco, reimplementar patches já demonstrados ou fabricar provas externas. Este contrato suplementa o [plano ativo](<../../../../.agent/plans/producao-2026-10-12.md>); status de tarefa permanece no [controlador](<../../../../.agent/backlog.json>).

## Autoridade e integridade

O pedido novo autoriza implementação reversível local e testes sintéticos. Não concede segredos, acesso a serviços/instalações, custos de provider, DDL real, mudança de DAC/ownership do host, assinatura, commit/push ou deploy. Perfil postgres-local-v1, D04 humano, critérios congelados e NO-GO permanecem. Onde orçamento/UX exigiria escolha material não ratificada, preservar contrato existente e falhar com honestidade; não inventar integração ou capacidade.

Baseline: HEAD `48e383c25ca4af32aa7ffe7e2367360ca9742c58`, worktree já alterada. [Manifesto inicial](<../../../../.runtime/implementation-aud15-20261015/entry/manifest.json>) e [patch anterior](<../../../../.runtime/implementation-aud15-20261015/entry/tracked-before.patch>) preservados antes de novos writers. Fonte dos defeitos: [auditoria](<../../relatorio-auditoria-2026-10-15.md>). Python efetivo 3.12.3; Node 24.20.0/npm 11.19.0 divergem do contrato 22.19.0/10.9.3; verificar ferramenta compatível disponível antes de afirmar T002.

## Barra obrigatória

Cada linha é obrigatória no escopo do objetivo completo. Critério local aprovado não dispensa sua prova externa/review. Targets e DoD detalhados do backlog permanecem integrais; tabela somente indexa. Baselines abaixo referem à auditoria anterior, não nova prova desta rodada.

| ID | Dimensão/target | Método de evidência | Pri | Baseline/validade |
|---|---|---|---|---|
| B01 | Logout OIDC nunca confirma revogação que não executa; sucesso invalida autoridade relevante; erro não emite completed | T006: API real in-process, JWT, sessão nativa e falhas do adapter | alta | AUD15-01 reproduzido; IdP externo não executado |
| B02 | Reset tem quota antes de KDF/consume, sem enumeração/replay/race novos | T008: spies de custo, API e single-use/corrida | alta | AUD15-02 reproduzido; budgets existentes não enfraquecidos |
| B03 | Offline preserva pergunta e identidade de retry; callback antigo nunca publica | T011: React deferred network/offline/online, retry e troca de sessão | alta | AUD15-03 reproduzido; browser integrado separado |
| B04 | Create de caso não apaga edição posterior nem duplica submit | T012: POST adiado, edição concorrente, falha e troca de escopo | alta | AUD15-04 reproduzido |
| B05 | Aba velha não mostra A enquanto age como B; revalidação falha fechada e sem broadcasts sensíveis | T010/T022: eventos, requests antigas e browser multi-page | alta | AUD15-05 estático; reproduzir antes de corrigir |
| B06 | Outage da autoridade é indisponibilidade, não anonimato/false logout | T007: resolver down/recovery e credencial inválida | alta | AUD15-06 reproduzido local |
| B07 | Identidade/KDF/DB lentos não bloqueiam event loop; offload/admissão têm limites e deadline | T009: agendamento concorrente, saturação e cancelamento | alta | AUD15-07 scheduling reproduzido; capacidade real não medida |
| B08 | Inventário identifica componentes executáveis sem manifesto extra silencioso nem exclusões amplas | T005: teste original e negativos de manifesto/ausência | alta | AUD15-08 falha isoladamente |
| B09 | Caso 51 acessível com contagem honesta, erro recuperável e escopo preservado | T013: páginas, dedup, erro e resposta tardia | média | AUD15-09 estático |
| B10 | 403 não habilita retry cego; revalidação legítima restaura ação | T014: denied/revalidated/stale/offline e política canônica | média | AUD15-10 estático; specs antigas conflitantes |
| B11 | Mesmo job pode ser acompanhado após budget/transiente sem reupload/duplicação | T016: timeout/503→published, cancelamento e escopo | média | AUD15-11 estático |
| B12 | Sucesso HTTP malformado é erro de contrato, não vazio/autoridade válida | T015: HTML/JSON inválido/missing fields, sucesso válido e no-body legítimo | média | AUD15-12 estático |
| B13 | OTel não substitui exceção do corpo, não faz segundo yield e cleanup não altera negócio | T017: attach/detach/body errors e worker regressões | baixa | AUD15-13 reproduzido como utilitário |
| B14 | Toolchain, lane VPS e skips possuem prova real ou bloqueio explícito; sem mudar DAC para fabricar verde | T002–004: versões/locks, coleta/testes Linux e inventário de skips | alta | 277 falhas VPS e 221 skips históricos; namespace restrito |
| B15 | Foco/teclado, tipos/cobertura e documentação refletem o candidato com denominador explícito | T018–021: testes, typecheck/lint/docs e avaliação browser/assistiva disponível | média | 13 arquivos Python e 539 linhas web eram recortes, não global |
| B16 | Candidato local integrado passa gates relevantes e crítica independente; testes novos rejeitam defeitos | T001/T022/T023: baseline→fix→regressões, hashes, CI local, reviewer novo read-only | alta | Auditoria local não é aceite atual |
| B17 | Runtime/isolamento/providers/RAG/DR/carga/chaos/soak/release têm provas/autoridade reais antes de GO | T024 e PROD12-027–056 com predecessores canônicos | alta | NOT_RUN/BLOCKED_EXTERNAL; não substituível por mocks ou documentação |

## Ownership inicial e execução

- Lead: preservação/controle/integração; casos e documentos, inventário/diagnóstico, OTel. Não tocar arquivos dos builders enquanto trabalham.
- Builder identidade: API auth/dependencies/services/config/errors se necessário, pacote identity e testes relacionados. Um writer para logout/reset/offload.
- Builder web: session-provider, chat-workspace/adapter, lib/api + validadores auxiliares, UI/foco, specs e testes dessas fronteiras. Não editar casos/documentos, seus testes ou config de cobertura compartilhada sem coordenação.
- Dois builders independentes iniciam juntos; conflitos de interface comunicados antes de editar. Lead reexecuta gates integrados e solicita crítico independente novo/read-only após resultados. Builders não aprovam seus próprios patches.

## Recuperação e verificação

Não resetar ou restaurar o checkout inteiro: patches anteriores pertencem ao usuário. Comparar somente a superfície de cada writer com a cópia inicial. Não alterar histórico assinado, barra Gauntlet ou ledgers antigos. Logs grandes vão para a área runtime desta rodada, com hashes/limitações resumidos no resultado durável. Compilação Next pode reescrever arquivos gerados: preservar bytes antes, comparar depois e não apagar mudança prévia. Nenhuma execução está prevista como PASS antes de ocorrer.
