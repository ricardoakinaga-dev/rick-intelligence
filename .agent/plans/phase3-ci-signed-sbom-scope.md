# Phase 3 — escopo SBOM coberto pela assinatura do CI

Baseline limpa 112552095fb2b79c6dbbb73ff44732dd0c59f9a3. A autorização existente
permite alterações reversíveis, publicação em phase3/a8a83ca-candidate e
quality.yml. Não autoriza publicação GHCR, promoção de main ou deployment.
O controlador AUD15, os ledgers, o quality bar e os pacotes históricos ficam
preservados. Este plano é narrativa de implementação, não aceite de produção.

Problema: o publicador já inclui sbom_scope em seu predicate, mas o CI candidato
continua emitindo inventário v1 sem escopo. A classificação só era reproduzida
localmente. Contrato: inventário v2 incorpora escopo, hash canônico e arquivo
sbom-scope.json entre os arquivos assinados. O verificador reexecuta a
reconciliação nos inputs assinados e recusa escopo divergente ou omitido.

Compatibilidade: v1 permanece verificável como evidência histórica sem escopo.
Os caminhos atuais do CI e da CLI exigem v2; v1 nunca satisfaz essa exigência.
Não criar um predicate de produção substituto, credenciais, aceite independente
ou selo de release. production_safe/promotion_authorized continuam false.

Verificação: negativos para omissão, downgrade, alteração de escopo/input,
rehash de arquivo, hash canônico, falha de reconciliação e flags de promoção.
Executar regressões VPS em clone protegido, validate/ops-static/compose-static,
publicar no branch autorizado, executar CI e reverificar os artefatos novos.
Usar .runtime para os resultados; preservar os bytes dos pacotes anteriores.

Pendências externas: publicador de produção em main com políticas revisadas,
TLS/auth/stores, corpus/avaliador, workloads/budgets, revisão independente,
assinaturas de registry, selo e GO com rollback/janela. Não simular esses inputs.

## Progresso

- [x] Recuperação e contrato delimitado.
- [x] Implementação: 76 testes focados; VPS 795 passed/1 skipped em clone
  protegido; ops-static 385 passed; validate/compose-static/diff-check PASS.
- [ ] CI remoto e verificação do escopo assinado.

Verificação remota de pré-requisitos: main ainda em
c6fb3f0ae8e485960d3d54c2a3294ce476e2781d, sem variáveis ou secrets de Actions
configurados. Nenhum valor de segredo foi consultado. O publicador continua
exigindo main/SHA exatos, políticas independentes e PHASE3 success. A pergunta
pendente ao usuário solicita responsáveis reais pelas aprovações; não há
substituição automática dessas autoridades pelo builder ou pelo CI.
