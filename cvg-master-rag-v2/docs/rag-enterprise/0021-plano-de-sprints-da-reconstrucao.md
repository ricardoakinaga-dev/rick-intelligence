# 0021 — Plano de Sprints da Reconstrução

## Objetivo

Registrar o plano da reconstrução principal da Fase 0. Este documento permanece como referência histórica da rodada maior que reconstruiu o baseline.

---

## Status Deste Documento

### Leitura correta

- Este plano descreve a **reconstrução principal** já executada
- Ele continua útil para entender a ordem e a lógica da rodada original
- Ele **não é mais o plano operacional corrente**

### Plano operacional vigente

Para a execução atual, usar:

- `0015-roadmap-executivo.md`
- `0016-backlog-priorizado.md`
- `0020-master-execution-log.md`
- `0022-plano-da-rodada-complementar.md`

---

## O Que Este Documento Ainda Explica Bem

- por que a Fase 0 precisou ser reaberta
- como a reconstrução principal foi decomposta em sprints
- quais problemas estruturais existiam no baseline antigo

## O Que Este Documento Não Deve Ser Usado Para Decidir Sozinho

- status atual dos sprints
- decisão de Gate F0
- sequência operacional da rodada corrente

---

## Resumo da Reconstrução Principal

```text
Sprint 0 ─► Sprint 1 ─► Sprint 2 ─► Sprint 3 ─► Sprint 4 ─► Sprint 5
Contratos    Ingestão     Vetores      Query/LLM    Avaliação    Hardening
e dados      e chunks     retrieval    grounding    telemetria   gate rehearsal
```

Essa decomposição continua válida como mapa conceitual da reconstrução.

---

## Encaminhamento Atual

Depois da reconstrução principal, a auditoria mais recente concluiu que ainda restam pendências objetivas de fechamento:

- limpeza da suíte principal
- convergência de scripts auxiliares ao contrato final
- consolidação do corpus canônico em disco
- rodada final de evidência para Gate F0

Por isso, a execução corrente foi movida para a rodada complementar.

---

## Próximo Passo

Executar `0022-plano-da-rodada-complementar.md`.
