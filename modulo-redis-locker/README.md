# modulo-redis-locker

Microserviço HTTP simples para lock distribuído em Redis usando `SET NX PX`.

## O que faz
- cria lock com TTL
- remove lock manualmente
- expõe healthcheck para orquestradores
- serve como dependência leve para o `rick-professor`

Security boundary: this service does not implement an application-level HTTP
credential. Deploy it only on a private service network or behind an
authenticated gateway; Redis credentials and the endpoint must not be exposed
to untrusted clients. The lock value is still mandatory and owner-checked for
every release/renew operation.

## Requisitos
- Docker 24+
- Redis acessível pela aplicação

## Variáveis de ambiente
| Variável | Obrigatória | Padrão | Descrição |
|---|---:|---|---|
| `REDIS_URL` | sim | - | URL de conexão com Redis |
| `PORT` | não | `3000` | Porta HTTP do serviço |

## Build
```bash
docker build -t modulo-redis-locker .
```

## Run
```bash
docker run -d \
  --name modulo-redis-locker \
  -p 3000:3000 \
  -e REDIS_URL=redis://redis:6379 \
  modulo-redis-locker
```

## Endpoints
### `GET /healthz`
Retorna:
```json
{"ok": true}
```

### `POST /lock`
Body:
```json
{"lock_key":"k","lock_value":"v","ttl_ms":45000}
```

### `POST /unlock`
Body:
```json
{"lock_key":"k","lock_value":"v"}
```

The lock is deleted only when `lock_value` still belongs to the caller. A
wrong owner receives `deleted: false` and cannot remove the active lock.

### `POST /renew`
Body:
```json
{"lock_key":"k","lock_value":"v","ttl_ms":45000}
```

The TTL is extended only for the current owner and returns `renewed: true` on
success.

## Exemplo com Docker Compose
```yaml
services:
  redis:
    image: redis:7-alpine

  redis-locker:
    build: .
    environment:
      REDIS_URL: redis://redis:6379
      PORT: 3000
    ports:
      - "3000:3000"
    depends_on:
      - redis
```

## Deploy em outra máquina
1. Clone o repositório
2. Ajuste `REDIS_URL`
3. Rode `docker build`
4. Suba com `docker run` ou `docker compose`
