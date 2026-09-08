# Escopo canônico por persona — REC-02

08/09/2026. Implementação canônica: `apps/web` → `apps/api` → `packages`.
Os três repositórios legados são preservados; portar comportamento por contrato,
sem importar seus módulos na UI ou nos domínios root.

| Persona | Jornada mínima de produto | Permissões que controlam a superfície |
|---|---|---|
| Administrador da organização | usuários/memberships, sessões, auditoria e configuração no tenant da sessão | users.manage, sessions.revoke, audit.read, runtime.manage |
| Gestor do conhecimento | coleções, ingestão, jobs, publicação/reindexação/exclusão, busca e fontes | collections.manage/read, documents.read/upload/manage, ingestion.run, reindex.run, chat.query |
| Veterinário | buscar evidência, conversar, retomar histórico próprio e conferir fontes | chat.query, history.read, sources.read, collections.read |

Essas são jornadas-alvo, não declaração de que todo o console está entregue.
A tabela de permissões executável continua exclusivamente em
`packages/authorization/src/rick_authorization/policy.py`. O servidor resolve
overrides e emite o snapshot final em login, `/auth/me` e `/session`.
`permissions=[]` ou campo ausente não recupera defaults pelo papel na UI.
Wildcard explícito é aceito; remoções devem ser resolvidas antes do snapshot.

`/app` permanece a entrada comum; `/app/documents` é catálogo operacional;
`/app/search` e `/app/chat` são jornadas de evidência; `/admin` é console da
organização, com cada operação verificada pela API. O veterinário não consulta
a contagem do catálogo quando não tem `documents.read`; isso não é falha nem
catálogo vazio. Acesso por URL não elimina a autorização no servidor.

Decisão recebida do usuário nesta execução: Postgres com fila transacional,
S3-compatible e OIDC em ambiente local descartável. Gestão global de tenants
permanece separada do administrador de um tenant; `PLATFORM_ADMIN` não se
torna autorização para ler/mutar outros tenants. O produto não terá criação
global de tenants aberta ao console comum. Bootstrap operacional será explícito.

Paridade opcional com OpenWebUI (plugins arbitrários, marketplace de modelos,
ferramentas executáveis, navegação web, multimodalidade e compartilhamento público)
não integra o mínimo deste release. Conversas persistentes/multi-turn, fontes,
cancelamento e estados de confiança integram. Dados do caso clínico e thresholds
de qualidade dependem da aprovação de corpus/domínio em D04.

Critérios: três papéis reais, permissões removidas, sessão sem grants e troca de
identidade; nenhum pedido administrativo ou de catálogo sabidamente proibido;
respostas antigas não restauram dados privados. Mocks testam falhas específicas;
aceite de persistência exige API/DB reais.
