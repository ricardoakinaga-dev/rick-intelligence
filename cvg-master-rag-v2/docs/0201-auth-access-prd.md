# 0201 — Auth Access PRD

## Objetivo do Módulo
Implantar uma camada de acesso interna, robusta e auditável para o console RAG híbrido, cobrindo identidade, autenticação, senhas, sessões, papéis, permissões e trilha de auditoria sem quebrar o restante do sistema.

## Contexto de Uso
- Sistema interno, não público nesta fase.
- Usuários operam:
  - ingestão
  - revisão de corpus
  - busca de chunks
  - chat RAG
  - auditoria operacional
- A prioridade é segurança prática com baixo impacto arquitetural.

## Escopo

### Dentro do escopo
- Usuários internos sem cadastro público.
- Criação controlada de usuários por admin autorizado.
- Ativação/desativação de usuário.
- Login com identificador e senha.
- Sessão revogável com expiração.
- Logout.
- Troca de senha autenticada.
- Reset de senha com token temporário.
- RBAC com papéis canônicos:
  - `super_admin`
  - `admin_rag`
  - `auditor`
  - `operator`
  - `viewer`
- Permissões explícitas para ações críticas.
- Auditoria de eventos de segurança e acesso.
- Compatibilidade incremental com o estado atual do sistema.

### Fora de escopo nesta rodada
- Cadastro público.
- MFA.
- SSO.
- OAuth externo.
- ABAC completo.
- Gerenciamento de dispositivos confiáveis.
- Política avançada de risco geográfico/IP.
- Refatoração completa para banco relacional.

## Perfis de Usuário

### super_admin
Pode:
- gerenciar usuários
- alterar papéis e permissões
- resetar senha de terceiros
- revogar sessões
- consultar e exportar auditoria
- gerenciar configurações sensíveis
- executar ações destrutivas do RAG

Não pode:
- contornar trilha de auditoria

### admin_rag
Pode:
- gerenciar fontes
- subir documentos
- rodar ingestão
- rodar reindexação conforme política
- executar auditorias operacionais do corpus
- consultar sinais operacionais e logs de operação

Não pode:
- gerenciar usuários e papéis
- alterar configurações ultra sensíveis de acesso

### auditor
Pode:
- usar busca e chat
- consultar documentos e chunks
- consultar logs/auditoria autorizados
- rodar leitura operacional sem mutação

Não pode:
- ingerir
- apagar
- reindexar destrutivamente
- gerenciar usuários

### operator
Pode:
- subir documentos
- rodar ingestões permitidas
- revisar chunks
- usar chat e busca

Não pode:
- gerenciar usuários
- alterar permissões
- executar ações destrutivas sensíveis

### viewer
Pode:
- consultar chat
- pesquisar chunks
- ler conteúdos permitidos

Não pode:
- ingerir
- reindexar
- alterar base
- acessar governança operacional sensível

## Regras de Negócio
- Não existe cadastro público.
- Todo usuário nasce por ação controlada.
- Usuário inativo ou desabilitado não autentica.
- Password reset token deve expirar e ser invalidado após uso.
- Mudança de senha invalida sessões anteriores do usuário.
- Desativação de usuário invalida sessões anteriores do usuário.
- Ações críticas devem ter autorização explícita por permissão, não apenas por tela.
- Acesso negado deve ser auditado quando tecnicamente viável.
- A trilha de auditoria não deve registrar senha ou token puro.

## Ações Críticas
- criar usuário
- editar usuário
- desativar usuário
- resetar senha de outro usuário
- alterar papel
- revogar sessão
- criar/remover fonte de dados
- iniciar ingestão
- iniciar reindexação
- apagar documentos
- apagar chunks
- exportar auditoria
- alterar configurações sensíveis

## Critérios de Aceite
- Login funcional com senha válida e usuário ativo.
- Login inválido gera resposta segura e evento de auditoria.
- Troca de senha autenticada funciona e revoga sessões anteriores.
- Reset com token funciona, expira e registra auditoria.
- Sessão expira e pode ser revogada.
- Viewer não consegue ingerir.
- Auditor não consegue mutar corpus.
- Admin RAG não consegue gerenciar usuários.
- Super admin consegue governança completa.
- Chat, busca e indexação continuam funcionais.
- Trilhas de auditoria registram eventos de segurança e ações críticas.

## Restrições do Projeto
- Preservar a arquitetura atual baseada em FastAPI + frontend Next.js + persistência local JSON.
- Não substituir o stack de auth por serviço externo nesta rodada.
- Não quebrar contratos já consumidos pelo frontend.
- Fazer migração aditiva e reversível.

## Compatibilidade com Uso Interno e Não Público
- Fluxos podem ser objetivos e operacionais.
- Recuperação de acesso humana assistida pode coexistir com reset técnico.
- UI pode priorizar clareza operacional em vez de onboarding público.

## Decisão de Compatibilidade
- O papel legado `admin` será tratado como alias/migração para `super_admin` para não quebrar o runtime atual.
- O restante das rotas será migrado para permissões explícitas preservando a semântica atual até a transição ser concluída.
