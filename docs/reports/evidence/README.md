# Política de evidência (AUD07-18)

Esta pasta deixa de ser um depósito de 1,86 GB não rastreado e passa a ter dois destinos
distintos. As regras abaixo são a **única fonte** desta decisão e são aplicadas pela ferramenta
`scripts/phase11/evidence_store.py`, cujo `check` corre no `make validate`.

## 1. O que fica aqui e é versionado no git

1. **Evidência citada** — qualquer ficheiro referenciado pelo control-plane (`.agent/`),
   pelos `control-inputs` (`docs/ci/control-inputs/`), por documentos (`docs/**`) ou por
   ferramentas (`scripts/**`, `tests/**`). São estas as referências que os gates verificam
   hoje (337 ficheiros, 1,84 MB) e, por isso, não se movem.
2. **Conjuntos `auditoria-*`** — os sumários e páginas de evidência das auditorias
   (p. ex. esta remediação) destinam-se a ser lidos nos relatórios: ficam inteiros.
3. **Ficheiros na raiz desta pasta** — a própria política e os sumários (texto < 1 MB).

Tudo o resto é material bruto (árvores de *build*, `node_modules`, `.venv`, `.next`, `dist`,
tarballs, binários, logs não citados).

**Exceção ao `.gitignore`:** a regra `*.log` da raiz esconderia 248 dos ficheiros mantidos —
ficariam nem versionados nem na bolsa, existindo só no *worktree*. O `.gitignore` tem por isso
`!docs/reports/evidence/**/*.log`, e o `check` repete a mesma pergunta ao git
(`git check-ignore --no-index`), falhando com `evidência mantida ignorada pelo git` se a
exceção desaparecer. Sonda:
[`discrimination/evidence-store-gitignore.txt`](auditoria-2026-10-07/discrimination/evidence-store-gitignore.txt).

## 2. Para onde vai o material bruto

Nada é apagado: cada ficheiro é **movido** (renomeado, no mesmo sistema de ficheiros) para a
bolsa *content-addressed* `artifacts/evidence-store/<sha[:2]>/<sha256>` (ignorada pelo git),
com os *links* simbólicos registados em `links/…`.

- `artifacts/evidence-store/MANIFEST.tsv` — inventário completo
  (`original_path`, `sha256`, `bytes`, `kind`, `store_relpath`), gerado pela aplicação.
- `STORE-SUMMARY.json` (versionado) — sumário com **proveniência** (data, regra, contagens,
  bytes) e o **hash do manifesto** (`manifest_sha256`), que ancora o inventário no git.

## 3. Comandos

| Comando | Papel | Onde corre |
|---|---|---|
| `evidence_store.py apply` | classifica, move para a bolsa, grava manifesto e sumário | manual, uma vez por material novo |
| `evidence_store.py check` | layout conforme, citadas presentes, hash do manifesto, amostra de *blobs* | `make validate` (e CI) |
| `evidence_store.py verify` | recomputa **todos** os hashes da bolsa | manual / evidência |
| `evidence_store.py restore [caminho …]` | devolve um ficheiro ao caminho original (hash verificado) | manual, antes de consumir um *bundle* |
| `evidence_store.py relink` | fecha o inventário: recupera caminhos por pares `(path, sha256)` e regista como `-` os *blobs* sem caminho | manual, após qualquer `apply` interrompido |
| `evidence_store.py stat` | mostra o sumário corrente | manual |

Num *clone* novo a bolsa não existe (é ignorada pelo git): o `check` valida então as citadas e a
ausência de material bruto na pasta; a verificação completa só é possível com a bolsa presente.

## 4. Regras operacionais

- **Evidência nova dirigida a relatório** → `auditoria-<data>/…`, que fica versionada.
- **Material de execução/validação novo** → roda `apply`; não deixe nada bruto na pasta.
- `verify` antes de arquivar/promover; um hash divergente é falha, nunca silencie.
- A bolsa vive em `artifacts/` (gitignored). Enquanto não houver publicação externa (artefacto
  de CI ou armazenamento com referência imutável — ver limites na evidência desta tarefa), ela é
  o único sítio com o conteúdo: trate-a como dados preciosos e faça cópia de segurança.

## 5. Limites conhecidos

- As referências do `.gauntlet/state.json` (2916 caminhos) apontam para material agora na
  bolsa: o validador `gauntlet_state.py validate` **não** verifica esses caminhos
  (`artifacts.jsonl` está vazio), mas um *run* que precise deles deve `restore` primeiro.
- Os *scripts* `docs/ci/prove_control_restore.py` e `snapshot_control_inputs.py` leem
  histórico dessa pasta; corra `restore` antes de os executar.

## 6. Notas de execução (2026-10-08)

O primeiro `apply` foi **interrompido** por um diretório só-leitura
(`production-2026-10-04/identity-replica30/...`) antes de gravar o manifesto: o conteúdo já
movido para a bolsa ficou sem o mapeamento caminho→hash. A ferramenta foi corrigida para
(`a`) tornar o diretório de origem gravável e re-tentar, (`b`) gravar o manifesto de forma
crash-safe e (`c`) ganhar o subcomando `relink`, que:

1. recupera caminhos a partir dos pares `(path, sha256)` de inventários sobreviventes
   (`.gauntlet/state.json`, `.agent`, `docs/ci/control-inputs`, JSON de evidência mantidos);
2. regista o resto como linha `original_path = -`: o **conteúdo** continua íntegro e
   verificável por hash, mas o caminho original dessas linhas não é recuperável.

Ver `docs/reports/evidence/auditoria-2026-10-07/evidence-destination.md` para a contagem
exata e a lista de citações a diretórios afetadas.

Páginas-ponte criadas para os diretórios citados que ficaram só com a política:

- `docs/reports/evidence/implementation-aud03-2026-10-03/README.md`
- `docs/reports/evidence/implementation-aud03-2026-10-03/ci-restore/README.md`
- `docs/reports/evidence/implementation-aud03-2026-10-03/runtime/README.md`

## 7. Detecção de citações

`check` exige a existência das citações **absolutas** (`docs/reports/evidence/…`). Citações em
forma relativa (`evidence/…`, `reports/evidence/…`, `../reports/evidence/…`) são normalizadas e
também contam para manter um ficheiro no lugar (`is_kept`), mas reportam-se apenas como aviso
quando o alvo não existe — a árvore histórica tem links relativos a material anterior a esta
política.

Uma segunda passagem varre os **ficheiros de texto já mantidos dentro desta pasta** e resolve os
seus próprios links markdown contra o diretório onde estão: um pacote de revisão guardado aqui
(`…/identity30-review-output/review.md`, por exemplo) liga-se a irmãos `review.json`,
`independent-check.py`, etc. Esses alvos entram no conjunto de citações (forma relativa), de
forma que o pacote fica completo na árvore. Sem a passagem, o `apply` movia parte de um conjunto
citado e deixava a página mantida a apontar para ficheiros ausentes. Link de página mantida a
alvo ausente continua a ser aviso, como nas outras formas.

## 8. Recuperar conteúdo da bolsa

Três rotas, por ordem de preferência:

1. **Caminho conhecido** — `restore <caminho-original>` (lê o manifesto e re-grava no sítio).
2. **Cópia local de referência** — copie a cópia e confirme que o hash calculado existe na bolsa
   (`artifacts/evidence-store/<sha[:2]>/<sha256>`). Só então o ficheiro pode voltar para a
   árvore: é conteúdo que já estava preservado, com prova.
3. **Hash registado noutro sítio** — se a evidência guarda a hash do próprio ficheiro (p. ex.
   `archive-manifest.json` de um pacote), localize o *blob* por hash e copie-o de volta.

Depois de repor ficheiros, corra `check`: alvo reposto com hash diferente da bolsa é erro
(`restaurado com hash diferente`), não aviso.
