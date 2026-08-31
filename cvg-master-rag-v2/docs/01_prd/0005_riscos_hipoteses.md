# 0005 — Riscos e Hipóteses

## Riscos do Programa

### Risco 1: Dataset Sintético Não Representa Realidade
- **Probabilidade:** Alta
- **Impacto:** Alto
- **Mitigação:** Usar perguntas de usuários reais ou validadas por domain expert

### Risco 2: Breaking Change em Auth
- **Probabilidade:** Média
- **Impacto:** Alto
- **Mitigação:** Backward compatibility, testes incrementais

### Risco 3: Gap Entre Docs e Código Muito Grande
- **Probabilidade:** Alta
- **Impacto:** Médio
- **Mitigação:** Validar código vs docs antes de fazer engenharia reversa

---

## Hipóteses do Programa

### Hipótese 1: Dataset Real Tera Hit Rate >= 60%
- Dataset de 20+ perguntas reais terá hit rate >= 60%
- Validado por execução em retrieval real

### Hipótese 2: Auth Server-side Não Quebrara Frontend
- Implementação incremental não quebrará fluxo existente
- Testado por smoke tests após cada mudança

### Hipótese 3: Isolamento Funciona com 3 Tenants
- 3 tenants ativos provam não-vazamento
- Suite de teste (TKT-010) valida

---

## Limitações Conhecidas

- Apenas 4 formatos (PDF, DOCX, MD, TXT)
- Chunking apenas Recursive
- Sem audio
- Sem streaming de resposta

---

## Próximo Passo

Avançar para 0010_casos_de_uso.md