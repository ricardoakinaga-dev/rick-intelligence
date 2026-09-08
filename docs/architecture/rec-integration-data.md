# Integração local e dados — contrato REC-05/06/07

## Decisão e limites

Em 08/09/2026 o usuário aprovou Postgres (incluindo fila transacional), S3-compatible
e OIDC em ambiente descartável local. Não autorizou cutover de dados reais nem
rollout de produção. OpenAI/Anthropic são candidatos autorizados de integração;
teto de gasto e corpus ainda precisam ser definidos. O bootstrap de tenants é
operacional, não uma ampliação de autoridade do administrador de tenant.

## Modelo e ownership

O schema novo é aditivo e independente das estruturas SQLite existentes.
Identidades OIDC globais são vinculadas a memberships por tenant/workspace.
Sessões armazenam hash de token, não bearer recuperável, e versão de autorização.
Coleções, grants, documentos, versões, chunks, objetos, jobs, conversas, mensagens
e auditoria possuem escopo obrigatório. Chaves compostas impedem FK cruzada de
tenant/workspace. O worker só publica versão após objetos/chunks/vetores serem
verificados; a versão anterior continua publicada se uma tentativa falhar.

DB é autoridade para memberships, catálogo, publicação, jobs e conversas. S3 é
autoridade dos bytes privados; Qdrant é projeção recuperável. Nenhum desses
serviços decide permissões com base apenas em campos fornecidos pelo navegador.
Mutações sensíveis e audit/outbox precisam compartilhar a transação local.
Indisponibilidade de audit impede a mutação, sem capturar texto clínico no audit.

As consultas de runtime precisam de predicados tenant/workspace e RLS em um papel
sem superuser/BYPASSRLS; migrations usam identidade distinta. RLS ausente ou
configuração de tenant ausente deve negar, não assumir `default`. Bootstrap e
worker exigem escopo explícito. Dado de prompt não altera permissão.

## Compatibilidade e migração

Inventário de consumidores: API root, worker separado, UI root, ferramentas de
avaliação, backups e serviços legados preservados. Legados não escreverão nas
novas tabelas. SQLite continua autoridade do modo local até existir comparação
e aceite da composição externa. Não haverá dual-write implícito.

1. Aplicar expansão em DB vazio descartável, sob lock e checksum de migration.
2. Testar repetição, erro no meio, history divergente e FK de outro tenant.
3. Implementar adapters e composição; comparar consultas com fixture sintética.
4. Só após inventário autorizado: backfill por tenant em lotes de IDs estáveis,
   checkpoint, checksum e versão de origem. Quarentenar IDs sem tenant; não
   deduzir ownership a partir do nome de coleção.
5. Sob concorrência, revalidar versão antes de gravar e reconciliar diferenças;
   counts iguais sozinhos não provam autorização nem conteúdo.
6. Cutover, restore e contract requerem REC-30/33/35. Nenhum DROP automático.

Rollback da expansão: parar novos writers e voltar ao código local mantendo as
novas tabelas. Após writes externos, preferir roll-forward ou restore ensaiado;
reverter código não é prova de preservação dos novos dados.

## Verificação exigida

Dois tenants com IDs de objetos iguais; membership ausente/desativado; token
expirado/revogado; FK cross-scope; concorrência de migration; checksum alterado;
crash antes/depois de commit; job replay/lease perdido; mensagens de outro dono;
paginação limitada; nenhum secret/DSN nos relatórios. Integração real deve usar
papel runtime não privilegiado. Testes com fake de driver verificam o runner,
não provam os constraints do PostgreSQL.

O lock de migration segue as semânticas transacionais documentadas pelo
[PostgreSQL](https://www.postgresql.org/docs/16/explicit-locking.html).
Keycloak `start-dev` é reservado ao laboratório isolado, conforme o
[guia de containers](https://www.keycloak.org/server/containers); não é configuração
de produção. Imagens precisam de digest/scan antes de REC-33.

## Gates ainda abertos

Runtime de containers/DB neste host, integração OIDC real, adapter completo,
restore, corpus/custo/SLO e revisão independente de segurança. Especialista de
segurança não está disponível nesta sessão; autorrevisão não substitui REC-31/34.
