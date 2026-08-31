# 0020 — PRD Master

## Consolidação do PRD

Este documento consolida todo o Product Requirement Document para o programa RAG Enterprise Premium.

---

## Visão Geral

### Nome do Produto
**RAG Database Builder — Enterprise Premium**

### Problema
O programa RAG Enterprise existe como código funcional e frontend robusto, mas não constitui uma plataforma enterprise comprovada devido a:
1. Dataset inexistente (impossibilita gates)
2. Auth incompleto (headers não confiáveis)
3. Isolamento não provado
4. Observabilidade insuficiente
5. Documentação não reflete código

### Oportunidade
Transformar o sistema em plataforma enterprise com:
- Dataset verificável (20+ perguntas, hit rate >= 60%)
- Auth server-side (sessões persistidas, RBAC)
- Isolamento provado (3 tenants, não-vazamento)
- Observabilidade (request_id, métricas, alertas)
- Nota: 87/100 → 92/100

---

## Usuários e Stakeholders

| Papel | Responsabilidade | Needs |
|---|---|---|
| Operator | Upload, query, monitoramento | UI, métricas |
| Admin | Gestão de tenants e usuários | Admin panel, RBAC |
| QA/Data | Validação de gates | Dataset, métricas |
| SRE/DevOps | Operação, incidentes | Observabilidade, tracing |
| Tech Lead | Decisões, roadmap | Visão clara, gaps |

---

## Fluxos Principais

### Fluxo 1: Upload de Documento
1. Operator seleciona arquivo
2. Sistema valida formato e tamanho
3. Sistema parseia e extrai texto
4. Sistema chunka e indexa
5. Sistema retorna document_id

### Fluxo 2: Query/RAG
1. Usuário digita pergunta
2. Sistema executa busca híbrida
3. Sistema avalia low confidence
4. Se confiante: sistema chama LLM
5. Sistema retorna resposta com citações

### Fluxo 3: Autenticação
1. Usuário faz login
2. Sistema valida credenciais
3. Sistema cria sessão persistente
4. Sistema retorna token
5. Cliente envia token em cada request

### Fluxo 4: Admin CRUD
1. Admin acessa /admin
2. Admin faz CRUD de tenants/users
3. Sistema persiste e registra auditoria

---

## Escopo

### IN SCOPE
1. Dataset de avaliação real (20+ perguntas, hit rate >= 60%)
2. Auth enterprise (server-side, sessões persistidas, RBAC)
3. Isolamento multi-tenant provado (3 tenants, não-vazamento)
4. Observabilidade enterprise (request_id, métricas, alertas)
5. Engenharia reversa seguindo pipeline CVG

### OUT OF SCOPE
1. HyDE, Semantic Chunking, Reranking (sem evidência)
2. Frontend comercial completo (F2 atual é suficiente)
3. Billing, monetização, workflows de aprovação
4. White label, branding

### FUTURE SCOPE
1. Implementação de features premium se dataset mostrar necessidade
2. White label, branding
3. Billing/quotas
4. Audio input

---

## Regras de Negócio

| ID | Regra |
|---|---|
| RN-01 | Autenticação obrigatória |
| RN-02 | RBAC: admin, operator, viewer |
| RN-03 | Isolamento por workspace/tenant |
| RN-04 | Formatos aceitos: PDF, DOCX, MD, TXT |
| RN-05 | Busca usa dense + sparse + RRF |
| RN-06 | Low confidence se best_score < threshold |
| RN-07 | Resposta inclui citações |

---

## Requisitos Funcionais

1. **Ingestão:** Upload, parse, chunk, index, return document_id
2. **Retrieval:** Busca híbrida com filtros, scores, top_k
3. **Query/RAG:** Retrieval + contexto + LLM + citações
4. **Auth:** Login, logout, recuperação, validação server-side
5. **RBAC:** Validação de role, ações permitidas/proibidas
6. **Admin CRUD:** Tenants e usuários com auditoria
7. **Isolamento:** Filtro por workspace em todas as operações
8. **Avaliação:** Dataset, hit_rate, groundedness
9. **Observabilidade:** request_id, logs, health, métricas

---

## Requisitos Não Funcionais

| Categoria | Requisito |
|---|---|
| Performance | Latência query < 5s (p95) |
| Confiabilidade | Uptime >= 99% |
| Rastreabilidade | request_id em todos os logs |
| Segurança | Auth server-side, RBAC, isolamento |
| Multi-tenant | 3+ tenants simultâneos |

---

## Métricas de Sucesso

| KPI | Atual | Meta |
|---|---|---|
| Nota geral | 87/100 | >= 92/100 |
| Dataset | Não existe | 20+ perguntas, hit >= 60% |
| Auth | Headers | Server-side, persistido |
| Isolamento | Não provado | 3 tenants, não-vazamento |
| Observabilidade | Limitada | request_id, métricas tenant |

---

## Riscos e Mitigações

| Risco | Mitigação |
|---|---|
| Dataset sintético não representa realidade | Usar perguntas reais de usuários |
| Breaking change em auth | Backward compatibility, testes incrementais |
| Gap docs/código muito grande | Validar código vs docs antes |

---

## Próximo Passo

Avançar para `/docs/02_spec/` seguindo o pipeline CVG.