# Plano executivo — RICK Intelligence Triplo AAA

**Data-base:** 2026-09-07
**Status:** proposta operacional baseada na auditoria atual
**Objetivo:** promover o RICK Intelligence de uma plataforma local hermética
  para um produto multi-tenant de produção, com qualidade State of Art e uma
  barra Triplo AAA verificável.

Documentos relacionados:

- [Relatório de auditoria](../reports/relatorio-auditoria-state-of-art-2026-09-07.md)
- [Roadmap Triplo AAA](triplo-aaa-roadmap-2026-09-07.md)
- [Backlog Triplo AAA](triplo-aaa-backlog-2026-09-07.md)
- [Plano executivo anterior](state-of-art-executive.md)

## 1. North Star

Entregar respostas úteis, seguras e explicáveis sobre conhecimento autorizado,
com ingestão durável, isolamento forte de tenant, operação observável e uma web
acessível. O produto só pode declarar promoção quando o comportamento for
demonstrado na topologia-alvo; um mock determinístico verde é evidência local,
não evidência de produção.

## 2. Definição do Triplo AAA

Triplo AAA é uma barra interna de qualidade, não uma certificação externa.
Cada “A” possui critérios obrigatórios e evidência própria.

### A1 — Accuracy & Trust

Respostas e resultados devem ser corretos dentro do corpus autorizado,
reproduzíveis e honestos sobre incerteza.

Critérios propostos:

- leakage cross-tenant: **0**;
- claims sem suporte no golden set: **0**;
- cobertura de citações para claims apoiados: **100%** no conjunto aprovado;
- resposta sem evidence suficiente: estado explícito `NO_EVIDENCE`/`WEAK_EVIDENCE`;
- recall, hit@k, freshness e latência com thresholds aprovados pelo owner de
  produto antes do corpus final;
- checksum, página, documento e escopo preservados da ingestão até a UI.

### A2 — Accessibility & Experience

O produto deve ser compreensível, navegável e recuperável por diferentes perfis,
dispositivos e modos de interação.

Critérios propostos:

- WCAG AA como alvo de produto, com teclado, foco visível, contraste, zoom,
  reflow, reduced motion e leitor de tela verificados;
- 375, 768 e 1440 px sem overflow ou perda da ação principal;
- loading, empty, forbidden, network error, stale data e success distintos;
- zero finding Critical/High aberto na revisão visual independente;
- score visual mínimo **95/100** para o pacote aplicável;
- nenhum texto de confiança, aprovação clínica ou health externo fabricado.

### A3 — Availability & Operations

O sistema deve sobreviver a falhas previsíveis, reinícios, crescimento e
intervenção operacional sem perder escopo, dados ou auditabilidade.

Critérios propostos:

- upload e job idempotentes, duráveis e recuperáveis após restart;
- retry finito, dead-letter, backpressure, cancellation e leases owner-safe;
- readiness distinguindo dependência required, optional, degraded e `no_data`;
- logs, métricas e traces bounded, redacted e correlacionáveis;
- RPO inicial proposto: 15 minutos; RTO inicial proposto: 60 minutos;
- disponibilidade inicial proposta: 99,9% mensal, sujeita à aprovação de produto
  e operações;
- backup/restore, canary, rollback e drills executados antes da promoção.

Se qualquer critério obrigatório falhar, a nota numérica não compensa a falha:
o gate permanece `PARTIAL`, `BLOCKED` ou `FAIL`.

## 3. Baseline atual

| Dimensão | Estado observado |
| --- | --- |
| Construção local | 81/100; API, packages, RAG, ingestão, Professor, worker local e web funcionais |
| Produção | 55/100; spine externo, identidade e operação live não demonstrados |
| Matriz principal | `api14-full` 477 PASS; `api16-full` 455 PASS; `api15-full` falha no benchmark |
| Web | 219/225 E2E, 108/108 visuais, 6 skips planejados |
| Ambiente externo | Docker e serviços externos indisponíveis nesta observação |
| Release | sem `docs/progress/release-evidence.json`; checkout dirty |

O primeiro bloqueio é [GAP-AAA-001](../reports/relatorio-auditoria-state-of-art-2026-09-07.md#gap-aaa-001--benchmark-phase-15-quebrado).

## 4. Objetivos executivos

### O1 — Tornar a evidência confiável

Corrigir a matriz Phase 1.5, reconciliar artefatos de performance e manter uma
fonte única para status, requisitos, evidência e gaps.

**Resultado:** gates locais verdes, artefatos atuais e nenhum PASS histórico
  tratado como evidência vigente.

### O2 — Construir o spine durável

Promover conhecimento, jobs, auditoria, objetos, vetores, leases e provider para
adapters externos injetáveis e testados na topologia alvo.

**Resultado:** upload → queue → worker → index → retrieval → chat → delete/reindex
  sobrevive a restart e falha sem perder isolamento.

### O3 — Fechar segurança de identidade e escopo

Integrar identidade externa, revogação, roles, tenant derivado da sessão,
rate-limit apropriado e matriz negativa completa.

**Resultado:** nenhum header ou parâmetro do cliente amplia autorização; produção
  falha fechada quando a identidade não é segura.

### O4 — Entregar inteligência confiável

Versionar corpus aprovado, golden queries, thresholds, freshness, avaliação live,
grounded generation e fila de revisão humana.

**Resultado:** quality gate reproduzível para retrieval e respostas, com
  unsupported-claim negatives e feedback auditável.

### O5 — Fechar a experiência Triplo AAA

Concluir estados web, tenant switcher, operações de corpus, evidence drawer,
acessibilidade e integração com API real.

**Resultado:** produto utilizável por veterinário, knowledge manager e admin sem
  confundir vazio, indisponível, proibido ou não confirmado.

### O6 — Operar e promover com segurança

Entregar observabilidade, SLO, alertas, backup/restore, performance, compose,
canary, rollback e critic final.

**Resultado:** release candidate reproduzível, reversível e com evidência fresca.

## 5. Arquitetura alvo

```text
Browser / API clients
          |
     Edge + Web
          |
  FastAPI root + policy middleware
          |
  OIDC session + authorization snapshot
          |
  Domain services / contracts
    |       |        |        |
 Postgres  Object   Queue   Audit/Telemetry
 catalog   store    worker  collector
    |       |        |        |
 Qdrant vector read model -- Redis leases
          |
   Provider externo resiliente
```

Regras de composição:

- o cliente sugere escopo; a sessão e a política server-side decidem;
- stores, queue, object store, provider e lease entram por contratos injetados;
- nenhum adapter live conecta durante import;
- local/test permanece reproduzível, mas é marcado como `local` e nunca promove
  evidência de produção;
- children legados continuam preservados até equivalência e rollback serem
  demonstrados;
- o caminho de resposta mantém evidence, confidence, citation e failure state
  explícitos até a UI.

## 6. Modelo de governança

| Papel | Responsabilidade |
| --- | --- |
| Product owner | corpus, personas, thresholds, SLO/RTO/RPO e decisões de valor |
| Security owner | OIDC, tenant isolation, threat model, secrets e aprovação de risco |
| Domain builder | knowledge, ingestion, schemas, migrations e idempotência |
| Platform builder | Postgres, object, queue, Qdrant, Redis e provider live |
| Web/design owner | UX, accessibility, visual QA e estados de recuperação |
| Ops/release owner | observabilidade, backup, drills, canary, rollback e evidence packet |
| Integration reviewer | verifica composição e regressões sem ser o builder principal |
| Final critic | julga o pacote completo contra o Quality Bar congelado |

Decisões materiais não devem ser inferidas pelo agente: IdP, corpus/licença,
topologia de deploy, fornecedor de object/queue, SLO e política de retenção
precisam de owner humano.

## 7. Definition of Done do programa

O programa só pode ser declarado `RELEASE_READY` quando:

- todos os gates P0 do [roadmap](triplo-aaa-roadmap-2026-09-07.md) tiverem PASS
  atual;
- `api15-full`, `api16-full`, segurança, contrato, retrieval e web estiverem
  verdes no mesmo candidate revision;
- integração live descartável comprovar health, ACL, timeout, retry, cleanup e
  shutdown;
- OIDC, Postgres, object, queue, worker, Qdrant, Redis e provider estiverem
  presentes no composition root de produção;
- corpus e thresholds estiverem aprovados e versionados;
- WCAG/visual/manual, backup/restore, RTO/RPO, load/soak e canary/rollback
  tiverem evidência atual;
- não houver Critical/High aberto sem autoridade explícita de aceite;
- release evidence, fingerprint, manifest, reviewers e limitações estiverem
  sincronizados;
- o pacote final não afirmar mais do que foi executado.

## 8. Sequência de investimento

1. Reparar evidência local e remover o bloqueio do benchmark.
2. Fechar decisões humanas de identidade, corpus, SLO e topologia.
3. Construir o spine externo em uma fatia vertical de upload até resposta.
4. Executar negativos de segurança e drills de restart/falha.
5. Aprovar qualidade de retrieval e grounding contra corpus real.
6. Fechar web AAA e integração sem mocks.
7. Fechar operações, performance e promoção reversível.

O detalhamento por gates está no [roadmap](triplo-aaa-roadmap-2026-09-07.md) e
as unidades executáveis estão no [backlog](triplo-aaa-backlog-2026-09-07.md).
