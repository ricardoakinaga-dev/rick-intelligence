# 0015 — Métricas de Sucesso

## KPIs do Programa

### KPI-01: Nota Geral do Programa
- **Atual:** 87/100
- **Meta:** >= 92/100
- **Como medir:** Auditoria formal após correções

### KPI-02: Dataset Verificável
- **Indicador:** Dataset de 20+ perguntas reais existe
- **Meta:** Hit rate top-5 >= 60% no gate F0
- **Como medir:** Execução de suite de avaliação

### KPI-03: Auth Enterprise
- **Indicador:** Sessões persistidas, RBAC server-side
- **Meta:** Não depende de headers X-Enterprise-*
- **Como medir:** Testes de segurança

### KPI-04: Isolamento Provado
- **Indicador:** 3 tenants ativos sem vazamento
- **Meta:** Suite TKT-010 passa 100%
- **Como medir:** Suite de não-vazamento

### KPI-05: Observabilidade
- **Indicador:** request_id implementado, métricas por tenant
- **Meta:** Health check e métricas funcionais
- **Como medir:** Endpoints respondem corretamente

---

## Métricas de Retrieval

### M-01: Hit Rate Top-5
- Definição: % de queries onde documento correto está no top-5
- Atual: Dataset sintético, hit rate 100% (não confiável)
- Meta: >= 60% com dataset real

### M-02: Avg Score
- Definição: Score médio do primeiro resultado
- Meta: >= 0.70 (threshold)

### M-03: Low Confidence Rate
- Definição: % de queries com best_score < threshold
- Meta: < 20%

---

## Métricas de Resposta

### M-04: Grounded Rate
- Definição: % de respostas com citação válida
- Meta: >= 80%

### M-05: Citation Coverage
- Definição: % do texto da resposta que está citado
- Meta: >= 80%

### M-06: Avg Latency
- Definição: Latência média de query (sem streaming)
- Meta: < 5s

---

## Métricas de Operação

### M-07: Uptime
- Definição: % de tempo healthy
- Meta: >= 99%

### M-08: Error Rate
- Definição: % de requests com erro 5xx
- Meta: < 2%

### M-09: p99 Latency
- Definição: Latência no percentil 99
- Meta: < 3s

---

## Critérios de Sucesso

| Métrica | Atual | Meta | Status |
|---|---|---|---|
| Nota geral | 87/100 | >= 92/100 | ❌ |
| Dataset | Não existe | 20+ perguntas, hit >= 60% | ❌ |
| Auth | Headers | Server-side, persistido | ⚠️ Parcial |
| Isolamento | Não provado | 3 tenants, não-vazamento | ❌ |
| Observabilidade | Limitada | request_id, métricas tenant | ❌ |

---

## Próximo Passo

Avançar para 0020_prd_master.md (consolidação)