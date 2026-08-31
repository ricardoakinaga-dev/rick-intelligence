# 0001 — Visão Inicial

## Nome do Produto

**RAG Database Builder — Enterprise Premium**

---

## Contexto Geral

O produto é uma plataforma de Retrieval Augmented Generation (RAG) que evoluiu de um motor técnico funcional para uma plataforma enterprise em construção. O objetivo atual é fechar os gaps restantes para constituir uma plataforma enterprise comprovada.

### Estado Atual (2026-04-17)
- Nota geral: 87/100
- F0 funcional (95/100)
- F1 parcial (78/100)
- F2 frontend OK, features pendentes (82/100)
- F3 bloqueado (60/100)

---

## Dor Principal

A plataforma não pode ser considerada "enterprise ready" porque:
1. Não há dataset real para validar gates
2. Auth depende de headers manipuláveis
3. Isolamento multi-tenant não verificado
4. Observabilidade insuficiente para operação
5. Documentação não reflete código real

---

## Hipótese de Valor

Resolver estes gaps resultará em:
- **Validação objetiva** — gates verificáveis com métricas
- **Segurança comprovada** — auth server-side, RBAC, isolamento
- **Operação confiável** — observabilidade, tracing, alertas
- **Documentação confiável** — código e docs alinhados
- **Nota do programa:** 87/100 → 92/100

---

## Posicionamento

O RAG Enterprise é uma **plataforma B2B** para organizações que precisam de:
- Retrieval de alta qualidade sobre documentos internos
- Multi-tenant com isolamento comprovado
- Governança e auditoria
- Operações observáveis com SLA

**Público-alvo:** Empresas que precisam de sistema de busca inteligente sobrebase de conhecimento interna, com требования de segurança e compliance.

---

## Próximo Passo

Avançar para 0002_problema_oportunidade.md