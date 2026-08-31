# 0091 — PRD Runtime Closeout

## Objetivo

Fechar, dentro da trilha `01_prd`, os requisitos e métricas originalmente definidos para o programa.

---

## Requisitos funcionais com evidência de runtime

| Requisito PRD | Evidência atual | Status |
|---|---|---|
| RF-01 Autenticação | login, logout, recovery e switch tenant ativos | ✅ |
| RF-02 Upload | UI e backend de upload passam no smoke | ✅ |
| RF-03 Busca | retrieval híbrido validado por smoke e avaliação | ✅ |
| RF-04 Query/RAG | resposta com citações e grounding ativos | ✅ |
| RF-05 RBAC | enforcement server-side + UI aderente | ✅ |
| RF-06 Multi-tenant | `3` tenants ativos com suite TKT-010 formal | ✅ |
| RF-07 Métricas | `/metrics`, `/observability/*` e `/admin/runtime` ativos | ✅ |
| RF-08 Health Check | `/health` por workspace com estado de corpus e Qdrant | ✅ |
| RF-09 Auditoria | logs, alertas, auditorias e repairs operáveis via UI | ✅ |
| RF-10 Dataset | dataset real com gate executável e política recorrente | ✅ |

---

## Métricas do PRD consolidadas

### Runtime validation
- `pytest -q` verde no backend
- `pnpm -C frontend exec tsc --noEmit` verde
- `pnpm -C frontend lint` verde
- `pnpm -C frontend test:smoke` verde

### Dataset e avaliação
- dataset ativo com `20+` perguntas reais
- `hit_rate_top5 >= 60%` sustentado
- avaliação oficial operacionalizada em runtime e admin
- política de reexecução: reavaliar após mudanças em corpus, retrieval, ranking ou contratos de resposta

### Observabilidade e operação
- SLI/SLO legíveis por workspace
- tracing legível por workspace
- alertas e dashboard executivo disponíveis

---

## Regras de negócio fechadas

### Governança sensível
- rebaixamento de `admin` exige aprovação explícita
- ticket de aprovação é obrigatório
- tentativa sem aprovação falha no backend e é auditável

### Proteção de tenant
- tenant bootstrap segue protegido
- tenant com usuários ativos não pode ser removido
- tenant com documentos ativos não pode ser removido

### Isolamento
- Operator não acessa dados de outro workspace
- Search e documentos respeitam `workspace_id`
- Admin só muda escopo quando explicitamente troca tenant

---

## Decisão

### STATUS
**PRD_CONFIRMED_IN_RUNTIME**

### Conclusão
O PRD foi atendido no runtime atual com evidência suficiente para sustentar o score `96/100`, sem expansão indevida de escopo além do produto especificado.

### Próximo passo
Manter as próximas melhorias como incrementais, fora do núcleo já fechado por este PRD.
