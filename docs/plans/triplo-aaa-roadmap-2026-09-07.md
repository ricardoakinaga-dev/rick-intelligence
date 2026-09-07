# Roadmap — RICK Intelligence Triplo AAA

**Data-base:** 2026-09-07
**Modelo:** roadmap orientado por gates, não por datas artificiais.
**Regra:** cada estágio produz comportamento demonstrável ou evidência de
  promoção; “em desenvolvimento” não é gate.

Documentos relacionados:

- [Plano executivo](triplo-aaa-executive-plan-2026-09-07.md)
- [Backlog](triplo-aaa-backlog-2026-09-07.md)
- [Auditoria](../reports/relatorio-auditoria-state-of-art-2026-09-07.md)

## 1. Visão dos estágios

| Estágio | Objetivo | Estado de entrada | Gate de saída |
| --- | --- | --- | --- |
| R0. Integridade | Tornar a evidência local confiável | `api15` quebrado | G0 LOCAL PASS; Phase 1.5/1.6 reproduzíveis |
| R1. Spine durável | Tirar o root do modo local/process-local | SQLite e adapters herméticos | G1 PASS: persistência, objetos, queue, worker e recovery live |
| R2. Segurança de produção | Fechar identidade e escopo externo | identidade local/dev | G2 PASS: OIDC, RBAC, tenant negatives e secrets |
| R3. Inteligência AAA | Provar qualidade semântica e grounding | fixture offline | G3 PASS: corpus, thresholds, retrieval e Professor live |
| R4. Experiência AAA | Fechar web, acessibilidade e integração | web local aprovada | G4 PASS: web real, WCAG AA e estados completos |
| R5. Operação AAA | Operar sob falha, carga e recuperação | runbooks estáticos | G5 PASS: SLO, telemetry, backup, restore, load e drills |
| R6. Promoção | Liberar de modo reversível | todos os gates anteriores | G6 PASS: canary, rollback, critic e release evidence |

## 2. R0 — Integridade e baseline confiável

**Resultado:** a matriz local volta a representar o código atual; o gate é
verde somente no escopo hermético/local, sem promover integrações externas.

Principais itens: `AAA-001`–`AAA-004`.

Sequência:

1. Corrigir o contexto tenant-scoped do benchmark Phase 1.5.
2. Rodar `make api15-full`, `make api15-verify` e `make api16-verify`.
3. Atualizar somente artefatos gerados pelo comando correto.
4. Reconciliar a divergência do LCP web e registrar build/window.
5. Congelar Quality Bar, fingerprint, manifest e lista de gaps.

Saída obrigatória:

- `api14-full`, `api15-full` e `api16-full` PASS nesta execução;
- `api15-verify` e `api16-verify` PASS;
- `api-security`, `api-contract`, retrieval e web PASS;
- nenhum teste enfraquecido para atingir o resultado;
- gaps P0 externos continuam abertos e explicitamente classificados.

Se o benchmark voltar a falhar, parar em R0; não iniciar promoção externa.

## 3. R1 — Spine de produção

**Resultado:** uma fatia vertical durável funciona em uma topologia descartável.

Principais itens: `AAA-010`–`AAA-018`.

Dependências humanas: escolha de Postgres, object store, broker, Qdrant, Redis,
provider, topologia de rede e secret manager.

Fatia demonstrável:

```text
login OIDC -> upload -> object checksum -> job queue -> worker lease
-> parse/chunk/embed -> Postgres + Qdrant -> search/chat -> delete/reindex
```

Saída obrigatória:

- schema Postgres com migrations, constraints, indexes e checksum;
- object store privado sem path traversal, com cleanup e retenção;
- queue/worker com idempotência, backpressure, retry, dead-letter,
  cancellation, lease e restart recovery;
- Qdrant, Redis e provider com health, timeout, redaction e shutdown;
- readiness real sem transformar dependência indisponível em `ready`;
- disposable integration executada em ambiente autorizado.

## 4. R2 — Segurança e identidade de produção

**Resultado:** o escopo é sempre derivado de uma identidade confiável e
revogável.

Principais itens: `AAA-020`–`AAA-027`.

Saída obrigatória:

- OIDC com discovery/configuration validada e sem fallback permissivo;
- mapeamento de subject para usuário, tenant, workspace e roles;
- sessão segura, logout/revogação e rotação de credenciais;
- route matrix completa com negativos cross-tenant e no-existence oracle;
- CSRF/CORS/cookies/headers e abuse limits contra browser real;
- secrets ausentes de logs, erros, métricas, jobs e evidence;
- threat model, residual risk e aprovação do Security owner.

R2 pode avançar em paralelo com o início de R1, mas não pode ser declarado
verde sem a topologia externa que transporta a identidade.

## 5. R3 — Inteligência e confiança

**Resultado:** o produto responde apenas quando consegue sustentar a resposta.

Principais itens: `AAA-030`–`AAA-038`.

Saída obrigatória:

- corpus aprovado/licenciado, sem dados sensíveis indevidos e com versão;
- golden queries por persona, tenant, idioma, formato e dificuldade;
- thresholds publicados para recall, hit@k, ACL leakage, freshness, latency e
  citation coverage;
- retrieval live com zero leakage e revalidação de ACL;
- Professor live com budgets, timeout, retry, unsupported-claim negatives,
  citation validation e estados `APPROVED`, `WEAK`, `NO_EVIDENCE`, `FAILED`;
- revisão humana, feedback e auditoria sem mutação silenciosa de prompt ou
  corpus.

Não promover qualidade semântica usando apenas provider determinístico ou
fixture não licenciada.

## 6. R4 — Experiência e acessibilidade

**Resultado:** a web apresenta a verdade operacional do backend e é utilizável
por diferentes modos de interação.

Principais itens: `AAA-040`–`AAA-047`.

Saída obrigatória:

- web chama somente a API root no fluxo de produção;
- tenant switcher, roles, logout, retry e permission states completos;
- documents workspace com upload, progresso, retry, cancel, delete, reindex,
  paginação, empty/error/forbidden;
- search/chat com evidence drawer, citation metadata e confidence honesta;
- keyboard, focus, contrast, zoom, reduced motion, screen reader e touch
  targets verificados;
- 375/768/1440 sem overflow ou perda da ação principal;
- matriz atual com `234/234` em 375/768/1440, sem skip planejado ou executável, mais evidência persistente de 320 px, escala 200% e interações;
- crítica visual independente com score >=95 e sem Critical/High.

## 7. R5 — Operação e escala

**Resultado:** a equipe consegue detectar, recuperar e explicar falhas.

Principais itens: `AAA-050`–`AAA-058`.

Saída obrigatória:

- traces, metrics, logs e audit exportados com redaction e cardinalidade segura;
- dashboards e alertas para error rate, latency, queue depth, dead-letter,
  provider failures, ACL denials e storage health;
- readiness/liveness/degraded checks contra todas as dependências required;
- backup de Postgres, Redis/Qdrant quando aplicável e object store;
- restore isolado com checksum, contagem, ACL e smoke matrix;
- load, soak, concorrência, memória, custo e p50/p95/p99 documentados;
- RPO/RTO demonstrados em drill, não apenas escritos no runbook.

## 8. R6 — Promoção reversível

**Resultado:** o release candidate é identificável, auditável e reversível.

Principais itens: `AAA-060`–`AAA-066`.

Saída obrigatória:

- candidate revision, manifest e fingerprint imutáveis;
- checkout e artefatos de release limpos;
- integration reviewer independente com packet selado;
- Final Critic avaliando o pacote completo, não apenas a web;
- canary com métricas e janela de decisão;
- rollback de imagem e plano de migration roll-forward testados;
- `release-evidence.json` completo e gate final PASS;
- decisão humana registrada para qualquer risco residual.

## 9. Gates e critérios de parada

| Gate | Critério mínimo | Bloqueia quando |
| --- | --- | --- |
| G0 | baseline local atual, sem `api15` quebrado | benchmark, contrato ou teste obrigatório falha |
| G1 | spine vertical live com recovery | qualquer store/queue/provider obrigatório é local-only |
| G2 | identidade e ACL externas | fallback permissivo, leakage ou revogação ausente |
| G3 | corpus/eval/grounding aprovados | claim não suportado, citation gap ou threshold ausente |
| G4 | web AAA completa | Critical/High visual/a11y, stale state ou mock de produção |
| G5 | operação mensurável | backup/restore, SLO, load ou alertas `NOT_RUN` |
| G6 | release reversível | evidence ausente, reviewer ausente ou rollback não testado |

Um gate `NOT_RUN` obrigatório não é PASS. Uma média alta não pode substituir um
critério obrigatório reprovado.

## 10. Dependências e paralelismo permitido

Após G0, estas lanes podem avançar em paralelo com ownership disjunto:

- **Data/Platform:** `AAA-010`–`AAA-018`;
- **Security/Identity:** `AAA-020`–`AAA-027`;
- **Intelligence/Eval:** `AAA-030`–`AAA-038`;
- **Web/Design:** `AAA-040`–`AAA-047`;
- **Ops/Release:** `AAA-050`–`AAA-066`.

Todas convergem em R5/R6. Nenhuma lane pode alterar contratos compartilhados
sem integração, teste de regressão e atualização do backlog.
