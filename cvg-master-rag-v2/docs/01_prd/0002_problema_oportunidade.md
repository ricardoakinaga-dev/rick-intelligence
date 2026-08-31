# 0002 — Problema e Oportunidade

## Problema Atual

### Descrição

O programa RAG Enterprise tem código funcional e frontend robusto, mas não constitui uma plataforma enterprise comprovada. Os problemas estruturais impedem:

1. **Validação de gates** — sem dataset real, impossível verificar qualidade objetivamente
2. **Segurança** — auth por headers não é enterprise
3. **Isolamento** — multitenancy existe, mas não foi provado
4. **Observabilidade** — sem request_id, métricas por tenant, alertas
5. **Documentação** — gap entre código e docs

### Sintomas Operacionais

- Equipe não consegue validar gates com critérios objetivos
- Auth permite manipulação por headers não confiáveis
- Não há prova de que tenant A não vê dados de tenant B
- Incidentes em produção difíceis de debugar sem tracing
- Documentação promete features que não existem

### Impacto

| Tipo | Descrição |
|---|---|
| Tempo | Validação manual excessiva, debugging difícil |
| Dinheiro | Decisões de investimento sem dados |
| Erro | Gates podem ser aprovados incorretamente |
| Experiência | Sistema não pode ser vendido como enterprise |

### Custo de Não Resolver

- Continuar com nota 87/100 sem progresso
- Impossibilidade de fechar gates F3
- Sistema não pode ser comercializado como enterprise
- Riscos de segurança e isolamento em produção

---

## Oportunidade

### O Que Podemos Construir

1. **Dataset de avaliação real**
   - 20+ perguntas reais validadas
   - Hit rate >= 60% verificável
   - Gates objetivos

2. **Auth enterprise**
   - Autenticação server-side
   - Sessões persistidas
   - RBAC em endpoints

3. **Isolamento multi-tenant provado**
   - 3 tenants ativos
   - Suite de não-vazamento
   - Auditoria documentada

4. **Observabilidade enterprise**
   - request_id ponta a ponta
   - Métricas por tenant
   - Alertas configurados

### Benefício Esperado

- Nota do programa: 87/100 → 92/100
- F3 gate approved
- Plataforma enterprise comprovada
- Comercialização viável

---

## Próximo Passo

Avançar para 0003_stakeholders_usuarios.md