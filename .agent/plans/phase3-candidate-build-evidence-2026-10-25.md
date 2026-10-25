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

### Primeira execução remota e formato do scanner

da46ac2 / quality 40230862139: os sete gates de código PASS. As três imagens
foram realmente construídas com OCI/SBOM/proveniência, mas o scan falhou: Trivy
0.74 suporta Docker tar ou diretório OCI, não tar OCI. Falha preservada. A
proveniência nativa real da API passou no leitor, com 120 pacotes SPDX.

Adaptação limitada: após validar o OCI, exportar somente os bytes da aplicação
selecionada para layout temporário readonly, conferindo SHA256/tamanho novamente.
No publicador existente, corrigir também o mesmo defeito: a captura privada já
admitida fornece um índice normalizado readonly; extração ocorre somente dentro
do container do scanner. Manter verificação dos snapshots antes/depois do tool,
conferência do config digest, cobertura, reconciliação e políticas existentes.
Nenhuma publicação GHCR foi executada.

Provas locais no OCI remoto da API: os dois adaptadores reais de Trivy PASS,
config digest idêntico ao OCI e zero achados, usando o DB local já baixado.
60 regressões focadas PASS; regressão VPS completa corrigida: 764 passed,
1 skipped, em clone privado com TMPDIR=/tmp. make validate PASS. Novo CI no SHA
corrigido ainda necessário; não transferir PASS ou identidade do da46 para outro
SHA. A política de oito gates de publish-images continua intacta e requer revisão
da separação construção/promoção; artefatos deste novo lane não a ratificam.
