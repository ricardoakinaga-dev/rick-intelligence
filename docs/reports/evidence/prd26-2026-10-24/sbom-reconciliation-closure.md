# SBOM runtime reconciliation — correção local

Data: 25/10/2026. Base de entrada: `b116f6c358c13c673ad3a729150701b07bb2c0bb`.
As alterações descritas aqui estavam no worktree, sem commit, no momento da
verificação. Este relatório complementa o
[fechamento operacional](operational-closure.md) e o
[fechamento runtime formal](formal-runtime-closure.md); não substitui nenhum
deles e não constitui aprovação de produção.

## Defeito observado

A reconciliação estrita dos três SBOMs nativos falhava com
`versioned package URL required for runtime coverage` e, depois de removidos os
componentes sem versão, com `scanner omitted SPDX runtime distribution
coverage`. A causa não era o scanner Trivy nem a ausência de cobertura das
imagens: o gerador Syft do BuildKit importa metadados que não são distribuições
instaladas.

- API e worker: o SBOM da Pillow embutido no wheel
  (`pillow-13.0.0.dist-info/sboms/pillow-13.0.0.cdx.json`) declara `pybind11`
  sem versão. Os SBOMs `auditwheel.cdx.json` de Pillow, cryptography e
  pypdfium2 também declaram bibliotecas apk empacotadas dentro dos wheels
  (`libbsd`, `libgcc`, `libmd`, `libstdc++`, `libxau`, `libxdmcp`) que não
  existem no banco apk da imagem. O Trivy corretamente não as reporta como
  pacotes instalados.
- Web: `next/dist/compiled/**/package.json` contém manifestos de bundles
  internos do Next.js sem campo `version` (133 entradas). O Trivy reporta as
  39 distribuições npm instaladas, não os shims compilados.

O SBOM nativo tem 121/121/192 nós de pacote. Desses, 7/7/133 são metadados
suplementares; os inventários de runtime comparáveis são 85/85/56, exatamente
os mesmos do Trivy.

## Correção

`infrastructure/vps/publish_candidate.py` passou a separar o inventário de
runtime do metadado suplementar antes da reconciliação:

- um pacote só é classificado como suplementar quando `sourceInfo` o vincula a
  um SBOM embutido de wheel (`*.dist-info/sboms/*.json`) ou a um manifesto de
  bundle compilado do Next.js (`node_modules/**/dist/compiled/**/package.json`);
- o pacote precisa ter purl de um ecossistema de runtime (`deb`, `apk`, `pypi`
  ou `npm`);
- nenhuma identidade versionada do pacote pode estar no inventário do Trivy;
  se estiver, o pacote continua no conjunto estrito e não é excluído;
- caminhos com `..`, purls malformados, identidades sem versão fora dessas
  proveniências e pacotes de runtime sem correspondência continuam recusados.

A decisão é registrada em `sbom_scope`, com `spdx_id`, nome, versão, purls,
`sourceInfo`, motivo (`embedded_sbom` ou `compiled_node_bundle`) e classificação
(`unversioned` ou `not_in_scanner`). O publicador grava `sbom-scope.json`,
inclui o objeto no predicate assinado, inclui seu hash (`sbom_scope_sha256`) e
`admission.candidate_policy` exige que o escopo seja estruturalmente válido,
que `native_sbom_sha256` coincida com `sbom_sha256` e que o hash do escopo
confira. A política de admissão não recebe uma lista de exclusões sem
proveniência: ela verifica o vínculo assinado e a consistência dos campos.

O `spdx_packages` e a regra de que todo pacote de runtime do scanner precisa de
uma identidade SPDX versionada permanecem inalterados. A exceção é limitada a
metadados nativos que não são distribuições instaladas.

## Evidência local

Executado sobre os artefatos assinados de `b116f6c`, com as assinaturas
Sigstore novamente verificadas:

| Serviço | Pacotes de runtime | Pacotes do scanner | Suplementares | Resultado |
| --- | ---: | ---: | ---: | --- |
| api | 85 | 85 | 7 (embedded SBOM) | PASS |
| worker | 85 | 85 | 7 (embedded SBOM) | PASS |
| web | 56 | 56 | 133 (compiled Node bundle) | PASS |

O recibo local está em
`.runtime/phase-3/candidate-build-b116f6c/image-verification-after-fix.json`;
os escopos por serviço estão em
`.runtime/phase-3/candidate-build-b116f6c/review-metadata/sbom-scope-{api,worker,web}.json`.
Esses caminhos são diagnósticos locais, não artefatos assinados de release.

Validação executada:

- `infrastructure/vps/tests`: **778 passed, 1 skipped**;
- regressões focadas de publisher/admission/workflow: **370 passed**;
- `make validate`: **PASS**;
- `make compose-static`: **PASS**;
- `make typecheck`: **PASS**;
- `make lint`: **PASS**;
- `git diff --check`: **PASS**.

## Contrato de publicação

O dispatch de candidate com `candidate_image_evidence=true` agora executa apenas
os sete gates de código e as três lanes de construção. As seis lanes de
produção/ambiente e o job `RELEASE` ficam `skipped` nesse dispatch, porque
dependem de ambiente e autoridade externos. Um dispatch normal em `main`
continua executando todas as lanes; `publish_guard.py` exige `PHASE3` e os
demais gates com conclusão `success`, e `skipped` não satisfaz a promoção. A
separação é de estágio, não de critério: o candidate continua
`promotion_authorized=false`.

## Limites preservados

- O pacote de revisão original de `b116f6c` continua histórico e registra a
  falha anterior; ele não foi reescrito nem reassinado.
- O predicate assinado de `b116f6c` não contém `sbom_scope`, porque foi gerado
  antes desta correção. É necessário um novo rebuild remoto no SHA que contém
  esta mudança para produzir predicate, inventário e assinaturas com o escopo.
- Nenhum corpus/avaliador, perfil TLS/auth, budget operacional, revisão
  independente, assinatura de release ou decisão humana foi criado por este
  relatório.
- A produção continua **NO-GO**. A correção fecha apenas a reconciliação local
  dos SBOMs; os inputs externos e a decisão `GO` permanecem pendentes.
