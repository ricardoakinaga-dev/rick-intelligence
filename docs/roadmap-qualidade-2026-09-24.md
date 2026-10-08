# Roadmap de atualizações e melhorias — RICK Intelligence

**Data-base:** 24/09/2026. **Versão:** RM24-v1, atualizada com checkpoint local de 25/09/2026. M0/M1 e fatias de M2/M3 avançaram, incluindo auditoria atualizada de dependências e medição RAG desagregada; nenhum marco de fluxo integrado, operação ou promoção está aceito por este registro.

Referências: [plano executivo](plano-executivo-qualidade-2026-09-24.md), [backlog](backlog-qualidade-2026-09-24.md) e [auditoria](relatorio-auditoria-2026-09-24.md). Os marcos M0–M5 desta proposta não renomeiam os marcos históricos nem alteram o [plano ativo](../.agent/plans/phase-3-runtime-evidence-production-promotion.md).

## 1. Sequência de entregas

| Marco | Entrega verificável | Tarefas | Saída esperada |
|---|---|---|---|
| M0 — Preparação | Candidato preservado e requisitos ligados a responsáveis/evidências | Q24-01–Q24-02 | Escopo reconciliado com Q17 e próximo trabalho sem duplicação. |
| M1 — Fundamentos | Upload/retry corrigidos, dependências verificadas, avaliação coerente e checks locais | Q24-03–Q24-09 | Regressões pertinentes verdes e estratégia de migração pronta para ensaio. |
| M2 — Primeiro fluxo real | API, worker, persistência, provider e interface demonstrados juntos | Q24-10–Q24-16 | Um documento percorre o sistema e sustenta uma resposta autorizada, com fontes e histórico. |
| M3 — Completude | Busca híbrida, auditoria, isolamento, resiliência dos fluxos, UX e qualidade RAG | Q24-17–Q24-27 | Capacidades obrigatórias exercitadas nos caminhos canônicos e com falhas controladas. |
| M4 — Operação | Restore, capacidade, caos e estabilidade | Q24-28–Q24-30 | Objetivos operacionais atendidos na carga e janela aprovadas. |
| M5 — Candidato final | Manuais, artefatos, revisão, reauditoria e promoção verificável | Q24-31–Q24-33 | Decisão documentada, sem bloqueios obrigatórios ocultos ou aprovação por média. |

As faixas de tarefas são inclusivas. O aceite do marco considera o conjunto; a preparação de uma tarefa posterior pode começar assim que suas dependências estiverem satisfeitas. A demonstração inicial de M2 não substitui a campanha completa de M3/M4.

## 2. M0 — Preparação e continuidade

**Responsável proposto:** Lead. **Entrada:** auditoria, checkout atual e controles existentes acessíveis.

Conferir o trabalho não commitado, ler os requisitos vigentes, reconciliar Q24/Q17 e definir o registro de evidência de cada entrega. Resolver somente conflitos reais de escopo ou contrato. Não migrar o projeto para um segundo plano de controle.

**Demonstração:** um novo implementador consegue identificar a próxima tarefa, os arquivos afetados, seus limites e o teste que confirma o resultado. Todas as 26 áreas e os dez achados têm tarefas vinculadas. Nenhum item é duplicado como trabalho novo quando falta apenas validação.

**Saída:** Q24-01 e Q24-02 verificadas documentalmente; autoridade existente e decisões ainda necessárias distinguidas. Falta de uma decisão de produção não bloqueia preparação ou correção local independente.

## 3. M1 — Fundamentos e defeitos imediatos

**Responsáveis propostos:** backend/segurança, frontend e QA. **Entrada:** M0 ou dependências específicas concluídas.

Dar prioridade às dependências A24-01 e ao upload A24-03. Separar o retry em contrato de transporte, preservação da fonte e adaptação da interface. Corrigir a inconsistência do pacote RAG com uma versão justificada, e definir a atualização de banco antes de iniciar ensaios. A telemetria limitada e os checks locais avançam em escopos independentes.

**Demonstração:** upload sem tocar no seletor envia a coleção exibida; trocar ou arquivar a coleção produz resultado definido; PDF/DOCX mantêm bytes no retry. A resolução de dependências é reproduzível. O avaliador aceita exemplos corretos e rejeita incorretos segundo uma métrica viável.

**Saída:** regressões focadas e checks locais passam. A correção do teste de multipart deve distinguir dados da aplicação de delimitadores; ajustar o parser do teste não pode mascarar envio de coleção vazia. A estratégia de migração deve considerar que um checksum incompatível pode interromper o runner antes de uma nova migration.

**Pode antecipar:** levantamento de dados/infraestrutura e desenho da política de domínio de M2. Não iniciar chamadas reais sem endpoint e limite definidos.

## 4. M2 — Primeiro fluxo integrado real

**Responsáveis propostos:** operações/dados, plataforma RAG e backend. **Entrada:** correções e contratos necessários de M1; D01–D04 aplicáveis resolvidas para o ensaio.

Preparar laboratório separado dos serviços do usuário. Provar instalação, upgrade e bootstrap nos estados suportados. Exercitar provider real autorizado, que pode ser local quando cumprir os contratos necessários. Conectar uma política de domínio que permita consultas adequadas e trate incerteza corretamente; preservar as garantias de fontes no streaming e no histórico.

**Demonstração:** enviar um documento sintético autorizado pela interface, observar objeto e job, acompanhar processamento real, recuperar o trecho correto e gerar resposta permitida com citação verificável. Reabrir o histórico e confirmar metadados. Repetir com fonte insuficiente ou acesso negado para verificar o caminho negativo.

**Saída:** Q24-16 possui evidência do fluxo e identifica todos os serviços, candidato, modelo e dados. A busca dense atual pode ser usada nessa demonstração inicial, sem alegar que A24-05 foi encerrado. Não substituir o fluxo por respostas interceptadas no navegador.

**Regra de avanço:** se aparecer um defeito estrutural, corrigi-lo e revalidar esta sequência antes de ampliar funcionalidades. O laboratório pode ser usado para testes de migração; a tarefa de desenho Q24-07 não depende de seu próprio teste futuro, evitando um ciclo de planejamento.

## 5. M3 — Completude e garantias entre componentes

**Responsáveis propostos:** plataforma RAG, backend, frontend, operações e QA. **Entrada:** fluxo inicial demonstrado e dependências específicas atendidas.

Completar o schema sparse, ingestão e consulta HTTP híbrida como uma entrega conectada. Implementar consistência da operação administrativa com auditoria e um consumidor durável das pendências. Verificar isolamento, sessões, concorrência, replays, publicação e reindexação. Completar acompanhamento de jobs, estados web, acessibilidade e corpus de avaliação. Preparar produtores/consumidores de evidência de release sem antecipar o resultado dos ensaios operacionais.

**Demonstrações:** as duas modalidades de busca são observadas sob escopo; uma operação administrativa sobrevive a falha do sink e reinício sem duplicação; um worker que perdeu a posse do job não publica; uma fonte revogada durante geração não é aprovada no resultado final; a interface apresenta estados reais de erro e retomada.

**Saída:** A24-02, A24-03, A24-05, A24-06 e A24-08 têm provas completas nas tarefas correspondentes; isolamento e corpus representativo passam nos contratos definidos. O mecanismo de release consegue consumir observações reais e rejeitar artefatos inválidos. O conjunto ainda depende dos ensaios M4 e do julgamento M5.

## 6. M4 — Recuperação, capacidade e estabilidade

**Responsável proposto:** operações, com QA e responsável pelo domínio da carga. **Entrada:** componentes consistentes, telemetria útil e D05 definido antes da campanha.

Executar restore do conjunto persistente em cópia descartável; incluir índices reconstruíveis e reconciliação de jobs/auditoria. Medir latências de upload, ingestão, recuperação, primeiro token e resposta completa, throughput, filas, uso de memória e custo. Comparar cargas previstas no contrato do produto, preservando as matrizes históricas obrigatórias até uma revisão explícita de escopo.

Em seguida, executar falhas controladas e estabilidade prolongada. As janelas de observação e limites são parâmetros do ensaio, não datas prometidas por este documento. Registrar também falhas de medição, amostras insuficientes e saturação.

**Saída:** RPO/RTO, capacidade e estabilidade possuem valores medidos, limites acordados e resultado reproduzível; nenhum gate obrigatório é tratado como aprovado por ausência de erro. Falha de recuperação ou corrupção bloqueia a saída e reabre as tarefas causais.

## 7. M5 — Candidato revisado e promoção

**Responsáveis propostos:** Lead, QA/release e revisores independentes. **Entrada:** tarefas anteriores concluídas e evidências do candidato preservadas.

Consolidar manuais e inventário de dependências/imagens, preparar um candidato que inclua as mudanças aprovadas, executar CI e revisão do conjunto e reavaliar as 26 áreas. A nota final é calculada após a revisão. O pacote deve comprovar correspondência entre fonte, build, testes e ambiente.

**Demonstração:** o verificador aceita um conjunto completo e válido de evidências e rejeita ausência, alteração, expiração, candidato incorreto e autoaprovação indevida. A observação de prontidão do laboratório precisa vir do laboratório; a revisão precisa vir do revisor; a autorização precisa vir de sua autoridade.

**Saída:** decisão final rastreável. D07 autoriza apenas a ação operacional realmente definida; eventual implantação exige plano de canário/rollback e destinos conhecidos. Se um critério obrigatório estiver bloqueado, a entrega permanece candidata com pendências explícitas.

## 8. Paralelismo e caminho de maior dependência

| Frente | Pode avançar em paralelo | Deve ter integração serial |
|---|---|---|
| Fundamentos | Dependências, seleção de coleção, avaliador e telemetria, com arquivos separados | Retry e upload compartilham `page.tsx`/`lib/api.ts`; combinar antes da regressão web. |
| Primeiro fluxo | Infraestrutura, testes de provider e especificação de política | Decision e Evidence compartilham `professor_backend.py`; designar um integrador. |
| Completude | Busca híbrida, reconciliação administrativa e UX, respeitando contratos | Schema/upsert antes da consulta híbrida; outbox antes do consumidor; matriz de isolamento após integração. |
| Operação | Preparação de workloads, manuais e contratos de evidência | Não misturar medição de carga com restore/chaos no mesmo ambiente; congelar o candidato testado. |

O caminho de maior dependência é **candidato/contratos → laboratório e persistência → política/fontes/provider → fluxo real → integração completa → recuperação/capacidade → revisão/promoção**. A velocidade efetiva dependerá da equipe, do ambiente e das decisões pendentes; esforço relativo não é duração de calendário.

## 9. Validação e acompanhamento

Usar os comandos existentes catalogados no [backlog](backlog-qualidade-2026-09-24.md), após conferir seus efeitos e pré-requisitos. Cada marco produz evidência com ID de tarefa, candidato, ambiente, comando, exit code, resultado, logs sanitizados e limitações. As pastas de evidência futuras devem ser próprias de cada candidato; a auditoria de 24/09 permanece histórica.

Acompanhar quantidade de tarefas aceitas, achados reabertos, critérios obrigatórios sem evidência e decisões que bloqueiam o próximo resultado. Contagem de testes, quantidade de documentação e média de notas não substituem esses sinais. O estado efetivo permanece nos controles canônicos, não nesta tabela de roadmap.

**Checkpoint de execução (25/09):** Q24-01/Q24-02 foram reconciliadas; avançaram API/autorização/chat, decisão/publicação, ingestão, retrieval híbrido, migrações e Q24-19/Q24-20. C1–C12 rejeitaram snapshots exatos. C11 encontrou reset PostgreSQL sem escopo workspace; C12 corrige o caminho com membership exata, passando API 743, PostgreSQL 16 descartável 108, mutações administrativas 15 e lint/typecheck. A revisão C12 rejeitou somente o snapshot por corrida de credenciais entre PATCH esparso e recuperação de senha; C13 corrigiu o lock; a regressão concorrente PostgreSQL passou junto a API 743 e migrações 109. C13 foi aceito no escopo local; avançar agora na reconciliação Q24-19/20 do consumidor outbox e da composição worker, mantendo os gates externos abertos. Domínio, Qdrant descartável e verificações estáticas estão no [checkpoint Q24](reports/estado-implementacao-q24-2026-09-24.md). M2–M5 e os critérios operacionais/de promoção permanecem abertos. Este roadmap não transforma testes parciais em conclusão de marco.

**Continuidade local (25/09):** Q24-03 atualizou Starlette/Uvicorn, alinhou manifests e CI — com pin direto de `python-multipart` no phase-1.5 — auditou 45 pacotes e passou 749 testes API em ambiente Python 3.12; imagem/inventário seguem pendentes de D02. Q24-05 reenvia exatamente o mesmo DOCX sintético após falha transitória e valida checksum/escopo; retenção durável/reload depende de D01. Q24-06 mantém o pack v2 sintético; Q24-21 cobre somente a corrida esparsa PATCH/recovery em PostgreSQL; Q24-25 valida falha de coleções para upload no navegador, com 27/27 focados no candidato final e crítica visual independente sem achados. Q24-26 separa métricas/intervalos por identidade exata e rótulos; IDs ausentes herdam defaults do pack, espaços-only permanecem válidos e os componentes do `stratum_id` são percent-encoded, com rótulos em base64 URL-safe reversível. A incerteza `overall` é identificada como agregada. As regressões passaram 20 testes do harness e 15 do pack. A campanha real continua `NOT_RUN`/`BLOCKED` até D04 e pré-requisitos externos. Revisões válidas encontraram falhas de encoding, defaults e descrição, já corrigidas; uma revisão do snapshot atualizado está pendente. Esses resultados avançam preparação local, sem fechar tarefas nem marcos. As limitações e hashes ficam nos manifestos listados no [checkpoint de implementação](reports/estado-implementacao-q24-2026-09-24.md).
