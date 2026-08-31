# 0028 — Backlog por Sprint do Frontend Premium

## Objetivo

Transformar o plano da Fase 2 em backlog executável por sprint, com itens claros para:

- frontend
- backend
- UX e conteúdo
- QA e validação

Este documento complementa o `0027-plano-de-implementacao-do-frontend-premium.md`.

---

## Como usar este backlog

Cada sprint deve produzir:

- tela utilizável
- integração real com backend
- estados de erro e loading minimamente tratados
- evidência demonstrável
- critério de aceite verificável

Regra de execução:

1. fechar frontend e contrato da sprint juntos
2. não deixar endpoint “para depois” se a tela depender dele
3. não aprovar sprint apenas com mock visual
4. registrar gaps reais no execution log

### Estado atual da implementação

Leitura honesta do código em `2026-04-16`:

- `frontend/` é o app canônico em evolução
- não existe base paralela ativa de frontend fora de `frontend/`
- `F1-F6` já possuem implementação material
- `F7` já está materialmente implementado com persistência de contexto, breadcrumbs, hardening e responsividade consolidada
- `F8` está na etapa de validação formal do gate visual, com a implementação técnica já fechada

---

## Sprint F1 — Base do Frontend e Layout

### Resultado esperado

Existir um app frontend navegável, visualmente consistente e pronto para receber as telas da Fase 2.

### Backlog de frontend

- criar aplicação `Next.js`
- definir estrutura de rotas base:
  - `/`
  - `/documents`
  - `/search`
  - `/chat`
  - `/dashboard`
  - `/audit`
- criar shell global:
  - sidebar
  - header
  - área principal
- criar sistema visual base:
  - cores
  - tipografia
  - espaçamentos
  - bordas
  - estados
- criar componentes base:
  - botão
  - input
  - textarea
  - select
  - card
  - badge
  - table
  - tabs
  - modal
  - drawer
  - toast
  - skeleton
  - empty state
  - error state
- criar página inicial com cards de navegação para os módulos
- implementar responsividade básica desktop e tablet

### Backlog de backend

- validar `GET /health` como endpoint de healthcheck para o frontend
- garantir CORS adequado para frontend local
- documentar URL base de API e estratégia de ambiente

### Backlog de UX e conteúdo

- definir linguagem visual da Fase 2
- definir padrão de títulos, subtítulos e descrições curtas por página
- definir padrão visual para estados:
  - carregando
  - vazio
  - erro
  - sucesso

### Backlog de QA

- validar navegação entre rotas
- validar renderização sem quebrar em refresh
- validar layout mínimo em desktop
- validar layout mínimo em tablet

### Critério de aceite

- app sobe localmente
- navegação funciona entre os módulos
- componentes base existem e suportam as próximas telas
- produto já parece software e não template cru

### Plano executável do Sprint F1

#### Ordem recomendada de implementação

1. inicializar o app frontend
2. configurar tema e tokens visuais
3. montar shell global
4. criar rotas placeholder
5. construir biblioteca mínima de componentes
6. integrar healthcheck
7. fechar estados globais de loading, erro e vazio
8. validar responsividade básica

#### Bloco F1.1 — Bootstrap do app

Objetivo:

- deixar a aplicação frontend rodando localmente com estrutura limpa

Tarefas:

- criar diretório do frontend
- inicializar projeto `Next.js` com `App Router`
- configurar TypeScript
- configurar lint e formatação
- configurar aliases de import
- configurar variáveis de ambiente do frontend
- definir `NEXT_PUBLIC_API_BASE_URL`

Entregáveis:

- app sobe com comando único
- estrutura inicial pronta para expansão

#### Bloco F1.2 — Estrutura de pastas e arquitetura de UI

Objetivo:

- evitar crescimento caótico do frontend

Tarefas:

- definir estrutura mínima de pastas:
  - `app/`
  - `components/`
  - `components/ui/`
  - `components/layout/`
  - `lib/`
  - `services/`
  - `types/`
  - `styles/`
- separar componentes de layout dos componentes de UI
- definir camada simples para consumo de API
- definir convenção para tipos compartilhados do frontend

Entregáveis:

- arquitetura de frontend documentada e previsível

#### Bloco F1.3 — Sistema visual base

Objetivo:

- criar uma identidade visual coerente para a Fase 2

Tarefas:

- definir paleta principal
- definir paleta semântica:
  - sucesso
  - alerta
  - erro
  - informação
- definir tipografia
- definir escala de espaçamento
- definir bordas, sombras e raios
- definir grid e largura máxima das páginas
- criar tokens CSS ou tema centralizado

Entregáveis:

- base visual reutilizável nas próximas telas

#### Bloco F1.4 — Shell global

Objetivo:

- criar a moldura de navegação do produto

Tarefas:

- construir `sidebar`
- construir `header`
- construir área principal com conteúdo scrollável
- marcar rota ativa na navegação
- incluir acesso visível aos módulos:
  - início
  - documentos
  - busca
  - chat
  - dashboard
  - auditoria
- preparar espaço para ações globais futuras

Entregáveis:

- layout principal utilizável
- navegação consistente entre páginas

#### Bloco F1.5 — Rotas placeholder

Objetivo:

- preparar a navegação real da Fase 2

Tarefas:

- criar página `/`
- criar página `/documents`
- criar página `/search`
- criar página `/chat`
- criar página `/dashboard`
- criar página `/audit`
- em cada página, incluir:
  - título
  - descrição curta
  - estado placeholder com contexto da tela

Entregáveis:

- rotas funcionando com conteúdo mínimo e consistente

#### Bloco F1.6 — Componentes base

Objetivo:

- formar o kit inicial de interface para acelerar os próximos sprints

Tarefas:

- criar `Button`
- criar `Input`
- criar `Textarea`
- criar `Select`
- criar `Card`
- criar `Badge`
- criar `Table`
- criar `Tabs`
- criar `Modal`
- criar `Drawer`
- criar `Toast`
- criar `Skeleton`
- criar `EmptyState`
- criar `ErrorState`
- garantir variantes mínimas dos componentes mais usados

Entregáveis:

- biblioteca de UI suficiente para F2, F3 e F4

#### Bloco F1.7 — Estado global mínimo e integração técnica

Objetivo:

- preparar o frontend para conversar com a API sem acoplamento improvisado

Tarefas:

- criar utilitário de cliente HTTP
- padronizar tratamento de erro de requisição
- implementar verificação de `GET /health`
- exibir estado simples de conectividade da API
- validar CORS no ambiente local

Entregáveis:

- frontend pronto para integração real com backend

#### Bloco F1.8 — Responsividade e polimento inicial

Objetivo:

- garantir que a base não fique quebrada fora do desktop largo

Tarefas:

- ajustar layout para desktop
- ajustar layout para tablet
- garantir sidebar e header utilizáveis em largura reduzida
- revisar overflow, scroll e truncamento
- revisar empty states e skeletons

Entregáveis:

- experiência mínima consistente em desktop e tablet

### Definição de pronto do Sprint F1

O Sprint F1 só deve ser considerado concluído quando:

- o frontend subir localmente sem ajustes manuais obscuros
- as seis rotas base existirem e navegarem entre si
- o shell global estiver implementado
- existir biblioteca mínima de componentes reutilizáveis
- o tema visual estiver definido
- o healthcheck da API estiver integrado
- a responsividade básica estiver validada

### Saída esperada para iniciar o Sprint F2

Ao final do F1, o time deve ter:

- base visual pronta
- base de navegação pronta
- base de integração com API pronta
- estrutura de componentes pronta
- páginas de documentos, busca, chat, dashboard e auditoria preparadas para evolução

### Riscos que invalidam o fechamento do F1

- layout bonito mas sem estrutura de rotas real
- páginas só com mock estático sem navegação
- componentes visuais sem reutilização real
- ausência de integração mínima com `GET /health`
- base responsiva quebrada
- shell global inconsistente entre páginas

---

## Sprint F2 — Painel de Documentos

### Resultado esperado

Operador consegue subir documento, visualizar lista, inspecionar metadata e entender o estado do corpus sem Swagger.

### Backlog de frontend

- construir página `/documents`
- implementar tabela/lista de documentos
- implementar área de upload visual
- implementar estado de upload em progresso
- implementar sucesso e erro de upload
- implementar modal ou drawer de metadata do documento
- implementar filtros visuais:
  - nome
  - tipo de arquivo
  - status
- implementar paginação
- exibir colunas mínimas:
  - filename
  - source_type
  - chunk_count
  - status
  - created_at
  - indexed_at
- adicionar ação “ver detalhes”
- preparar ação visual “reprocessar” mesmo que ainda bloqueada por backend

### Backlog de backend

- garantir `POST /documents/upload` está estável para uso web
- garantir `GET /documents/{document_id}` retorna metadata completa
- implementar `GET /documents?workspace_id=...`
- definir payload de listagem com:
  - `document_id`
  - `filename`
  - `source_type`
  - `chunk_count`
  - `status`
  - `created_at`
  - `indexed_at`
  - `tags`
- definir paginação e ordenação mínima
- padronizar erros de upload para mensagem amigável

### Backlog de UX e conteúdo

- definir mensagens de erro de upload:
  - tipo inválido
  - arquivo vazio
  - falha de parsing
  - falha de indexação
- definir empty state para corpus vazio
- definir microcopy do painel de documentos

### Backlog de QA

- testar upload de `pdf`
- testar upload de `docx`
- testar upload de `md`
- testar upload de `txt`
- testar metadata visual
- testar lista com corpus pequeno
- testar lista com corpus médio
- testar erro de upload

### Critério de aceite

- documento pode ser enviado pela UI
- documento aparece listado sem inspeção manual de disco
- metadata é compreensível para operador
- tela sustenta rotina básica de ingestão

### Plano executável do Sprint F2

#### Ordem recomendada de implementação

1. fechar contrato de listagem de documentos
2. implementar página de documentos com estrutura base
3. integrar upload visual
4. integrar metadata detalhada
5. fechar filtros, paginação e estados da tela
6. validar erros de upload e comportamento com corpus real

#### Bloco F2.1 — Contrato de documentos e base de dados da tela

Objetivo:

- garantir que a tela opere com payload estável e suficiente

Tarefas:

- validar `POST /documents/upload`
- validar `GET /documents/{document_id}`
- implementar `GET /documents?workspace_id=...`
- definir payload mínimo da listagem:
  - `document_id`
  - `filename`
  - `source_type`
  - `chunk_count`
  - `status`
  - `created_at`
  - `indexed_at`
  - `tags`
- definir ordenação padrão
- definir paginação mínima
- definir shape de erro de upload

Entregáveis:

- contrato de documentos pronto para consumo visual

#### Bloco F2.2 — Estrutura da página `/documents`

Objetivo:

- criar a moldura funcional do painel de documentos

Tarefas:

- montar cabeçalho da página com título e descrição
- criar área de ações do módulo
- criar região de filtros
- criar região de tabela/lista
- criar estado vazio do corpus
- criar estado de carregamento da lista
- criar estado de erro da lista

Entregáveis:

- página de documentos estruturada e navegável

#### Bloco F2.3 — Upload visual

Objetivo:

- permitir ingestão de documentos pela interface web

Tarefas:

- criar componente de upload
- permitir seleção de arquivo por clique
- permitir arrastar e soltar, se fizer sentido
- enviar `workspace_id` junto do upload
- exibir progresso ou estado de envio
- exibir sucesso de upload
- exibir erro de upload com mensagem legível
- invalidar ou atualizar a lista após upload bem-sucedido

Entregáveis:

- operador consegue subir documentos sem Swagger

#### Bloco F2.4 — Listagem de documentos

Objetivo:

- tornar o corpus visível de forma útil

Tarefas:

- implementar tabela ou cards de documentos
- exibir colunas principais:
  - filename
  - source_type
  - chunk_count
  - status
  - created_at
  - indexed_at
- destacar status visualmente
- permitir ação “ver detalhes”
- preparar ação “reprocessar” como botão desabilitado ou oculto até backend existir

Entregáveis:

- corpus pode ser inspecionado visualmente

#### Bloco F2.5 — Metadata e detalhe de documento

Objetivo:

- permitir inspeção rápida de um documento sem sair da tela

Tarefas:

- criar modal ou drawer de metadata
- integrar `GET /documents/{document_id}`
- exibir no detalhe ao menos:
  - document_id
  - filename
  - source_type
  - chunk_count
  - created_at
  - indexed_at
  - embeddings_model
  - tags
- definir layout limpo para o detalhe

Entregáveis:

- metadata pode ser aberta e entendida rapidamente

#### Bloco F2.6 — Filtros, paginação e estados operacionais

Objetivo:

- permitir uso real em corpus pequeno e médio

Tarefas:

- implementar filtro por nome
- implementar filtro por tipo de arquivo
- implementar filtro por status
- implementar paginação
- implementar mensagem para “nenhum documento encontrado”
- implementar refresh da lista
- persistir filtro mínimo na rota, se conveniente

Entregáveis:

- tela continua utilizável com volume crescente de documentos

#### Bloco F2.7 — Copy, UX e feedback visual

Objetivo:

- fazer a tela parecer produto e não painel cru

Tarefas:

- definir texto do cabeçalho da página
- definir microcopy do upload
- definir mensagens de erro:
  - tipo inválido
  - arquivo vazio
  - falha de parsing
  - falha de indexação
- definir empty state para corpus vazio
- definir feedback de sucesso pós-upload

Entregáveis:

- mensagens claras para operador técnico e funcional

#### Bloco F2.8 — QA funcional do módulo

Objetivo:

- fechar o módulo com evidência de uso real

Tarefas:

- testar upload de `pdf`
- testar upload de `docx`
- testar upload de `md`
- testar upload de `txt`
- testar listagem com corpus pequeno
- testar listagem com corpus médio
- testar detalhe de metadata
- testar erro de upload
- testar atualização da lista após envio

Entregáveis:

- checklist funcional do módulo executado

### Definição de pronto do Sprint F2

O Sprint F2 só deve ser considerado concluído quando:

- a página `/documents` estiver funcional
- o upload visual estiver integrado ao backend real
- a listagem de documentos funcionar sem inspeção manual de arquivos
- a metadata detalhada puder ser aberta pela interface
- filtros e paginação estiverem implementados no nível mínimo necessário
- a tela estiver utilizável com corpus pequeno e médio

### Saída esperada para iniciar o Sprint F3

Ao final do F2, o time deve ter:

- painel de documentos operacional
- contrato de listagem de documentos estabilizado
- fluxo real de ingestão pela UI
- base visual e estrutural pronta para busca e chat

### Riscos que invalidam o fechamento do F2

- upload funcionando só no happy path
- lista dependendo de refresh manual obscuro
- metadata incompleta ou ilegível
- contrato de listagem instável
- tela boa para demo, mas ruim para corpus real
- erros de upload sem mensagem útil

---

## Sprint F3 — Tela de Busca e Validação

### Resultado esperado

Operador consegue validar retrieval visualmente, entender ranking e inspecionar evidências.

### Backlog de frontend

- construir página `/search`
- implementar caixa de busca
- implementar formulário com:
  - query
  - top_k
  - threshold
  - include_raw_scores
- implementar painel lateral de filtros:
  - `document_id`
  - `source_type`
  - `tags`
  - faixa de página
- implementar lista de resultados
- exibir por resultado:
  - chunk
  - document_filename
  - document_id
  - score final
  - score breakdown
  - page_hint
  - tags
- implementar seleção de resultado para abrir evidência expandida
- destacar termos buscados quando fizer sentido

### Backlog de backend

- garantir `POST /search` está estável para uso visual
- padronizar payload de filtros suportados
- garantir `include_raw_scores=true` retorna `scores_breakdown`
- expor fonte de dados para popular filtros:
  - documentos
  - tags
  - tipos
- se necessário, implementar endpoint auxiliar para catálogo de filtros

### Backlog de UX e conteúdo

- definir visual de score e confiança do resultado
- definir como apresentar `scores_breakdown` sem poluir a tela
- definir empty state para busca sem resultados
- definir mensagem para retrieval de baixa qualidade

### Backlog de QA

- validar busca com resultado forte
- validar busca sem resultado
- validar filtros por `document_id`
- validar filtros por `source_type`
- validar filtros por `tags`
- validar faixa de página
- validar exibição de `scores_breakdown`

### Critério de aceite

- operador valida retrieval sem Swagger
- evidências ficam legíveis
- filtros funcionam como no backend
- página ajuda debug real de qualidade

### Plano executável do Sprint F3

#### Ordem recomendada de implementação

1. fechar payload de busca e catálogo de filtros
2. montar a estrutura da página `/search`
3. integrar formulário de busca
4. renderizar resultados e evidências
5. integrar filtros visuais
6. expor score e `scores_breakdown`
7. fechar estados vazios, erros e busca sem resultado
8. validar comportamento com queries reais de recuperação

#### Bloco F3.1 — Contrato de busca e dados auxiliares

Objetivo:

- garantir que a página de validação opere com payload estável e informativo

Tarefas:

- validar `POST /search`
- revisar contrato de:
  - `query`
  - `workspace_id`
  - `top_k`
  - `threshold`
  - `include_raw_scores`
  - `filters`
- garantir retorno consistente de:
  - chunk
  - `document_filename`
  - `document_id`
  - score final
  - `scores_breakdown`
  - `page_hint`
  - `tags`
  - `source_type`
- definir fonte de dados para popular filtros
- se necessário, implementar endpoint auxiliar para catálogo de filtros

Entregáveis:

- contrato de busca pronto para consumo visual

#### Bloco F3.2 — Estrutura da página `/search`

Objetivo:

- criar a base funcional da tela de busca e validação

Tarefas:

- montar cabeçalho com título e descrição
- criar área do formulário de busca
- criar painel lateral de filtros
- criar região de lista de resultados
- criar painel de detalhe/evidência expandida
- criar estado inicial antes da primeira busca
- criar estado vazio da busca
- criar estado de erro da busca

Entregáveis:

- página de busca estruturada e pronta para integração completa

#### Bloco F3.3 — Formulário de busca

Objetivo:

- permitir execução real de retrieval pela interface

Tarefas:

- criar campo principal de query
- criar controles de:
  - `top_k`
  - `threshold`
  - `include_raw_scores`
- permitir submissão por botão e `Enter`
- integrar request ao backend
- exibir loading durante a busca
- preservar a última query executada na tela

Entregáveis:

- operador consegue buscar sem depender do Swagger

#### Bloco F3.4 — Lista de resultados e evidências

Objetivo:

- tornar o resultado do retrieval auditável e compreensível

Tarefas:

- renderizar lista de resultados
- exibir por item:
  - trecho do chunk
  - `document_filename`
  - `document_id`
  - score final
  - `page_hint`
  - `source_type`
  - `tags`
- permitir seleção de um resultado
- abrir painel de evidência expandida
- destacar o chunk selecionado

Entregáveis:

- evidências podem ser inspecionadas visualmente

#### Bloco F3.5 — Filtros de busca

Objetivo:

- permitir validação dirigida do retrieval

Tarefas:

- implementar filtro por `document_id`
- implementar filtro por `source_type`
- implementar filtro por `tags`
- implementar filtro por faixa de página
- exibir filtros ativos
- permitir limpar filtros rapidamente
- refletir filtros no request enviado ao backend

Entregáveis:

- operador consegue restringir o retrieval pela UI

#### Bloco F3.6 — Visualização de score e breakdown

Objetivo:

- explicar por que determinado resultado subiu no ranking

Tarefas:

- definir componente visual para score principal
- definir exibição compacta de `scores_breakdown`
- exibir `scores_breakdown` quando `include_raw_scores=true`
- esconder ou simplificar esse bloco quando não solicitado
- evitar poluição visual excessiva

Entregáveis:

- score e breakdown ficam úteis para debug operacional

#### Bloco F3.7 — UX, copy e estados da busca

Objetivo:

- fazer a tela servir para operação real e não só inspeção técnica crua

Tarefas:

- definir microcopy do módulo
- definir mensagem para busca sem resultados
- definir mensagem para retrieval fraco
- definir empty state pré-busca
- definir feedback de erro de consulta
- revisar legibilidade de chunks longos

Entregáveis:

- experiência de validação mais clara para o operador

#### Bloco F3.8 — QA funcional do módulo

Objetivo:

- fechar o módulo com evidência reproduzível

Tarefas:

- validar busca com resultado forte
- validar busca sem resultado
- validar filtro por `document_id`
- validar filtro por `source_type`
- validar filtro por `tags`
- validar faixa de página
- validar exibição de `scores_breakdown`
- validar navegação entre resultados e painel de evidência

Entregáveis:

- checklist funcional da tela de busca executado

### Definição de pronto do Sprint F3

O Sprint F3 só deve ser considerado concluído quando:

- a página `/search` estiver funcional
- o operador conseguir executar buscas reais pela UI
- resultados exibirem evidências legíveis
- filtros da UI refletirem o comportamento do backend
- `scores_breakdown` estiver visualmente acessível quando solicitado
- a tela ajudar validação real de retrieval

### Saída esperada para iniciar o Sprint F4

Ao final do F3, o time deve ter:

- tela de busca operacional
- contrato de busca estabilizado para uso visual
- base forte para o chat web reutilizar padrões de evidência
- feedback claro sobre qualidade de retrieval

### Riscos que invalidam o fechamento do F3

- busca funcionando só com query simples e sem filtros
- chunk ilegível ou truncado a ponto de perder valor operacional
- `scores_breakdown` confuso ou inútil
- filtros da UI não refletirem o backend real
- página boa para demo, mas ruim para debug de retrieval

---

## Sprint F4 — Chat Web

### Resultado esperado

Existir uma interface principal de perguntas e respostas utilizável no dia a dia.

### Backlog de frontend

- construir página `/chat`
- implementar input principal de pergunta
- implementar lista de mensagens da sessão
- implementar estado de carregamento da resposta
- implementar bloco de resposta com:
  - answer
  - citations
  - chunks usados
  - document_filename
  - confidence
  - grounded
  - citation_coverage
  - low_confidence
  - needs_review
- implementar visual de citações clicáveis/expansíveis
- implementar histórico local de sessão
- implementar ação de copiar resposta
- implementar ação de expandir contexto usado

### Backlog de backend

- garantir `POST /query` está estável para uso visual
- garantir payload retorna campos usados pelo chat
- opcional: criar persistência básica de histórico por sessão
- opcional: endpoint para listar histórico de conversas

### Backlog de UX e conteúdo

- definir hierarquia visual da resposta
- definir padrão de badges:
  - baixa confiança
  - grounded
  - needs review
- definir mensagens para:
  - resposta fraca
  - sem contexto
  - falha do modelo

### Backlog de QA

- validar query com resposta forte
- validar query com `low_confidence=true`
- validar query com `needs_review=true`
- validar visualização de citações
- validar comportamento em erro de backend
- validar retenção do histórico local na sessão

### Critério de aceite

- usuário consegue perguntar sem interface técnica
- resposta tem visual de produto
- citações e confiança são legíveis
- tela serve como interface principal de uso

### Plano executável do Sprint F4

#### Ordem recomendada de implementação

1. fechar contrato visual do `/query`
2. montar a estrutura da página `/chat`
3. integrar envio de pergunta e loading
4. renderizar resposta com hierarquia forte
5. integrar citações e contexto usado
6. expor confiança, groundedness e revisão
7. persistir histórico local da sessão
8. validar comportamento com respostas fortes e fracas

#### Bloco F4.1 — Contrato de query e payload da resposta

Objetivo:

- garantir que o chat opere com dados suficientes para uma UI premium

Tarefas:

- validar `POST /query`
- revisar payload de request:
  - `query`
  - `workspace_id`
  - `top_k`
  - `threshold`
- garantir retorno consistente de:
  - `answer`
  - `chunks_used`
  - `citations`
  - `document_filename`
  - `confidence`
  - `grounded`
  - `grounding`
  - `citation_coverage`
  - `low_confidence`
  - `needs_review`
- revisar estabilidade do shape para renderização visual
- definir estratégia para histórico local ou persistido

Entregáveis:

- contrato de query pronto para a tela principal do produto

#### Bloco F4.2 — Estrutura da página `/chat`

Objetivo:

- criar a principal interface de uso diário do sistema

Tarefas:

- montar cabeçalho da página
- criar área de mensagens
- criar região fixa ou clara para o input principal
- criar estado inicial antes da primeira pergunta
- criar estado de carregamento da resposta
- criar estado de erro do chat
- preparar layout confortável para leitura longa

Entregáveis:

- tela de chat estruturada para uso real

#### Bloco F4.3 — Envio de perguntas e ciclo de resposta

Objetivo:

- permitir interação principal com o produto

Tarefas:

- implementar input principal
- permitir envio por botão e `Enter`
- bloquear envio duplicado durante loading
- integrar request ao backend
- renderizar pergunta do usuário na sessão
- renderizar estado de resposta em progresso
- renderizar resposta final do sistema

Entregáveis:

- usuário consegue perguntar e receber resposta pela UI

#### Bloco F4.4 — Renderização premium da resposta

Objetivo:

- transformar a resposta em experiência de produto e não só texto cru

Tarefas:

- criar componente de mensagem do sistema
- destacar resposta principal
- separar claramente:
  - resposta
  - evidências
  - indicadores de confiança
- permitir copiar resposta
- tratar respostas longas com boa legibilidade
- revisar hierarquia visual para leitura rápida

Entregáveis:

- resposta fica clara, escaneável e com aparência de produto premium

#### Bloco F4.5 — Citações e contexto usado

Objetivo:

- deixar a resposta auditável diretamente no chat

Tarefas:

- exibir lista de citações
- exibir `document_filename` por citação
- permitir expandir ou recolher contexto citado
- exibir `chunks_used`
- destacar a origem documental da resposta
- permitir navegação visual entre resposta e evidências

Entregáveis:

- usuário entende de onde veio a resposta

#### Bloco F4.6 — Confiança, groundedness e revisão

Objetivo:

- tornar sinais de qualidade visíveis e acionáveis

Tarefas:

- exibir `confidence`
- exibir `grounded`
- exibir `citation_coverage`
- exibir `low_confidence`
- exibir `needs_review`
- definir badges e cores para cada estado
- definir microcopy para:
  - baixa confiança
  - grounding fraco
  - revisão necessária

Entregáveis:

- a UI não mascara respostas frágeis como seguras

#### Bloco F4.7 — Histórico local e persistência básica da sessão

Objetivo:

- evitar que o chat pareça one-shot e frágil

Tarefas:

- manter histórico local da conversa na sessão
- permitir múltiplas perguntas sequenciais
- garantir scroll adequado da conversa
- preservar estado ao navegar internamente, se viável
- opcional: persistir sessão local no navegador

Entregáveis:

- chat se comporta como ferramenta de uso contínuo

#### Bloco F4.8 — UX, copy e estados do chat

Objetivo:

- tornar a experiência clara também em casos imperfeitos

Tarefas:

- definir texto do empty state do chat
- definir mensagem para resposta de baixa confiança
- definir mensagem para ausência de contexto suficiente
- definir mensagem para falha do modelo
- revisar legibilidade das badges e dos painéis de evidência

Entregáveis:

- operador entende quando confiar e quando revisar

#### Bloco F4.9 — QA funcional do módulo

Objetivo:

- fechar o chat com evidência funcional real

Tarefas:

- validar query com resposta forte
- validar query com `low_confidence=true`
- validar query com `needs_review=true`
- validar exibição de citações
- validar exibição de `document_filename`
- validar comportamento em erro de backend
- validar histórico local da sessão
- validar leitura em respostas longas

Entregáveis:

- checklist funcional do chat executado

### Definição de pronto do Sprint F4

O Sprint F4 só deve ser considerado concluído quando:

- a página `/chat` estiver funcional
- o usuário conseguir perguntar sem interface técnica
- a resposta exibir evidências e sinais de confiança de forma legível
- a UI deixar clara a origem documental da resposta
- o histórico local da sessão estiver funcionando no nível mínimo esperado
- a tela puder ser usada como interface principal do produto

### Saída esperada para iniciar o Sprint F5

Ao final do F4, o time deve ter:

- chat web operacional
- padrão visual sólido para respostas e evidências
- base reutilizável para auditoria de respostas
- interface principal do produto pronta para demonstração

### Riscos que invalidam o fechamento do F4

- chat bonito mas sem transparência de evidência
- resposta sem `document_filename` ou contexto útil
- sinais de confiança escondidos ou confusos
- histórico da sessão quebrando facilmente
- UX boa só no happy path
- tela parecendo wrapper de JSON com balões

---

## Sprint F5 — Dashboard Operacional

### Resultado esperado

Operador consegue entender rapidamente a saúde do sistema por uma tela visual.

### Backlog de frontend

- construir página `/dashboard`
- implementar cards de KPI
- implementar seções separadas:
  - ingestion
  - retrieval
  - answer
  - evaluation
- implementar gráficos simples ou barras de comparação
- destacar:
  - hit rate
  - groundedness
  - citation coverage
  - low confidence
  - latência
  - parse failures
- implementar filtros por período
- implementar estados de loading, vazio e erro

### Backlog de backend

- garantir `GET /metrics` está estável para consumo de dashboard
- estabilizar shape das métricas por bloco
- se necessário, implementar resumo por período
- se necessário, implementar séries temporais mínimas

### Backlog de UX e conteúdo

- definir semáforo ou indicador visual para métricas críticas
- definir mensagens interpretativas:
  - groundedness baixa
  - hit rate ruim
  - parse failures elevadas
- definir ordem de prioridade visual dos KPIs

### Backlog de QA

- validar renderização com payload completo
- validar comportamento com dados parciais
- validar filtros de período
- validar que métricas críticas aparecem de forma acionável

### Critério de aceite

- dashboard ajuda rotina operacional diária
- operador entende o estado do sistema em poucos segundos
- métricas não parecem dump de JSON

### Plano executável do Sprint F5

#### Ordem recomendada de implementação

1. estabilizar o contrato visual de `/metrics`
2. montar a estrutura da página `/dashboard`
3. implementar cards de KPI
4. implementar blocos por domínio operacional
5. integrar filtros de período
6. adicionar gráficos simples e alertas
7. fechar interpretações visuais de métricas críticas
8. validar leitura operacional com dados completos e parciais

#### Bloco F5.1 — Contrato de métricas e shape do dashboard

Objetivo:

- garantir que o dashboard consuma métricas de forma previsível

Tarefas:

- validar `GET /metrics`
- revisar shape por bloco:
  - `ingestion`
  - `retrieval`
  - `answer`
  - `evaluation`
- garantir retorno consistente de KPIs principais
- definir quais métricas entram no dashboard inicial
- se necessário, estabilizar resumo por período
- se necessário, estabilizar séries temporais mínimas

Entregáveis:

- contrato de métricas pronto para consumo visual

#### Bloco F5.2 — Estrutura da página `/dashboard`

Objetivo:

- criar a base da tela de monitoramento operacional

Tarefas:

- montar cabeçalho da página
- criar área de filtros globais
- criar região de KPIs principais
- criar seções separadas por domínio
- criar estado inicial da página
- criar estado de carregamento
- criar estado de erro
- criar estado com dados parciais

Entregáveis:

- dashboard estruturado para receber os blocos analíticos

#### Bloco F5.3 — KPIs principais

Objetivo:

- resumir rapidamente a saúde do sistema

Tarefas:

- criar cards para:
  - hit rate
  - groundedness
  - citation coverage
  - low confidence
  - latência
  - parse failures
- definir variação visual de KPI crítico
- destacar métricas que exigem ação
- manter leitura rápida e escaneável

Entregáveis:

- operador entende o status geral em poucos segundos

#### Bloco F5.4 — Blocos por domínio operacional

Objetivo:

- separar claramente ingestão, retrieval, respostas e avaliação

Tarefas:

- criar seção de `ingestion`
- criar seção de `retrieval`
- criar seção de `answer`
- criar seção de `evaluation`
- exibir métricas de cada bloco em agrupamentos claros
- evitar mistura visual entre métricas de naturezas diferentes

Entregáveis:

- leitura operacional por domínio fica clara e acionável

#### Bloco F5.5 — Filtro por período e contexto temporal

Objetivo:

- permitir leitura operacional por janela de tempo

Tarefas:

- implementar seletor de período
- refletir o período na consulta das métricas
- exibir claramente o intervalo ativo
- tratar ausência de dados no período
- revisar impacto do período nos gráficos e KPIs

Entregáveis:

- dashboard responde ao contexto temporal de uso

#### Bloco F5.6 — Gráficos simples e indicadores visuais

Objetivo:

- enriquecer a leitura sem transformar a tela em painel confuso

Tarefas:

- escolher gráficos simples ou barras comparativas
- representar tendência mínima quando houver dado temporal
- adicionar indicadores de alerta para:
  - groundedness baixa
  - hit rate ruim
  - parse failures altas
  - latência elevada
- garantir legibilidade dos gráficos sem excesso visual

Entregáveis:

- dashboard fica mais informativo sem perder clareza

#### Bloco F5.7 — UX, copy e leitura operacional

Objetivo:

- garantir que a tela não dependa de leitura técnica profunda

Tarefas:

- definir microcopy dos blocos
- definir mensagens interpretativas para métricas críticas
- revisar títulos e subtítulos
- revisar ordem de prioridade visual dos KPIs
- definir empty state para ambiente sem histórico relevante

Entregáveis:

- operador entende o que olhar e por quê

#### Bloco F5.8 — QA funcional do módulo

Objetivo:

- fechar o dashboard com evidência de leitura real

Tarefas:

- validar renderização com payload completo
- validar renderização com payload parcial
- validar comportamento com ausência de dados
- validar filtros de período
- validar exibição de alertas críticos
- validar separação visual entre ingestion, retrieval, answer e evaluation

Entregáveis:

- checklist funcional do dashboard executado

### Definição de pronto do Sprint F5

O Sprint F5 só deve ser considerado concluído quando:

- a página `/dashboard` estiver funcional
- KPIs principais estiverem visíveis e úteis
- métricas estiverem separadas por domínio operacional
- filtros de período estiverem funcionando
- o dashboard permitir leitura rápida da saúde do sistema
- a tela servir para rotina diária e não apenas demonstração

### Saída esperada para iniciar o Sprint F6

Ao final do F5, o time deve ter:

- dashboard operacional utilizável
- contrato de métricas estabilizado para UI
- sinais de qualidade visíveis de forma acionável
- base visual e estrutural pronta para auditoria de respostas

### Riscos que invalidam o fechamento do F5

- dashboard bonito mas sem utilidade operacional
- métricas exibidas como dump visual sem interpretação
- blocos misturando ingestion, retrieval e answer de forma confusa
- filtro de período inconsistente
- ausência de destaque para métricas críticas
- tela boa para demo, mas ruim para monitoramento diário

---

## Sprint F6 — Auditoria de Respostas

### Resultado esperado

Existir uma tela específica para revisão de respostas frágeis e triagem de qualidade.

### Backlog de frontend

- construir página `/audit`
- implementar lista de respostas auditáveis
- implementar filtros por:
  - low confidence
  - needs review
  - grounded false
  - baixa citation coverage
- implementar detalhe da resposta auditada
- exibir:
  - pergunta
  - resposta
  - chunks usados
  - citações
  - grounding.reason
  - uncited_claims_count
  - document_filename
- permitir ordenação por criticidade
- destacar visualmente respostas frágeis

### Backlog de backend

- implementar `GET /queries/logs?workspace_id=...`
- definir payload auditável mínimo com:
  - query
  - answer
  - chunks_used
  - citations
  - grounded
  - grounding_reason
  - citation_coverage
  - low_confidence
  - needs_review
  - uncited_claims_count
  - created_at
- garantir paginação e filtro mínimo

### Backlog de UX e conteúdo

- definir score visual de criticidade
- definir badges de revisão
- definir empty state para “nenhuma resposta crítica”

### Backlog de QA

- validar listagem de respostas auditáveis
- validar filtros por criticidade
- validar detalhe de resposta
- validar ordenação das respostas mais frágeis

### Critério de aceite

- operador consegue revisar qualidade sem abrir logs em arquivo
- grounding e falta de citação ficam claros
- tela ajuda triagem real de qualidade

### Plano executável do Sprint F6

#### Ordem recomendada de implementação

1. fechar contrato de logs auditáveis
2. montar a estrutura da página `/audit`
3. implementar lista de respostas auditáveis
4. integrar filtros de criticidade
5. implementar painel de detalhe da resposta
6. destacar grounding, citações e claims frágeis
7. fechar ordenação por criticidade
8. validar a tela com respostas fortes e problemáticas

#### Bloco F6.1 — Contrato de auditoria e logs consultáveis

Objetivo:

- garantir que a tela de auditoria opere sobre dados consultáveis e úteis

Tarefas:

- validar necessidade de `GET /queries/logs?workspace_id=...`
- definir payload mínimo auditável com:
  - query
  - answer
  - `chunks_used`
  - `citations`
  - `grounded`
  - `grounding_reason`
  - `citation_coverage`
  - `low_confidence`
  - `needs_review`
  - `uncited_claims_count`
  - `document_filename`
  - `created_at`
- definir paginação mínima
- definir filtros suportados pelo backend
- garantir ordenação mínima por criticidade ou data

Entregáveis:

- contrato de auditoria pronto para consumo visual

#### Bloco F6.2 — Estrutura da página `/audit`

Objetivo:

- criar a base da tela de triagem de qualidade

Tarefas:

- montar cabeçalho da página
- criar área de filtros
- criar região de lista de respostas
- criar painel de detalhe
- criar estado inicial
- criar estado de carregamento
- criar estado vazio
- criar estado de erro

Entregáveis:

- página de auditoria estruturada para operação real

#### Bloco F6.3 — Lista de respostas auditáveis

Objetivo:

- dar visão rápida dos casos que merecem revisão

Tarefas:

- renderizar lista paginada de respostas
- exibir por item:
  - pergunta
  - data
  - `low_confidence`
  - `needs_review`
  - `grounded`
  - `citation_coverage`
  - `uncited_claims_count`
- destacar visualmente itens mais críticos
- permitir seleção de uma resposta para análise detalhada

Entregáveis:

- operador consegue navegar por respostas auditáveis sem abrir logs em arquivo

#### Bloco F6.4 — Filtros e triagem de criticidade

Objetivo:

- permitir que a auditoria foque primeiro nos casos frágeis

Tarefas:

- implementar filtro por `low_confidence`
- implementar filtro por `needs_review`
- implementar filtro por `grounded=false`
- implementar filtro por baixa `citation_coverage`
- permitir combinação de filtros
- permitir limpeza rápida dos filtros
- refletir filtros no request ao backend

Entregáveis:

- operador consegue priorizar a revisão do que importa

#### Bloco F6.5 — Detalhe da resposta auditada

Objetivo:

- tornar a análise de qualidade concreta e navegável

Tarefas:

- criar painel ou área de detalhe
- exibir:
  - pergunta
  - resposta
  - chunks usados
  - citações
  - `grounding.reason`
  - `uncited_claims_count`
  - `document_filename`
- permitir expandir contexto usado
- destacar visualmente claims frágeis quando possível

Entregáveis:

- resposta auditada pode ser examinada em profundidade pela UI

#### Bloco F6.6 — Criticidade visual e leitura de risco

Objetivo:

- deixar claro o nível de fragilidade de cada resposta

Tarefas:

- definir score ou classes visuais de criticidade
- definir badges de revisão
- destacar respostas sem grounding suficiente
- destacar baixa cobertura de citação
- destacar claims sem suporte

Entregáveis:

- a tela comunica risco com clareza

#### Bloco F6.7 — UX, copy e estados da auditoria

Objetivo:

- fazer a tela ser útil também para operador não profundamente técnico

Tarefas:

- definir microcopy do módulo
- definir empty state para “nenhuma resposta crítica”
- definir mensagem para ausência de logs auditáveis
- definir texto curto explicando os filtros principais
- revisar a clareza do detalhe da resposta

Entregáveis:

- operador entende como usar a auditoria sem depender de contexto implícito

#### Bloco F6.8 — QA funcional do módulo

Objetivo:

- fechar a auditoria com evidência reproduzível

Tarefas:

- validar listagem de respostas auditáveis
- validar paginação
- validar filtro por `low_confidence`
- validar filtro por `needs_review`
- validar filtro por `grounded=false`
- validar filtro por baixa `citation_coverage`
- validar detalhe da resposta
- validar ordenação ou priorização dos casos mais frágeis

Entregáveis:

- checklist funcional da tela de auditoria executado

### Definição de pronto do Sprint F6

O Sprint F6 só deve ser considerado concluído quando:

- a página `/audit` estiver funcional
- respostas auditáveis puderem ser listadas e filtradas pela UI
- o detalhe da resposta mostrar grounding, citações e fragilidade
- a tela permitir triagem real de qualidade
- o operador não depender mais de logs em arquivo para revisar respostas

### Saída esperada para iniciar o Sprint F7

Ao final do F6, o time deve ter:

- trilha visual de auditoria de respostas funcionando
- contrato de logs auditáveis estabilizado
- produto cobrindo documentos, busca, chat, dashboard e auditoria
- base pronta para hardening final da experiência

### Riscos que invalidam o fechamento do F6

- auditoria funcionando como lista rasa sem detalhe útil
- filtros sem impacto real na triagem
- ausência de clareza sobre grounding e citações
- criticidade visual pouco útil
- tela boa para demo, mas ruim para revisão operacional
- dependência residual de leitura manual de log em arquivo

---

## Sprint F7 — Hardening de UX, Navegação e Estado

### Resultado esperado

As telas passam de “funcionais” para “produto premium consistente”.

### Backlog de frontend

- unificar comportamento de loading entre páginas
- unificar comportamento de erros entre páginas
- persistir filtros relevantes por rota
- persistir sessão atual do chat
- revisar responsividade
- revisar navegação ativa e breadcrumbs
- revisar performance de renderização básica
- revisar acessibilidade mínima:
  - foco
  - contraste
  - labels
  - atalhos de teclado prioritários
- refinar animações e transições

### Backlog de backend

- ajustar payloads que ainda gerarem fricção visual
- remover inconsistências de nomenclatura
- garantir estabilidade contratual onde a UI depender fortemente

### Backlog de UX e conteúdo

- revisar copy de todos os empty states
- revisar copy de erros
- revisar coesão visual final
- revisar onboarding visual do operador

### Backlog de QA

- smoke test por todas as telas
- validar persistência de filtros
- validar persistência da sessão do chat
- validar navegação entre módulos
- validar mobile/tablet funcional
- revisar acessibilidade mínima

### Critério de aceite

- experiência fica coerente entre todas as páginas
- não há sensação de telas isoladas
- produto parece pronto para demonstração séria

### Plano executável do Sprint F7

#### Ordem recomendada de implementação

1. mapear inconsistências transversais entre as telas
2. unificar estados de loading, vazio e erro
3. consolidar navegação e persistência de contexto
4. revisar responsividade entre módulos
5. revisar performance básica de renderização
6. revisar acessibilidade mínima
7. polir copy, transições e comportamento visual
8. executar smoke test completo de experiência

#### Bloco F7.1 — Mapa de inconsistências do produto

Objetivo:

- transformar telas isoladas em produto coerente

Tarefas:

- revisar todas as páginas:
  - `/`
  - `/documents`
  - `/search`
  - `/chat`
  - `/dashboard`
  - `/audit`
- identificar divergências de layout
- identificar divergências de comportamento
- identificar inconsistências de copy
- identificar inconsistências de componentes e padrões

Entregáveis:

- lista objetiva de inconsistências a corrigir

#### Bloco F7.2 — Estados globais consistentes

Objetivo:

- padronizar a percepção de qualidade entre todos os módulos

Tarefas:

- unificar componentes de loading
- unificar componentes de empty state
- unificar componentes de error state
- padronizar toasts e feedbacks rápidos
- revisar mensagens de sucesso e erro
- aplicar o mesmo padrão de feedback entre telas

Entregáveis:

- estados globais deixam de variar de forma improvisada

#### Bloco F7.3 — Navegação, contexto e persistência

Objetivo:

- evitar que o usuário perca contexto ao circular pelo produto

Tarefas:

- revisar navegação ativa na sidebar
- adicionar breadcrumbs quando fizer sentido
- persistir filtros relevantes por rota
- persistir sessão atual do chat
- manter contexto mínimo ao navegar entre módulos
- revisar comportamento de refresh nas páginas principais

Entregáveis:

- navegação mais estável e menos frágil

#### Bloco F7.4 — Responsividade e adaptação de layout

Objetivo:

- evitar que a experiência premium dependa de uma única resolução

Tarefas:

- revisar layout em desktop
- revisar layout em tablet
- revisar largura de tabelas e painéis laterais
- revisar drawers, modais e áreas scrolláveis
- revisar densidade visual em telas médias
- corrigir overflow e truncamento inadequados

Entregáveis:

- produto permanece utilizável fora do desktop largo

#### Bloco F7.5 — Performance e estabilidade visual

Objetivo:

- reduzir sensação de interface pesada ou quebradiça

Tarefas:

- revisar renderização de listas e tabelas
- revisar re-renders desnecessários
- revisar carregamento inicial das páginas
- revisar spinners e skeletons longos
- revisar estabilidade visual durante requisições

Entregáveis:

- interface responde de forma mais estável e profissional

#### Bloco F7.6 — Acessibilidade mínima

Objetivo:

- garantir padrão mínimo de uso e navegação

Tarefas:

- revisar foco visível
- revisar contraste
- revisar labels e nomes acessíveis
- revisar navegação por teclado nos componentes principais
- revisar leitura de modais e drawers
- revisar botões e ações críticas

Entregáveis:

- produto atinge mínimo aceitável de acessibilidade funcional

#### Bloco F7.7 — Copy, refinamento visual e microinterações

Objetivo:

- fechar o acabamento visual do produto antes do gate

Tarefas:

- revisar copy de títulos, subtítulos e estados
- revisar consistência de badges e ícones
- revisar microinterações relevantes
- revisar transições e animações sutis
- revisar sensação final de coesão visual

Entregáveis:

- interface deixa de parecer conjunto de módulos montados separadamente

#### Bloco F7.8 — QA transversal do produto

Objetivo:

- validar a experiência premium como um todo

Tarefas:

- executar smoke test em todas as telas
- validar persistência de filtros
- validar persistência da sessão do chat
- validar navegação entre módulos
- validar comportamento em refresh
- validar mobile/tablet funcional no nível mínimo previsto
- revisar acessibilidade mínima dos fluxos principais

Entregáveis:

- checklist transversal de UX e navegação executado

### Definição de pronto do Sprint F7

O Sprint F7 só deve ser considerado concluído quando:

- a experiência estiver coerente entre todas as páginas
- loading, erro e vazio seguirem o mesmo padrão
- a navegação preservar contexto de forma razoável
- a responsividade básica estiver consolidada
- o produto parecer software premium consistente, e não coleção de telas

### Saída esperada para iniciar o Sprint F8

Ao final do F7, o time deve ter:

- frontend premium coeso
- experiência pronta para validação formal
- inconsistências transversais reduzidas ao mínimo
- produto com aparência e comportamento de software utilizável

### Riscos que invalidam o fechamento do F7

- boa qualidade isolada por página, mas baixa coerência entre módulos
- filtros e contexto se perdendo ao navegar
- responsividade quebrada em pontos importantes
- loading e erro mudando arbitrariamente por tela
- sensação final de produto incompleto apesar das features existirem
- polimento insuficiente para uma demonstração séria

---

## Sprint F8 — Gate Visual da Fase 2

### Resultado esperado

Concluir a validação formal do frontend premium como produto da Fase 2.

### Backlog de frontend

- revisar polish final das telas
- revisar consistência visual final
- revisar estados de borda
- preparar fluxo de demonstração ponta a ponta

### Backlog de backend

- validar endpoints usados pelo frontend premium
- congelar contratos mínimos da Fase 2
- registrar endpoints complementares que ficam para Fase 3

### Backlog de documentação

- atualizar roadmap
- atualizar backlog priorizado
- atualizar execution log
- atualizar guia de uso do programa com a nova interface
- registrar runbook de operação do frontend, se necessário

### Backlog de QA

- rodar checklist funcional completo:
  - documentos
  - busca
  - chat
  - dashboard
  - auditoria
- rodar validação visual ponta a ponta
- registrar gaps remanescentes de Fase 3

### Critério de aceite

- operador executa a rotina principal sem Swagger
- frontend premium pode ser demonstrado como produto real
- a Fase 2 pode ser declarada concluída com evidência

### Plano executável do Sprint F8

#### Ordem recomendada de implementação

1. revisar readiness de todas as telas da Fase 2
2. executar checklist funcional completo
3. executar validação visual ponta a ponta
4. validar contratos mínimos usados pela UI
5. consolidar evidências de frontend, backend e UX
6. atualizar a documentação oficial
7. registrar gaps remanescentes da Fase 3
8. tomar decisão formal do gate visual

#### Bloco F8.1 — Revisão de readiness da Fase 2

Objetivo:

- confirmar que todos os módulos previstos realmente existem em nível de produto

Tarefas:

- revisar:
  - `/documents`
  - `/search`
  - `/chat`
  - `/dashboard`
  - `/audit`
- verificar consistência com os critérios dos sprints F2 a F7
- consolidar pendências residuais por módulo
- classificar pendências em:
  - bloqueantes
  - não bloqueantes
  - escopo de Fase 3

Entregáveis:

- mapa final de readiness da Fase 2

#### Bloco F8.2 — Checklist funcional ponta a ponta

Objetivo:

- validar que a rotina principal funciona sem interface técnica

Tarefas:

- testar fluxo de documentos:
  - upload
  - listagem
  - metadata
- testar fluxo de busca:
  - query
  - filtros
  - evidências
- testar fluxo de chat:
  - pergunta
  - resposta
  - citações
  - sinais de confiança
- testar fluxo de dashboard:
  - KPIs
  - período
  - alertas
- testar fluxo de auditoria:
  - listagem
  - filtros
  - detalhe da resposta

Entregáveis:

- checklist funcional completo executado e registrado

#### Bloco F8.3 — Validação visual de produto

Objetivo:

- garantir que o frontend premium realmente parece produto e não camada cosmética

Tarefas:

- revisar consistência visual final
- revisar estados de borda
- revisar qualidade das transições principais
- revisar hierarquia visual entre módulos
- revisar legibilidade em desktop e tablet
- preparar roteiro de demonstração ponta a ponta

Entregáveis:

- validação visual consolidada para demonstração real

#### Bloco F8.4 — Congelamento de contratos mínimos da Fase 2

Objetivo:

- evitar que a UI premium fique dependente de contratos ainda instáveis

Tarefas:

- revisar endpoints usados pela UI:
  - `GET /health`
  - `POST /documents/upload`
  - `GET /documents`
  - `GET /documents/{document_id}`
  - `POST /search`
  - `POST /query`
  - `GET /metrics`
  - `GET /queries/logs`
- congelar payload mínimo esperado para cada tela
- registrar endpoints complementares que ficam para Fase 3
- registrar limitações conhecidas sem mascará-las

Entregáveis:

- base contratual mínima da Fase 2 estabilizada

#### Bloco F8.5 — Consolidação de evidências

Objetivo:

- transformar a conclusão da fase em algo auditável

Tarefas:

- consolidar evidências de frontend
- consolidar evidências de backend
- consolidar evidências de UX
- consolidar evidências de QA
- registrar resultados dos checklists
- identificar riscos remanescentes não bloqueantes

Entregáveis:

- pacote de evidências pronto para suportar a decisão do gate

#### Bloco F8.6 — Atualização documental final da Fase 2

Objetivo:

- alinhar a narrativa oficial ao estado real do produto

Tarefas:

- atualizar roadmap executivo
- atualizar backlog priorizado
- atualizar execution log
- atualizar guia completo de uso do programa
- registrar runbook operacional do frontend, se necessário
- registrar o que passa a ser foco da Fase 3

Entregáveis:

- documentação oficial refletindo a conclusão da Fase 2

#### Bloco F8.7 — Registro de gaps remanescentes da Fase 3

Objetivo:

- separar claramente o que é pendência real do que é próximo estágio do produto

Tarefas:

- listar itens ainda não resolvidos
- classificar o que é:
  - hardening adicional
  - admin panel
  - autenticação forte
  - RBAC
  - multitenancy
  - white-label
  - observabilidade enterprise
- registrar esses itens como backlog da Fase 3

Entregáveis:

- transição limpa entre Fase 2 e Fase 3

#### Bloco F8.8 — Decisão formal do gate visual

Objetivo:

- encerrar a Fase 2 com decisão explícita e defensável

Tarefas:

- revisar evidências consolidadas
- verificar se operador executa rotina principal sem Swagger
- verificar se o frontend premium pode ser demonstrado como produto real
- verificar se os gaps remanescentes não inviabilizam o uso diário
- decidir formalmente:
  - `Fase 2 concluída`
  - ou `nova rodada corretiva necessária`

Entregáveis:

- decisão formal do gate visual registrada

### Definição de pronto do Sprint F8

O Sprint F8 só deve ser considerado concluído quando:

- os módulos principais da Fase 2 estiverem validados ponta a ponta
- a documentação oficial estiver atualizada
- os contratos mínimos da Fase 2 estiverem congelados
- os gaps remanescentes da Fase 3 estiverem claramente separados
- existir uma decisão formal e justificada sobre o gate visual

### Saída esperada ao final da Fase 2

Ao final do F8, o time deve ter:

- frontend premium validado
- rotina principal executável sem interface técnica
- documentação oficial coerente com o produto entregue
- backlog da Fase 3 aberto de forma limpa
- decisão formal de conclusão ou correção adicional da Fase 2

### Riscos que invalidam o fechamento do F8

- declarar a Fase 2 concluída sem evidência consolidada
- manter contratos centrais instáveis
- esconder gaps relevantes como se fossem detalhes
- documentação desatualizada em relação ao produto real
- frontend visualmente bonito, mas ainda dependente de Swagger para a rotina principal

---

## Fechamento da trilha da Fase 2

Ao final do backlog `F1` a `F8`, o produto deve entregar:

- frontend robusto
- painel de documentos
- tela de busca e validação
- chat web
- dashboard operacional
- auditoria de respostas
- experiência premium consistente
- operação principal sem dependência de interface técnica

Se esse estado não for alcançado, a Fase 2 não deve ser declarada concluída.

---

## Dependências críticas entre sprints

| Sprint | Depende de | Bloqueios principais |
|---|---|---|
| F1 | fundação pronta | frontend não inicializado |
| F2 | F1 | falta de `GET /documents` |
| F3 | F1, F2 | payload de filtros instável |
| F4 | F1 | payload de `/query` incompleto |
| F5 | F1 | `/metrics` sem shape estável |
| F6 | F4, F5 | ausência de `GET /queries/logs` |
| F7 | F2, F3, F4, F5, F6 | gaps espalhados de UX e contratos |
| F8 | F2 a F7 | ausência de validação final e documentação |

---

## Ordem sugerida de execução real

1. Sprint F1
2. Sprint F2
3. Sprint F3
4. Sprint F4
5. Sprint F5
6. Sprint F6
7. Sprint F7
8. Sprint F8

---

## Próximo passo

Usar este backlog para abrir tickets de implementação por sprint, começando por `Sprint F1`.
