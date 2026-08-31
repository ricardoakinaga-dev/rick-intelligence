# 0008 — Arquitetura Alvo e Arquitetura Atual

## Objetivo

Documentar a arquitetura atual da fundação e a arquitetura alvo da versão final **Enterprise Premium**.

---

## Arquitetura Atual

### Estado atual

Hoje o sistema é um backend RAG funcional com interface predominantemente técnica.

### Núcleo atual

- FastAPI
- Qdrant
- filesystem
- OpenAI
- endpoints REST
- Swagger

### Leitura correta

Isso é suficiente para:

- validar o motor
- operar tecnicamente
- medir qualidade

Mas isso ainda não representa o produto final visual.

---

## Arquitetura Alvo — Enterprise Premium

### Visão de alto nível

```text
Frontend Web Enterprise
    ├── Chat Web
    ├── Painel de Documentos
    ├── Painel de Busca e Auditoria
    ├── Dashboard Operacional
    └── Painel Administrativo

Camada de Aplicação
    ├── API de Chat
    ├── API de Documentos
    ├── API de Admin
    ├── API de Métricas
    └── API de Avaliação

Serviços de Domínio
    ├── Ingestion
    ├── Retrieval
    ├── Grounding
    ├── Evaluation
    ├── Telemetry
    └── Governance

Infraestrutura
    ├── Qdrant
    ├── Banco relacional para metadata/admin
    ├── Object/File storage
    ├── Auth provider
    ├── Observabilidade
    └── Alerting
```

---

## Componentes esperados da arquitetura final

### 1. Frontend robusto

- Next.js ou stack equivalente
- interface de documentos
- interface de busca
- chat web
- dashboard
- painel administrativo

### 2. Backend de produto

- APIs separadas por domínio lógico
- contratos estáveis
- autenticação
- autorização
- trilha de auditoria

### 3. Camada de governança

- RBAC
- multitenancy
- configuração por tenant
- branding por tenant

### 4. Camada de observabilidade

- métricas
- tracing
- alertas
- dashboards

---

## Diferença principal entre atual e alvo

### Atual

- backend funcional
- operação técnica
- uso por API/Swagger

### Alvo

- produto visual
- operação por frontend
- administração completa
- experiência enterprise

---

## Decisão Arquitetural Central

O frontend não é acessório.

Na versão final Enterprise Premium, o frontend é parte central do produto.

Ele deve existir como camada robusta para:

- uso diário
- administração
- auditoria
- visualização de qualidade
- operação multiempresa

---

## Próximo Passo

Ir para `0015-roadmap-executivo.md`.
