# Observability boundary

`packages/observability` supplies safe composition primitives without making
telemetry a hidden global dependency. `safe_event` and `redact` serialize only
bounded JSON-compatible values, with per-event node and UTF-8 byte budgets;
event names accept only a bounded identifier syntax and invalid names collapse
to `event`. Sensitive keys include authorization/cookies, credentials, tokens,
prompts, document/content fields, stack traces and raw responses. Hierarchical
URLs are reduced to scheme/host/path and lose userinfo, queries and fragments,
including non-HTTP schemes such as Redis; the same rule applies to URL-like
text embedded inside a free-form diagnostic string.

`CorrelationContext` validates request/correlation/trace identifiers.
`should_sample` is deterministic for a trace ID. `CounterRegistry` and
`Histogram` have explicit cardinality/sample bounds. `evaluate_slo` and
`AlertRule` distinguish `healthy`, `breach`, and `no_data`; no missing sample
is treated as healthy.

## Composição local verificada

O seam da API está implementado em `apps/api/src/core/telemetry.py` e é
instalado pelo `MetricsMiddleware` na borda mais externa da aplicação. Ele
observa rejeições antecipadas, respostas nativas de erro, encerramentos por
desconexão/cancelamento e respostas concluídas sem colocar caminhos, queries,
identidades ou conteúdo em labels. A taxonomia de rotas e as classes de status
são finitas; a janela de SLO e o histograma retêm no máximo 10.000 requests.

O snapshot é exposto somente em
`GET /api/v1/admin/metrics`, protegido por `observability.read`. Os testes
`apps/api/tests/test_telemetry.py`, `test_transport_observation.py`,
`test_server_error_transport.py` e `test_health.py` verificam o limite do
registro, a precedência de falhas reais sobre transporte fechado, a janela de
SLO e a ausência de tokens, queries e conteúdo. O snapshot declara
`export.status=NOT_CONFIGURED` porque ainda é um sinal por processo; isso não
é uma afirmação de agregação distribuída.

Os primitives de correlação e tracing continuam disponíveis no pacote, e a
API devolve `X-Request-ID`/`X-Correlation-ID`. A auditoria de ações sensíveis é
uma fronteira separada: tanto o
`InMemoryAuditSink` (retenção bounded de 10.000) quanto o `SQLiteAuditSink`
redigem campos sensíveis antes de armazenar; somente o segundo prova reopen
local.

## Stream local de lifecycle do worker

`BoundedEventBuffer` e `emit_safely`, em `packages/observability`, formam o
seam de eventos locais. O buffer é um ring thread-safe de 256 registros por
padrão, com redaction na entrada e deep-copy na entrada e no snapshot. O
helper normaliza o evento antes de entregá-lo ao sink, usa uma espera bounded
em thread daemon e engole falhas do callback: um collector bloqueado não pode
prender o worker, e observabilidade não pode alterar o estado autoritativo do
job.

`LocalJobRunner` e `SQLiteDurableQueue` aceitam um `event_sink` opcional. Eles
emitem eventos depois das transições locais de enqueue/start/claim,
heartbeat/failure/terminal/cancel/recovery, sem executar callbacks enquanto o
lock ou a transação está ativo. O payload do worker não é encaminhado:
somente status, estágio/progresso, códigos de erro bounded e referências
opacas hashadas de job/worker atravessam a fronteira. Tenant, workspace,
collection, source key, argumentos, metadata e texto de exceção não fazem
parte dos eventos.

O `create_app` agora cria o `ApiTelemetry` pertencente àquela instância antes
de compor o `IngestionApplicationService` padrão e injeta esse sink no
executor local real do upload. A borda `ApiTelemetry.emit` aplica uma segunda
allowlist finita, com esquema próprio por evento para os nomes documentados de
runner, job, queue e ingestion; estados inválidos e campos de outro evento são
descartados;
`worker.arbitrary.internal` é descartado, mesmo que tenha formato válido. O
upload root usa uma barreira por submissão: em uma submissão nova que chega ao
worker, `enqueued` precede `started` e o estado terminal. Cancelamento antes do
início pode omitir `started`, e recuperação do journal não recria um evento
`enqueued`; essas exceções são parte do contrato, não uma sequência universal.
Os eventos carregam refs opacas de job/request/correlation e não filename,
conteúdo ou scope. O sink continua opcional para serviços injetados,
preservando a identidade do container chamador.

Esse stream é por processo e opt-in; a fila SQLite continua sendo uma
durabilidade local de processo único. Ela mantém uma janela explícita e
bounded de linhas terminais (`max_terminal_rows`) além do limite de jobs
ativos; terminais fora da janela deixam de reservar a chave de idempotência.
O runner em memória continua volátil. Não há persistência de telemetria,
exporter, collector, replay ou agregação multi-instância implícitos.

## Limite de promoção

O pacote não possui exporter, collector, registry global mutável, chamada de
rede ou dependência de provider. A implementação local do stream de worker
não é evidência de entrega: agregação multi-instância, exportação de traces,
collector, entrega de alertas e drills live de SLO permanecem `NOT_RUN`; sua
execução exige runtime externo autorizado. Qualquer integração futura deve
preservar a redação, os labels bounded e a declaração explícita de `no_data`.
