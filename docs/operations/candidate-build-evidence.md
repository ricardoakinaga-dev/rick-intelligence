# Evidências de construção do candidato Phase 3

O opt-in `candidate_image_evidence` de `quality.yml` constrói API, worker e web
depois dos sete gates de código do mesmo run. O branch permitido é
`phase3/a8a83ca-candidate`. O checkout, contexto Git remoto, labels, proveniência
e certificado da assinatura devem carregar o mesmo SHA completo. Nenhum gate
de produção ou requisito de `publish-images.yml` é removido.

```bash
gh workflow run quality.yml --ref phase3/a8a83ca-candidate \
  -f candidate_image_evidence=true
```

A construção utiliza os Dockerfiles versionados e o catálogo
`infrastructure/vps/candidate-toolchain.json`. Esse catálogo é uma **proposta não
revisada**. As versões Python 3.12.15 e Node 22.23.2 divergem do CI canônico
(3.12.3/22.19.0). Os digests fixam os bytes; não concedem aprovação de toolchain.
As receitas incluem patches Alpine explícitos para musl/musl-utils e zlib,
sem depender de alterações posteriores em imagens construídas.

Cada artefato `candidate-build-SHA-SERVICE-ATTEMPT` contém:

- `image.tar`: OCI com statements nativos de proveniência e SBOM;
- `provenance.json` e `sbom.json`: cópias dos statements do OCI;
- `scan.json`: Trivy no arquivo OCI exato, com inventário e todas as severidades;
- `quality.json`, `toolchain.json`, `buildx.json`: origem, gates e ferramentas;
- `sbom-scope.json`: escopo reconciliado, com a origem de cada componente suplementar;
- `inventory.json` v2: hashes SHA256 e tamanhos desses oito arquivos, o escopo
  incorporado e seu hash canônico;
- `inventory.sigstore.json`: assinatura keyless do inventário pela identidade CI.

O inventário registra `production_safe=false`, `promotion_authorized=false`,
`signature_scope=CI_CONSTRUCTION_INVENTORY_ONLY` e revisão/GO ausentes.
Uma imagem com achados conserva seu scan e faz a lane falhar. Uma falha anterior
à assinatura pode deixar somente diagnósticos; upload não implica completude.

O escopo v2 é calculado no runner antes da assinatura. Seu
`native_sbom_sha256` vincula os bytes de `sbom.json`; `sbom_scope_sha256` vincula
o objeto canônico. A verificação confere os oito arquivos, reexecuta a
reconciliação e exige igualdade entre o escopo incorporado, o arquivo e os inputs
nativos. O hash canônico do objeto e o hash do arquivo JSON são conferências
distintas. Os arquivos nativos não são filtrados nem reescritos.

Inventários v1, inclusive os de 1125520, permanecem evidência histórica sem
escopo assinado. A função Python admite sua verificação histórica com
`require_scope=False`; os caminhos atuais de assinatura/CLI exigem v2. Essa
compatibilidade não importa um escopo derivado localmente para a assinatura v1.
O schema v2 é exclusivo de construção e não é o predicate do publicador de
produção, uma assinatura de registry, revisão independente ou release seal.

BuildKit armazena SBOM e proveniência como statements anexados ao índice OCI.
O leitor confere os hashes dos blobs, a identidade da aplicação, o sujeito de
cada statement e o source/builder da proveniência. Isso não substitui a revisão
de materiais, receitas, camadas ou política feita pela admissão de produção.
Ver [formato nativo do BuildKit](https://docs.docker.com/build/metadata/attestations/attestation-storage/).

Trivy 0.74 lê OCI em diretório. Depois da verificação, a lane copia somente
manifest, configuração e layers da aplicação escolhida para um layout temporário
montado readonly no scanner; confere novamente SHA256 e tamanho, sem extrair
caminhos do tar. O `Metadata.ImageID` do scan precisa coincidir com o digest da
configuração do OCI original. O arquivo original, com attestations, é conservado.
Ver o [leitor OCI do Trivy](https://github.com/aquasecurity/trivy/blob/v0.74.0/pkg/fanal/image/oci.go).

O publicador de produção também adapta o OCI para esse formato: usa um índice
da aplicação já admitida como input privado readonly e extrai o arquivo
previamente verificado somente dentro do container do scanner. As verificações
de snapshot, digest da configuração, cobertura, reconciliação de SBOM e políticas
continuam obrigatórias, antes de qualquer cópia para registry.

Para inspeção, obtenha o SHA/run/attempt reais de Actions e baixe cada artefato
em um diretório separado. Exemplo a executar na raiz de um checkout confiável
desse SHA, usando os valores reais:

```bash
gh run download RUN_ID --name candidate-build-SHA-api-ATTEMPT \
  --dir .runtime/candidate-review/api
cd .runtime/candidate-review/api
```

A assinatura cobre o inventário, que cobre os arquivos. Verifique ambos,
usando Cosign 2.5.3 obtido e conferido por um canal confiável, o SHA exato e a
identidade completa do workflow:

```bash
cosign verify-blob --bundle inventory.sigstore.json \
  --certificate-identity https://github.com/ricardoakinaga-dev/rick-intelligence/.github/workflows/quality.yml@refs/heads/phase3/a8a83ca-candidate \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-github-workflow-sha SHA \
  --certificate-github-workflow-ref refs/heads/phase3/a8a83ca-candidate \
  --certificate-github-workflow-repository ricardoakinaga-dev/rick-intelligence \
  inventory.json
```

Não desative a conferência do transparency log, certificado ou identidade.
Os argumentos de assinatura e verificação estão documentados nas referências
[sign-blob](https://github.com/sigstore/cosign/blob/v2.5.3/doc/cosign_sign-blob.md)
e [verify-blob](https://github.com/sigstore/cosign/blob/v2.5.3/doc/cosign_verify-blob.md).
Na raiz do checkout confiável, os hashes podem ser conferidos sem executar
nenhum conteúdo do artefato:

```bash
GITHUB_SHA=SHA PYTHONPATH=infrastructure/vps python3 - <<'PY'
from pathlib import Path
import candidate_evidence as ce
ce.OUT = Path('.runtime/candidate-review/api')
ce.verify_files(require_scope=True)
print('construction file hashes verified; production approval remains absent')
PY
```

O job tem somente `contents:read` e `id-token:write`, sem registry write ou
ambiente de deployment. A assinatura identifica a execução de CI; não constitui
revisão independente, selo do release packet ou decisão humana. O instalador
de produção não admite esse schema. A publicação de imagens e promoção
continuam exigindo suas políticas, autoridade e validações originais.

## Construção e promoção são estágios distintos

O dispatch de candidate com `candidate_image_evidence=true` executa somente os
sete gates de código e as três lanes de construção. As seis lanes de
produção/ambiente (`PHASE3`, `CHAOS`, `SOAK`, `PERFORMANCE`, `RUNTIME` e
`FRONTEND-RUNTIME`) e o job `RELEASE` permanecem definidos, mas ficam
`skipped` nesse dispatch porque exigem ambiente e autoridade que o candidate não
possui. Isso permite que a execução de construção termine verde sem transformar
um `skipped` em aprovação.

Um dispatch normal em `main` continua executando as seis lanes e o `RELEASE`.
`publish_guard.py` exige `PHASE3` e os demais gates com conclusão `success`;
`skipped` nunca satisfaz a promoção. O candidato continua com
`promotion_authorized=false` e o pacote de produção continua exigindo corpus e
avaliador aprovados, perfil TLS/auth, budgets, CI confiável, revisão
independente e decisão humana `GO`.
