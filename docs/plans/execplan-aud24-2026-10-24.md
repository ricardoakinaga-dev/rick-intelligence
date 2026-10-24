# Plano executivo AUD24 — da base local forte ao candidato promovível

**ID:** `AUD24-PLAN-001`
**Data:** 24/10/2026 (America/Sao_Paulo)
**Estado:** `PROPOSTO` — planejamento; não é ledger de execução, não adota tarefas no controlador e não autoriza produção. **Decisão AUD24-D1 ratificada em 24/10/2026:** [ADR-024](../architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md) (A+ em duas etapas; OIDC fora do perfil de produção).
**Baseline:** [auditoria AUD24](<../reports/relatorio-auditoria-2026-10-24.md>) — **74,7/100**, produção `NO-GO`, HEAD `48e383c`, worktree com 109 entradas.
**Artefatos irmãos:** [roadmap](<../roadmap-auditoria-2026-10-24.md>) e [backlog](<../backlog-auditoria-2026-10-24.md>).
**Status local em 24/10/2026:** G0 `PASS`; AUD24-001/002/003, 010/011/012 (etapas 1–2), 013–018, 020–025, 030, 040 e 042 executados e verificados localmente. Pendentes: 033–034, 044–045 e M5–M7; 031/032/041/043 concluídos localmente; PostgreSQL/IdP/AT reais `NOT_RUN`. **Nenhum aceite, release ou promoção.**

## 1. Sumário executivo

A base local é forte: 6.018 testes Python aprovados, 258 testes web, gates estáticos verdes, arquitetura de fronteiras consistente e controles fail-closed maduros. O produto **não está pronto para produção** por três razões independentes:

1. **Defeitos de prioridade alta (P1 no relatório) em identidade e auditoria.** O reset pode efetivar a troca e responder 503 sem auditoria; o logout depende da disponibilidade do sink; o B01 persiste `completed` após 503 e não tem estado terminal reconciliável.
2. **Regressões de recuperação no chat.** Duas sequências comuns deixam o composer silenciosamente inoperante ou o painel em spinner permanente.
3. **Candidato não promovível.** O worktree está sujo, o lane CONTRACT falha no B01 e as obrigações externas continuam `NOT_RUN`.

**Decisão executiva proposta:** congelar qualquer ambição de promoção até que os seis achados altos (AUD24-01…06) estejam fechados com regressões discriminantes e um candidato limpo tenha os lanes locais verdes. Em paralelo, preparar — sem executar — a onda externa. A promoção continua sendo decisão humana separada.

**Resultado esperado do programa:** todos os achados altos do relatório fechados, zero teste conhecido falhando, checkout limpo com evidência de release válida, matriz externa executada sob autoridade própria e revisão independente sem achado alto. A nota indicativa de saída é **≥ 85/100**, mas a aceitação é baseada em gates observáveis, não na média.

## 2. Diagnóstico que fundamenta o plano

| Fato observado | Consequência |
|---|---|
| 6.018 PASS / 1 FAIL / 137 skips no núcleo | Base de regressão relevante; a única falha é um contrato aberto (B01), não ruído. |
| API 79,42% e worker 80,11% de cobertura; web 90,65% linhas | Cobertura razoável, mas denominadores restritos e sem branch coverage em Python. |
| Lane VPS com 277 falhas ambientais | Não há prova de que a lane passaria em Linux representativo; não é 277 bugs. |
| Worktree com 70 modificados + 39 não rastreados | Release integrity e evidência commit-bound inviáveis. |
| 117 itens no backlog: 8 DONE, 80 TODO | O produto local é uma fração aceita do programa; a maior parte é evidência externa ou aceite pendente. |
| Node 24/npm 11 no host vs 22/10 no contrato | Reprodutibilidade do frontend não está demonstrada no toolchain declarado. |
| 1.028 links válidos, mas 742 citações sem arquivo e 3 docs divergentes | Documentação ampla, com custo de manutenção e risco de afirmação obsoleta. |

## 3. Objetivo, sucesso e não-objetivos

### Objetivo

Converter os 12 achados AUD24 em correções verificáveis, recuperar uma cadeia de release reproduzível e preparar a execução das fronteiras externas, **sem** reescrever a arquitetura, **sem** enfraquecer gates e **sem** fabricar evidência.

### Definição de sucesso

1. **Achados altos fechados:** AUD24-01..06 com teste que rejeita a versão defeituosa e aprova a corrigida.
2. **Candidato limpo:** checkout commitado, fingerprint reproduzível, worktree limpo.
3. **Lanes locais verdes:** `make validate`, núcleo Python, API/worker coverage, lint, typecheck, build, web unit e E2E aplicável; nenhum teste conhecido falhando.
4. **Lane CONTRACT verde:** o B01 não pode ser removido do caminho de `make api-coverage`.
5. **Runtime externo:** provas reais de stores, identidade, providers, restore, observabilidade, carga/chaos/soak e browser, sob autoridade própria.
6. **Revisão independente:** nenhum achado alto sem disposição legítima; risco residual aceito pela autoridade correta.
7. **Decisão:** `GO` explícito para o artefato exato ou `NO-GO` mantido. A média ≥ 85 é indicativa, não substituta de gate.

### Não-objetivos

- Reescrita arquitetural, troca de framework, novo produto ou novas features de negócio.
- Escolher IdP, provider, corpus clínico, SLO ou topologia de produção sem autoridade.
- Aplicar DDL real, consumir provider pago, publicar imagem, assinar release ou fazer deploy.
- “Fechar” itens PROD12 por analogia com testes locais.
- Perseguir nota por checklist; a nota é consequência da evidência.

## 4. Invariantes de execução

1. **Preservar antes de editar.** O worktree atual contém trabalho não commitado do usuário; nenhum reset, checkout amplo ou restauração destrutiva.
2. **Um writer por arquivo/recurso.** Identidade, web-chat, documentos, CI e docs têm owners disjuntos.
3. **Teste primeiro a falha.** Correção só é aceita com reprodução RED e regressão que rejeite o defeito antigo.
4. **Não enfraquecer gates.** Proibido remover teste, marcar `skip`/`xfail`, reduzir floor, alargar allowlist ou mascarar `NOT_RUN`.
5. **Evidência vinculada.** Cada aceite registra SHA/fingerprint, comando, exit code, artefato, timestamp UTC e limitações.
6. **Separação builder/revisor.** Quem implementa não aprova o próprio patch em identidade, auditoria, dados e release.
7. **Humano decide o que é material.** Contrato do B01, UX offline, perfil OIDC de produção, recursos externos, risco clínico e promoção.
8. **Planejamento ≠ adoção.** Estes 29 contratos permanecem `PROPOSTOS` até pedido humano explícito de adoção no controlador.

## 5. Workstreams

| WS | Nome | Resultado | Owner sugerido | Contratos |
|---|---|---|---|---|
| **WS1** | Identidade e auditoria | Reset/logout com efeito e confirmação honestos; estado de auditoria terminal, idempotente e reconciliável; OIDC sem promessa falsa; sessão com limite absoluto | Backend/identity + security reviewer | 010–018 |
| **WS2** | Recuperação web | Chat nunca perde a ação silenciosamente; 403/abort/outage distintos; paginação e corrida inicial corrigidas | Frontend lead | 020–025 |
| **WS3** | CI, release e ambiente | Lane CONTRACT verde; candidato limpo; toolchain 22/10; `TMPDIR` portátil; executor VPS representativo; CI remoto vinculado | Plataforma/CI | 030–034 |
| **WS4** | Qualidade e documentação | Docs alinhados; contrato único; tipos/cobertura com denominadores explícitos; avaliação RAG ampliada; acessibilidade | QA + docs + domain | 040–045 |
| **WS5** | Evidência externa | Stores, IdP, providers, restore, observabilidade, carga/chaos/soak e browser reais, sob autoridade | SRE/runtime + domain | Herança PROD12 |

### Fronteiras de ownership

- **Auth/identity:** um único writer em `apps/api/src/routes/auth.py`, `services/identity_offload.py`, `services/postgres_identity.py`, `packages/identity/**` e testes correlatos. Web não edita esses arquivos.
- **Web-chat:** um único writer em `components/chat/**`; WS2 não altera `lib/api.ts` sem coordenar com o owner de contratos.
- **Auditoria:** um writer em `services/audit.py`, `postgres_audit.py` e migrations de auditoria; identity consome o contrato, não cria um segundo.
- **CI/release:** um writer em `.github/workflows/**`, `Makefile`, locks e scripts de evidência.
- **Docs:** um writer em `docs/`, com exceção dos relatórios de evidência de cada task.

## 6. Marcos

| Marco | Nome | Resultado | Gate de saída |
|---|---|---|---|
| **M0** | Baseline e decisão | Baseline preservada, escopo reconciliado, contrato do B01 ratificado, quality bar congelada | **G0:** patch/checkpoint com hashes; nenhum ID duplicado; decisão do B01 registrada; barra e comandos congelados antes de código. |
| **M1** | Identidade e auditoria | Reset/logout/audit/OIDC/sessão corrigidos | **G1:** AUD24-01..03 e 07..10 fechados; testes discriminantes; revisão independente de identidade; nenhum achado alto de auth/audit aberto. |
| **M2** | Recuperação web | Chat, casos, documentos e contratos estáveis | **G2:** AUD24-04/05/11 fechados; unit + E2E dos fluxos; nenhuma perda silenciosa; 403/abort/outage distinguidos. |
| **M3** | CI, release e ambiente | Candidato limpo e reproduzível | **G3:** checkout limpo; lane CONTRACT e demais lanes locais verdes; toolchain 22/10; release evidence válida; VPS em executor representativo ou bloqueio explícito. |
| **M4** | Qualidade e docs | Rastreabilidade e denominadores coerentes | **G4:** docs sem divergência conhecida; contrato único; tipos/cobertura ampliados sem reduzir floors; pack RAG ampliado; acessibilidade avaliada. |
| **M5** | Runtime externo I — dados | PostgreSQL/Redis/Qdrant/S3, migrations, ingestão E2E e restore | **G5:** provas reais, tenant A/B, crash/replay, checksums e RPO/RTO medidos. |
| **M6** | Runtime externo II — identidade/providers/operação | IdP, providers/RAG, observabilidade, carga/chaos/soak e browser real | **G6:** matriz externa completa, negativos, budgets e alertas; nenhum `NOT_RUN` obrigatório oculto. |
| **M7** | Release candidate e decisão | Packet, revisão independente e decisão | **G7:** todos os gates mandatórios PASS; risco alto sem pendência; `GO` humano para o artefato exato, ou `NO-GO` mantido. |

**Promoção/canary** não é um marco deste plano: é decisão pós-G7, com autoridade própria.

## 7. Caminho crítico

```text
M0 baseline + decisão do B01
  └─ WS1: contrato de auditoria (012)
       ├─ reset (010) ─┐
       ├─ logout (011) ─┼─ CONTRACT lane (030)
       ├─ OIDC (013)   │
       └─ sessão/timing/access denied (014–017)
  └─ WS2: chat (020→021→022), casos (023), documentos (024), UX (025)
                 │
                 └─ candidato limpo + release evidence (031)
                          ├─ toolchain (032)
                          ├─ VPS (033)
                          └─ CI remoto (034)
                                   │
                                   └─ M4 qualidade/docs ─ M5/M6 externos ─ M7 decisão
```

O caminho mais longo é **decisão do B01 → estado de auditoria → lane CONTRACT → candidato limpo → runtime externo**. Os trabalhos web e de documentação podem correr em paralelo, mas não podem atrasar a decisão de auditoria.

## 8. Governança

### Estados

`PROPOSTO → ADOTADO → IN_PROGRESS → VERIFY → DONE` ou `BLOCKED_EXTERNAL`.

- **PROPOSTO:** este documento; sem efeito no controlador.
- **ADOTADO:** somente após pedido humano explícito; o `.agent/backlog.json` passa a ser a única fonte de status.
- **VERIFY:** implementação e evidência local prontas; aceite ainda não concedido.
- **DONE:** critério observável satisfeito e aceite registrado; não é “código escrito”.

### Evidência por tarefa

Cada aceite deve produzir um envelope com:

1. data/hora UTC;
2. SHA e estado do worktree;
3. fingerprint do candidato/config;
4. comando completo e exit code;
5. artefato e hash;
6. dependências/autoridades usadas;
7. limitação (`PASS`, `FAIL`, `NOT_RUN`, `BLOCKED_EXTERNAL`).

### Revisões independentes

- **G1:** revisor novo, read-only, foco em identidade/auditoria.
- **G3:** revisor de release/CI, sem acesso ao racional dos builders.
- **G7:** revisão final independente, com packet e artefato exatos.

### Decisões humanas necessárias

| ID | Decisão | Quando | Se ausente |
|---|---|---|---|
| AUD24-D1 | Contrato do B01: outbox idempotente + reconciliador, fence prepare/commit, ou semântica indeterminada explícita | M0 — **ratificada em 24/10/2026** | [ADR-024](../architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md) (A+ em duas etapas); M1 não começa sem o ADR; teste não é removido nem `completed` é declarado |
| AUD24-D2 | UX offline do composer: permitir redigir ou manter desabilitado | **Resolvida em 24/10: permitir redigir offline; envio bloqueado** | Rascunho local preservado; submit continua fail-closed por `online`/autorização |
| AUD24-D3 | OIDC no perfil de produção: broker/revogação ou “sem logout” explícito | **Resolvida em 24/10: OIDC fora do perfil de produção** | Manter nativo Postgres; OIDC só com broker em programa separado |
| AUD24-D4 | Recursos, corpus, provider, orçamento e autoridade externa | M5/M6 | `BLOCKED_EXTERNAL`; nenhuma prova simulada |
| AUD24-D5 | Risco residual e `GO`/`NO-GO` | M7 | `NO-GO` por padrão |

## 8.1 Registro de decisões

| Decisão | Estado | Registro |
|---|---|---|
| AUD24-D1 — contrato do B01 | **RATIFICADA** | [ADR-024 — Audit outcome state machine and revocation ordering](../architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md): A+ em duas etapas; `completed` = acknowledgment; revogação independente do sink; `503 result_indeterminate` com `request_id`; reconciliador; fast path transacional no Postgres. |
| AUD24-D2 — UX offline | Aberta | Recomendação: permitir redigir offline e bloquear envio. |
| AUD24-D3 — OIDC em produção | **RESOLVIDA por decisão do usuário: não promover OIDC** até existir broker/revogação; nativo Postgres é o perfil de produção. | Pendente de ADR/registro em AUD24-013. |
| AUD24-D4 — recursos externos | Aberta | Depende de autoridade/orçamento. |
| AUD24-D5 — GO/NO-GO | Aberta | Default `NO-GO`; decisão em M7. |

## 9. Riscos

| # | Risco | Prob. | Impacto | Mitigação | Owner |
|---|---|---|---|---|---|
| R1 | Decisão do B01 trava o caminho crítico | Alta | Alto | Timebox de 2 dias; default recomendado: outbox idempotente + reconciliador | Lead + segurança |
| R2 | Outbox adiciona escrita dupla e nova complexidade | Média | Alto | Uma transação/outbox; reconciliador idempotente; testes de crash entre prepare/commit | Backend |
| R3 | Correções web introduzem novas regressões | Média | Alto | Um writer em chat; E2E novo; revisão independente de G2 | Frontend |
| R4 | Worktree não commitado se perde | Baixa | Crítico | Patch e manifesto antes de qualquer edição; sem reset; checkpoint por task | Lead |
| R5 | Ambiente externo indisponível | Alta | Alto | Preparação antecipada; `BLOCKED_EXTERNAL` honesto; nenhuma prova fake | SRE |
| R6 | Node 22/npm 10 indisponíveis | Média | Médio | Toolchain pinada/container; não alterar contrato para o host | Plataforma |
| R7 | Lane VPS continua sem executor representativo | Alta | Médio | Provisionar executor descartável; não mudar DAC do host | Plataforma/segurança |
| R8 | Scope creep e “caça à nota” | Média | Médio | Gates observáveis; não abrir features; revisão de escopo em M0 | Lead |
| R9 | Docs continuam divergindo durante o programa | Média | Baixo | Docs como parte do DoD de cada task; link checker no CI | Docs/QA |

## 10. Equipe, esforço e horizonte

**Equipe mínima sugerida:** 1 backend/identity sênior, 1 frontend sênior, 1 plataforma/CI, 0,5 QA, SRE/produto em regime parcial, revisor independente nos gates G1/G3/G7.

**Esforço relativo:** os 29 contratos somam majoritariamente tarefas P/M; os G são AUD24-012 (auditoria), AUD24-031 (release), AUD24-033 (VPS), AUD24-044 (RAG) e auditoria acessível. Não usar contagem de tarefas como prazo.

**Horizonte indicativo:** 6–8 semanas para M0–M4, condicionado à decisão do B01 e à disponibilidade da equipe; M5–M7 dependem de autoridade e ambientes externos e **não têm data prometida**. A disponibilidade externa domina o prazo real.

## 11. Primeiros 10 dias úteis

1. **Dia 1:** preservar patch/manifesto do worktree; criar checkpoint AUD24; congelar a quality bar e os comandos de evidência. Runbook: [primeira onda](<aud24-first-wave-2026-10-24.md>).
2. **Dia 1–2:** reconciliar AUD24 com AUD15/PROD12; confirmar que nenhum contrato duplica ID existente.
3. **Dia 2–3:** levar AUD24-D1 à autoridade; registrar a decisão em ADR; se não houver decisão, parar M1 e não mascarar o teste.
4. **Dia 3–4:** desenhar o estado de auditoria (eventos, unicidade, reconciliação) e o contrato de reset/logout; revisar com segurança.
5. **Dia 4–6:** implementar AUD24-012 e, em sequência, 010/011; testes de crash entre efeito e confirmação.
6. **Dia 5–7:** corrigir AUD24-020/021 (chat) com E2E direcionado; um único writer.
7. **Dia 7–8:** corrigir 022–024 e decidir AUD24-D2.
8. **Dia 9–10:** rodar CONTRACT, núcleo e web no candidato; registrar evidência; revisão independente de G1. Se verde, preparar commit limpo — não promover.

## 12. Rastreabilidade

| Achado | Contratos | Marco | Gate |
|---|---|---|---|
| AUD24-01 reset/503/sem auditoria | 010, 011, 012 | M1 | G1 |
| AUD24-02 logout refém da auditoria | 011, 012 | M1 | G1 |
| AUD24-03 B01/estado terminal/CI | 002, 012, 030 | M0/M1/M3 | G0/G1/G3 |
| AUD24-04 chat morto após Nova conversa | 020 | M2 | G2 |
| AUD24-05 chat spinner permanente | 021 | M2 | G2 |
| AUD24-06 worktree sujo/release | 001, 031, 034 | M0/M3 | G0/G3 |
| AUD24-07 OIDC sem logout | 013 | M1 | G1 |
| AUD24-08 timing/multi-workspace | 014, 017 | M1 | G1 |
| AUD24-09 access denied engolido | 015 | M1 | G1 |
| AUD24-10 sessão sem vida absoluta | 016 | M1 | G1 |
| AUD24-11 web 403/paginação/corrida/offline | 022–025 | M2 | G2 |
| AUD24-12 docs/ambiente/CI | 032, 040, 041, 043 | M3/M4 | G3/G4 |

## 13. Critérios de parada

O programa para e retorna `NO-GO` se qualquer condição abaixo persistir:

- decisão do B01 não ratificada;
- candidato não commitável ou evidência não reproduzível;
- qualquer achado alto aberto ou teste conhecido falhando;
- lane CONTRACT ou gate local obrigatório vermelho;
- prova externa obrigatória `NOT_RUN`/`BLOCKED_EXTERNAL` sem disposição aceita;
- revisão independente com achado alto sem correção;
- tentativa de converter skip, mock ou média em PASS.

## 14. Encerramento

Este plano termina quando os gates G0–G7 forem avaliados com evidência atual, vinculados ao mesmo artefato, e a autoridade competente registrar `GO` ou `NO-GO`. O plano não promove o produto, não aceita risco e não substitui o [controlador](../../.agent/backlog.json), a [política de promoção](../architecture/promotion-authority.md) ou a [integridade de release](../architecture/release-integrity.md).
