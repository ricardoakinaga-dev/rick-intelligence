# Plano executivo PRD26 — da maturidade local à decisão de produção

**ID:** `PRD26-PLAN-001`
**Data:** 24/10/2026 (America/Sao_Paulo) · **UTC:** 25/10/2026, 01:43
**Estado:** `PROPOSTO` — planejamento; não é ledger de execução, não adota tarefas no [controlador](../../.agent/backlog.json) e não autoriza produção.
**Baseline:** [avaliação independente AVAL24](<../reports/avaliacao-independente-2026-10-24.md>) — **78,0/100**, `NO-GO`, HEAD `dc79ec6`, worktree limpo.
**Artefatos irmãos:** [roadmap](<../roadmap-prod26-2026-10-24.md>) e [backlog](<../backlog-prod26-2026-10-24.md>).
**Herança:** [AUD24](<../plans/execplan-aud24-2026-10-24.md>), [PROD12](<../backlog-producao-2026-10-12.md>) e [AUD07](<../backlog-auditoria-2026-10-07.md>). Nenhum ID herdado é renumerado, substituído ou declarado `DONE` por este plano.

## 1. Sumário executivo

O produto local deixou de ser uma base frágil. A avaliação AVAL24 encontrou **6.043 testes Python aprovados**, **265 testes web**, **363/363 cenários E2E em produção**, gates estáticos verdes, candidato limpo, PostgreSQL/Qdrant/S3 reais com evidência registrada e multi-worker com **8/8 crash points** provados. A arquitetura tem fronteiras automatizadas, o worker tem fencing real e a remediação de identidade/auditoria do ADR-024 está no código com testes discriminantes.

O produto **continua `NO-GO`** por razões que não são de volume de código:

1. **Qualidade de IA/RAG não demonstrada.** O pack sintético de 12 casos foi rejeitado como representativo; não há corpus licenciado, labels de domínio, thresholds D04 assinados ou avaliação com modelo real. Nota do item: **46/100**.
2. **Runtime externo incompleto.** IdP/OIDC, provider real, observabilidade distribuída, restore/DR, performance, chaos e soak permanecem `NOT_RUN` ou `BLOCKED_EXTERNAL`.
3. **Release não commit-bound em CI remoto.** O branch está 14 commits à frente do `origin/archive` e 15 à frente do `origin/main`; não houve execução remota, scan, SBOM, assinatura ou packet selado.
4. **Aceite formal atrasado.** O controlador registra **117 itens: 8 `DONE`, 3 `IN_PROGRESS`, 21 `VERIFY`, 5 `BLOCKED` e 80 `TODO`**; dos 48 P0, 26 seguem `TODO`/`IN_PROGRESS`. Há trabalho implementado que ainda não foi aceito.
5. **Documentação corrente defasada.** `production-runtime.md`, `release-readiness.md` e o roadmap ainda descrevem um estado anterior às evidências M0–M5.

**Decisão executiva proposta:** tratar o PRD26 como um programa de **fechamento de evidência, aceite e release**, não como uma nova rodada de features. O objetivo não é subir a média; é transformar o candidato local em um artefato exato, reproduzível e externamente provado, para que uma autoridade humana possa decidir `GO` ou manter `NO-GO` com informação completa.

**Resultado esperado:** todos os gates mandatórios `PASS` no mesmo artefato, riscos altos sem pendência, revisão independente sem achado alto e decisão humana registrada. A nota indicativa de saída é **≥ 85/100**, mas a média é consequência, não critério de aceite.

## 2. Diagnóstico que fundamenta o plano

| Fato observado | Consequência |
|---|---|
| 6.043 PASS / 137 skips no núcleo; 0 falha conhecida | A base de regressão local é confiável; os 137 skips são dependências externas declaradas, não defeitos. |
| 363/363 E2E em produção; LCP máx. 1.008 ms | A experiência web está funcionalmente coberta; acessibilidade humana e WCAG formal continuam abertas. |
| API 79,27% statements / 75,65% branch; worker 79,58% / 75,93% | Cobertura razoável, mas denominadores ainda restritos e sem mutation testing. |
| 14 packages, 61 rotas, worker durável, 11 migrations | O produto é substancial; o risco migrou da construção para a prova externa e o aceite. |
| 80 TODO; 48 P0 no total (26 abertos) | “Implementado” não é “aceito”; a maior parte do caminho restante é evidência e governança. |
| Branch local à frente de `origin/main` | Nenhum gate remoto, scan ou release packet pode ser considerado atual. |
| Pack RAG de 12 casos rejeitado | A dimensão de IA/RAG é a maior lacuna técnica isolada (46/100). |
| Docs correntes divergem da evidência | A rastreabilidade é boa, mas afirmações obsoletas podem induzir decisão errada. |

## 3. Objetivo, sucesso e não-objetivos

### Objetivo

Converter a maturidade local demonstrada pela AVAL24 em um **release candidate promovível**, com:

1. aceite formal dos itens já implementados;
2. documentação corrente e rastreável;
3. engenharia sustentável (toolchain, tipos, contrato único);
4. qualidade de IA/RAG representativa e acessibilidade humana;
5. dados, identidade, providers e operação provados em runtime real;
6. CI remoto, supply chain e packet de release vinculados ao SHA exato;
7. decisão humana `GO`/`NO-GO` com risco residual explícito.

### Definição de sucesso

1. **Aceite local fechado:** todo item AUD24/PROD12 já implementado tem disposição formal (`DONE`, `VERIFY` com evidência ou `BLOCKED_EXTERNAL` justificado).
2. **Documentação corrente:** nenhuma afirmação atual contradiz a evidência mais recente; `make docs-check` verde.
3. **Engenharia reproduzível:** bootstrap em host limpo com Python 3.12.3, Node 22.19.0, npm 10.9.3, `make ci` e E2E verdes.
4. **RAG representativo:** D04 assinado, corpus com proveniência/licença, labels revisados, thresholds por grupo e avaliação live.
5. **Acessibilidade:** auditoria humana de teclado, leitor de tela, zoom, contraste e foco; lacunas WCAG documentadas.
6. **Runtime real:** PostgreSQL/Redis/Qdrant/S3, ingestão golden path, restore com RPO/RTO, IdP/membership, provider, observabilidade, performance, chaos e soak.
7. **Release:** CI remoto no SHA exato, imagens imutáveis, SBOM, scans, assinatura, release packet e revisão independente.
8. **Decisão:** `GO` humano para o artefato exato ou `NO-GO` mantido. A nota ≥ 85 é indicativa.

### Não-objetivos

- Reescrever a arquitetura, trocar framework, provider ou modelo sem decisão material.
- Adicionar features de negócio não exigidas por gate.
- Escolher IdP, corpus clínico, SLO, topologia ou orçamento sem autoridade.
- Aplicar DDL real, consumir provider pago, publicar imagem, assinar release ou fazer deploy sem autorização.
- Fechar itens PROD12 por analogia com teste local ou por média de notas.
- Transformar `NOT_RUN`, `BLOCKED_EXTERNAL`, skip ou mock em `PASS`.

## 4. Invariantes de execução

1. **Preservar antes de editar.** Nenhum reset, `checkout` amplo ou restauração destrutiva; mudanças pequenas e reversíveis.
2. **Um writer por arquivo/recurso.** Identidade, auditoria, web, dados e release têm owners disjuntos.
3. **Evidência antes de aceite.** Cada item registra SHA, comando, exit code, artefato, timestamp UTC, ambiente e limitação.
4. **Não enfraquecer gates.** Proibido remover teste, marcar `skip`/`xfail`, reduzir floor, alargar allowlist ou reciclar evidência.
5. **Separação builder/revisor.** Quem implementa não aprova o próprio patch em identidade, dados, segurança, release ou risco clínico.
6. **Humano decide o material.** Corpus, perfil de produção, recursos externos, risco residual e `GO`/`NO-GO`.
7. **Planejamento ≠ adoção.** Os contratos PRD26 permanecem `PROPOSTOS` até pedido humano explícito; o controlador é a única fonte de status após a adoção.
8. **Custo controlado.** Nenhum provider pago, ambiente destrutivo ou campanha de carga sem orçamento e janela aprovados.

## 5. Workstreams

| WS | Nome | Resultado | Owner sugerido | Contratos |
|---|---|---|---|---|
| **WS0** | Governança e aceite | Baseline reconciliada, itens locais aceitos, docs correntes | Lead/QA + autoridade | 001–003 |
| **WS1** | Engenharia sustentável | Toolchain limpo, tipos ampliados, contrato único, cobertura com denominadores | Plataforma + API/worker + web | 010–013 |
| **WS2** | IA/RAG e acessibilidade | D04 assinado, corpus representativo, avaliação live, AT humano | Domínio + RAG + QA/design | 020–022 |
| **WS3** | Dados e runtime | PostgreSQL/Redis/Qdrant/S3, golden path, restore, RPO/RTO | DBA + SRE + ingestão | 030–032 |
| **WS4** | Identidade, providers e operação | IdP/membership, provider live, observabilidade, worker A/B, carga/chaos/soak | Identity + provider + SRE | 033, 040–043 |
| **WS5** | Release e decisão | CI remoto, supply chain, packet, revisão independente, canary readiness | Release + segurança + Lead | 050–053 |

### Fronteiras de ownership

- **Identidade/autorização:** um writer em `apps/api/src/routes/auth.py`, `services/identity_*`, `services/postgres_identity.py`, `packages/identity/**` e testes correlatos.
- **Auditoria:** um writer em `services/audit*`, `postgres_audit.py`, `audit_operations*` e migrations de auditoria.
- **Worker/dados:** um writer em `apps/worker/**`, migrations e adapters PostgreSQL/Redis/Qdrant/S3.
- **Web:** um writer em `apps/web/components/**`, `app/**` e testes; contratos compartilhados coordenados com WS1.
- **CI/release:** um writer em `.github/workflows/**`, `Makefile`, locks, `scripts/state_of_art/**` e `infrastructure/docker/**`.
- **Docs:** um writer em `docs/`, exceto relatórios de evidência de cada task.

## 6. Marcos

| Marco | Nome | Resultado | Gate de saída |
|---|---|---|---|
| **M0** | Baseline e reconciliação | AVAL24 vinculada ao SHA, matriz PRD26 ↔ AUD24/PROD12, programa declarado `PROPOSTO` | **G0:** nenhum ID duplicado; baseline reproduzível; docs novos linkados; controlador intacto até adoção. |
| **M1** | Aceite local e docs | Itens AUD24/PROD12 implementados com disposição formal; documentação corrente | **G1:** 100% dos itens locais com `DONE`/`VERIFY`/`BLOCKED_EXTERNAL` justificado; `make docs-check` verde; nenhuma afirmação atual contraditória. |
| **M2** | Engenharia sustentável | Toolchain 22/10, E2E portátil, mypy ampliado, contrato único, cobertura explícita | **G2:** bootstrap limpo; `make ci` verde no toolchain declarado; tipos/contrato sem regressão; floors preservados. |
| **M3** | IA/RAG e acessibilidade | D04 assinado, corpus representativo, avaliação live, auditoria AT humana | **G3:** corpus/licenças/labels/thresholds aprovados; métricas por grupo; nenhum bloqueio crítico de AT; sem alegação clínica indevida. |
| **M4** | Dados e restore | Stores reais, migrations, golden path com crash/replay, restore com RPO/RTO | **G4:** todos os gates de dados `PASS`; tenant A/B; nenhuma publicação duplicada; restore verificado. |
| **M5** | Identidade, providers e operação | IdP real, provider live, observabilidade distribuída, worker A/B, performance/chaos/soak | **G5:** matriz de identidade sem vazamento; provider com falha/cancelamento/budget; traces/alertas; budgets de carga; sem leak no soak. |
| **M6** | Release candidate e supply chain | CI remoto no SHA exato, imagens imutáveis, SBOM/scans/assinatura, packet e revisão independente | **G6:** todos os lanes mandatórios `PASS` no mesmo artefato; nenhum achado alto; release integrity válida. |
| **M7** | Decisão e canary readiness | Decisão humana, risco residual, plano de canary/rollback | **G7:** `GO` assinado para o artefato exato ou `NO-GO` mantido; canary só com autoridade e janela próprias. |

**Canary, expansão e operação contínua** não são marcos deste plano: são decisões pós-G7, com autoridade própria.

## 7. Caminho crítico

```text
M0 baseline + reconciliação
  └─ M1 aceite local + docs
       ├─ M2 engenharia sustentável
       └─ M3 RAG + acessibilidade
            ├─ M4 dados + restore
            │    └─ M5 identidade + providers + operação
            │         └─ M6 release + supply chain + revisão
            │              └─ M7 decisão + canary readiness
            └─ (M2 e M3 podem correr em paralelo; M1 não bloqueia M4 se o escopo externo estiver autorizado)
```

O caminho mais longo é **M3 (corpus/D04) → M4 (dados/restore) → M5 (IdP/provider/operação) → M6 (release/revisão)**. A disponibilidade de autoridade, corpus, credenciais e ambientes externos domina o prazo; as janelas são indicativas, não promessas.

## 8. Governança

### Estados

`PROPOSTO → ADOTADO → IN_PROGRESS → VERIFY → DONE` ou `BLOCKED_EXTERNAL`.

- **PROPOSTO:** este documento; sem efeito no controlador.
- **ADOTADO:** somente após pedido humano explícito; o `.agent/backlog.json` passa a ser a única fonte de status.
- **VERIFY:** implementação e evidência prontas; aceite ainda não concedido.
- **DONE:** critério observável satisfeito, evidência vinculada e aceite registrado.
- **BLOCKED_EXTERNAL:** dependência de autoridade, corpus, credencial ou ambiente; não é `PASS`.

### Evidência por tarefa

Cada aceite produz um envelope com:

1. data/hora UTC;
2. SHA, branch e estado do worktree;
3. fingerprint do candidato/configuração;
4. comando completo, ambiente e exit code;
5. artefato, caminho e hash;
6. dependências e autoridades usadas;
7. limitação (`PASS`, `FAIL`, `NOT_RUN`, `BLOCKED_EXTERNAL`).

### Revisões independentes

- **G1:** revisor de aceite/documentação, read-only, sem acesso ao racional dos builders.
- **G3:** revisor de domínio/RAG e acessibilidade.
- **G4/G5:** revisão de dados, segurança e operação.
- **G6/G7:** revisão final independente com packet e artefato exatos; o builder não assina o próprio release.

### Decisões humanas necessárias

| ID | Decisão | Quando | Se ausente |
|---|---|---|---|
| PRD26-D1 | Adotar o PRD26 no controlador e definir autoridade de aceite | M0 | Programa permanece `PROPOSTO`; nenhum item vira `DONE` |
| PRD26-D2 | Corpus, licença, labels, thresholds e risco clínico do RAG (D04) | M3 | `BLOCKED_EXTERNAL`; nenhum pack sintético é representativo |
| PRD26-D3 | Perfil de produção: IdP nativo Postgres vs OIDC com broker, provider/modelo, SLO | M5 | Perfil nativo do ADR-024; OIDC fora até broker |
| PRD26-D4 | Recursos, credenciais, orçamento e janela para ambientes externos | M4/M5 | Gates externos `BLOCKED_EXTERNAL` |
| PRD26-D5 | Autoridade de release, assinatura, canary e rollback | M6/M7 | Nenhuma imagem publicada/assinada; `NO-GO` |
| PRD26-D6 | Aceitação de risco residual e `GO`/`NO-GO` | M7 | `NO-GO` por padrão |

## 9. Riscos

| # | Risco | Prob. | Impacto | Mitigação | Owner |
|---|---|---|---|---|---|
| R1 | Corpus/D04 não aprovado trava M3 | Alta | Alto | Timebox; decisão humana antecipada; nenhum substituto sintético | Domínio + Lead |
| R2 | Recursos externos indisponíveis | Alta | Alto | Preparar pacote/autorizações; `BLOCKED_EXTERNAL` honesto; não simular | SRE + Lead |
| R3 | CI remoto não reproduz o local | Média | Alto | Bootstrap por locks; executor limpo; mesma matriz de comandos | Plataforma |
| R4 | Custo de provider/carga estoura | Média | Médio | Budgets, aborto, limites por execução; aprovação prévia | SRE + produto |
| R5 | Aceite local vira “carimbo” sem evidência | Média | Alto | Envelope por item; revisão independente; nenhuma média compensa gate | QA + Lead |
| R6 | Correções de tipos/contrato quebram a API | Média | Médio | Baseline explícito; contract-drift; rollout incremental | API + web |
| R7 | Documentação volta a divergir | Média | Baixo | Docs no DoD; `make docs-check`; revisão de frescor em G1/G6 | Docs/QA |
| R8 | Scope creep e “caça à nota” | Média | Médio | Não-objetivos; gates observáveis; revisão de escopo em M0 | Lead |
| R9 | Regressão silenciosa em auth/dados | Baixa | Crítico | Testes discriminantes; revisão independente; crash/replay | Segurança |

## 10. Equipe, esforço e horizonte

**Equipe mínima sugerida:** 1 backend/identity sênior, 1 frontend sênior, 1 plataforma/CI, 1 SRE/DBA, 0,5 QA/acessibilidade, domínio/RAG em regime parcial, revisor independente em G1/G3/G6/G7.

**Esforço relativo:** P/M na maioria dos contratos; os maiores são PRD26-020 (corpus/D04), 030–033 (dados/restore/carga), 040–042 (IdP/provider/observabilidade), 050–052 (CI/supply chain/packet) e 053 (decisão).

**Horizonte indicativo:** 4–6 semanas para M0–M3, condicionado à decisão D04 e à equipe; M4–M7 dependem de autoridade e ambientes externos e **não têm data prometida**. A disponibilidade externa domina o prazo real.

## 11. Primeiros 10 dias úteis

1. **Dia 1:** reconciliar AVAL24 com o controlador; registrar baseline, SHA e matriz de IDs; confirmar que nenhum ID PRD26 duplica AUD24/PROD12.
2. **Dia 1–2:** levar PRD26-D1 à autoridade; se adotado, abrir o ledger e congelar comandos/quality bar.
3. **Dia 2–3:** executar PRD26-002 (aceite local) em modo read-only: classificar cada item implementado como `DONE`, `VERIFY` ou `BLOCKED_EXTERNAL` com evidência.
4. **Dia 3–4:** corrigir PRD26-003 (docs correntes) e rodar `make docs-check`.
5. **Dia 4–5:** iniciar PRD26-010 (toolchain limpo) e PRD26-011 (mypy) em paralelo.
6. **Dia 5–6:** abrir PRD26-D2 (D04) e PRD26-D4 (recursos externos); preparar pacote de evidência, sem executar.
7. **Dia 6–7:** PRD26-012 (contrato único) e PRD26-013 (cobertura/mutação) com um writer por arquivo.
8. **Dia 7–8:** revisão de G1; se verde, congelar o candidato local e iniciar M3.
9. **Dia 8–9:** preparar a onda de dados (PRD26-030/031/032) e o runbook de restore.
10. **Dia 9–10:** revisão de prontidão para M3/M4; registrar decisões e bloqueios; não iniciar M5 sem autorização externa.

## 12. Rastreabilidade AVAL24 → PRD26

| Dimensão AVAL24 | Nota | Contratos PRD26 | Marco | Gate |
|---|---:|---|---|---|
| 1 Arquitetura/fronteiras | 87 | 001, 012 | M0/M2 | G0/G2 |
| 2 Contratos de API | 84 | 012 | M2 | G2 |
| 3 Autenticação/sessão | 80 | 002, 040 | M1/M5 | G1/G5 |
| 4 Autorização/tenant | 85 | 040 | M5 | G5 |
| 5 Entrada/abuso | 76 | 040 | M5 | G5 |
| 6 Auditoria/honestidade | 80 | 002, 042 | M1/M5 | G1/G5 |
| 7 Persistência/integridade | 86 | 030, 032 | M4 | G4 |
| 8 Ingestão/documentos | 86 | 031 | M4 | G4 |
| 9 Worker/concorrência | 89 | 031, 043 | M4/M5 | G4/G5 |
| 10 Providers/resiliência | 84 | 041 | M5 | G5 |
| 11 Retrieval/proveniência | 86 | 020, 021 | M3 | G3 |
| 12 IA/RAG | 46 | 020, 021 | M3 | G3 |
| 13 Frontend/UX | 84 | 003, 022 | M1/M3 | G1/G3 |
| 14 FE ↔ API | 82 | 012 | M2 | G2 |
| 15 Acessibilidade | 75 | 022 | M3 | G3 |
| 16 Testes/regressão | 89 | 002, 011, 013 | M1/M2 | G1/G2 |
| 17 Cobertura/denominadores | 77 | 013 | M2 | G2 |
| 18 Tipagem | 75 | 011 | M2 | G2 |
| 19 Lint/higiene | 90 | 010 | M2 | G2 |
| 20 Build frontend | 89 | 010 | M2 | G2 |
| 21 CI/supply chain | 74 | 050, 051 | M6 | G6 |
| 22 Documentação | 79 | 003 | M1 | G1 |
| 23 Reprodutibilidade | 76 | 010 | M2 | G2 |
| 24 Observabilidade/operação | 74 | 042 | M5 | G5 |
| 25 Backup/restore/DR | 55 | 032 | M4 | G4 |
| 26 Prontidão de produção | 40 | 050–053 | M6/M7 | G6/G7 |

## 13. Critérios de parada

O programa para e retorna `NO-GO` se qualquer condição persistir:

- baseline não reproduzível ou item sem disposição formal;
- documentação corrente contradiz a evidência;
- toolchain declarado não reproduzível em host limpo;
- D04/corpus não aprovado ou pack sintético apresentado como representativo;
- qualquer gate de dados, identidade, provider, restore, observabilidade ou carga `NOT_RUN`/`BLOCKED_EXTERNAL` sem disposição aceita;
- CI remoto não vinculado ao SHA exato ou release packet incompleto;
- revisão independente com achado alto sem correção;
- tentativa de converter skip, mock, média ou documento em `PASS`;
- ausência de decisão humana para risco residual ou `GO`.

## 14. Encerramento

Este plano termina quando os gates G0–G7 forem avaliados com evidência atual, vinculados ao mesmo artefato, e a autoridade competente registrar `GO` ou `NO-GO`. O plano não promove o produto, não aceita risco e não substitui o [controlador](../../.agent/backlog.json), a [política de promoção](../architecture/promotion-authority.md) ou a [integridade de release](../architecture/release-integrity.md).

**Próxima decisão:** PRD26-D1 — adoção do programa e autoridade de aceite. Até lá, este documento permanece `PROPOSTO`.
