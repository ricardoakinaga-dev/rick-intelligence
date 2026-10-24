# Backlog AUD24 — 29 contratos de remediação e verificação

**Data:** 24/10/2026 (America/Sao_Paulo). **Estado de publicação:** `PROPOSTO`. **Produto:** `NO-GO`.
**Baseline:** [auditoria AUD24](<reports/relatorio-auditoria-2026-10-24.md>) — 74,7/100, HEAD `48e383c`, worktree com 109 entradas.
**Documentos irmãos:** [plano executivo](<plans/execplan-aud24-2026-10-24.md>) e [roadmap](<roadmap-auditoria-2026-10-24.md>). **Decisão AUD24-D1 ratificada:** [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>).

Este documento é **especificação**, não ledger de execução. Os 29 contratos abaixo são novos e não substituem itens AUD07/AUD15/PROD12. As obrigações já especificadas em [PROD12](<backlog-producao-2026-10-12.md>) permanecem com seus IDs e são referenciadas na §5, sem duplicação. Nenhum item é adotado no [controlador](<../.agent/backlog.json>) por este documento.

## 1. Regras

- **IDs `AUD24-001…045` são tarefas; `AUD24-01…12` são achados.** Não confundir nem renumerar.
- **Prioridade:** `P0` = bloqueia segurança, dados ou release; `P1` = obrigatório antes da candidatura; `P2` = robustez/manutenção.
- **Tamanho:** `P` pequeno e delimitado; `M` múltiplas fronteiras; `G` grande ou dependente de ambiente/decisão. Não são dias.
- **Dependências são AND.** Preparação pode avançar antes; o aceite exige todos os predecessores.
- **Um writer por arquivo/recurso.** Mesmo sem dependência funcional, dois contratos não editam o mesmo arquivo em paralelo.
- **Sem weakening:** proibido remover teste, `skip`/`xfail`, reduzir floor, alargar allowlist, rejuvenescer timestamp ou converter `NOT_RUN` em PASS.
- **Aceite é observável.** “Implementado” não é DONE; “DONE” exige critério cumprido, evidência vinculada e aceite registrado.

## 2. Definition of Done comum

1. Candidato identificado por SHA + estado do worktree + fingerprint de config.
2. Procedimento completo, ambiente, exit code, timestamp UTC, artefatos e hashes.
3. Defeito reproduzido antes; o novo teste falha na versão antiga e passa na corrigida.
4. Cobertura de sucesso, erro, callback tardio, concorrência/escopo quando aplicável.
5. Revisão independente para identidade, auditoria, dados e release; o autor não aprova o próprio patch.
6. Nenhum gate enfraquecido; nenhuma evidência histórica apresentada como atual.
7. Limitações e riscos residuais explícitos (`PASS`, `FAIL`, `NOT_RUN`, `BLOCKED_EXTERNAL`).

## 3. Visão por épico

| Épico | Contratos | IDs | Foco |
|---|---:|---|---|
| E0 — Governança e baseline | 3 | 001–003 | Preservar, decidir, reconciliar |
| E1 — Identidade e auditoria | 9 | 010–018 | Reset, logout, estado de auditoria, OIDC, sessão |
| E2 — Recuperação web | 6 | 020–025 | Chat, casos, documentos, UX offline |
| E3 — CI, release e ambiente | 5 | 030–034 | Lane CONTRACT, candidato limpo, toolchain, VPS, CI remoto |
| E4 — Qualidade e documentação | 6 | 040–045 | Docs, contrato único, tipos, cobertura, RAG, acessibilidade |

**Total: 29 contratos** — 11 P0, 13 P1, 5 P2.

## 4. Contratos

### E0 — Governança e baseline

#### AUD24-001 — Preservar baseline, patch e checkpoint

**Prioridade:** P0 · **Tamanho:** P · **Dono:** Lead · **Depende:** —
**Entrega:** manifesto do worktree (109 entradas) com hashes, patch das 70 mudanças rastreadas, lista das 39 não rastreadas, checkpoint e procedimento de recuperação. Nenhum reset, `checkout` amplo ou restauração destrutiva.
**Aceite:** restauração em sandbox reproduz bytes idênticos; nenhum arquivo do usuário perdido; manifesto verificável por hash; o candidato executável atual permanece identificável.
**Evidência:** manifesto JSON, patch, SHA-256, log de restauração dry-run.
**Status local (24/10):** executado; 1.525/1.525 hashes rastreados, 48/48 não rastreados, status 116/116; ver [implementation-stage1](<reports/evidence/auditoria-2026-10-24/implementation-stage1.md>).
**Achado:** AUD24-06.

#### AUD24-002 — Ratificar o contrato do B01

**Prioridade:** P0 · **Tamanho:** P · **Dono:** autoridade de produto/segurança + Lead · **Depende:** —
**Entrega:** ADR comparando (A) outbox idempotente + reconciliador, (B) fence prepare/commit/abort e (C) semântica indeterminada explícita; escolha registrada, máquina de estados, semântica de HTTP, idempotência e autoridade.
**Aceite:** decisão datada e assinada; o teste atual não é removido nem afrouxado; o contrato define o que significa `completed` e como um `requested` órfão é resolvido; se não houver decisão, o item permanece `BLOCKED` e M1 não começa.
**Evidência:** ADR + sign-off; nenhum código.
**Status:** decisão ratificada em 24/10/2026 — [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>) publicado. A tarefa permanece pronta para adoção no controlador; não é `DONE` por este documento.
**Achado:** AUD24-03.

#### AUD24-003 — Reconciliar AUD24 com AUD15/PROD12

**Prioridade:** P0 · **Tamanho:** M · **Dono:** Lead/QA · **Depende:** 001
**Entrega:** matriz de rastreabilidade achado → contrato → marco → gate; mapa de sobreposição com AUD15-T006/T019/T023 e PROD12-007/014/016/017/018/020/025/026/034/044/050; confirmação de que nenhum ID foi renumerado.
**Aceite:** cada um dos 12 achados tem exatamente um contrato primário; heranças apontam para IDs existentes; `check_control_plane` continua PASS; nenhum aceite anterior é alterado.
**Evidência:** matriz versionada + validação do control plane.
**Status local (24/10):** executado; 29 contratos, 12 achados, 0 sobreposição; ver [reconciliation.json](<reports/evidence/auditoria-2026-10-24/reconciliation.json>).
**Achado:** todos.

### E1 — Identidade e auditoria

#### AUD24-010 — Separar efeito e confirmação do reset de senha

**Prioridade:** P0 · **Tamanho:** M · **Dono:** Backend/identity · **Depende:** 002, 012
**Entrega:** o reset efetiva a troca e revoga sessões de forma atômica; a resposta distingue sucesso confirmado de `result_indeterminate` com `request_id`; a efetivação gera evento de auditoria idempotente, mesmo se o chamador abandonar; retry não consome duas vezes nem paga KDF de novo.
**Aceite:** teste com commit concluído e resposta abandonada retorna indeterminado, mas a auditoria registra exatamente uma efetivação; reset válido retorna 200 e um evento; replay retorna 400 sem KDF/consume; o teste antigo que aceitava 503 silencioso é substituído por um que rejeita perda de auditoria.
**Evidência:** pytest focado + probe de concorrência + log de auditoria.
**Status local (24/10):** caminho normal implementado; efeito e operação durável na mesma transação no provider Postgres; residual apenas de store real/IdP `NOT_RUN`.
**Achado:** AUD24-01.

#### AUD24-011 — Revogar logout independentemente da auditoria

**Prioridade:** P0 · **Tamanho:** M · **Dono:** Backend/identity · **Depende:** 002, 012
**Entrega:** a revogação da sessão é o efeito de segurança e não fica bloqueada por sink indisponível; a resposta informa `result_indeterminate` com `request_id`; os cookies de sessão/CSRF são removidos quando a revogação foi confirmada, mas a resposta não afirma `signed_out`/`completed`; a auditoria é reconciliada depois, conforme [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>).
**Aceite:** sink indisponível → sessão invalidada e resposta honesta; sink saudável → `signed_out` e auditoria terminal; nenhum `completed` sem confirmação; teste que exigia “auditoria antes de revogar” é revisado para o novo contrato aprovado.
**Evidência:** pytest com sink down/up + auditoria + cookie.
**Status local (24/10):** implementado com operação durável; revogação ocorre mesmo com sink indisponível; resposta `result_indeterminate`, sem `completed`.
**Achado:** AUD24-02.

#### AUD24-012 — Máquina de estados e reconciliador de auditoria

**Prioridade:** P0 · **Tamanho:** G · **Dono:** Backend/identity + auditoria · **Depende:** 002
**Entrega:** estados terminais definidos pelo [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>); registro durável `rick_audit_operations` com `UNIQUE(action, request_id)`; writer idempotente; migração; reconciliador CLI/job para `requested`/`effect_applied`/`indeterminate`; nenhum evento sem desfecho. Etapa 1 (semântica) precede a tabela/reconciliador.
**Aceite:** escrita concorrente do mesmo evento gera uma linha; crash entre efeito e confirmação é resolvido pelo reconciliador; nenhum `completed` tardio após resposta abandonada; migração aplica e reverte em ambiente descartável.
**Evidência:** testes de concorrência/crash, migração, relatório do reconciliador.
**Status local (24/10):** etapa 1 e etapa 2 implementadas — migração `0011`, `rick_audit_operations`, escrita na mesma transação para logout/reset, ack e reconciliador; B01 e CONTRACT passam. PostgreSQL real `NOT_RUN`.
**Achado:** AUD24-03.

#### AUD24-013 — Contrato de logout OIDC na composição

**Prioridade:** P1 · **Tamanho:** M · **Dono:** Identity/security · **Depende:** 002, 012
**Entrega:** a composição de produção exige porta de revogação/broker ou declara explicitamente “OIDC sem logout”, com política de cookie e resposta; nenhum adapter `production_safe` sem capacidade correspondente.
**Aceite:** OIDC é rejeitado no perfil de produção (decisão AUD24-D3) ou, se um broker for autorizado em programa separado, logout retorna estado documentado sem `signed_out` falso nem cookie persistente; identidade nativa permanece inalterada; teste de composição cobre os dois caminhos.
**Evidência:** teste de composição + matriz de capacidades + documentação.
**Status:** decisão AUD24-D3 registrada em 24/10/2026; `OIDCIdentityProvider.logout_capable=False` e a composição de produção rejeita a identidade sem revogação.
**Achado:** AUD24-07; extensão de PROD12-007/AUD15-T006.

#### AUD24-014 — Login resistente a enumeração por timing

**Prioridade:** P1 · **Tamanho:** P · **Dono:** Identity/security · **Depende:** —
**Entrega:** verificação dummy de custo fixo para usuário inexistente/inativo/tenant inválido; caminho de erro indistinguível; teste baseado em contagem de KDF, não em relógio frágil.
**Aceite:** usuário inexistente executa o mesmo custo de verificação; resposta e headers idênticos; quota continua aplicada; teste diferencia o caminho antigo (sem dummy) do novo.
**Evidência:** pytest com spy de KDF + negativos.
**Status local (24/10):** `verify_dummy` de custo fixo para conta inexistente; teste confirma uma chamada dummy e zero `verify`.
**Achado:** AUD24-08.

#### AUD24-015 — Auditoria de acesso negado não silenciosa

**Prioridade:** P1 · **Tamanho:** P · **Dono:** API/security · **Depende:** 012
**Entrega:** `auth.access_denied` usa o mecanismo durável/outbox; falha gera log estruturado, métrica e/ou spool; orçamento separado da validação de sessão; nenhum `except: pass`.
**Aceite:** sink down → negação continua 403 e a falha é observável (evento, contador ou log com tipo); teste garante que não há descarte silencioso; nenhum dado sensível no log.
**Evidência:** pytest + métrica/log + revisão de redaction.
**Status local (24/10):** falha de auditoria de acesso negado gera log estruturado, sem payload/exception; teste cobre.
**Achado:** AUD24-09.

#### AUD24-016 — Expiração absoluta e TTL configurável de sessão

**Prioridade:** P1 · **Tamanho:** M · **Dono:** Identity/backend · **Depende:** —
**Entrega:** `absolute_expires_at` persistido e validado; `touch` não ultrapassa o limite absoluto; TTL idle/absoluto configurável; `max_age` do cookie derivado da configuração; migração compatível.
**Aceite:** uso contínuo não estende além do absoluto; sessão expirada retorna 401; configuração altera ambos os limites de forma coerente; migração e rollback testados.
**Evidência:** pytest de tempo + configuração.
**Status local (24/10):** validade absoluta derivada de `created_at` imutável + `SESSION_ABSOLUTE_TTL_SECONDS`; `touch` não estende; cookie usa `SESSION_TTL_SECONDS`.
**Achado:** AUD24-10.

#### AUD24-017 — Resolver multi-workspace no login

**Prioridade:** P1 · **Tamanho:** M · **Dono:** Identity/backend · **Depende:** —
**Entrega:** resolução determinística de workspace ou resposta acionável de ambiguidade; fluxo de seleção/escopo; sem `401` indistinguível de senha errada.
**Aceite:** usuário com duas memberships no mesmo tenant autentica no workspace escolhido ou recebe erro acionável; nenhuma escolha implícita; teste de isolamento entre workspaces.
**Evidência:** pytest + matriz de memberships.
**Status local (24/10):** login aceita `workspace_id`, resolve a membership explícita e retorna 409 acionável; campo opcional de workspace adicionado ao login web; typecheck PASS.
**Achado:** AUD24-08.

#### AUD24-018 — Unificar schema e tipagem de auditoria

**Prioridade:** P2 · **Tamanho:** M · **Dono:** Backend/audit · **Depende:** 012
**Entrega:** modelo tipado único de evento; um writer; remoção dos três vocabulários (`_audit`, `emit_required` inline, `access_denied`); validação e documentação do schema.
**Aceite:** todos os eventos validam no modelo; não há dict ad-hoc em rota; testes de contrato cobrem os status; nenhuma perda de campos atuais.
**Evidência:** pytest + schema + busca por writers.
**Achado:** AUD24-03/09.
**Status local (24/10):** `AuditEvent` tipado + `make_audit_event` allow-list; auth/dependencies migrados; teste de rejeição.

### E2 — Recuperação web

#### AUD24-020 — Corrigir abort obsoleto em “Nova conversa”

**Prioridade:** P0 · **Tamanho:** P · **Dono:** Frontend/chat · **Depende:** —
**Entrega:** `startNewConversation` limpa `detailAbortRef` e invalida a geração; nenhuma referência a controller abortado bloqueia envio/paginação; teste de corrida.
**Aceite:** abrir conversa com GET adiado → “Nova conversa” → enviar pergunta produz POST e resposta; o callback antigo não publica; Enter nunca retorna em silêncio.
**Evidência:** unit + E2E com rede adiada.
**Status local (24/10):** implementado e coberto em `prod12-chat.test.tsx`.
**Achado:** AUD24-04.

#### AUD24-021 — Recuperar abertura de conversa abortada

**Prioridade:** P0 · **Tamanho:** P · **Dono:** Frontend/chat · **Depende:** 020
**Entrega:** aborto externo (focus/visibility/sessão) durante `openConversation` retorna a estado `ready` com mensagem e retry; nunca spinner permanente; callback tardio descartado.
**Aceite:** abortar GET durante abertura → composer habilitado, erro visível e retry funcional; teste de focus/visibility cobre o fluxo.
**Evidência:** unit + E2E.
**Status local (24/10):** implementado e coberto em `prod12-chat.test.tsx`.
**Achado:** AUD24-05.

#### AUD24-022 — Mapeamento único de erro 401/403/409/abort/outage

**Prioridade:** P1 · **Tamanho:** M · **Dono:** Frontend/contracts · **Depende:** 020, 021
**Entrega:** um normalizador compartilhado; chat, casos e documentos usam a mesma classificação; `403` não vira outage; `abort` não vira falha de dados; `409` mantém semântica de conflito.
**Aceite:** testes para cada status em cada superfície; nenhuma tela oferece retry cego para 403; abort de revalidação não exibe “serviço indisponível”.
**Evidência:** unit + specs de UI.
**Status local (24/10):** implementado em casos/documentos; testes de 403/abort/paginação adicionados.
**Achado:** AUD24-11.

#### AUD24-023 — Semântica de 403 em casos

**Prioridade:** P1 · **Tamanho:** P · **Dono:** Frontend/casos · **Depende:** 022
**Entrega:** 403 de lista/detalhe leva a estado `restricted`; detalhe proibido não apaga a lista; retry só para 5xx/rede; mensagem de permissão acionável.
**Aceite:** 403 de lista mostra página de permissão; 403 de detalhe preserva itens e seleção; 500 mostra retry; testes cobrem os dois.
**Evidência:** unit/spec.
**Status local (24/10):** implementado e testado.
**Achado:** AUD24-11.

#### AUD24-024 — Paginação de documentos com dedupe e cursor

**Prioridade:** P1 · **Tamanho:** P · **Dono:** Frontend/documentos · **Depende:** 022
**Entrega:** dedupe por `document_id`, rejeição de cursor não avançante, trava de requisição em voo, mensagem de parcialidade; nenhum segundo `loadMore` concorrente.
**Aceite:** cursor repetido falha com erro visível e não duplica; clique duplo gera uma requisição; página seguinte não apaga a anterior; teste dedicado.
**Evidência:** unit/spec.
**Status local (24/10):** implementado e testado.
**Achado:** AUD24-11.

#### AUD24-025 — Ratificar UX offline do composer

**Prioridade:** P2 · **Tamanho:** P · **Dono:** Produto + frontend/chat · **Depende:** 021
**Entrega:** decisão registrada: permitir redigir offline ou manter desabilitado com explicação; teste alinhado à decisão; nenhuma renomeação de teste para mascarar regressão.
**Aceite:** decisão datada; comportamento e teste coerentes; draft preservado em ambos os casos; mensagem honesta.
**Evidência:** ADR curto + teste.
**Status local (24/10):** decisão AUD24-D2 registrada — composer editável offline, envio bloqueado; teste unitário cobre; E2E atualizado mas `NOT_RUN` nesta rodada.
**Achado:** AUD24-11.

### E3 — CI, release e ambiente

#### AUD24-030 — Lane CONTRACT verde com o B01

**Prioridade:** P0 · **Tamanho:** P · **Dono:** Plataforma/CI · **Depende:** 012, 020, 021, 022
**Entrega:** `make api-coverage` verde no candidato corrigido; `tests/test_aud15_identity.py` permanece no caminho do lane; envelope de evidência atualizado.
**Aceite:** `make api-coverage` exit 0; lane CONTRACT PASS; nenhum teste removido/skipado; API coverage ≥ floor 75.
**Evidência:** execução do lane + envelope + log.
**Status local (24/10):** `make api-coverage` exit 0 — 1.864 passed, 18 skipped, 79,48%; CONTRACT verde.
**Achado:** AUD24-03.

#### AUD24-031 — Candidato limpo e release evidence

**Prioridade:** P0 · **Tamanho:** M · **Dono:** Lead/release · **Depende:** 010–025, 030, 032
**Entrega:** candidato revisado e commitado; fingerprint; checkout limpo; release evidence gerada e verificada; nenhum artefato histórico reutilizado.
**Aceite:** `git status` limpo; `release_integrity --require-clean` PASS; SHA/fingerprint/config vinculados; nenhuma mudança posterior invalida a prova.
**Evidência:** commit + manifesto + gate de release.
**Achado:** AUD24-06.

#### AUD24-032 — Toolchain Node 22/npm 10 e testes portáveis

**Prioridade:** P1 · **Tamanho:** M · **Dono:** Plataforma · **Depende:** —
**Entrega:** Node 22.19/npm 10.9 reproduzíveis via toolchain/container; `TMPDIR` dos testes web dentro do workspace ou temp portátil; documentação; lock intacto.
**Aceite:** bootstrap/build/test/coverage web passam no toolchain declarado; nenhuma dependência do `TMPDIR` do host; contrato não é alterado para o host.
**Evidência:** logs de bootstrap/build/test + versões efetivas.
**Status local (24/10):** `TMPDIR` portátil implementado no Vitest (workspace-local, com override); 263 testes web passam sem `TMPDIR` do host. Node 22.19/npm 10.9 não estão instalados neste host — verificação `NOT_RUN`/bloqueio explícito.
**Achado:** AUD24-12.

#### AUD24-033 — Executor VPS representativo

**Prioridade:** P1 · **Tamanho:** G · **Dono:** Plataforma/segurança · **Depende:** 001
**Entrega:** executor Linux descartável com UID/GID/sticky/namespace representativos; execução da lane; classificação de cada falha; nenhuma mudança de DAC/ownership do host.
**Aceite:** lane executada no executor; 277 falhas reconciliadas por causa e disposição; nenhuma suprimida; procedimento reproduzível.
**Evidência:** relatório da lane + ambiente + negativos.
**Achado:** AUD24-12; extensão de PROD12-003/AUD15-T003.

#### AUD24-034 — CI remoto e evidência vinculada

**Prioridade:** P0 · **Tamanho:** M · **Dono:** Plataforma/release · **Depende:** 031, 032
**Entrega:** execução dos lanes no CI remoto sobre o SHA do candidato; artefatos/envelopes vinculados; comparação local↔remoto.
**Aceite:** lanes obrigatórios verdes no remoto; evidência aponta para o SHA exato; nenhuma alegação “local-only” como release.
**Evidência:** run IDs + artefatos + SHA.
**Achado:** AUD24-03/06/12.

### E4 — Qualidade e documentação

#### AUD24-040 — Alinhar documentação corrente

**Prioridade:** P1 · **Tamanho:** P · **Dono:** Docs/Lead · **Depende:** 031
**Entrega:** corrigir [api-security](architecture/api-security.md#L44-L46) (CSRF implementado), [canonical-web](architecture/canonical-web.md#L48-L53) (histórico/streaming), [README](../README.md#L28-L31) (ponteiro AUD24) e [INDEX](INDEX.md); registrar AUD24.
**Aceite:** `make docs-check` 0 erros; nenhuma divergência conhecida nas autoridades; históricos preservados; links novos resolvem.
**Evidência:** docs-check + diff.
**Status local (24/10):** CSRF e limites do chat alinhados ao código; README/INDEX já apontam AUD24; docs-check 1.136 links/0 erros.
**Achado:** AUD24-12.

#### AUD24-041 — Contrato único ou teste de drift web/backend

**Prioridade:** P2 · **Tamanho:** M · **Dono:** Frontend/contracts · **Depende:** 022
**Entrega:** reduzir a duplicação entre `response-contract.ts`, `chat-response.ts` e schemas do backend; teste que falha quando um endpoint muda sem atualizar o contrato web; ou geração a partir de schema.
**Aceite:** adicionar/alterar endpoint sem contrato falha no CI; nenhum fallback silencioso para 2xx desconhecido; testes existentes preservados.
**Evidência:** teste de drift + build.
**Achado:** AUD24-12.

#### AUD24-042 — Ampliar tipagem nos caminhos de risco

**Prioridade:** P2 · **Tamanho:** M · **Dono:** API/identity · **Depende:** 030
**Entrega:** incluir no mypy `services/audit.py`, `services/postgres_identity.py`, stores de sessão/recuperação e o writer de auditoria; baseline zero; sem `ignore` amplo.
**Aceite:** novos módulos com 0 erros; `mypy` no CI; imports fora do denominador permanecem interfaces, sem alegação de monorepo tipado.
**Evidência:** mypy + baseline.
**Status local (24/10):** mypy em 14 módulos (audit, audit_event, audit_operations_store, postgres_audit), 0/0; baseline explícito; `make typecheck` PASS.
**Achado:** AUD24-12; extensão de PROD12-017.

#### AUD24-043 — Branch coverage Python e denominadores explícitos

**Prioridade:** P2 · **Tamanho:** M · **Dono:** QA · **Depende:** 030
**Entrega:** medir branch coverage em API/worker; relatório; floor explícito sem reduzir o de linhas; exclusões documentadas.
**Aceite:** branch % reportado; floor definido e aplicado; nenhuma exclusão nova para obter verde; comparação com a baseline.
**Evidência:** relatório de cobertura + CI.
**Status local (24/10):** branch coverage medido (API 76%, worker 76%); `--cov-branch` habilitado com floors de linhas preservados (75/74). Gate API verde (1.877 passed, 75,65%, exit 0); worker em execução.
**Achado:** AUD24-12; extensão de PROD12-018.

#### AUD24-044 — Ampliar o pack de avaliação RAG

**Prioridade:** P1 · **Tamanho:** G · **Dono:** Domínio/QA · **Depende:** 003 + AUD24-D4
**Entrega:** pack estratificado com corpus/labels/direitos aprovados; métricas de retrieval, citação e faithfulness; limitações e revisão humana; nenhum caso clínico real sem autorização.
**Aceite:** pack aprovado pela autoridade de domínio; resultados reproduzíveis; métricas e denominadores explícitos; 2 casos sintéticos deixam de ser a única prova.
**Evidência:** manifesto do pack + relatório + revisão.
**Achado:** AUD24 (dimensão 12).

#### AUD24-045 — Auditoria de acessibilidade e tecnologia assistiva

**Prioridade:** P1 · **Tamanho:** M · **Dono:** QA/design · **Depende:** 034
**Entrega:** auditoria por teclado, leitor de tela, zoom, contraste e foco nos fluxos críticos; correções; relatório de lacunas.
**Aceite:** nenhum bloqueio crítico nos fluxos principais; lacunas documentadas; evidência de browser/AT, sem alegar WCAG global.
**Evidência:** relatório + capturas + achados.
**Achado:** AUD24 (dimensão 15); extensão de PROD12-025/041.

## 5. Herança PROD12 — referência, não duplicação

Estas obrigações permanecem no [backlog PROD12](<backlog-producao-2026-10-12.md>) e no [plano ativo](<../.agent/plans/producao-2026-10-12.md>). O AUD24 apenas indica onde há delta.

| Faixa PROD12 | Conteúdo | Relação AUD24 |
|---|---|---|
| 001–006 | Baseline, controle, executor, perfil, budgets, inputs externos | M0 reutiliza; 001/033 dão delta local |
| 007 | Logout honesto/revogação recuperável | **Estendido** por 011/013; não substituído |
| 008–010 | Shutdown, claims, teardown | Sem delta; preservar |
| 011–014 | Busca, limiter, CSRF/origin | 014 dá delta de timing; 002 pode tocar 014 |
| 015–020 | Inventário, toolchain, tipos, cobertura, módulos, docs | 032/040/041/042/043 dão delta |
| 021–025 | Casos, chat, autorização/confiança, catálogo, foco | 020–025 e 045 dão delta |
| 026 | Candidato local integrado | **Estendido** por 031/034 |
| 027–030 | Topologia, imagens, lab, migrations PostgreSQL | M5 herda integralmente |
| 031–032 | Redis e lifecycle S3/Qdrant | M5 herda integralmente |
| 033–034 | Provider/embeddings e golden path durável | M5/M6 herdam |
| 035–037 | Identidade real, workers A/B, arquivos hostis | M5/M6 herdam |
| 038–040 | Campanha RAG, evidência forjada, casos clínicos | M6 herda; 044 dá delta de pack |
| 041–042 | Browser/AT e revisão de segurança | M6 herda; 045 dá delta |
| 043–049 | Observabilidade, auditoria durável, restore, capacidade, chaos, soak, runbooks | M5/M6 herdam; 012/018 dão delta de auditoria |
| 050–053 | CI remoto, reviews, packet, decisão | M7 herda; 034/031 dão delta |
| 054–056 | Canary, expansão, operação | Pós-GO, fora deste backlog |

## 6. Rastreabilidade achado → contrato

| Achado | Contrato primário | Secundários |
|---|---|---|
| AUD24-01 reset/503/sem auditoria | 010 | 012, 018 |
| AUD24-02 logout refém da auditoria | 011 | 012, 013 |
| AUD24-03 B01/estado terminal/CI | 012 | 002, 030, 034 |
| AUD24-04 chat morto após Nova conversa | 020 | 021, 022 |
| AUD24-05 chat spinner permanente | 021 | 022 |
| AUD24-06 worktree sujo/release | 031 | 001, 034 |
| AUD24-07 OIDC sem logout | 013 | 002 |
| AUD24-08 timing/multi-workspace | 014 | 017 |
| AUD24-09 access denied engolido | 015 | 012, 018 |
| AUD24-10 sessão sem vida absoluta | 016 | — |
| AUD24-11 web 403/paginação/corrida/offline | 022 | 020, 021, 023, 024, 025, 041 |
| AUD24-12 docs/ambiente/CI | 040 | 032, 042, 043, 045 |

## 7. Não escopo

- Novas features de produto, reescrita de módulos, troca de framework/provider.
- Alterar IDs, aceites ou status de AUD07/AUD15/PROD12.
- Simular store/IdP/provider/browser com fixture e chamar de evidência externa.
- Aplicar DDL real, publicar imagem, assinar release ou fazer deploy sem autoridade.
- “Fechar” acessibilidade, RAG clínico ou SLO por documento.

## 8. Adoção, status e primeira onda

- Este backlog permanece `PROPOSTO`. Adoção no [controlador](<../.agent/backlog.json>) exige pedido humano explícito; a partir daí, o controlador é a única fonte de status/aceite.
- Até a adoção, nenhum item pode ser declarado `DONE` por este documento.
- **Primeira onda recomendada:** 001 → 002 → 003; depois 012 → 010/011; em paralelo 020/021 e 032. Não abrir 013–017 antes de 012 estar estável. Runbook: [escopo executável da primeira onda](<plans/aud24-first-wave-2026-10-24.md>).
- **Não iniciar** 031/034 antes de 010–025; não iniciar M5/M6 sem AUD24-D4.

## 9. Contagem final

| Status | Quantidade |
|---|---:|
| Contratos AUD24 | 29 |
| P0 | 11 |
| P1 | 13 |
| P2 | 5 |
| Herdados PROD12 (referência) | 56 |
| Itens AUD07/AUD15 preservados | 46 + 24 |
