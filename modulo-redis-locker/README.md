# modulo-redis-locker

Microserviço HTTP simples para lock distribuído em Redis usando `SET NX PX`.

## O que faz
- cria lock com TTL
- remove lock manualmente
- expõe healthcheck para orquestradores
- serve como dependência leve para o `rick-professor`

Security boundary: this service does not implement an application-level HTTP
credential. Deploy it only on a private service network or behind an
authenticated application gateway; Redis credentials and the endpoint must not
be exposed to untrusted clients. The lock value is still mandatory and
owner-checked for every release/renew operation, but it is not an HTTP auth
credential.

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
docker network create --internal modulo-redis-locker-private

docker run -d \
  --name redis \
  --network modulo-redis-locker-private \
  redis:7.0.15-alpine

docker run -d \
  --name modulo-redis-locker \
  --network modulo-redis-locker-private \
  -e REDIS_URL=redis://redis:6379 \
  modulo-redis-locker
```

The run example intentionally publishes no host port. Access it from the
Professor/application network at `http://modulo-redis-locker:3000`, or expose
it only through an authenticated private gateway.

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
    image: redis:7.0.15-alpine
    networks:
      - locker-private

  redis-locker:
    build: .
    environment:
      REDIS_URL: redis://redis:6379
      PORT: 3000
    expose:
      - "3000"
    networks:
      - locker-private
    depends_on:
      - redis

networks:
  locker-private:
    internal: true
```

`expose` documents the container port for private service discovery; it is not
a host publication. Do not add a `ports` mapping, host networking, ingress, or
reverse-proxy route for this service. The application or gateway must enforce
caller authentication before reaching Locker.

## Deploy em outra máquina
1. Clone o repositório
2. Ajuste `REDIS_URL`
3. Rode `docker build`
4. Suba com `docker run` ou `docker compose`
