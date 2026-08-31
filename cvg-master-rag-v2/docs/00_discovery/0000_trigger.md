# 0000 — Trigger

## Origem do Programa

**Programa:** RAG Database Builder / RAG Enterprise Premium
**Tipo de Gatilho:** Dor operacional + oportunidade de negócio
**Data de Identificação:** 2024-2026 (evolução contínua)
**Contexto Inicial:** Sistema de RAG funcional existente que precisa evoluir para produto enterprise completo

---

## Situação Identificada

O programa parte de um motor RAG técnico funcional que precisa se transformar em uma plataforma enterprise premium completa.

### Estado atual identificado (auditoria 2026-04-17):

- **F0 — Foundation:** ✅ Funcional (95/100)
  - Motor RAG core operacional
  - API REST com FastAPI
  - Ingestão multi-formato (PDF, DOCX, MD, TXT)
  - Chunking recursivo
  - Retrieval híbrido (dense + sparse + RRF)
  - Query com grounding
  - Telemetria estruturada
  - Dataset de 30 perguntas reais com HIT@5=100%

- **F1 — Profissional:** ⚠️ Parcial (78/100)
  - Reranking não implementado
  - Observabilidade parcialmente implementada

- **F2 — Premium:** ⚠️ Frontend OK, features pendentes (82/100)
  - Frontend Next.js 15 completo
  - Chat web funcional
  - Painéis operacionais funcionais
  - HyDE não implementado
  - Semantic chunking não implementado

- **F3 — Enterprise:** ❌ Bloqueada (60/100)
  - Auth com senha verificada ✅
  - Isolamento multi-tenant comprovado ✅
  - SLA/alertas não implementados
  - Multitenancy funcional em progresso

---

## Problema Central

O sistema atual é um backend RAG funcional com frontend premium validado, mas que ainda não constitui uma plataforma enterprise completa. A documentação existente é extensa mas não segue um pipeline formal de engenharia.

### Débitos identificados:

1. **Dataset de avaliação real** — blocker número 1 (não existe dataset validado)
2. **Auth enterprise** — sessões persistidas, não dependendo de headers do cliente
3. **Reranking** — implementado ou com justificativa documentada
4. **HyDE** — implementado ou removido do roadmap
5. **Semantic chunking** — implementado ou com justificativa
6. **SLA e alertas** — não implementados
7. **Observabilidade enterprise** — incompleta

---

## Oportunidade de Negócio

Transformar o sistema atual em uma **plataforma RAG enterprise premium** com:
- Backend forte com dataset auditável
- Frontend robusto com chat, painéis, administração
- Multitenancy com isolamento provado
- RBAC com auth enterprise real
- Observabilidade enterprise com alertas e SLA

---

## Origem da Ideia

- Evolução de sistema técnico (API + Swagger) para produto web robusto
- Necessidade de validar qualidade com dataset real
- Requisito de multitenancy e governança para uso comercial
- Roadmap documentado em múltiplos ajustes e auditorias

---

## quem Identificou

- Equipe de desenvolvimento (Codex/OpenClaw)
- Auditorias técnicas successivas (2026-04-16, 2026-04-17)
- Processo de engenharia CVG

---

##下一步

Avançar para Análise da Dor (0001_analise_da_dor.md)