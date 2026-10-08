# Relatório de auditoria — RICK Intelligence

**Data:** 17/09/2026  
**Revisão analisada:** `b52f32c`  
**Nota geral: 70/100**

**Diagnóstico:** há uma implementação substancial, com módulos de domínio, API, interface conectada e muitos testes locais. Entretanto, existem problemas de integração no próprio código, além da falta de comprovação operacional. **Eu não recomendaria a promoção para produção neste estado.**

Essa conclusão é compatível com o README, que declara `STATE_OF_ART_CANDIDATE` e não reivindica prontidão de produção: `README.md:19`.

## 1. Método e significado das notas

Comparei documentação de arquitetura, operação, avaliação e entrega com código e testes de `apps/`, `packages/`, `infrastructure/` e scripts relacionados. Três análises paralelas cobriram áreas distintas; uma quarta revisão conferiu cinco achados importantes.

Cada nota considera:

| Critério | Peso |
|---|---:|
| Implementação frente ao escopo documentado | 40 |
| Correção e tratamento de falhas | 25 |
| Qualidade das evidências e testes | 20 |
| Integração e comprovação operacional | 15 |

As notas são **julgamentos técnicos fundamentados**, não percentuais medidos de conclusão. A nota geral é a média arredondada dos 26 itens abaixo; um bloqueador de produção não desaparece por causa dessa média.

**Limites:** não foi uma revisão linha por linha de todos os arquivos e históricos. Não executei ambiente distribuído, providers pagos, testes de carga, recuperação destrutiva ou inspeção visual em navegador.

## 2. O que já está construído

O repositório **não é apenas documentação ou um esqueleto**. Existem:

- API FastAPI com autenticação, permissões, chat, histórico, busca, documentos, jobs e administração.
- Interface Next.js que chama a API, incluindo streaming, cancelamento e acompanhamento de ingestão.
- Pacotes de conhecimento, ingestão, recuperação, evidências, decisão, providers e Professor.
- Implementações de persistência e integração com PostgreSQL, Redis, Qdrant e armazenamento compatível com S3.
- Worker com leases, heartbeat, cancelamento e controle de concorrência.
- Compose, migrações, instrumentação e verificadores de entrega.

A ressalva central é: **ter um adapter implementado não equivale a ter seu funcionamento integrado demonstrado.**

## 3. Notas por item

### Arquitetura e fundamentos

| Item | Nota | Avaliação |
|---|---:|---|
| 1. Arquitetura e separação de responsabilidades | **85** | Fronteiras reais entre aplicações e pacotes; validação de dependências passou. A coexistência com o legado ainda aumenta a complexidade. |
| 2. Documentação e aderência ao estado atual | **65** | Extensa e transparente sobre bloqueios, mas documentos antigos e READMEs de pacotes ainda descrevem funcionalidades existentes como futuras. |
| 3. Identidade e sessões | **80** | Sessões revogáveis e invalidação por mudanças de usuário/papel. Validade do cookie e renovação no servidor precisam de alinhamento. |
| 4. Autorização e isolamento | **83** | Permissões efetivas, escopo e revalidação de resultados bem estruturados. Semântica de concessões vazias e matriz documental precisam ficar explícitas. |
| 5. Kernel HTTP e controles defensivos | **84** | Readiness, limites, CSRF, CORS e tratamento de erros implementados. Alguns testes não demonstram precisamente a proteção que pretendem verificar. |
| 6. Contratos e compatibilidade | **65** | DTOs estritos em parte das fronteiras, mas aplicação desigual, parsers duplicados e testes de equivalência com asserções inócuas. |

### Conhecimento e inteligência

| Item | Nota | Avaliação |
|---|---:|---|
| 7. Knowledge: documentos, versões e proveniência | **81** | Identidades e persistência bem desenvolvidas. Há divergência de terminalidade da exclusão entre memória e stores persistentes. |
| 8. Ingestão e reindexação | **76** | Pipeline completo, compensações e parsing isolado. Limite de embeddings e deduplicação impedem alguns cenários importantes. |
| 9. Retrieval e busca híbrida | **69** | Escopo, fusão, deduplicação e reranking existem. O adapter Qdrant conectado devolve apenas resultados dense. |
| 10. Evidence: fontes e citações | **81** | Bundles imutáveis e validação de proveniência. A verificação posterior à geração não oferece a mesma garantia da validação inicial. |
| 11. Decision: responder, abster e escalar | **70** | Motor de políticas implementado; integração fixa risco baixo e intenção clara, limitando seu comportamento efetivo. |
| 12. Professor e geração fundamentada | **70** | Orquestração com limites, cancelamento e leases. Pode aprovar resposta gerada sem citações explícitas. |
| 13. Integração com providers | **83** | Clientes tipados, validação, retries e streaming. Falta comprovação com providers reais e há limites na resiliência de streaming. |
| 14. Avaliação de qualidade RAG | **63** | Harness útil e honesto sobre dados sintéticos. Corpus mínimo e métricas documentadas ainda incompletas. |

### Produto e interface

| Item | Nota | Avaliação |
|---|---:|---|
| 15. Chat, histórico e apresentação das evidências | **72** | Fluxos conectados à API, com retry e cancelamento. Metadados de evidência se perdem no transporte SSE. |
| 16. Documentos, busca e ingestão pela interface | **68** | Catálogo e ações reais. Upload fixa coleção; retry transforma arquivos binários em texto. |
| 17. Administração, auditoria e casos | **71** | Permissões e operações implementadas. Há inconsistência entre mutação e auditoria, além de idempotência incompleta na UI. |

*As notas da interface avaliam implementação e fluxos, não aparência, contraste ou responsividade observados em navegador.*

### Operação e entrega

| Item | Nota | Avaliação |
|---|---:|---|
| 18. Containers e composição do ambiente | **52** | Topologia passa na validação estática, mas existem incompatibilidades de configuração que essa validação não detecta. |
| 19. Jobs, PostgreSQL e migrações | **66** | Contratos duráveis e fencing desenvolvidos. Migração de dados legados contém chamada SQL incompatível com PostgreSQL padrão. |
| 20. Worker e ciclo de vida | **65** | Heartbeat e controle de concorrência implementados. Healthcheck e orçamento de shutdown precisam de correção. |
| 21. Redis e coordenação distribuída | **71** | Operações atômicas e controle de owner presentes. TLS de staging e comportamento entre réplicas não estão comprovados. |
| 22. Storage e inicialização persistente | **66** | Namespaces, assinatura e limites implementados. Integridade na leitura e reconciliação do bootstrap têm lacunas. |
| 23. Observabilidade e SLO | **55** | Instrumentação e propagação de contexto existem. Entrega ao coletor e alertas não estão demonstrados; sink bloqueado pode acumular threads. |
| 24. Recuperação, capacidade e tolerância a falhas | **45** | Ferramentas locais e contratos existem. Não há comprovação atual de recuperação completa, RPO/RTO, carga e execução prolongada. |
| 25. CI e promoção de release | **63** | Controle conservador de evidências. Algumas etapas obrigatórias não têm caminho de conclusão no orquestrador atual. |
| 26. Qualidade global dos testes | **74** | Boa quantidade de verificações locais passando. Mocks, testes estruturais e asserções tautológicas deixam falhas de integração descobertas. |

## 4. Principais achados

Os problemas abaixo foram sustentados por **inspeção do código conectado**. Não estou apresentando consequências previstas como incidentes reproduzidos em produção.

### A. Existem bloqueadores internos para subir e validar o ambiente

**Composição da API:** o factory fornecido exige `RICK_WORKER_ID`, mas o Compose não encaminha essa variável ao container da API.

- Exigência: `apps/worker/deployment_composition.py:120`
- Uso pelo factory da API: `apps/worker/deployment_composition.py:212`
- Ambiente do container: `docker-compose.dev.yml:224`

Isso afeta a composição fornecida; não significa que qualquer factory customizado falhará.

**Migração legada:** a migration utiliza `jsonb_object_length`, que não é uma função nativa do PostgreSQL 16, e não foi encontrada definição própria no repositório.

- `infrastructure/migrations/0005_rewrite_legacy_jobs.sql:148`
- `infrastructure/migrations/0005_rewrite_legacy_jobs.sql:227`

O problema depende de alcançar essas expressões ao migrar registros antigos. **Não implica falha obrigatória numa instalação vazia.**

**Promoção:** três etapas obrigatórias são declaradas sem comando, retornam bloqueio e não são substituídas pela aplicação do pacote de aprovação.

- `scripts/state_of_art/triple_aaa_verify.py:513`
- `scripts/state_of_art/triple_aaa_verify.py:541`
- `scripts/state_of_art/triple_aaa_verify.py:544`

**Consequência:** liberar o Docker, isoladamente, não resolve toda a entrega.

### B. A garantia de fundamentação da resposta está incompleta

O Professor valida marcadores existentes, mas não exige que exista algum. Uma resposta sem marcadores pode resultar em `APPROVED_EVIDENCE` com lista vazia de citações.

- Validação: `packages/professor/src/rick_professor/orchestration.py:1097`
- Aprovação: `packages/professor/src/rick_professor/orchestration.py:621`

Isso ocorre após os gates de recuperação autorizada: **não é ausência total de evidência recuperada**, mas falta de ligação explícita entre a resposta gerada e suas fontes.

Além disso, a integração informa sempre risco baixo e intenção clara ao motor de decisão:

- `apps/api/src/services/professor_backend.py:330`

Para um produto com contexto veterinário, essas garantias merecem prioridade antes de ampliar o uso.

### C. A busca externa não entrega toda a capacidade híbrida descrita

O adapter Qdrant retorna candidatos dense acompanhados de lista sparse vazia:

- `packages/retrieval/src/rick_retrieval/backends.py:143`
- `packages/retrieval/src/rick_retrieval/backends.py:201`

A infraestrutura de fusão existe, mas **o caminho externo inspecionado não fornece as duas modalidades**.

### D. Ingestão tem incompatibilidade de tamanho de lote

A ingestão envia todos os chunks do documento em uma chamada; o adapter externo rejeita mais de 256 textos.

- Chamada: `packages/ingestion/src/rick_ingestion/pipeline.py:593`
- Limite: `apps/api/src/services/external_composition.py:166`

Documentos maiores podem falhar mesmo respeitando os limites de upload e parsing.

### E. A interface perde ou transforma informações importantes

- **Upload:** envia sempre para `rag_phase0`, em `apps/web/app/app/documents/page.tsx:157`.
- **Retry:** usa `file.text()`, inadequado para preservar bytes de PDF/DOCX, em `apps/web/app/app/documents/page.tsx:231`.
- **Chat SSE:** omite os metadados usados para classificar a evidência, em `apps/api/src/services/chat_service.py:448`.

No último caso, a resposta imediata pode aparecer como “Evidência fraca”, enquanto o histórico posteriormente recupera a classificação persistida.

### F. Auditoria administrativa pode falhar depois da alteração

Atualização, desativação e reset executam a mutação antes de exigir a gravação do evento de auditoria:

- `apps/api/src/routes/admin.py:112`
- `apps/api/src/routes/admin.py:124`
- `apps/api/src/routes/admin.py:140`

Se o sink falhar, o cliente pode receber erro depois de a operação já ter ocorrido. Falta uma garantia consistente entre resultado da operação e registro obrigatório.

### G. Alguns testes verdes não provam o que seus nomes sugerem

A comparação de equivalência termina com `or True`:

- `apps/api/tests/test_dual_equivalence.py:30`

Assim, aquela comparação não pode falhar. Isso não invalida toda a suíte, mas demonstra por que **quantidade de testes passando não substitui qualidade das asserções**.

## 5. Verificações executadas nesta auditoria

| Comando ou conjunto | Resultado |
|---|---|
| `make validate` | Passou |
| `make lint` e `make typecheck` | Passaram |
| Lint e typecheck próprios de `apps/web` | Passaram |
| `make api16-domain` | **169 testes passaram** |
| `make api16-worker` | **73 testes passaram** |
| `make api16-root` | **472 testes passaram** |
| Contratos / providers / locking / Professor | **6 / 70 / 54 / 36 passaram** |
| Storage / jobs / backup local | **26 / 37 / 7 passaram** |
| Identity, authorization, evidence, decision e observability | **67 passaram** |
| `make eval-retrieval-pack` | Passou: **2 positivos e 3 negativos sintéticos** |
| `make compose-static` | Passou: **14 serviços em cada composição** |
| `make ops-static` | Passou; **não executa as migrações no banco** |
| `git diff --check` | Passou |

Foram **1.017 execuções de testes aprovadas**, com sobreposição entre conjuntos — não 1.017 testes únicos.

A suíte adicional inicialmente falhou na coleta por ausência do caminho da API no comando que montei; após corrigir a invocação, os 67 testes passaram. Houve também avisos de depreciação de dependências.

**Não comprovado por esses resultados:**

- Funcionamento integrado de PostgreSQL, Redis, Qdrant e S3.
- Qualidade das respostas de um LLM real.
- Qualidade clínica ou representatividade do corpus.
- Recuperação de desastre, desempenho sob carga e estabilidade prolongada.
- Acessibilidade e experiência visual efetiva.
- Aprovação da CI no mesmo commit e prontidão de release.

O `typecheck` Python existente é compilação, não análise estática completa de tipos: `scripts/phase11/runner.py:736`.

## 6. Ordem recomendada de trabalho

| Prioridade | Ação | Evidência esperada para fechar |
|---|---|---|
| **1** | Corrigir composição, migração legada e verificações de readiness | Ambiente descartável iniciando; migração com dados antigos; healthcheck do processo real |
| **2** | Fechar garantias de citações, risco e metadados SSE | Respostas sem citações tratadas corretamente; classificação consistente entre stream e histórico |
| **3** | Corrigir ingestão e operações de documentos | Documento acima de 256 chunks; retry PDF/DOCX íntegro; coleção respeitada |
| **4** | Tornar mutação e auditoria consistentes; completar idempotência da UI | Testes de falha do sink e repetição sem efeitos duplicados |
| **5** | Fortalecer testes e avaliação RAG | Remoção de tautologias; métricas documentadas; corpus representativo e autorizado |
| **6** | Completar validação operacional e promoção | Fluxo upload → worker → índice → resposta real; restore, carga e pacote de release verificável |

## Conclusão

**A base de engenharia está mais madura que a entrega operacional.** Os pontos fortes são modularização, controles de acesso, contratos de domínio e verificações locais. Os pontos mais fracos são integração distribuída, recuperação e demonstração da qualidade final das respostas.

**70/100 significa uma base relevante, ainda com lacunas materiais — não “70% pronto para produção”.** O próximo passo de maior valor é corrigir os bloqueadores conhecidos e provar um fluxo completo no ambiente descartável, em vez de ampliar a documentação de aprovação.

Nenhum código foi alterado e nenhum commit foi criado. O estado final continuou com apenas `.opencode/` não rastreado, já presente no início.
