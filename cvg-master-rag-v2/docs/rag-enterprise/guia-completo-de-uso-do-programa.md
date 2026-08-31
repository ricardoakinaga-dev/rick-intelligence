# Guia Completo de Uso do Programa — Versão Enterprise Revisada

## Objetivo deste documento

Este guia explica, de forma operacional e executiva:

- o que o programa faz
- que problema ele resolve
- o que já existe hoje
- o que é interface técnica
- o que será interface web final
- como usar as principais funcionalidades
- como interpretar as respostas
- como o sistema evolui por fases
- como operar o sistema sem depender de leitura do código

---

## 1. O que é este programa

O `cvg-master-rag` é um sistema de RAG.

RAG significa, na prática:

1. você envia documentos para o sistema
2. o sistema extrai e organiza o conteúdo
3. ele quebra o conteúdo em trechos consultáveis
4. indexa esses trechos em um mecanismo de busca vetorial
5. depois você faz perguntas em linguagem natural
6. o sistema recupera os trechos mais relevantes
7. a resposta final é gerada com base no conteúdo encontrado

Em vez de depender apenas do conhecimento geral do modelo, o programa responde com base no corpus documental da operação.

---

## 2. Que problema o programa resolve no dia a dia

### 2.1 Encontrar respostas sem ler documentos inteiros

Se a empresa possui:

- políticas
- contratos
- manuais
- normas
- FAQs
- instruções operacionais
- playbooks internos

o sistema permite perguntar diretamente, por exemplo:

- “Qual é o prazo para reembolso?”
- “Quais são as condições de cancelamento?”
- “Onde está a regra de aprovação?”
- “Que documento fala sobre exceções?”

Isso reduz o tempo de busca manual e evita abrir vários arquivos para achar uma regra específica.

### 2.2 Reduzir erro de interpretação

Como a resposta é baseada em trechos recuperados do próprio documento, o sistema ajuda a:

- responder com base documental
- reduzir respostas “de memória”
- melhorar consistência operacional
- mostrar de onde a informação veio

### 2.3 Centralizar conhecimento disperso

No dia a dia, a informação costuma estar espalhada em:

- PDFs
- DOCX
- Markdown
- TXT

O programa transforma esse conjunto em uma base pesquisável e perguntável.

### 2.4 Apoiar atendimento, operação e backoffice

Esse sistema é útil quando alguém precisa responder rápido, com consistência e com apoio documental.

Exemplos:

- atendimento interno
- suporte ao cliente
- financeiro
- compliance
- operações
- onboarding
- time administrativo

### 2.5 Saber quando não há base suficiente para responder

O sistema também serve para indicar quando não encontrou base suficiente.

Isso aparece em campos como:

- `low_confidence`
- `grounded`
- `citation_coverage`
- `needs_review`

Na prática, isso ajuda a evitar respostas com aparência confiante quando o corpus não sustenta a conclusão.

---

## 3. O que já existe hoje

Com base na operação descrita neste guia, o sistema já possui um núcleo funcional de RAG.

### 3.1 Núcleo funcional já existente

Hoje já existe, em nível operacional:

- API REST
- upload de documentos
- ingestão
- parsing
- normalização documental
- chunking
- geração de embeddings
- indexação no Qdrant
- retrieval híbrido
- endpoint de busca
- endpoint de pergunta com resposta pronta
- metadata de documentos
- métricas operacionais
- fluxo de avaliação
- runbook de reindex / rebuild
- documentação técnica de operação

### 3.2 O que isso significa na prática

Hoje o programa já funciona como motor RAG utilizável.

Ou seja:

- ele recebe documentos
- indexa conteúdos
- recupera trechos
- responde perguntas
- mostra sinais de confiança e grounding
- expõe métricas
- permite operação técnica real

---

## 4. O que é a interface do sistema hoje

### 4.1 Interface técnica existente hoje

Atualmente, a interface principal do sistema é técnica/operacional.

Ela existe em três formas principais:

### A. Swagger / OpenAPI

Disponível em:

- `http://localhost:8000/docs`

Essa é uma interface web técnica, usada para:

- visualizar endpoints
- testar requisições
- inspecionar contratos
- validar entradas e saídas
- depurar comportamento da API

### B. API REST

A operação principal do sistema hoje acontece por endpoints como:

- `POST /documents/upload`
- `POST /search`
- `POST /query`
- `GET /documents/{document_id}`
- `GET /metrics`
- `POST /evaluation/run`

### C. Operação por linha de comando

Hoje também existe uso por:

- `curl`
- scripts
- runbooks
- logs
- métricas
- inspeção técnica

### 4.2 O que significa “interface técnica”

Interface técnica é uma interface voltada para operador técnico, desenvolvedor, analista ou administrador do sistema.

Ela não é pensada, neste estágio, como produto final bonito para usuário comum.

Exemplos do que caracteriza interface técnica:

- Swagger
- chamadas REST
- JSON de resposta
- inspeção de chunks
- leitura de scores
- debug de retrieval
- execução de avaliação
- acompanhamento de métricas

### 4.3 Estado atual da camada visual

Hoje o projeto já possui uma camada visual funcional em `frontend/`.

Essa camada já cobre:

- documentos
- busca
- chat
- dashboard
- auditoria

Ela ainda está em evolução para fechamento total da Fase 2, mas já deve ser tratada como frontend canônico do programa neste momento.

---

## 5. O que ainda não deve ser considerado como interface web final

Pelo estado descrito neste guia, ainda não há evidência de um frontend web final completo com experiência comercial madura.

Ou seja, neste estágio o sistema não deve ser tratado como plataforma web final de produto, e sim como um backend operacional com interface técnica.

Isso significa que, neste momento, ainda não é obrigatório existir:

- tela de login refinada
- dashboard visual maduro
- upload visual com UX final
- chat web final para usuário comum
- painel administrativo completo
- branding / white-label
- gestão multiempresa visual
- telas prontas para operação não técnica

---

## 6. O que será a interface web final

A interface web final é a camada de produto voltada para uso operacional diário por usuários não técnicos ou sem necessidade de lidar com API diretamente.

### 6.1 Componentes esperados da interface web final

Quando evoluído, o sistema poderá ter:

### Painel de documentos

- upload por tela
- lista de documentos
- status de processamento
- filtros
- paginação
- reprocessamento
- inspeção visual de metadata

### Painel de busca e validação

- caixa de busca
- visualização dos chunks recuperados
- scores
- filtros por documento
- filtros por tipo de arquivo
- evidências destacadas

### Chat web

- campo de pergunta
- resposta pronta
- citações
- arquivos fonte
- sinalização de baixa confiança
- histórico de conversas

### Painel administrativo

- configurações
- thresholds
- embeddings
- workspaces
- gestão de usuários
- permissões
- métricas
- auditoria

### Dashboard operacional

- ingestão por período
- groundedness
- cobertura de citação
- hit rate
- latência
- falhas de parsing
- drift / necessidade de reindex

---

## 7. Estrutura de evolução por fases

A evolução correta do programa deve ser tratada por fases.

### Fase 0 — Foundation / Núcleo funcional

#### Objetivo

Construir e validar o motor RAG funcional.

#### O que entra na Fase 0

- API REST
- ingestão básica
- upload de documentos
- suporte inicial para:
  - PDF
  - DOCX
  - MD
  - TXT
- parsing
- normalização
- chunking inicial
- embeddings
- indexação no Qdrant
- retrieval híbrido inicial
- endpoint `/search`
- endpoint `/query`
- metadata de documentos
- métricas mínimas
- avaliação básica
- runbook de reindex
- Swagger/OpenAPI

#### Interface da Fase 0

A interface da Fase 0 é técnica.

Ou seja:

- Swagger
- `curl`
- API
- inspeção por JSON
- métricas via endpoint

#### O que não entra na Fase 0

- frontend comercial completo
- painel admin sofisticado
- white-label
- multitenancy avançado
- chat web final
- dashboards visuais complexos

### Fase 1 — Operação profissional

#### Objetivo

Tornar o sistema mais forte para operação técnica e validação de qualidade.

#### O que entra na Fase 1

- melhoria do retrieval
- ajustes de chunking
- reranking
- melhor telemetria
- melhores filtros
- dataset de avaliação mais robusto
- métricas mais claras
- melhor inspeção de resultados
- início de uma interface web operacional simples

#### Interface da Fase 1

A Fase 1 pode incluir um painel web técnico simples, por exemplo:

- tela de upload
- lista de documentos
- status de ingestão
- tela de testes de busca
- tela de perguntas
- visualização de chunks e scores
- painel simples de métricas

Essa interface ainda é operacional/técnica, não necessariamente o produto final.

### Fase 2 — Produto premium

#### Objetivo

Transformar o sistema em uma ferramenta mais amigável e robusta para uso diário.

#### O que entra na Fase 2

- chat web
- evidências/citações melhor apresentadas
- melhorias de groundedness
- painéis de qualidade
- filtros avançados
- histórico de consultas
- UX melhor para operador funcional
- comparação de estratégias, se necessário
- melhorias anti-hallucination
- componentes visuais mais maduros

#### Interface da Fase 2

A Fase 2 já começa a parecer um produto web real.

Pode incluir:

- chat web funcional
- página de documentos
- tela de auditoria de respostas
- dashboard visual
- navegação por workspace
- experiência mais amigável

### Fase 3 — Plataforma enterprise

#### Objetivo

Transformar o sistema em uma plataforma robusta, escalável e pronta para múltiplos clientes ou unidades.

#### O que entra na Fase 3

- multitenancy
- white-label
- painel admin completo
- gestão de usuários
- permissões
- governança
- auditoria forte
- observabilidade enterprise
- dashboards executivos
- configurações por empresa
- quotas / billing, se fizer sentido
- workflows de aprovação
- segurança endurecida

#### Interface da Fase 3

Aqui sim existe a interface web final enterprise, com cara de produto completo.

Exemplos:

- login
- gestão multiempresa
- branding por cliente
- dashboards executivos
- administração completa
- chat do usuário final
- auditoria e governança visual

---

## 8. Principais funcionalidades atuais

### Upload e ingestão de documentos

O programa aceita:

- PDF
- DOCX
- MD
- TXT

Quando você envia um arquivo, ele:

1. valida o tipo
2. extrai o texto
3. normaliza o documento
4. quebra em chunks
5. gera embeddings
6. indexa no Qdrant
7. grava o documento no filesystem

### Busca híbrida

O endpoint `/search` faz retrieval híbrido.

Isso combina:

- busca densa por embeddings
- busca esparsa por termos
- fusão por RRF

Na prática, isso melhora a chance de recuperar o trecho certo tanto para perguntas semânticas quanto para buscas literais.

### Pergunta com resposta pronta

O `/query` usa retrieval e depois pede ao modelo uma resposta final.

Ele também devolve:

- resposta
- chunks usados
- citações
- groundedness
- cobertura de citação
- sinal de baixa confiança

### Metadata de documentos

O endpoint `GET /documents/{document_id}` permite inspecionar:

- nome do arquivo
- tipo de origem
- quantidade de chunks
- data de criação
- modelo de embeddings
- data de indexação

### Avaliação automatizada

O sistema possui dataset de avaliação e endpoint de execução para medir qualidade.

Isso ajuda a responder perguntas como:

- o retrieval está acertando?
- a base piorou depois de uma mudança?
- o corpus continua recuperando o documento certo?

### Métricas operacionais

O `/metrics` expõe métricas agregadas de:

- retrieval
- respostas
- evaluation
- ingestão

Isso ajuda a acompanhar qualidade e comportamento do sistema sem abrir logs manualmente.

### Reindex e reconstrução do corpus

Se houver drift entre disco e índice, o sistema já possui fluxo de rebuild/reindex.

O runbook oficial está em:

- `docs/rag-enterprise/0024-operacao-de-corpus-e-reindex.md`

---

## 9. Como o programa funciona por dentro

### Fluxo resumido

1. documento entra
2. texto é extraído
3. documento vira JSON persistido
4. texto é quebrado em chunks
5. chunks viram vetores
6. vetores vão para o Qdrant
7. perguntas usam retrieval híbrido
8. o LLM recebe apenas o contexto recuperado
9. a resposta volta com grounding e citações

---

## 10. Forma de uso no dia a dia

### 10.1 Subir o ambiente

#### Pré-requisitos

- Python 3.12+
- Qdrant rodando
- `OPENAI_API_KEY`

#### Passos

```bash
cd src
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Depois configure no `.env`:

```bash
OPENAI_API_KEY=...
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

Suba a API:

```bash
cd src
source venv/bin/activate
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger:

- `http://localhost:8000/docs`

### 10.2 Enviar um documento

```bash
curl -X POST "http://localhost:8000/documents/upload" \
  -F "file=@politicas_fluxpay.md" \
  -F "workspace_id=default"
```

### 10.3 Fazer busca sem gerar resposta

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Qual o prazo para reembolso?",
    "workspace_id": "default",
    "top_k": 5,
    "threshold": 0.70,
    "include_raw_scores": true
  }'
```

Use isso para:

- depurar retrieval
- verificar se o documento certo está vindo
- inspecionar `scores_breakdown`
- testar filtros

### 10.4 Fazer pergunta e receber resposta pronta

```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Qual o prazo para reembolso?",
    "workspace_id": "default",
    "top_k": 5,
    "threshold": 0.70
  }'
```

O retorno inclui:

- `answer`
- `chunks_used`
- `citations`
- `confidence`
- `grounded`
- `grounding`
- `citation_coverage`
- `low_confidence`

### 10.5 Ler metadata de documento

```bash
curl "http://localhost:8000/documents/7f91fdbd-a4e3-4f24-84e3-6edaa802955b?workspace_id=default"
```

### 10.6 Rodar avaliação

```bash
curl -X POST "http://localhost:8000/evaluation/run?workspace_id=default&run_judge=false"
```

### 10.7 Consultar métricas

```bash
curl "http://localhost:8000/metrics?days=7"
```

---

## 11. Como interpretar os campos principais

### `low_confidence`

Se vier `true`, significa que o sistema entende que não encontrou base suficiente para responder bem.

Na prática:

- não trate a resposta como segura
- revise corpus
- revise pergunta
- confira se o tema realmente existe nos documentos

### `grounded`

Se vier `true`, significa que a resposta possui sustentação suficiente segundo a regra atual.

Se vier `false`, pode significar:

- baixa cobertura de citação
- claims sem apoio suficiente
- resposta fraca
- contexto inadequado

### `citation_coverage`

É a fração da resposta coberta por citações.

Quanto mais alto, melhor.

### `needs_review`

Indica que a resposta merece revisão humana.

### `document_filename`

Ajuda a saber de qual arquivo o chunk ou a resposta veio.

Isso é importante para auditoria e rastreabilidade.

---

## 12. O que o operador deve fazer no dia a dia

### Rotina básica

1. subir a API
2. confirmar `/health`
3. enviar documentos novos
4. testar perguntas críticas
5. acompanhar `/metrics`
6. rodar avaliação após mudança relevante

### Quando algo parecer errado

Verifique nesta ordem:

1. o documento está no corpus canônico?
2. o upload retornou `parsed`?
3. o metadata endpoint mostra `chunk_count` correto?
4. o `/search` recupera trechos úteis?
5. o `low_confidence` está alto?
6. há drift entre Qdrant e disco?

Se houver drift:

- usar o runbook `0024-operacao-de-corpus-e-reindex.md`

---

## 13. Exemplos de uso real

### Atendimento interno

Pergunta:

- “Qual o prazo para reembolso?”

O sistema:

- acha a regra no documento
- responde de forma objetiva
- mostra a origem da informação

### Conferência operacional

Pergunta:

- “Esse processo exige aprovação?”

O sistema:

- recupera o trecho relevante
- reduz busca manual em várias páginas

### Auditoria rápida

Pergunta:

- “De qual documento veio essa resposta?”

O sistema:

- devolve `document_filename`
- mostra chunks usados
- oferece rastreabilidade

### Quando o sistema deve recusar

Pergunta:

- “Como assar um bolo de chocolate?”

Se isso não existir no corpus, o sistema deve sinalizar baixa confiança.

Isso é importante para evitar resposta artificialmente confiante em tema fora da base.

---

## 14. O que este programa não substitui

Ele não substitui:

- revisão humana em casos críticos
- governança documental
- curadoria do corpus
- validação jurídica
- validação financeira
- validação regulatória

Ele acelera acesso à informação e melhora consistência operacional, mas não elimina julgamento humano.

---

## 15. Boas práticas de uso

- use documentos limpos e atualizados
- evite múltiplas versões conflitantes no corpus ativo
- rode avaliação após mudanças de retrieval, chunking ou corpus
- acompanhe groundedness e `low_confidence`
- use reindex apenas quando houver necessidade operacional real

---

## 16. Estrutura mínima para lembrar

- enviar documentos: `POST /documents/upload`
- buscar trechos: `POST /search`
- perguntar e receber resposta: `POST /query`
- inspecionar documento: `GET /documents/{document_id}`
- ver métricas: `GET /metrics`
- rodar avaliação: `POST /evaluation/run`

---

## 17. Resumo executivo

No dia a dia, este programa resolve um problema simples e valioso:

> transformar documentos soltos em uma base pesquisável, perguntável e auditável.

Hoje ele já funciona como:

- motor RAG operacional com interface técnica

No futuro, ele pode evoluir para:

- plataforma web enterprise com chat, painel, administração e multitenancy

---

## 18. Resumo final por fase

### Fase 0

- motor RAG funcional
- API
- Swagger
- operação técnica

### Fase 1

- operação profissional
- telemetria melhor
- painel técnico simples

### Fase 2

- produto premium
- chat web
- dashboards
- melhor UX

### Fase 3

- plataforma enterprise
- multitenancy
- admin completo
- white-label
- governança

---

## 19. Referências rápidas

- guia técnico de operação: `src/README.md`
- runbook de corpus e reindex: `docs/rag-enterprise/0024-operacao-de-corpus-e-reindex.md`
- execution log oficial: `docs/rag-enterprise/0020-master-execution-log.md`
