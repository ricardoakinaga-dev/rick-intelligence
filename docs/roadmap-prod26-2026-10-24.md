# Roadmap PRD26 — oito marcos até a decisão de produção

**Data:** 24/10/2026 (America/Sao_Paulo) · **UTC:** 25/10/2026, 01:43
**Estado:** `PLANEJAMENTO PROPOSTO` · **Produção:** `NO-GO`
**Baseline:** [avaliação independente AVAL24](<reports/avaliacao-independente-2026-10-24.md>) — **78,0/100**, HEAD `dc79ec6`, worktree limpo.
**Documentos relacionados:** [plano executivo](<plans/execplan-prod26-2026-10-24.md>) e [backlog](<backlog-prod26-2026-10-24.md>).
**Regra:** este roadmap não é ledger de execução, não adota tarefas no [controlador](<../.agent/backlog.json>) e não autoriza serviços externos, DDL real, deploy ou promoção. O perfil de produção herdado do [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>) mantém OIDC fora até existir broker/revogação.

## 1. Objetivo e ponto de partida

O produto local está substancialmente construído: 61 rotas, worker durável, 14 packages, 8 rotas web, 11 migrations, 6.043 testes Python, 265 testes web e 363 cenários E2E aprovados em produção. A avaliação AVAL24 registra **78,0/100**, com o candidato limpo e os gates locais verdes.

O objetivo do PRD26 não é construir mais features. É **fechar a distância entre “implementado localmente” e “promovível”**: aceite formal, documentação corrente, engenharia reproduzível, RAG representativo, acessibilidade humana, dados/identidade/operação reais, CI remoto, supply chain, packet de release e decisão humana.

A nota é diagnóstico, não meta. O programa avança por gates observáveis; a média pode subir como consequência.

## 2. Visão dos oito marcos

| Marco | Nome | Janela indicativa | Resultado | Gate de saída |
|---|---|---|---|---|
| **M0** | Baseline e reconciliação | Semana 1 | AVAL24 vinculada ao SHA; matriz PRD26 ↔ AUD24/PROD12; programa proposto | **G0** |
| **M1** | Aceite local e docs | Semanas 1–2 | Itens implementados com disposição formal; documentação corrente | **G1** |
| **M2** | Engenharia sustentável | Semanas 2–3 | Toolchain 22/10, E2E portátil, mypy, contrato único, cobertura | **G2** |
| **M3** | IA/RAG e acessibilidade | Semanas 3–5 | D04, corpus representativo, avaliação live, AT humano | **G3** |
| **M4** | Dados e restore | Semanas 5–6 | PostgreSQL/Redis/Qdrant/S3, golden path, crash/replay, RPO/RTO | **G4** |
| **M5** | Identidade, providers e operação | Semanas 6–8 | IdP/membership, provider live, observabilidade, carga/chaos/soak | **G5** |
| **M6** | Release candidate e supply chain | Semanas 8–10 | CI remoto, imagens imutáveis, SBOM/scans/assinatura, packet, revisão | **G6** |
| **M7** | Decisão e canary readiness | Semana 10+ | `GO`/`NO-GO`, risco residual, plano de canary/rollback | **G7** |

**As janelas são relativas e indicativas.** A disponibilidade de autoridade, corpus, credenciais e ambientes externos domina o prazo. Nenhuma data deve ser prometida a partir da contagem de tarefas.

## 3. Marcos em detalhe

### M0 — Baseline e reconciliação

**Objetivo:** garantir que o estado atual seja reproduzível, que nenhum ID seja duplicado e que a adoção do programa seja um ato humano explícito.

**Entregas**
- Baseline AVAL24 vinculada ao SHA `dc79ec6`, branch e estado do worktree.
- Matriz PRD26 ↔ AUD24 ↔ PROD12 com 22 contratos, sem sobreposição de IDs.
- Confirmação de que `audit`/`shared` são reservados e de que 14 packages estão implementados.
- Publicação do plano, roadmap e backlog como `PROPOSTOS`, com links no [INDEX](INDEX.md).
- Congelamento dos comandos de evidência e da quality bar.

**Gate G0**
- Baseline reproduzível e nenhum arquivo do usuário sobrescrito.
- Nenhum contrato novo reivindica aceite existente.
- `make docs-check` e `make validate` verdes; links novos resolvem.
- Controlador intacto até PRD26-D1.

**Dependências:** nenhuma. **Contratos:** 001. **Decisão:** PRD26-D1.

**Riscos:** tratar o plano como ledger; duplicar PROD12; iniciar código antes da adoção.

---

### M1 — Aceite local e documentação

**Objetivo:** eliminar a ambiguidade “implementado, mas não aceito” e corrigir documentos correntes que descrevem um estado anterior.

**Entregas**
- Classificação de cada item AUD24/PROD12 já implementado: `DONE`, `VERIFY` com evidência ou `BLOCKED_EXTERNAL` justificado.
- Envelopes de evidência vinculados ao SHA, comando, exit code, artefato e limitação.
- Correção de `production-runtime.md`, `operations/release-readiness.md`, `roadmap-auditoria-2026-10-24.md` e `README.md` onde a evidência M0–M5 já superou o texto.
- Revisão de frescor: nenhuma afirmação atual contradiz a evidência mais recente.
- Atualização do `INDEX` com AVAL24, PRD26 e os artefatos irmãos.

**Gate G1**
- 100% dos itens locais com disposição formal; nenhum “DONE por documento”.
- `make docs-check` verde; links e citações relativas revisados.
- Nenhuma afirmação `NOT_RUN` obsoleta em documento marcado `CURRENT`.
- Revisor independente de aceite/documentação sem achado alto.

**Dependências:** M0. **Contratos:** 002, 003. **Decisão:** PRD26-D1.

**Riscos:** aceitar em bloco sem evidência; reescrever docs sem corrigir o código; criar um segundo ledger.

---

### M2 — Engenharia sustentável

**Objetivo:** provar que o candidato é reproduzível no toolchain declarado e reduzir o risco de drift entre backend, frontend e contratos.

**Entregas**
- Bootstrap em host limpo com Python 3.12.3, Node 22.19.0 e npm 10.9.3; locks por hash; `.runtime/toolchain` reproduzível.
- E2E portátil: `TMPDIR` curto e documentado; nenhum caminho dependente do host.
- mypy ampliado para rotas, services e worker, com baseline explícito e sem `ignore` genérico.
- Fonte única de contrato OpenAPI → TypeScript (geração ou validação runtime), eliminando o espelho manual de 479 linhas.
- Cobertura com denominadores explícitos; mutation testing nos caminhos críticos como advisory, sem reduzir floors.

**Gate G2**
- `make ci`, `make web-validate` e E2E verdes no toolchain declarado em host limpo.
- `make typecheck` cobre o novo escopo sem regressão.
- Contrato único falha o CI em drift; nenhum schema duplicado.
- Cobertura existente preservada; PRD26-013 é advisory e não bloqueia G2.

**Dependências:** M1. **Contratos:** 010–013. **Decisão:** nenhuma; PRD26-D3 pode fixar o perfil de provider.

**Riscos:** Node 22 indisponível; geração de tipos quebra a API; cobertura vira teatro sem mutação.

---

### M3 — IA/RAG e acessibilidade

**Objetivo:** substituir o pack sintético tautológico por uma avaliação representativa e concluir a auditoria humana de acessibilidade.

**Entregas**
- Decisão D04: corpus, proveniência, licença, labels, estratos, thresholds e risco clínico; assinatura de domínio.
- Pack representativo com casos single-hop, multi-hop, distrator, top-1 erra/top-3 recupera, abstenção real, ACL pré-filtro, claim não suportado e limite.
- Avaliação live de retrieval, citação, abstenção e claims, com modelo/provider aprovados; métricas por grupo, seeds e variância.
- Auditoria humana de teclado, leitor de tela, zoom, contraste e foco nos fluxos críticos; correções e relatório de lacunas WCAG.
- Nenhuma alegação clínica, de produção ou de `AAA` a partir do pack.

**Gate G3**
- D04 assinado e corpus com licença/proveniência verificáveis.
- Thresholds por grupo passam; abstenção e claim não suportado medidos de verdade.
- Nenhum bloqueio crítico de acessibilidade nos fluxos principais; lacunas documentadas.
- Revisor de domínio/RAG e QA/design sem achado alto.

**Dependências:** M1; pode correr em paralelo com M2. **Contratos:** 020–022. **Decisão:** PRD26-D2.

**Riscos:** corpus não aprovado; custo de provider; pack continuar tautológico; AT humano indisponível.

---

### M4 — Dados e restore

**Objetivo:** provar o plano de dados real em ambiente descartável autorizado, do upload ao restore, sem simulação.

**Entregas**
- PostgreSQL/Redis/Qdrant/S3 reais: migrations, constraints, índices, planos, queue fencing, DLQ, replay e retenção.
- Golden path de ingestão: upload → fila → lease → indexação → retrieval → delete/reindex, com crash boundaries.
- Multi-worker A/B e crash/replay; nenhuma publicação duplicada.
- Restore integrado `seed → backup → destroy → restore → rebuild → verify`, com RPO/RTO medidos.
- Evidência de tenant A/B e negativos de escopo.

**Gate G4**
- Todos os gates de dados `PASS` no mesmo artefato; nenhum `NOT_RUN` obrigatório.
- Restore verificado, checksums/counts/ACL pós-restore e RPO/RTO registrados.
- Nenhuma publicação duplicada ou perda de job nos crash points.
- Revisão de DBA/SRE sem achado alto.

**Dependências:** M1, M2. **Contratos:** 030–032. **Decisão:** PRD26-D4.

**Riscos:** ambiente indisponível; restore destrutivo sem autorização; dados de teste contaminarem produção.

---

### M5 — Identidade, providers e operação

**Objetivo:** provar identidade, provider, observabilidade e comportamento sob carga/falha em topologia real.

**Entregas**
- IdP real/OIDC ou nativo Postgres conforme PRD26-D3; membership, sessão, revogação, logout e multi-workspace.
- Duas réplicas de API com rate limiter compartilhado, isolamento tenant e negativos cross-tenant.
- Provider real ou servidor local aprovado: streaming, cancelamento, timeout, retry, circuit breaker, budget e falha.
- OTel Collector/Jaeger/Prometheus/Alertmanager: propagação de trace, redaction, métricas, alertas e burn rate.
- Worker A/B com SIGTERM, claims em voo, shutdown e teardown seguros.
- Performance 1/10/50/100, chaos e soak com budgets, sem vazamento.

**Gate G5**
- Matriz de identidade/tenant sem vazamento; revogação e logout comprovados.
- Provider com falha/cancelamento/budget e nenhum segredo em log/trace.
- Traces ponta a ponta, alertas disparam/resolvem e SLO observável.
- Performance/chaos/soak dentro dos budgets; nenhum leak; nenhum `NOT_RUN` obrigatório.

**Dependências:** M4. **Contratos:** 033, 040–043. **Decisões:** PRD26-D3, PRD26-D4.

**Riscos:** IdP indisponível; provider pago; topologia não production-shaped; soak mascarar leak.

---

### M6 — Release candidate e supply chain

**Objetivo:** transformar o candidato local em um artefato exato, remoto, verificável e revisado.

**Entregas**
- Push do candidato e execução de todos os lanes no CI remoto, no SHA exato.
- Imagens imutáveis por digest, non-root, SBOM, scan de CVE/segredo, assinatura cosign e verificação.
- Release packet com 29 seções, scorecard tipado, mapa de evidência e limitações.
- Revisão independente de arquitetura, segurança, operação e web, com contexto novo.
- Release integrity fail-closed; nenhum envelope `NOT_RUN`/`BLOCKED_EXTERNAL` no caminho obrigatório.

**Gate G6**
- Todos os lanes mandatórios `PASS` no mesmo SHA; nenhuma evidência local-only.
- Imagens assinadas e verificadas; scans sem achado alto; SBOM e rollback disponíveis.
- Packet completo, links válidos e nenhum achado alto de revisão.
- `make release-evidence` e `release_integrity --require-clean` avaliados com o artefato exato.

**Dependências:** M3, M5. **Contratos:** 050–052. **Decisão:** PRD26-D5.

**Riscos:** CI remoto divergir; scan bloquear release; packet incompleto; assinatura/credencial indisponível.

---

### M7 — Decisão e canary readiness

**Objetivo:** obter decisão humana explícita sobre o artefato exato e preparar a operação pós-GO sem executá-la.

**Entregas**
- Dossiê de decisão: gates, riscos residuais, limitações, custos, SLO e plano de rollback.
- Decisão `GO` ou `NO-GO` assinada pela autoridade competente.
- Se `GO`: plano de canary, métricas de aborto, rollback/roll-forward e janela autorizada — **não executados** neste marco.
- Se `NO-GO`: disposição de cada bloqueio e retorno ao marco pertinente.

**Gate G7**
- Nenhum gate mandatório `FAIL`/`NOT_RUN`/`BLOCKED_EXTERNAL` sem disposição aceita.
- Nenhum achado alto aberto; risco residual aceito por autoridade.
- Decisão registrada e vinculada ao SHA/digest exato.
- Canary só com autoridade, janela e orçamento próprios.

**Dependências:** M6. **Contratos:** 053. **Decisão:** PRD26-D6.

**Riscos:** pressão por `GO` sem evidência; canary virar deploy não autorizado; risco residual não assinado.

---

## 4. Sequência e paralelismo

```text
M0 [G0]
 ├─ M1 (aceite/docs) [G1]
 │    ├─ M2 (engenharia) [G2] ─────────────┐
 │    └─ M3 (RAG/AT) [G3] ────────────────┤
 │                                         ▼
 │                                   M4 (dados/restore) [G4]
 │                                         ▼
 │                                   M5 (identidade/provider/operação) [G5]
 │                                         ▼
 │                                   M6 (release/supply chain) [G6]
 │                                         ▼
 └─────────────────────────────────── M7 (decisão) [G7]
```

**Paralelismo seguro:** M2 e M3 têm arquivos e autoridades disjuntos; M4 pode preparar fixtures/runbooks enquanto M3 corre, mas o aceite exige D04 e autorização. M5 não começa sem M4. M6 não começa sem M3 e M5. M7 não começa sem M6.

## 5. Portões externos herdados (sem duplicar IDs)

Estas obrigações permanecem nos IDs herdados; o PRD26 apenas sequencia, vincula evidência e aceita.

| Faixa herdada | Conteúdo | Relação PRD26 |
|---|---|---|
| AUD24-001–003 | Baseline, B01, reconciliação | M0 reutiliza; 001 dá delta |
| AUD24-010–018 | Identidade e auditoria | M1/M5 reutilizam; 040 dá delta de IdP real |
| AUD24-020–025 | Recuperação web | M1/M3 reutilizam; 022 dá delta de AT |
| AUD24-030–034 | CONTRACT, candidato, toolchain, VPS, CI remoto | M2/M6 reutilizam; 010/050 dão delta |
| AUD24-040–045 | Docs, contrato, tipos, cobertura, RAG, AT | M1–M3 reutilizam; 003/011/012/013/020/022 dão delta |
| PROD12-001–006 | Governança, baseline, perfil, budgets, inputs | M0/M1 reutilizam |
| PROD12-007–014 | Logout, shutdown, limiter, CSRF | M5 reutiliza; sem delta de código |
| PROD12-015–026 | Candidato local, toolchain, tipos, cobertura, web | M1/M2 reutilizam |
| PROD12-027–032 | Topologia, imagens, lab, PostgreSQL, Redis, S3/Qdrant | M4 herda integralmente |
| PROD12-033–040 | Provider, golden path, identidade, workers, arquivos hostis, RAG, evidência, casos | M4/M5 herdam |
| PROD12-041–049 | Browser/AT, revisão, observabilidade, auditoria, restore, performance, chaos, soak, runbooks | M5/M6 herdam |
| PROD12-050–053 | CI remoto, reviews, packet, decisão | M6/M7 herdam |
| PROD12-054–056 | Canary, expansão, operação | Pós-G7; fora deste roadmap |

## 6. Política de evidência e definição de pronto

### Pronto localmente — G2

- Candidato identificado por SHA + worktree + fingerprint.
- Comandos completos, exit codes, artefatos e hashes.
- Teste que falha na versão antiga e passa na corrigida.
- Nenhum gate enfraquecido; nenhum `NOT_RUN` convertido em `PASS`.
- Documentação corrente e links válidos.

### Pronto para decisão de produção — G7

- Todos os gates G0–G6 `PASS` no mesmo artefato.
- Runtime externo, restore, performance, chaos, soak, identidade, provider, observabilidade e supply chain com evidência vinculada.
- RAG representativo e acessibilidade humana com lacunas explícitas.
- Release packet revisado por contexto independente.
- Riscos residuais aceitos por autoridade; decisão `GO`/`NO-GO` registrada.

## 7. Indicadores de progresso (não substitutos de gate)

| Indicador | Baseline AVAL24 | Alvo indicativo |
|---|---:|---:|
| Nota AVAL24 | 78,0 | ≥ 85 (indicativo) |
| Itens `DONE` no controlador | 8 de 117 | 100% dos adotados |
| Itens P0 `TODO`/`IN_PROGRESS` | 26 | 0 |
| mypy — roots cobertos | 14 (AVAL24) → 19 (onda 1) | rotas + services + worker |
| API statements/branch | 79,27 / 75,65 | manter ou subir |
| Worker lines/branch | 79,58 / 75,93 | manter ou subir |
| Web lines/branches | 91,95 / 80,49 | manter ou subir |
| E2E produção | 363/363 | manter 363/363 |
| Gates externos `PASS` | 4 famílias de dados (evidência) | todos os mandatórios |
| CI remoto no SHA exato | `NOT_RUN` | `PASS` |

## 8. Critérios de parada

O roadmap para e retorna `NO-GO` se:

- a baseline não for reproduzível ou o aceite local não tiver evidência;
- D04/corpus não for aprovado ou o pack continuar tautológico;
- qualquer gate de dados/identidade/provider/restore/observabilidade/carga permanecer `NOT_RUN`/`BLOCKED_EXTERNAL` sem disposição;
- o CI remoto não executar o SHA exato ou o release packet estiver incompleto;
- houver achado alto de revisão independente sem correção;
- houver tentativa de converter skip, mock, média ou documento em `PASS`;
- não houver decisão humana para risco residual ou `GO`.

## 9. Próxima decisão

**PRD26-D1 — adotar o programa no controlador e definir a autoridade de aceite.** Sem essa decisão, os 22 contratos permanecem `PROPOSTOS`, nenhum item vira `DONE` e o produto continua `NO-GO`.
