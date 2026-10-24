# Roadmap AUD24 — oito marcos até um candidato promovível

**Data:** 24/10/2026 (America/Sao_Paulo). **Estado:** `PLANEJAMENTO PROPOSTO`. **Produção:** `NO-GO`.
**Baseline:** [auditoria AUD24](<reports/relatorio-auditoria-2026-10-24.md>) — 74,7/100.
**Documentos relacionados:** [plano executivo](<plans/execplan-aud24-2026-10-24.md>) e [backlog](<backlog-auditoria-2026-10-24.md>).
**Regra:** este roadmap não é ledger de execução, não adota tarefas no [controlador](<../.agent/backlog.json>) e não autoriza serviços externos, DDL real, deploy ou promoção. **AUD24-D1 ratificada:** [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>) — A+ em duas etapas; OIDC fora do perfil de produção.
**Status local em 24/10/2026:** M0/G0 `PASS`; M1 etapas 1–2 + 013–018 (live PG/IdP `NOT_RUN`); M2 020–025 (E2E `NOT_RUN`); M3 CONTRACT verde, candidato sujo (031/034 abertos); M4 040/042, 043 em medição, 041/044/045 pendentes; M5–M7 `BLOCKED_EXTERNAL` com [pacote preparado](operations/aud24-m5-m7-external-package.md).

## 1. Objetivo e ponto de partida

Converter os **12 achados AUD24** em correções demonstráveis, recuperar uma cadeia de release reproduzível e executar as provas externas já especificadas antes de qualquer decisão de promoção.

O ponto de partida é um produto local substancial — 61 rotas, worker durável, 14 packages, 9 páginas web, 10 migrations, 6.018 testes Python aprovados e 258 testes web — com **seis achados altos abertos (P1 no relatório)**, **worktree sujo** e **obrigações externas `NOT_RUN`**. A nota 74,7 não é meta; é diagnóstico. O objetivo não é subir a média, é fechar gates.

**Princípio:** corrigir o que falha, preservar o que já tem prova e obter o que ainda não foi executado. Não é proposta de reescrita, troca de provider ou aumento artificial de nota.

## 2. Visão dos oito marcos

| Marco | Nome | Janela indicativa | Resultado | Gate de saída |
|---|---|---|---|---|
| **M0** | Baseline e decisão | Semana 1 | Baseline preservada, escopo reconciliado, contrato do B01 ratificado | **G0** |
| **M1** | Identidade e auditoria | Semanas 1–2 | Reset/logout/audit/OIDC/sessão com efeito e confirmação honestos | **G1** |
| **M2** | Recuperação web | Semanas 2–3 | Chat, casos e documentos sem perda silenciosa; 403/abort/outage distintos | **G2** |
| **M3** | CI, release e ambiente | Semanas 3–4 | Candidato limpo, lane CONTRACT verde, toolchain 22/10, release evidence válida | **G3** |
| **M4** | Qualidade e documentação | Semanas 4–5 | Docs alinhados, contrato único, tipos/cobertura ampliados, RAG e acessibilidade avaliados | **G4** |
| **M5** | Runtime externo I — dados | Semanas 5–6 | PostgreSQL/Redis/Qdrant/S3, migrations, ingestão E2E e restore reais | **G5** |
| **M6** | Runtime externo II — identidade e operação | Semanas 6–7 | IdP, providers/RAG, observabilidade, carga/chaos/soak e browser real | **G6** |
| **M7** | Release candidate e decisão | Semana 8 | Packet, revisão independente e decisão humana | **G7** |

**As janelas são relativas e indicativas.** A disponibilidade de autoridade/ambiente externo domina o prazo; nenhuma data deve ser prometida a partir da contagem de tarefas.

## 3. Marcos em detalhe

### M0 — Baseline e decisão

**Objetivo:** garantir que o trabalho existente não se perca e que a decisão mais cara do programa seja tomada antes de código.

**Entregas**
- Patch/manifesto do worktree atual com hashes, checkpoint e procedimento de recuperação.
- Matriz de reconciliação AUD24 ↔ AUD15 ↔ PROD12, sem IDs duplicados.
- ADR do contrato de auditoria do B01 (outbox + reconciliador, fence, ou semântica indeterminada explícita).
- Quality bar AUD24 congelada: comandos, gates, evidências e critérios de parada.

**Gate G0**
- Baseline reproduzível e nenhum arquivo do usuário sobrescrito.
- Nenhum contrato novo reivindica aceite existente.
- Decisão do B01 registrada com autoridade no [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>); M1 usa o contrato A+ em duas etapas.
- Barra e comandos congelados **antes** de mudança funcional.

**Dependências:** nenhuma. **Contratos:** 001, 002, 003.

**Riscos:** perder alterações não commitadas; iniciar correções antes da decisão e cristalizar um contrato errado.

---

### M1 — Identidade e auditoria

**Objetivo:** tornar reset, logout e auditoria semanticamente honestos e recuperáveis, sem depender de disponibilidade de sink para o efeito de segurança.

**Entregas**
- Reset: separação entre efeito e confirmação; auditoria idempotente da efetivação; resultado indeterminado com `request_id`, conforme [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>).
- Logout: revogação não bloqueada por indisponibilidade de auditoria; semântica explícita para 503 com efeito aplicado.
- Auditoria: máquina de estados terminal, unicidade `(action, request_id, status)`, idempotência e reconciliador de eventos órfãos.
- OIDC: porta de revogação/broker exigida na composição **ou** declaração explícita de “sem logout”, sem manter cookie enganoso.
- Login resistente a timing; `access_denied` nunca silencioso; expiração absoluta de sessão; multi-workspace resolvido.
- Schema de auditoria unificado e tipado; nenhuma terceira linguagem de evento.

**Gate G1**
- AUD24-01/02/03 e 07–10 fechados com teste que falha na versão antiga.
- Nenhum `completed` após resposta abandonada; nenhum `requested` órfão sem disposição.
- Revisão independente de identidade/auditoria sem achado alto.
- Nenhum achado alto de auth/audit aberto.

**Dependências:** M0 (decisão do B01). **Contratos:** 010–018.

**Riscos:** complexidade do outbox; corrida entre commit e confirmação; tentação de “resolver” o B01 removendo o teste — proibido.

---

### M2 — Recuperação web

**Objetivo:** eliminar perdas silenciosas de ação e estados permanentes no web, mantendo a política fail-closed.

**Entregas**
- Chat: “Nova conversa” durante abertura não deixa composer morto; aborto externo não deixa spinner permanente; retry explícito.
- Casos: 403 é negação, não outage; detalhe proibido não apaga a lista; retry só quando legítimo.
- Documentos: paginação com dedupe, validação de cursor e trava de requisição; estado parcial anunciado.
- Corrida de auto-abertura da primeira conversa corrigida.
- Decisão de UX offline ratificada e refletida em teste, sem mascarar regressão.
- Mapeamento de erro único para 401/403/409/abort/outage.

**Gate G2**
- AUD24-04/05/11 fechados; unit e E2E dos fluxos em 375/768/1440.
- Nenhum caminho em que Enter não produz envio, erro ou retry visível.
- 403/abort/outage distinguidos em chat, casos e documentos.
- Nenhuma regressão de acessibilidade de foco.

**Dependências:** pode iniciar em paralelo a M1; aceite após M1 estável. **Contratos:** 020–025.

**Riscos:** dois writers no mesmo arquivo de chat; corrigir UI mascarando contrato; E2E instável.

---

### M3 — CI, release e ambiente

**Objetivo:** transformar o worktree em um candidato reproduzível e fazer o CI refletir a verdade.

**Entregas**
- Lane CONTRACT verde, incluindo `make api-coverage` e o B01.
- Candidato commitado/revisado, checkout limpo, fingerprint e release evidence válidos.
- Toolchain Node 22.19/npm 10.9 reproduzível; testes web portáveis (`TMPDIR`).
- Executor VPS representativo (UID/GID/namespace) ou bloqueio explícito, sem alterar DAC do host.
- CI remoto executado e evidência vinculada ao SHA.
- Scans de dependência/imagem, SBOM e assinatura no escopo autorizado.

**Gate G3**
- `make validate`, núcleo Python, API/worker coverage, lint, typecheck, build, web unit e E2E verdes no mesmo candidato.
- Zero teste conhecido falhando; lane CONTRACT verde.
- Worktree limpo; release evidence não rejeitada por sujeira/stale.
- Nenhuma prova histórica reutilizada como atual.

**Dependências:** M1 (B01) e M2 (web). **Contratos:** 030–034.

**Riscos:** instabilidade de lanes; Node indisponível; tentação de excluir teste do lane; release evidence gerada antes das últimas mudanças.

---

### M4 — Qualidade e documentação

**Objetivo:** alinhar documentação, contratos, tipos e denominadores ao candidato real.

**Entregas**
- Correção dos três docs divergentes (CSRF, web, README/INDEX) e registro AUD24.
- Fonte única de contratos web/backend ou teste de drift que falhe no CI.
- Tipagem ampliada para caminhos de risco da API/worker; cobertura com branch measurement em Python.
- Pack de avaliação RAG ampliado e estratificado, com limitações explícitas.
- Auditoria de acessibilidade/AT (não só axe) e registro de lacunas.

**Gate G4**
- `docs-check`/`make validate` sem links quebrados e sem divergência conhecida nas autoridades.
- Nenhuma duplicação silenciosa de schema; teste de drift rejeita mudança não registrada.
- Floors de cobertura não reduzidos; denominadores declarados.
- RAG avaliado com corpus/labels aprovados, não apenas 2 casos sintéticos.
- Achados de acessibilidade com disposição, não “WCAG certificado” sem prova.

**Dependências:** M3 (candidato estável). **Contratos:** 040–045.

**Riscos:** documentação como tarefa infinita; ampliar tipos sem cobrir caminhos reais; pack RAG depender de autoridade de domínio.

---

### M5 — Runtime externo I — dados

**Objetivo:** provar o caminho de dados real, não o mock.

**Entregas**
- PostgreSQL descartável: migrations, constraints, fila, lease/version, crash/replay, DLQ, retenção.
- Redis autenticado: namespace, rate limit compartilhado, failover/reconnect.
- Qdrant: coleções versionadas, ACL, alias/rebuild, delete/restore.
- S3-compatible: PUT/HEAD/GET/DELETE, checksum, retenção, credenciais e TLS.
- Ingestão E2E: upload → fila → parse → index → retrieve → delete/reindex.
- Restore integrado: seed → backup → destroy → restore → rebuild → verify, com RPO/RTO medidos.

**Gate G5**
- Tenant A/B e negativos de isolamento reais.
- Checksums, contagens e ACL conferidos após restore.
- Nenhum fallback local usado como prova de store real.
- RPO/RTO dentro do budget aprovado; nenhuma perda/duplicação silenciosa.

**Dependências:** M3 + AUD24-D4 (recursos/autoridade). **Herança:** PROD12 (stores, migrações, restore, golden path).

**Riscos:** ambientes indisponíveis; custo; dados sintéticos insuficientes; executar DDL sem autorização.

---

### M6 — Runtime externo II — identidade e operação

**Objetivo:** provar identidade, provider, observabilidade e comportamento sob falha/carga.

**Entregas**
- IdP/sessão real: login, logout, revogação, membership, outage, multiaba, tenant A/B.
- Provider real aprovado: capability, streaming, cancelamento, retry, citação, budget e custo.
- OTel Collector/Jaeger/Prometheus/alert sink: propagação, redação, agregação, alertas e burn rate.
- Performance production-shaped: p50/p95/p99, throughput, erros, memória, fila e custo.
- Chaos/soak: crash, latência, partição, dependência lenta, retry storm, vazamento.
- Browser real com API real: 403/401/offline/multiaba, teclado, leitor de tela e visual.

**Gate G6**
- Nenhum `NOT_RUN` obrigatório oculto; skips vinculados a gate/tarefa.
- Negativos de autorização e falha observados, não inferidos.
- Budgets e abortos definidos **antes** da execução.
- Relatório de performance/chaos com limites e riscos residuais.

**Dependências:** M5 + AUD24-D4. **Herança:** PROD12 (identidade, providers, observabilidade, carga/chaos/soak, browser).

**Riscos:** custo de provider; corpus/direitos; ambiente de carga compartilhado; fadiga de evidência.

---

### M7 — Release candidate e decisão

**Objetivo:** congelar um artefato único e submetê-lo a revisão e decisão independentes.

**Entregas**
- Packet de release: manifesto, digests, SBOM, scans, assinatura, evidências, riscos residuais.
- Revisão independente final (arquitetura, segurança, dados, web/ops) sem racional dos builders.
- Scorecard AUD24 atualizado por reavaliação, não por cópia da nota antiga.
- Decisão humana `GO`/`NO-GO` para o artefato exato.

**Gate G7**
- Todos os gates mandatórios PASS e frescos, vinculados ao mesmo SHA/config/digests.
- Nenhum achado alto/médio do relatório sem disposição; risco residual aceito pela autoridade.
- Nenhuma mudança posterior invalida a evidência; se houver, repetir os gates afetados.
- `NO-GO` é o default; `GO` exige decisão explícita.

**Dependências:** M4, M5, M6. **Contratos:** 034 + herança PROD12.

**Riscos:** pressão para promover; packet incompleto; revisão tardia; mudança de última hora.

---

## 4. Sequência e paralelismo

```text
M0 [G0]
 ├─ M1 (identidade/auditoria) ─┐
 ├─ M2 (web) ──────────────────┤
 └─ M4 preparação (docs) ──────┘
        ↓
M3 [G3] candidato limpo + lanes verdes
        ↓
M4 [G4] qualidade/documentação
        ↓
M5 [G5] dados reais
        ↓
M6 [G6] identidade/providers/operação
        ↓
M7 [G7] packet + revisão + decisão
```

**Paralelismo seguro:** M1 e M2 têm donos e arquivos disjuntos; M4 pode preparar docs enquanto M1/M2 rodam, mas seu aceite depende de M3. M5/M6 podem ter preparação antecipada (fixtures, runbooks, autorizações), mas execução/aceite respeita autoridade e predecessores.

**Não paralelizar:** dois writers em `auth.py`, `chat-workspace.tsx`, migrations de auditoria ou workflows; execução de ensaios destrutivos que compartilhem o mesmo namespace.

## 5. Portões externos herdados (sem duplicar IDs)

Estas obrigações já existem no [backlog PROD12](<backlog-producao-2026-10-12.md>) e no [plano ativo](<../.agent/plans/producao-2026-10-12.md>). O AUD24 não as renumera, não as aceita e não as declara cumpridas por analogia.

| Fronteira | O que precisa ser provado | Marco | Autoridade |
|---|---|---|---|
| Imagens/topologia | Build, digest, non-root, hardening, compose production-shaped | M5/M6 | Plataforma/segurança |
| PostgreSQL/fila | Migrations, constraints, lease/version, crash/replay, DLQ | M5 | D02 + operador |
| Redis/rate limit | Namespace, TLS/auth, failover, limite compartilhado | M5 | D02 |
| Qdrant | ACL, alias/rebuild, delete/restore, consistência | M5 | D02 |
| Objeto | Checksum, imutabilidade, retenção, credenciais | M5 | D02 |
| Identidade | IdP/membership/revogação/outage/multiaba | M6 | D03/D04 |
| Provider/RAG | Modelo, dimensão, custo, corpus, thresholds, citação | M6 | D04 |
| Observabilidade | Propagação, redação, métricas, alertas, burn rate | M6 | SRE |
| Restore/DR | RPO/RTO, consistência, tenant pós-restore | M5 | D05 |
| Performance/chaos/soak | Budgets, carga, falhas, vazamento, recuperação | M6 | SRE/produto |
| Browser/AT | API real, 375/768/1440, teclado, leitor de tela | M6 | QA/design |
| Supply chain/release | SBOM, scans, assinatura, canary/rollback | M7 | Segurança/release |
| Revisão final | Contexto novo, artefato exato, sem builder bias | M7 | D07 |

## 6. Política de evidência e definição de pronto

### Pronto localmente — G3

- Mesmo candidato, config e toolchain efetiva; executor VPS representativo.
- Gates estáticos, núcleo, cobertura, lint, tipos, build, web unit e E2E aplicável aprovados.
- Nenhum teste conhecido falhando; lane CONTRACT verde.
- Os defeitos antigos são rejeitados pelos novos testes, não apenas “cobertos”.
- Skips externos permanecem explicitamente vinculados aos gates de M5/M6; isso não permite G7.

### Pronto para decisão de produção — G7

Aplicam-se [integridade de release](<architecture/release-integrity.md>), [autoridade de promoção](<architecture/promotion-authority.md>) e a barra congelada vigente.

- Todos os gates mandatórios do perfil satisfeitos, com prova atual e mesmo artefato/config/digests.
- Nenhum `FAIL`, `NOT_RUN`, `STALE` ou skip obrigatório oculto.
- Stores/identidade/providers reais aplicáveis, tenant/worker negativos, segurança, domínio e observabilidade demonstrados.
- Restore/capacidade/resiliência medidos; runbooks, owners e rollback disponíveis.
- Scans/SBOM/assinatura/revisões e decisão humana independente; builder não aprova o próprio release.
- Mudança após teste invalida a prova afetada; não rejuvenescer timestamps nem reutilizar evidência de outro artefato.

## 7. Indicadores de progresso (não substitutos de gate)

| Indicador | Baseline AUD24 | Alvo local (G3) | Alvo externo (G6) |
|---|---:|---:|---:|
| Achados altos (P1 no relatório) abertos | 6 | 0 | 0 |
| Testes conhecidos falhando | 1 | 0 | 0 |
| Lane CONTRACT | FAIL | PASS | PASS |
| Worktree | 109 entradas | 0 | 0 |
| Cobertura API | 79,42% | ≥ 79,42%, sem reduzir floor | medida no candidato final |
| Cobertura worker | 80,11% | ≥ 80,11% | medida no candidato final |
| Web linhas | 90,65% | ≥ 90,65%, sem reduzir floor | medida no candidato final |
| Evidência externa | `NOT_RUN` | preparada | executada |
| Nota indicativa | 74,7 | ≥ 82 | ≥ 85 e gates PASS |

A nota é indicativa. Um número maior com um gate obrigatório aberto continua `NO-GO`.

## 8. Critérios de parada

- Decisão do B01 não ratificada até o fim de M0.
- Qualquer achado alto aberto ou teste conhecido falhando em G3.
- Lane CONTRACT ou gate local obrigatório vermelho.
- Candidato não commitável, evidência não reproduzível ou release evidence rejeitada.
- Prova externa obrigatória indisponível sem disposição/autoridade.
- Revisão independente com achado alto sem correção.
- Tentativa de converter skip, mock, média ou documento em PASS.

## 9. Próxima decisão

**AUD24-D1 — contrato do B01.** É a decisão que destrava o caminho crítico. Recomendação técnica: **outbox de auditoria idempotente com reconciliador**, porque preserva o efeito de segurança, permite resposta honesta de resultado indeterminado e elimina a classe de `completed` após 503 sem exigir que um sink síncrono arbitrário implemente fencing. A decisão final é humana e deve ser registrada antes de M1.
