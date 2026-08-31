# 0006 — Usuários e Stakeholders

## Objetivo

Identificar todos os envolvidos no problema e no programa.

---

## Usuário Primário

### Operador de Sistema (Operator)
- **Quem:** Pessoa que faz upload de documentos, faz queries, monitora o sistema
- **Needs:** Interface visual para operação, não dependência de curl/Swagger
- **Dor:** Sistema atual funciona mas operação requer conhecimento técnico

### Analista de Dados / QA
- **Quem:** Pessoa que valida qualidade do sistema
- **Needs:** Dataset real, métricas objetivas, gates verificáveis
- **Dor:** Não consegue validar gates objetivamente sem dataset

---

## Usuário Secundário

### Administrador (Admin)
- **Quem:** Pessoa que gerencia tenants, usuários, permissões
- **Needs:** Painel administrativo, gestão de acessos, configuração
- **Dor:** Admin panel existe mas dependência de headers não é seguro

### Desenvolvedor Backend
- **Quem:** Pessoa que implementa features, mantém código
- **Needs:** Documentação clara, código consistente, gates objetivos
- **Dor:** Documentação não reflete código, decisões sem evidência

### Desenvolvedor Frontend
- **Quem:** Pessoa que implementa UI, integra com backend
- **Needs:** Contratos estáveis, documentação atualizada
- **Dor:** Gap entre docs e código pode causar retrabalho

---

## Operador

### DevOps / SRE
- **Quem:** Pessoa que opera o sistema em produção
- **Needs:** Observabilidade, alertas, tracing, logs claros
- **Dor:** Sistema atual não tem request_id, métricas por tenant, alertas

### Platform Engineer
- **Quem:** Pessoa que mantém infraestrutura
- **Needs:** Health checks claros, backup/recovery documentado
- **Dor:** Runbook de reindex existe (0024) mas observabilidade limitada

---

## Decisor

### Tech Lead / Architect
- **Quem:** Pessoa que decide roadmap, arquitetura, prioridades
- **Needs:** Visão clara do estado do sistema, gaps identificados, prioridade
- **Dor:** Não há dataset real, features pendentes sem evidência

### Product Manager
- **Quem:** Pessoa que define produto, prioriza features
- **Needs:** Gates verificáveis, roadmap fundamentado
- **Dor:** Auditorias identificam gap entre promessa e implementação

---

## Impactados Indiretos

### Stakeholders de Negócio
- **Quem:** Investidores, gestores, clientes
- **Needs:** Plataforma enterprise comprovada, SLA garantido
- **Dor:** Sistema atual não pode ser vendido como enterprise sem features pendentes

### Clientes Finais
- **Quem:** Usuários que fazem queries no sistema
- **Needs:** Respostas corretas, confiança, disponibilidade
- **Dor:** Indirectamente afetados por gaps de qualidade e disponibilidade

---

## Papéis e Responsabilidades

| Papel | Responsabilidade | Needs Principais |
|---|---|---|
| Operator | Upload, query, monitoramento | UI, métricas |
| Admin | Gestão de tenants e usuários | Admin panel, RBAC |
| QA/Data | Validação de gates | Dataset, métricas |
| Dev Backend | Features, manutenção | Docs, código consistente |
| Dev Frontend | UI, integração | Contratos estáveis |
| SRE/DevOps | Operação, incidentes | Observabilidade, tracing |
| Tech Lead | Decisões, roadmap | Visão clara, gaps |
| PM | Produto, priorização | Gates verificáveis |

---

## Próximo Passo

Avançar para Riscos e Hipóteses (0007_riscos_e_hipoteses.md)