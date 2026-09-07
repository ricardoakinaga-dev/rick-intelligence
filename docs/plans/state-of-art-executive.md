# Plano executivo — RICK Intelligence State of the Art / AAA

**Status:** execução autorizada e em andamento
**Data de baseline:** 2026-09-05
**Modo:** brownfield, migração incremental, qualidade orientada por evidência

## Resultado executivo

Construir um produto de inteligência de conhecimento multi-tenant, seguro e
observável, com ingestão confiável, retrieval híbrido, respostas aterradas em
evidências, operação auditável e uma experiência web canônica de nível AAA.
O resultado precisa ser promovível por gates reproduzíveis; “AAA” não será
declarado por inspeção de código ou por um mock verde.

O caminho é incremental: o root passa a ser a plataforma canônica, enquanto
`cvg-master-rag-v2/`, `rick-professor/` e `modulo-redis-locker/` continuam
preservados como superfícies de compatibilidade até existir evidência de
equivalência e rollback.

## Situação confirmada

| Área | Construído hoje | Lacuna que impede promoção AAA |
| --- | --- | --- |
| API | FastAPI root versionada, auth/ACL, compatibilidade OpenAI, Professor, contratos de erro, busca, lifecycle e auditoria bounded | persistência e dependências externas ainda não são o caminho padrão de produção |
| Conhecimento/RAG | `packages/knowledge`, `ingestion`, `retrieval`, IDs estáveis, provenance, filtros ACL, read-model SQLite local e eval offline | matriz completa live/durável, corpus aprovado, freshness em produção e operação multi-instância |
| Ingestão | parser/chunker/index, jobs com journal/recovery local, fila bounded com retry/dead-letter, staging privado e vetores locais | Postgres, object storage S3-compatible, broker distribuído e idempotência multi-instância |
| Provider/lease | contratos tipados, adapters herméticos Qdrant/Redis, budgets, circuit breaker e redaction | rollout live, health real, métricas exportadas e falhas de dependências reais |
| Web | caller root `apps/web` com sessão, shell, documentos, busca, chat, admin/readiness, auditoria/lifecycle, filtros, E2E e render 375/768/1440 | critic visual/a11y independente, integração live e promoção AAA continuam pendentes |
| Operação | Makefile, workflows, validators, compose de referência, migração inicial, regras SLO, observabilidade local e runbooks | Docker/deploy root, collectors, backup/restore, RTO/RPO, canary e drills executáveis |
| Controle | planos/gates atuais, fingerprint diagnóstico, gate de release H1, preservação de histórico e children, critics prontos | checkout compartilhado continua dirty e não existe `release-evidence.json`; produção/live permanece NOT_RUN |

Baseline reproduzido nesta execução: `make validate`, `api14-full`,
`api15-full`, `api16-full`, `api-security`, `api-contract`, `storage-test`,
`api16-worker`, avaliação offline e `ops-static` passaram; a web passou lint,
typecheck, build e `16 passed / 2 skipped` em Playwright. O gate de integridade
classifica corretamente o checkout compartilhado como `NOT_RUN` por ausência de
`docs/progress/release-evidence.json`; isso não é uma promoção.

## Princípios executivos

1. **Verdade operacional:** toda capacidade terá um contrato, limite, métrica,
   teste e estado de rollout explícito.
2. **Segurança por desenho:** tenant/workspace/collection vêm da sessão e da
   política server-side; o cliente só pode reduzir escopo.
3. **Evidência antes de promoção:** cada gate registra comando, ambiente,
   artefato, frescor e limitação; ausência de Docker, credencial ou serviço
   externo continua `NOT_RUN`/`BLOCKED`.
4. **Experiência como produto:** a web canônica terá tese visual, sistema de
   tokens, estados completos, acessibilidade WCAG AA, responsividade e
   screenshots/render real antes do gate visual.
5. **Migração reversível:** nenhum child é editado ou apagado; caller switch,
   dual-read/dual-write e rollback são partes do desenho.
6. **Menor mudança coerente:** builders têm ownership disjunto; contratos e
   integração permanecem sob o Lead.

## Frentes executivas

- **F1 — Fundação verde:** reconciliar controle, fechar regressões, congelar
  contratos e tornar a matriz Phase 1.5/1.6 atual.
- **F2 — Runtime de produção:** promover os adapters locais para PostgreSQL,
  object storage, broker, Qdrant/Redis e provider reais somente com ambiente
  autorizado; fechar readiness, telemetria, backup e recovery.
- **F3 — Web canônica:** manter `apps/web` como caller único, auditar busca,
  lifecycle e estados de evidência; obter critic visual/a11y independente antes
  de qualquer claim AAA.
- **F4 — Inteligência:** transformar a fixture offline em corpus aprovado,
  executar freshness/quality live, fechar Professor grounded, citações,
  guardrails e feedback sem mutação silenciosa.
- **F5 — Operação e promoção:** CI/CD, supply chain, performance, segurança,
  acessibilidade, visual QA, critics independentes e decisão de rollout.

## Definition of Done do programa

O programa só é encerrado quando todos os critérios do bar
`.gauntlet-state-of-art/bar.json` têm evidência atual, sem `FAIL`, `BLOCKED`,
`INVALID`, `STALE` ou `NOT_RUN` obrigatório; a matriz live é executada em
ambiente autorizado; a web é avaliada em 375/768/1440px por render real; os
children preservados permanecem íntegros; e um Final Critic novo aprova o
artefato integrado. Até lá, o estado correto é `IN_PROGRESS` ou um handoff
honesto com o maior gap restante.
