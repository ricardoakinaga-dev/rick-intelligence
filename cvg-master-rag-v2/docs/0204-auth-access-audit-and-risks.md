# 0204 — Auth Access Audit and Risks

## Riscos Técnicos
- Persistência file-based pode sofrer concorrência se a carga crescer.
- Sessões já emitidas podem ficar incompatíveis se o schema for alterado sem tolerância.
- Roles novas exigem retrofit amplo de tipos e checagens.

## Riscos de Segurança
- Token em storage do frontend continua exposto a XSS; nesta rodada será mantido por compatibilidade arquitetural.
- Ausência atual de rate limit aumenta superfície de brute force.
- Reset de senha mal implementado pode vazar existência de usuário.
- Auditoria insuficiente de acesso negado reduz rastreabilidade.

## Riscos de Regressão
- Quebra do shell frontend por mudança no contrato de `EnterpriseSession`.
- Quebra de contas demo ou testes automatizados.
- Bloqueio indevido de rotas legítimas de operator/viewer.
- Impacto indireto em ingestão e corpus repair.

## Riscos de UX
- Mudança de papéis pode confundir operadores atuais.
- Reset/troca de senha pode gerar fricção se a política ficar excessivamente rígida.
- Mensagens muito detalhadas em login/reset podem expor informação sensível.

## Riscos de Dados
- Corrupção de JSON se a gravação atômica falhar.
- Tokens de reset precisam ser invalidados corretamente para evitar reuso.
- Sessões antigas precisam ser revogadas em mudanças sensíveis.

## Medidas Mitigatórias
- Migração aditiva e tolerante.
- Compatibilidade com hashes e roles legados.
- Sanitização rígida de logs.
- Testes específicos de mudança de senha, reset e sessão revogada.
- Proteção por permissão explícita nas rotas críticas.
- Rate limit mínimo em login e reset request.

## Pendências Abertas
- MFA.
- SSO.
- Cookies HttpOnly.
- trilha de auditoria exportável com paginação/retention policy formal.
- histórico de senhas e política de reuse.

## Itens Bloqueantes
- Nenhum bloqueante estrutural para a rodada.
- Limitação arquitetural conhecida: storage JSON local; será tratada como restrição, não como blocker.

## Itens Recomendados para Fase Futura
- MFA por TOTP.
- SSO corporativo.
- allowlist de IP por perfil.
- session/device management mais rico.
- ABAC para políticas por workspace/fonte/documento.
- migração do auth store para banco transacional quando o produto sair do modo interno controlado.
