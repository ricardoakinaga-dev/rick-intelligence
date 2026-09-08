# Benchmarks locais de Phase 1.5 e Phase 1.6

Os artefatos [`phase-1.5-perf.json`](phase-1.5-perf.json) e
[`phase-1.6-perf.json`](phase-1.6-perf.json) registram observações herméticas
do checkout local. A execução não inicia provider live, Qdrant, Redis,
object storage ou uma carga distribuída.

O formato foi ampliado de forma aditiva. Os campos legados `p50` e `p95` e as
seções `retrieval_ms`, `professor_ms`, `upload_ms` e `enqueue_ms` continuam
presentes; cada resumo também traz `n`, `p99`, `min` e `max`. O
`schema_version` do artefato é `2`.

Phase 1.5 mede o caminho local de retrieval e Professor com o provider
determinístico. Como o adapter local oferece stream de deltas, `ttft_ms` mede
o primeiro delta e `completion_ms` mede o evento final validado. `professor_ms`
continua representando a chamada completa legada, preservando a comparação
histórica.

Phase 1.6 mede upload, enfileiramento, publicação e retrieval usando staging
temporário, stores em memória e embeddings determinísticos. Não há fluxo de
geração nessa fase, por isso `ttft_ms` e `completion_ms` são marcados como
`NOT_APPLICABLE`.

Quando o host expõe `/proc/self/statm`, `/proc/self/status` ou `resource`,
`memory` registra RSS antes/depois e o maior RSS observado pelo processo. O
valor cobre o processo inteiro e não é uma alocação isolada por requisição. Se
as APIs não existirem, o status será `NOT_AVAILABLE`.

`cost.status` é sempre `NOT_RUN`: não há telemetria de cobrança e nenhum
provider externo é chamado. `failure_scenarios` contém probes locais
determinísticos com o código esperado e observado. `soak_scenario` é uma
repetição sequencial e limitada do fixture local; não representa capacidade,
concorrência, failover ou duração operacional de produção.
`local_scenarios_status` só fica `PASS` quando todas as sondas e o soak passam;
nesse caso o runner também retorna código zero. Cenários externos de carga,
dependência indisponível, multi-instância e soak de provider ficam
explicitamente em `NOT_RUN`.

## Reprodução

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase15/benchmark.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase16/benchmark.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  scripts/phase15/test_phase15_benchmark.py scripts/phase15/test_check_boundaries.py \
  scripts/phase16/test_phase16_benchmark.py
```

Esses comandos validam somente comportamento local e não autorizam uma
conclusão de carga externa, custo, capacidade multi-replica ou latência de
produção.
