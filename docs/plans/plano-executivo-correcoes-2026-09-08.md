# Plano executivo revisado — construção do RICK Intelligence

**Revisão 2, 08/09/2026.** Status: proposta executável de produto e integração.

**Fonte atual:** [reanálise do programa](../reports/reanalise-programa-2026-09-08.md).

**Resultado desejado:** três experiências operacionais numa plataforma: Super Admin, gestão RAG e workspace conversacional.

## 1. Diagnóstico executivo

A base local funciona: esta rodada confirmou 358 testes da API e 113 de domínio/storage. As lacunas que impedem uso pleno são funcionalidades incompletas, configuração ambígua do modelo e composição externa pendente. O timeout no sandbox não deve continuar sendo tratado como defeito confirmado da aplicação.

A análise anterior privilegiava infraestrutura e notas gerais; esta revisão prioriza jornadas utilizáveis com persistência e segurança. As notas detalhadas e sua rubrica pertencem à reanálise. Não se usa uma nota média como autorização de produção.

## 2. Entregas e valor para o usuário

| Entrega | Resultado de negócio | Demonstração de aceite |
|---|---|---|
| Configuração confiável | operador sabe qual backend/provider/modelo está em uso | exemplo de ambiente configura o root e diagnóstico comprova modo efetivo; ausência de provider não parece geração real |
| Super Admin | usuário consegue administrar acesso pela aplicação | criar/editar/desativar usuário, consultar/revogar sessão e concluir recuperação; tenant conforme política aprovada; alterações sobrevivem a restart |
| Console RAG | gestor controla corpus e publicação | gerir coleção, importar, acompanhar job, cancelar/repetir, publicar, reindexar e retirar documento com reflexo imediato na busca autorizada |
| Workspace conversacional | usuário retoma contexto e inspeciona evidências | conversa persistente com múltiplos turnos, geração real, fontes, erro/cancelamento claros e streaming efetivamente incremental |
| Operação verificável | equipe mantém o produto sob falha | duas réplicas, restore, alertas, limites de custo e rollback demonstrados |

## 3. Direção de arquitetura e fronteiras

Manter `apps/web` e `apps/api` como produto canônico, conforme documentação existente. Preservar CVG/Professor/Locker legados como referência de comportamento ou adapters enquanto houver dependências. Não há justificativa nesta rodada para copiar frontends, remover legado ou trocar framework.

Cada entrega atravessa UI → API → contrato → persistência/serviço → teste. O alvo externo usa Postgres, armazenamento de objetos, fila/worker, Qdrant, lease distribuído, provider e identidade aprovados. Existência de interface injetável não significa composição pronta.

Conversas persistentes e recuperação de contexto são contratos novos a detalhar; `conversation_id` isolado não assegura memória. Streaming precisa começar no provider e terminar na UI; o atual SSE que parcela resposta concluída não cumpre esse aceite. Publicação de texto provisório versus validado terá política explícita de citações.

O administrador atual é limitado ao tenant na API. Governança global de tenants exige contrato e política aprovados, sem ampliar acesso por inferência do nome `PLATFORM_ADMIN`.

## 4. Decisões necessárias

| ID | Decisão e material a preparar | Responsável | Bloqueia |
|---|---|---|---|
| D01 | tenant/membership e autoridade global; hospedagem Postgres; retenção e migração dos dados existentes | Produto + Segurança + Dados | REC-05/06/12 |
| D02 | IdP ou identidade própria; credenciais locais; broker, object store, secrets, ambiente e teto de infraestrutura | Segurança + Platform + Ops | REC-05/08/13/15/16 |
| D03 | provider/endpoint/modelos autorizados, política de dados enviados, teto de gasto e credencial de integração | Produto + Segurança + Ops | REC-21 |
| D04 | corpus/licença, casos e dados permitidos; thresholds de qualidade e escopo de apoio clínico; responsável por revisão | Produto + responsável de domínio | REC-22/27 |
| D05 | workload, concorrência, SLO, RTO/RPO, custos, retenção de telemetria e destinos de alertas | Produto + Ops | REC-29/30/32 |

As propostas podem ser preparadas imediatamente. Registrar escolha, alternativas, motivo, dono e data. As credenciais devem entrar por mecanismo de secrets, não por documentação ou conversa. Não se escolheu fornecedor ou modelo novo nesta rodada.

Argon2id não deve virar um subsistema duplicado se o produto adotar exclusivamente IdP: decidir manutenção/migração/descontinuação das senhas locais em D02 e comprovar o comportamento escolhido.

## 5. Organização, prioridade e capacidade

Engenharia responde por contratos e integração; Backend/Dados por persistência; Web por jornadas; Segurança por identidade/escopo; Ops por ambiente e recuperação; Produto por funcionalidades e corpus. Reviewers avaliam artefatos verificáveis sem reutilizar o parecer do implementador como aprovação independente.

Primeira frente: configuração, harness e matriz de personas; navegação em seguida. Entrega seguinte: usuários/sessões na UI com persistência. Em paralelo, preparar integração real de provider e ciclo RAG. O workspace conversacional depende de memória, mensagens e provider, além da UI.

Não há equipe ou disponibilidade informada para sustentar uma data final. Planejar capacidade por marco; estimar itens após D01–D05 e após a primeira fatia integrada. O roadmap oferece sequência e paralelismo; não promete prazo fixo para integrações desconhecidas.

## 6. Critérios de aceite do programa

A barra detalhada permanece no [Quality Bar existente](../progress/manifests/quality-bar-triplo-aaa-2026-09-07.json). Complementos de produto:

- três personas concluem suas jornadas pela UI usando API e stores de integração;
- nenhum tenant/usuário acessa conversa, documento, sessão ou mutação de outro sem autorização explícita;
- geração e embeddings reais demonstrados separadamente; corpus e citações avaliados com casos aprovados;
- chat multi-turn, persistência, cancelamento e estado final de geração verificáveis;
- operações sensíveis auditadas conforme política de falha; segredos e conteúdo privado não vazam para logs;
- restart, duplicação de job, falha parcial, restore e operação com duas réplicas testados;
- acessibilidade manual e automatizada, crítica visual independente e regressão atuais;
- carga, custos, alertas e rollback cumprem limites definidos antes dos ensaios;
- candidato e evidências referem a mesma revisão/configuração; Product/Security/Ops registram Go/No-Go.

Os testes web com interceptação permanecem úteis para estados de erro e corridas; os aceites integrados precisam de jornadas sem interceptação dos serviços que pretendem provar.

## 7. Riscos e resposta

| Risco | Resposta concreta |
|---|---|
| Professor selecionado mas ainda determinístico | diagnóstico do provider efetivo e teste de chamada real autorizado |
| LLM real sobre embeddings hash | composição de embeddings/query/index consistente e teste separado de retrieval |
| Usuários/tenants construídos com escopo errado | D01, modelo explícito, testes negativos antes de UI de governança global |
| Duplicação entre DB, queue, objetos e vetores | outbox ou reconciliação, idempotência e crash nos pontos de publicação |
| Texto em streaming tratado como já validado | estado provisório; validação final de citações; cancelamento e partial explícitos |
| Artefato verde referente a processo antigo | processo/porta/build/configuração identificados e ambiente isolado |
| Plano bloqueado indefinidamente por infraestrutura | preparar decisões e contratos em paralelo; concluir correções locais independentes |
| Produto polido mas incompleto | aceite por tarefas reais de cada persona, além de screenshots e testes de UI |

## 8. Recuperação e execução futura

O backlog REC é a proposta de trabalho desta revisão. Antes de iniciar uma tarefa, conferir Git e evidências mais recentes, atribuir dono, mapear o item ao controle canônico em `.agent/` e detalhar contrato/testes/rollback. Os planos de 07/09 e relatórios anteriores preservam história; esta tríade revisada orienta a próxima execução proposta.

Cada incremento deve poder ser revertido por código/configuração compatível; dados exigem migração e reconciliação explícitas. Não apagar volumes ou fontes para restaurar um teste. Mudança de requisito replaneja dependências e aceites antes de implementar.

**Execução iniciada:** REC-01–04 foram implementados localmente; REC-05 está preparado, sem aceite integrado. Postgres/fila transacional, S3-compatible e OIDC em laboratório local e instalação de Docker foram aprovados pelo usuário. Docker/Compose foram instalados externamente, mas o agente segue sem acesso ao daemon; sudo exige autenticação local. OpenAI/Anthropic foram indicados; modelo, teto de gasto e corpus ainda precisam ser definidos. Consulte o [relatório de execução](../reports/execucao-planejamento-2026-09-08.md); isso não declara concluído o programa nem autoriza promoção.

[Roadmap](roadmap-correcoes-2026-09-08.md) · [Backlog](backlog-correcoes-2026-09-08.md)
