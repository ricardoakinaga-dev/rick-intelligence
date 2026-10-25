# Phase 3 — construção remota de evidências do candidato

Continuação limitada do plano de inputs de produção; não altera o controlador
AUD15, seus aceites, o quality bar ou a política de publicação em main.

Baseline limpa: 169c1a792956eef44569a81d3ce5d1b5feddb6ea. O usuário já
autorizou o branch público phase3/a8a83ca-candidate e quality.yml. Escopo:
adicionar construção opt-in nesse workflow após os sete gates de código,
arquivos OCI, SBOM e proveniência nativos, scan e assinatura verificável de um
inventário de hashes. Artefatos somente em Actions; sem packages:write,
implantação, publicação GHCR ou assinatura de aprovação de produção.

Há ciclo entre PHASE3 e publish-images: PHASE3 exige imagens e a publicação
exige PHASE3. A evidência de construção anterior à promoção quebra a dependência
operacional sem remover nenhum requisito de promoção. Toolchain proposta deve
ser identificada como não revisada, incluindo a divergência de versões do CI.

Aceite local: rejeitar SHA/ref/repositório/gates incorretos; conferir o digest
do OCI e seus blobs, sujeito das attestations, source e builder da proveniência;
conservar resultados de scans; vincular os arquivos reais ao inventário assinado;
verificar certificado Sigstore contra identidade, emissor, SHA e branch exatos.
Testes negativos e make validate/ops-static/compose-static antes da publicação.
Depois, executar CI real no SHA publicado e registrar resultados reais.

Recuperação: arquivos em candidate-evidence/ nos runners e .runtime/ local,
sem segredos. Falhas preservadas por upload always. Nenhum artefato daqui é
admitido automaticamente pelo instalador ou pelos gates de produção. A revisão
independente, política de produção, corpus, budgets e GO humano seguem separados.

## Progresso

- [x] Descoberta, limites de autoridade e contrato registrados.
- [x] Implementação; 53 regressões focadas e 757 testes VPS PASS/1 skip em
  clone isolado com TMPDIR=/tmp. make validate/compose-static PASS.
- [ ] Execução remota, inspeção criptográfica e relatório do resultado.

## Descobertas de verificação

O TMPDIR original atravessa um ancestral gravável por grupo e foi corretamente
recusado pelas fronteiras de captura. O clone isolado preserva essas regras;
nenhuma permissão do host foi alterada. A suíte VPS expôs ainda um fixture antigo
de no-op com dez migrações, embora existam onze: usar o inventário completo no
caso no-op e deixar somente a última pendente no outro caso. Mantidos os asserts
de histórico intacto e nenhuma execução de SQL no no-op.

As saídas reais, inclusive execuções recusadas, ficam sob
`.runtime/phase-3/candidate-build-*.log`. Esta narrativa não aceita tarefas nem
aprova o perfil de produção.
