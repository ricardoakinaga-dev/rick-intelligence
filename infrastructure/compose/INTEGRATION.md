# Laboratório REC local

Preparação de REC-05, **não composição de produção**. Não há API/worker usando
estes serviços ainda. O launcher não declara saúde a partir de `docker up`.

Pré-requisito no host: Docker Engine e plugin Compose, socket local acessível.
A instalação foi autorizada nesta execução, mas `sudo -n apt-get install -y
docker.io docker-compose-v2` foi recusado por exigir senha local. O usuário deve
autenticar no próprio terminal; não compartilhar senha com o agente. Na checagem
final Docker/Compose já estavam instalados externamente, porém a sessão do agente
não conseguia acessar o daemon, mesmo fora do sandbox; sudo não interativo seguia
exigindo senha. Disponibilizar acesso controlado ao socket e reabrir a sessão se
necessário. Não usar permissões globais no socket; grupo Docker equivale a root
e sua concessão depende do responsável pelo host.

Injetar no ambiente, sem valores versionados, secrets descartáveis exclusivos
de 12–256 caracteres: `REC_POSTGRES_PASSWORD`, `REC_S3_ACCESS_KEY`,
`REC_S3_SECRET_KEY`, `REC_QDRANT_API_KEY`, `REC_OIDC_ADMIN_PASSWORD`.
Não usar credenciais de produção. O launcher não lê `.env` automaticamente.

```bash
python3 infrastructure/scripts/integration_lab.py preflight
python3 infrastructure/scripts/integration_lab.py start
python3 infrastructure/scripts/integration_lab.py status
python3 infrastructure/scripts/integration_lab.py stop
```

Projeto fixo `rick-rec-local`; socket explicitamente local, sem Docker context
remoto. Volumes recebem o namespace do projeto e são preservados ao parar.
Não há comando de purge nem `down -v`. Não usar o mesmo namespace para dados
reais. As portas são somente loopback: Postgres15432, S3 19000/console19001,
Qdrant16333 e Keycloak18080. A rede interna não oferece egress para geração IA.

Postgres usa DB/usuário de bootstrap `rick_integration`; esse superuser de
laboratório não pode ser a identidade de runtime da futura API. Keycloak usa
`local-operator` para bootstrap; `start-dev` e seu DB local são apenas fixture.
Reinos/memberships/usuários sintéticos A/B e callback OIDC ainda precisam ser
provisionados e verificados em REC-08, sem fallback para usuários demo da API.

As imagens de Postgres/MinIO/Qdrant reaproveitam os pins da topologia existente;
não são uma certificação de atualização/segurança. Digest e scan de imagens
permanecem em REC-33. Keycloak26.7.3 segue o
[guia oficial](https://www.keycloak.org/getting-started/getting-started-docker).

Sem Docker disponível, somente os testes do launcher e a inspeção do YAML podem
passar. Aplicação de schema, login real, restart, ACL, objetos/vetores, worker e
backup continuam **NOT_RUN**; o contrato está em
[rec-integration-data.md](../../docs/architecture/rec-integration-data.md).
