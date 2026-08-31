# 0003 — Stakeholders e Usuários

## Usuário Primário

### Operador de Sistema (Operator)
- **Responsabilidade:** Upload de documentos, execução de queries, monitoramento básico
- **Needs:** Interface visual, não depender de curl/Swagger
- **Dor atual:** UI existe mas operação requer conhecimento técnico

### Analista de QA/Data
- **Responsabilidade:** Validação de gates, qualidade do sistema
- **Needs:** Dataset real, métricas objetivas
- **Dor atual:** Sem dataset, validação manual obrigatória

---

## Usuário Secundário

### Administrador (Admin)
- **Responsabilidade:** Gestão de tenants, usuários, permissões
- **Needs:** Admin panel funcional, RBAC real
- **Dor atual:** Auth depende de headers, RBAC incompleto

### Desenvolvedor
- **Responsabilidade:** Features, manutenção, debugging
- **Needs:** Documentação clara, código consistente
- **Dor atual:** Gap entre docs e código

---

## Decisor

### Tech Lead / Architect
- **Responsabilidade:** Decisões de roadmap, arquitetura, prioridade
- **Needs:** Visão clara do estado, gaps identificados
- **Dor atual:** Sem dataset, decisões subjetivas

### Product Manager
- **Responsabilidade:** Priorização, roadmap, expectativas
- **Needs:** Gates verificáveis,里程碑 concretos
- **Dor atual:** Features pendentes sem evidência

---

## Impactados Indiretos

### SRE/DevOps
- **Responsabilidade:** Operação em produção, incidentes
- **Needs:** Observabilidade, tracing, alertas
- **Dor atual:** Sem request_id, sem métricas por tenant

### Stakeholders de Negócio
- **Responsabilidade:** Decisões de investimento
- **Needs:** Plataforma enterprise comprovada
- **Dor atual:** Sistema não pode ser vendido como enterprise

---

## Matriz de Priorização

| Stakeholder | Impacto | Prioridade |
|---|---|---|
| QA/Data | Alto | P0 |
| Admin | Alto | P1 |
| Operator | Alto | P1 |
| SRE/DevOps | Médio | P1 |
| Tech Lead | Alto | P1 |
| PM | Médio | P2 |
| Desenvolvedor | Médio | P2 |
| Stakeholders | Médio | P2 |

---

## Próximo Passo

Avançar para 0004_fluxo_atual.md (referência do discovery) ou iniciar Casos de Uso (0010)