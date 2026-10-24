# Decisão A — replay/idempotência compartilhado no Redis

**Data:** 24/10/2026. **Decisão humana:** opção A (store compartilhado). **Escopo:** prova local com Redis real, não promoção.

## O que foi provado

Dois clientes Redis independentes e dois `RedisRateLimiter` no mesmo namespace de tenant:

| Operação | Resultado |
|---|---|
| request ID `shared-request` no primeiro cliente | `True` (consome 1) |
| mesmo request ID no segundo cliente | `True` (replay, não consome) |
| request único seguinte | `True` (consome 2) |
| terceiro request único | `False` (limite 2 atingido) |

O script reproduzível é `scripts/phase11/redis_shared_replay_probe.py`; saída observada: `{"replay_on_first": true, "replay_on_second": true, "second_unique": true, "third_unique": false}`.

## Interpretação

A decisão A **já está implementada no boundary do pacote**: `RedisRateLimiter` grava a decisão em `rate-request` no Redis, com escopo de tenant e bucket, e o segundo cliente devolve a mesma decisão sem contar outro token.

O gate HTTP multi-réplica ainda falha porque ele reenvia o **X-Request-ID do chamador**, enquanto a API usa um **nonce server-owned** por requisição (`server_rate_request_id`) por decisão de segurança. Portanto o FAIL do gate é uma **divergência de contrato do harness**, não ausência do store compartilhado. O gate também consome o bucket de login por IP no bootstrap, o que zera o caso `login`.

**Não alterei a API para confiar em X-Request-ID do chamador**; isso reduziria a postura de segurança. Se o gate precisar provar replay cross-réplica via HTTP, ele deve receber um token de replay emitido pelo servidor (não o ID do cliente) ou testar o boundary do pacote.

## Limite

Esta prova não cobre HTTP multi-réplica, TLS, produção ou autorização de release. O gate `redis-multi-replica-runtime` permanece FAIL como harness a corrigir.
