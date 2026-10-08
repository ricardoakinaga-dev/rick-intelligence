# Continuação das melhorias AUD03 — 03/10/2026

Status: rodada local validada; promoção NO-GO. Este relatório descreve a continuação local
sobre o worktree compartilhado com alterações anteriores preservadas. HEAD
`b52f32c141916a2ea3af1a6b913bd91f380606e0`; nenhum commit, push ou deploy.
Os 36 aceites originais permanecem na barra congelada, sem nova nota agregada.

## Alterações desta continuação

- Coleta de cobertura da API e do worker em arquivos separados, permitindo o
  comando paralelo canônico sem mistura de resultados; pisos 75/74 preservados.
- Provider rejeita recusas em JSON/SSE, preserva tools no fallback, valida argumentos
  completos do streaming e conserva eventos de consumo de tokens. Professor
  recusa aprovação quando há ferramentas pendentes, mesmo com orçamento positivo.
- S3 consulta HEAD antes de DELETE para devolver ausência em exclusões repetidas.
  O README registra a permissão adicional e o limite de concorrência dessa observação.
- Criação, alteração, desativação, reset e revogação administrativos usam o
  ledger canônico. Adapters nativos compartilham commit/rollback; customizados
  usam workflow rastreável e mantêm efeitos incertos disponíveis para reconciliação.
- Recuperação de publicação limita tentativas de leitura e conserva resultado
  desconhecido como não terminal. A reconciliação local do serviço completa
  fonte, nome do documento, journal e refresh; não há promessa de recuperação
  após restart ou endpoint HTTP automático.
- Receitas API/worker declaram a dependência de storage usada em execução;
  a reprodução isolada que falhava em 18 casos passou em todos os 126 casos.
- Novas medições de navegador usam `.runtime/qa/web-e2e`. As observações que
  sobrescreveram 251 arquivos históricos foram arquivadas e os bytes autenticados
  anteriores restaurados; nenhum snapshot foi convertido em resultado novo.
- Checkers de CI/importação validam prefixos Python, dependências de jobs,
  loaders Module, redeclarações CommonJS e funções Bash importadas pelo ambiente.

## Evidências já concluídas

[584 testes de provider/Professor e rotas públicas](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-provider-empty-usage-final.command.json)
passaram, com dois casos inaplicáveis pulados, incluindo replay dos contraexemplos
de usage e argumentos de ferramentas. A [crítica independente final](evidence/implementation-aud03-2026-10-03/lead/continuation-provider-final-review/lead-verdict-index.json)
aprovou o recorte local com 123 testes próprios e 25 hashes estáveis. Replays
feitos pelo implementador não substituem essa crítica.

[339 testes de navegador](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-browser-final.command.json)
passaram em build de produção, nos tamanhos 375/768/1440, sem skips planejados.
A observação inicial usa fixtures de transporte e precede as últimas correções
do backend; seus hashes de frontend permitem conferir o recorte conservado.
[Nova execução](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-browser-output-fixed.command.json)
passou nos mesmos 339 casos, com 278 hashes estáveis e destino corrigido.
Os 18 ensaios locais de desempenho mediram LCP máximo de 936 ms e CLS máximo
de 0,0022; não representam p75 de campo nem latência de provider/banco. A cobertura web
foi 744/788 linhas (94,42%), com piso 85.

[Ensaio S3 real local](evidence/implementation-aud03-2026-10-03/runtime/minio-source-object-908e713609a815b9.json)
passou em 12 verificações, com assinatura SigV4, isolamento, limites e remoção
observada do container próprio. MinIO foi compilado do commit identificado:
isso não demonstra paridade com a imagem OCI declarada nem o golden path instalado.

As falhas iniciais e críticas negativas permanecem arquivadas. Em particular,
a primeira regressão integrada desta continuação falhou em dez expectativas
antigas de reset administrativo; os testes foram adaptados à nova unidade
atômica, preservando provas de rollback e persistência após restart.


[A regressão final de cobertura](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-coverage-sealed.command.json)
passou em 1.305 testes da API (18 opt-in pulados) e 154 do worker. Coberturas:
API 76,92% de statements, worker 75,32% de linhas; pisos 75/74 preservados.
As contagens de suites e revisões se sobrepõem e não constituem um total único.

[15 verificações de auditoria no PostgreSQL próprio](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-audit-postgres-sealed.command.json)
passaram com schemas sintéticos isolados e cleanup, cobrindo as novas transações
administrativas e o replay que preserva alteração posterior de papel.
O adapter customizado teve [116 testes focados](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-custom-owner-final.command.json)
aprovados, com 12 opt-in pulados, após corrigir a falsa alegação de rollback.

[Lint, typecheck, controles restaurados, validate e Compose estático](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-controls-sealed.command.json)
passaram sobre fontes estáveis. [OpenAPI](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-contract-sealed.command.json)
foi regenerado e conferido: 55 rotas, bytes iguais ao schema anterior.

A [revisão independente da ingestão](evidence/implementation-aud03-2026-10-03/lead/continuation-ingestion-final-review/novel-final.log)
passou em 20 probes próprios e 175 testes atuais. O aceite é limitado a memória,
SQLite e serviço assíncrono local; PostgreSQL/Qdrant instalado, restart e migração
de dados existentes não foram validados por essa revisão. O Lead executou
[53 verificações atuais de conhecimento/ingestão no PostgreSQL próprio](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-ingestion-postgres-owned.command.json),
todas aprovadas, em escopos sintéticos únicos do banco já migrado. Uma
[nota de escopo](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-ingestion-postgres-scope-note.json)
corrige a mensagem copiada do harness: essa execução não aplicou migrações.


A [crítica independente final de auditoria](evidence/implementation-aud03-2026-10-03/lead/continuation-audit-final-review/lead-verdict-index.json)
aprovou o recorte com 69 probes e 213 hashes estáveis. A
[crítica final de CI/importações](evidence/implementation-aud03-2026-10-03/lead/continuation-ci-final-review/lead-verdict-index.json)
aprovou a discriminação estática limitada com 16 controles de runtime TS,
434 regressões e hashes estáveis. Fluxos dinâmicos arbitrários continuam
conservadoramente rejeitados; não há execução comprovada de GitHub CI.
A [suíte final de ferramentas](evidence/implementation-aud03-2026-10-03/lead/continuation-20261003-tooling-sealed.command.json)
passou em 1.100 testes, com 74 opt-in pulados. Todos os pisos e critérios
originais foram preservados; revisões anteriores reprovadas ou inválidas
continuam disponíveis como evidência histórica.

## Limites de aceite

O checkpoint corrente é [v2](evidence/implementation-aud03-2026-10-03/execution-checkpoint-v2.json),
com o [v1](evidence/implementation-aud03-2026-10-03/execution-checkpoint-v1.json)
preservado como predecessor. Evidência positiva local não declara conclusão das
36 tarefas nem autorização de promoção. Inventário instalado de migrações,
IdP/provider/corpus representativo, collector/alertas, carga/DR/soak com budgets
aprovados e autoridade de assinatura continuam ausentes. Política clínica
continua fechada pelos flags existentes.

## Correção de reprodutibilidade do restore — 03/10/2026

O import em `docs/ci/restore_control_inputs.py` agora suspende a gravação de
bytecode e restaura a configuração anterior em `finally`. A checagem de conflitos
preserva a árvore também quando `PYTHONDONTWRITEBYTECODE` está ausente. Os quatro
testes de conflito forçam a configuração padrão do interpretador, para que o CI
não esconda uma regressão; quatro casos adicionais cobrem sucesso e exceção do
import, com as duas configurações iniciais.

A [reprodução anterior à correção](evidence/implementation-aud03-2026-10-03/lead/bytecode-fix-before-unset.command.json)
registrou 4 falhas e 15 testes aprovados, removendo explicitamente a variável com
`env -u PYTHONDONTWRITEBYTECODE`. Após a correção, passaram **23 testes sem a
variável** ([comando e hashes](evidence/implementation-aud03-2026-10-03/lead/bytecode-fix-after-unset.command.json))
e **23 com a variável igual a 1** ([comando e hashes](evidence/implementation-aud03-2026-10-03/lead/bytecode-fix-after-enabled.command.json)).
As fontes permaneceram estáveis durante ambas as execuções.

O runner agora registra `PYTHONPATH` e `PYTHONDONTWRITEBYTECODE` no campo
`environment` dos novos arquivos `.command.json`. Esse campo descreve o ambiente
passado ao lançador; nos ensaios desta correção, o comando `env` registrado em
`command` explicita a remoção ou definição da variável para o Python de teste.
A execução histórica de 1.100 testes usou o runner que define a variável como
`1`, mas seu registro não incluía esse campo. A evidência original foi preservada;
esta correção validou o arquivo de testes afetado, sem repetir a suíte completa.

Este complemento cobre o import, seus testes e o registro do ambiente. As
migrações, locks e demais alterações de rodadas anteriores não receberam uma
nova validação conjunta; as datas futuras dos locks também não foram alteradas.
O checkpoint v2 permanece como registro da rodada anterior, e este complemento
documenta a alteração posterior. Os limites de aceite e o NO-GO global permanecem.

## Runner de evidências v2 — 03/10/2026

O runner v1 (`evidence/implementation-aud03-2026-10-03/lead/run_validation.py`) definia
`PYTHONDONTWRITEBYTECODE=1` em toda execução, o que escondeu as quatro falhas do
restore na rodada anterior. Ele foi preservado sem alteração, porque evidências
existentes registram seu hash. O novo
[`run_validation_v2.py`](evidence/implementation-aud03-2026-10-03/lead/run_validation_v2.py)
herda a configuração de quem o chama e só define a variável com `--no-bytecode`
explícito. Cada registro agora traz `launcher_environment` e `effective_environment`;
o segundo aplica o prefixo `env -u`/`env NOME=valor` do comando, de modo que o JSON
mostra o ambiente efetivamente visto pelo processo de teste.

A [suíte de ferramentas executada pelo v2 sem a variável](evidence/implementation-aud03-2026-10-03/lead/tooling-runner-v2-unset.command.json)
passou em 1.104 testes, com 74 opt-in pulados, fontes estáveis em 126 hashes e
`PYTHONDONTWRITEBYTECODE` ausente nos dois campos de ambiente. As demais suítes
(API, worker, navegador) não foram reexecutadas por este runner.
