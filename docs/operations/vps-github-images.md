# Linux VPS from GitHub Container Registry

This installation targets `ricardoakinaga-dev/rick-intelligence` on a Linux amd64
VPS. Construction CI publishes **candidates**. It does not deploy, approve a
release, enable clinical features, or satisfy production/provider/runtime gates.
No remote host or credential is embedded. No hosted workflow or VPS execution has
been demonstrated by this local implementation.

## Candidate construction

Run `.github/workflows/publish-images.yml` from **main**, supplying `source_sha`
(the exact current 40-character main SHA) and `quality_run_id` (a real completed
`.github/workflows/quality.yml` run for that SHA, from canonical main).
The gate checks FAST, UNIT, CONTRACT, SECURITY, RAG-EVAL, FRONTEND,
SUPPLY-CHAIN and PHASE3 jobs succeeded,
including the canonical quality workflow's hash-locked Python and npm installs.
Missing/skipped/failed prerequisite jobs, PR/fork runs, cancelled runs and
mismatched SHAs are refused. A failed later RELEASE job does not block candidate
construction: promotion consumes these images afterwards. Its failure remains
recorded, and the signed candidate explicitly has no promotion authority.
No successful prerequisite run is invented; all eight gates remain mandatory.

Administrators must review and set these repository variables to verified
`registry/repository@sha256:<64 lowercase hex>` references:

| Repository variable | Required image capabilities |
| --- | --- |
| `RICK_PYTHON_IMAGE` | Debian Python 3.12 runtime with adduser/addgroup and pip |
| `RICK_NODE_BUILD_IMAGE` | Node 22 image usable by existing web build |
| `RICK_NODE_RUNTIME_IMAGE` | Alpine Node 22 runtime with adduser/addgroup |
| `RICK_BUILDKIT_IMAGE` | BuildKit supporting OCI exporter and attestations |
| `RICK_DOCKERFILE_FRONTEND_IMAGE` | Dockerfile frontend supporting existing Dockerfiles; overrides their mutable syntax comment through `BUILDKIT_SYNTAX` |
| `RICK_SBOM_GENERATOR_IMAGE` | BuildKit SBOM generator compatible with `generator=` |
| `RICK_TRIVY_IMAGE` | Trivy with OCI archive scanning and vulnerability database access |
| `RICK_SKOPEO_IMAGE` | Skopeo supporting `oci-archive`, `--all`, `--preserve-digests`, authfile and digestfile |

Also require `RICK_BUILDX_VERSION` (exact `vMAJOR.MINOR.PATCH`, no range,
prerelease or `latest`) and `RICK_BUILDX_SHA256` (independently reviewed lowercase
SHA-256 of that official Linux amd64 release binary). No version or checksum is
invented here. `buildx_binary.py` fetches the exact versioned official URL,
checks its bytes **before executing them**, checks the reported version and
installs it in an isolated private Docker CLI plugin directory. Missing or
changed inputs block construction. `buildx.json` records the binary URL, version,
checksum and observed version; the signed candidate predicate includes it.

There are no mutable/default base images. Reviewed tool digests and versions are
platform prerequisites; a digest alone does not establish publisher trust.
The Actions are pinned to verified official repository commits: [checkout](https://github.com/actions/checkout/commit/11bd71901bbe5b1630ceea73d27597364c9af683),
[build-push](https://github.com/docker/build-push-action/commit/263435318d21b8e681c14492fe198d362a7d2c83),
[Cosign installer](https://github.com/sigstore/cosign-installer/commit/d58896d6a1865668819e1d91763c7751a165e159),
[artifact upload](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02).
The pinned Cosign installer checks the downloaded version's checksum. Maintain
these reviewed pins through normal source review, not runtime tag resolution.
The previously pinned Buildx setup action has no checksum input and can execute
the downloaded binary during setup ([exact implementation](https://raw.githubusercontent.com/docker/setup-buildx-action/e468171a9de216ec08956ac3ada2f0791b6bd435/src/main.ts)).
Its use is replaced by the reviewed binary installer and explicit builder
creation with the immutable BuildKit image; action pinning alone is insufficient.

Each service builds once into a local OCI archive with maximum provenance and
SBOM, validates their metadata hashes and application bindings, and scans the archive before registry
copy. HIGH and CRITICAL findings, including unfixed findings, block copy. Scanner
failure or incomplete metadata also blocks copy. Skopeo copies all manifests
without changing digests to a unique `candidate-<SHA>-<run>-<attempt>` tag at:

- `ghcr.io/ricardoakinaga-dev/rick-intelligence-api`
- `ghcr.io/ricardoakinaga-dev/rick-intelligence-worker`
- `ghcr.io/ricardoakinaga-dev/rick-intelligence-web`

The copied registry digest must equal the scanned build digest. The workflow
then signs that digest, publishes a keyless in-toto candidate attestation and
verifies both. The candidate predicate binds source SHA, immutable image ref,
quality run URL/attempt, scan/SBOM/provenance/archive SHA-256 hashes, immutable
base/tool inputs, and `promotion_authorized: false`. Verification requires:

```
identity: https://github.com/ricardoakinaga-dev/rick-intelligence/.github/workflows/publish-images.yml@refs/heads/main
issuer: https://token.actions.githubusercontent.com
predicateType: https://rick-intelligence.dev/attestations/candidate/v1
```

OCI admission closes the published descriptor inventory: exactly one runnable
`linux/amd64` manifest, with all remaining members recognized non-runnable
attestations attached to that application. Transport wrappers may have no
siblings. Nested indexes, additional platforms/members, ambiguous descriptors,
unknown statement layers and attachments to another digest are refused before
scanning/copying. All referenced metadata and application-layer bytes are hash
checked. SPDX and maximum SLSA v0.2 statements must both name the service exporter
and the application digest. The Trivy report's `Metadata.ImageID` must equal the
sole runnable manifest's config digest, recorded in `oci-inventory.json`;
`--all` therefore cannot add another unscanned runnable image. The exact
build/index digest still controls copy/signing. Real Trivy/Skopeo behavior with
selected immutable versions remains an integration gate.

Construction now uses immutable remote Git context
`https://github.com/ricardoakinaga-dev/rick-intelligence.git#<SOURCE_SHA>`.
A locally echoed VCS revision cannot admit an archive. BuildKit's configSource
and resolved Git material must identify that exact context/SHA, and completeness
must cover parameters and materials. Source/recipe admission additionally needs
an independently reviewed construction policy and its separately supplied
SHA-256. No policy is generated or approved by the builder.

For **each** service (`API`, `WORKER`, `WEB`), administrators must supply
`RICK_<SERVICE>_CONSTRUCTION_POLICY_JSON` and
`RICK_<SERVICE>_CONSTRUCTION_POLICY_SHA256`. The hash is over the exact UTF-8
JSON bytes, including any whitespace/newline. These expose
`CONSTRUCTION_POLICY_JSON` / `CONSTRUCTION_POLICY_SHA256` to the matrix job.
Missing values, altered policy bytes or workflow arguments differing from that
review fail before builder creation. Protect those variables under the existing
review authority. A policy supplied with a self-computed hash has no independent
review authority.

The executable `construction_contract.admit_review` contract accepts precisely
these keys in `rick.vps.construction-policy/v1`:

| Key | Required reviewed value |
| --- | --- |
| `schema`, `service`, `source_sha` | Exact schema above, service, full candidate source SHA |
| `context` | Exact object `uri`, `digest: {sha1: source_sha}`, `entryPoint`; URI is the remote Git context above, entry point is `infrastructure/docker/<service>.Dockerfile` |
| `dockerfile`, `dockerfile_sha256` | That repository path and SHA-256 of its reviewed file bytes |
| `dockerfile_source_name` | Actual reviewed BuildKit source-info filename, either that full path or its basename |
| `parameters` | Exact full `invocation.parameters` object: `frontend`, `args`, `locals`, `secrets`, `ssh`; frontend is dockerfile.v0/gateway.v0 and the final three lists must be empty |
| `materials` | Complete unordered set of exact `uri`/`digest` objects, no duplicate URI; each digest has one supported sha1/sha256 value, including the Git context material |
| `base_materials` | Map each used base plus frontend to an exact `image_ref` and `material` present in `materials`: PYTHON_IMAGE + BUILDKIT_SYNTAX for API/worker; NODE_BUILD_IMAGE + NODE_RUNTIME_IMAGE + BUILDKIT_SYNTAX for web |
| `build_config_sha256` | Canonical JSON hash of the **entire** expected `predicate.buildConfig`, including LLB operations/inputs |
| `source_mapping_sha256` | Canonical JSON hash of the **entire** expected `predicate.metadata["https://mobyproject.org/buildkit@v1#metadata"].source` |

`parameters.args` must include exactly the workflow's five `build-arg:` keys:
PYTHON_IMAGE, NODE_BUILD_IMAGE, NODE_RUNTIME_IMAGE, BUILDKIT_SYNTAX and
RICK_API_INTERNAL_URL. The first four are immutable refs; the final value is
`http://api:8000`. The two `label:org.opencontainers.image.source/revision` keys
must match this repository/source. Every other frontend option emitted by the
actual invocation is also reviewed and compared exactly; there is no wildcard
for filename, target, platform, context or source options. Resolve the exact
frontend parameter spelling against the Parent's diagnostic before review.

Canonical recipe hashes use UTF-8 JSON with sorted keys, comma/colon separators,
`ensure_ascii=False`, `allow_nan=False`; invoke
`construction_contract.canonical_sha256(value)`. Material array order is ignored;
recipe/source arrays retain their exact order. Source locations must point to
LLB step IDs. One source-info entry must name the reviewed Dockerfile; its strict
base64 `data` bytes must match the reviewed Dockerfile hash and the protected
checkout's file bytes. The provenance must match all these reviewed values,
including exact resolved base materials, before `construction-binding.json`
is recorded. Base inputs in the candidate predicate are drawn from validated
provenance arguments, rather than environment echoes. `configured_build_tools`
is explicitly configuration, not authenticated evidence of tool execution.

For a multi-platform base reference, its pinned index digest may differ from the
resolved linux/amd64 material digest. `base_materials` is the reviewer's explicit
reference-to-material mapping; verify that relation against actual immutable
construction evidence. This validator does not fetch a registry or fabricate
that proof. Policy equality and builder-id/source labels alone do not
authenticate BuildKit: the real remote construction, protected quality workflow,
registry digest preservation and keyless verification remain external gates.

To check a diagnostic archive offline from a protected installer checkout:

```sh
python3 -B infrastructure/vps/construction_contract.py \
  --policy "$REVIEWED_CONSTRUCTION_POLICY_FILE" \
  --trusted-policy-sha256 "$REVIEWED_CONSTRUCTION_POLICY_SHA256" \
  --service "$SERVICE" --source "$REVIEWED_SOURCE_SHA" \
  --archive "$DIAGNOSTIC_OCI_ARCHIVE" --built-digest "$CAPTURED_BUILD_DIGEST" \
  --builder "$ACTUAL_BUILDER_ID" --output "$PRIVATE_DIAGNOSTIC_OUTPUT"
```

The policy input must be an absolute private regular file with trusted owner and
one link; the checkout's Dockerfile must pass protected source capture. No
Docker/socket/network call occurs. Output comprises validated SPDX/provenance,
closed inventory and construction binding; it grants no review approval.
Use `--policy` without archive options to check reviewed policy/source inputs.

Parent integration questions: does the diagnostic use the exact remote Git
context with complete materials, and what are the actual configSource,
parameters, resolved base/frontend material mappings, buildConfig and embedded
source-info/locations? Retain the original mode=max,v0.2 + SPDX archive, named
exporter/build digest, invocation and tool versions. Review those inputs against
source and immutable base evidence, then supply policy/hashes separately.
If the existing diagnostic uses local context it can establish format only;
produce a remote-context diagnostic before authenticated construction admission.
Unsupported shapes refuse and require an explicit reviewed contract update.
See [Docker SLSA definitions](https://docs.docker.com/build/metadata/attestations/slsa-definitions/)
for parameters/materials/source mapping and the unverified VCS hint, and
[Docker attestation storage](https://docs.docker.com/build/metadata/attestations/attestation-storage/)
for the attached manifest layout. Actual construction has not been exercised
by this remediation.

Certificate identity/issuer, digest subject and transparency-log verification
are mandatory; no insecure verification flags are provided. A registry copy
followed by signing/verification failure may leave an **unsigned candidate**;
that is not an admitted release. Do not deploy tags. Both registry attestation
and signature must verify. See [Sigstore attestation verification](https://docs.sigstore.dev/cosign/verifying/attestation/)
and [Skopeo digest preservation](https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo-copy.1.md).

Download the three `ghcr-candidate-<SHA>-<service>` artifacts from the **same**
successful publication run into `evidence/api`, `evidence/worker`, `evidence/web`.
Each contains actual reports, extracted OCI SBOM/provenance, verification output,
bundles and a candidate fragment. Authentication files are temporary and excluded.
Assemble the existing REC-33 construction manifest without approving it:

```sh
python3 infrastructure/vps/assemble_candidate.py /absolute/evidence \
  --output /absolute/evidence/release-candidate.json
```

It remains `CANDIDATE`, with canary/rollback `NOT_RUN`. The existing REC-33 checker
intentionally refuses that incomplete rollout packet. The Lead/release authority
must complete existing release-integrity, sealed promotion, canary, rollback,
backup/restore and independent review requirements. Only that authority can
supply a `READY_FOR_REVIEW` manifest, its independently reviewed SHA-256, and a
reviewed configuration SHA-256. Computing hashes of an unreviewed candidate is
not approval. Construction CI cannot write those decisions.

## Runtime and environment contract

Keep the reviewed matching repository checkout on the VPS. Python 3, Docker
Engine, Docker Compose v2 with `--wait`, OpenSSL, a reviewed PyYAML 6.0.2
installation, and verified Cosign 2.5.3 are prerequisites.
Authentication to private GHCR packages uses a read-only package credential in
Docker's private credential store; do not put it in Compose or command arguments.
Run operations from a private administrative account with explicitly selected
operation/TLS reader identities (see below). The installer uses only
local Docker; no SSH, host-level service cleanup or remote billing is implemented.

Copy `infrastructure/vps/config.env.example` **outside Git**, to an absolute
path such as `/etc/rick-vps/config.env`, set `chmod 600`, and fill every blank.
The file is literal `KEY=value`, without shell syntax, quotes, whitespace or
interpolation. Use URL-safe generated credentials and percent-encoded URL
credentials. Unknown/duplicate/missing fields fail before Docker effects.
`RICK_REDIS_URL` must use `rediss://default`, exact internal endpoint `redis`
with no port or port 6379, and database `/0`, without query/fragment. Strict
percent decoding of its password must equal `REDIS_PASSWORD`; malformed escapes,
invalid UTF-8, a different user/host/port/database or credential mismatch are
refused before effects. The Redis server and application consume the same
reviewed secret.
Config, manifest, migration plan, rollback inputs and mounted assets are captured
as bounded regular files. Every absolute path component is opened with a
no-follow directory descriptor; symlink parents (including `/proc/self/root`),
lexical traversal, observed parent replacement and mutation during reading are
refused. A sticky `/tmp` containing a private child is supported.
Config/plans/policies/reports/private keys and retained SQL must have a sole trusted owner
(the installer UID or root), no special mode bits and no group/world access.
The public assets-report, admission-policy and fresh-inventory capture paths require private
inputs too: mode 0600 passes this gate; mode 0644 is refused before operation
effects, even when the content hash matches.
Manifests, public TLS files and source assets must not be
group/world writable; a development checkout with mode 0664 is refused.
Both retained-SQL capture sites (finish and bundle stage) enforce private=True;
0644, extra links and an owner other than the installer UID/root are refused.
The same captured bytes are hash checked and parsed. The REC-33 validator and
Compose receive protected snapshots, never the original operator paths. Changing
those original files after capture cannot alter deployment effects.
No command prints the resolved config, DSNs, passwords, provider keys or
container error output. Docker administrators can inspect runtime environments;
protect access to that account, files and the daemon.

The publisher retains a bounded private disk capture of `image.tar`, quality,
Buildx evidence and the reviewed Dockerfile before OCI admission. Admission writes
SBOM, provenance, construction binding and OCI inventory directly into this
capture; construction/tool policy bytes are retained too. Files have independent
inodes, not links to operator inputs. Open no-follow directory and leaf descriptors,
stat identity and streaming SHA-256 bindings stay alive through publication.
Both the captured copies and original inputs/exports are checked before each
tool invocation and after its return (including failure), before authentication,
and before producing a candidate. Observed changes, including replacement or
extra links, stop subsequent effects. Predicate archive/report hashes come from
the retained bytes; signing reads the retained predicate.

Trivy and Skopeo receive `/input:ro` and a separate `/output:rw`, with the
publisher's numeric UID:GID, all capabilities dropped and no new privileges.
Trivy's cache lives under `/output/trivy-cache`. No writable operator archive
directory is mounted. The read-only mount denies container writes even by
container root; this is a mount contract, not a claim that chmod makes files
immutable to their host owner. Generated exports use exclusive no-follow creation
with mode 0600. Start with a fresh publication directory containing the captured
build archive, quality and Buildx inputs; existing generated output names refuse
instead of being overwritten. Capture uses 64 KiB chunks, at most 8 GiB for the
stored archive and 16 MiB per metadata file, with one additional archive on disk.
Repeated identity checks incur disk reads; free disk and I/O budgets matter.

The host publisher UID, host signing executable and Docker daemon are trusted
authorities. Other processes with that host UID, root or daemon access are not
isolated by this implementation. If host operator processes must be outside that
authority, the required integration is a separately reviewed root-owned capture
and signing service: retain no-follow source descriptors, copy into a root-owned
0700 workspace, expose root-owned 0440 inputs in a 0750 reader-group directory
only through read-only mounts to a distinct tool UID, and accept bounded tool
outputs through a separate writable directory. Only that service may verify the
retained bindings, authorize authentication/copy, and invoke the signer with its
captured predicate. CI must invoke that reviewed service rather than an arbitrary
same-UID script. That broker/CI integration requires Parent authority; it is not
implemented or evidenced by these local controls. Native Docker mount denial,
hosted scanner/copy/signing and separated-UID protection remain to be exercised.
A return-time refusal can leave an unsigned remote object after copy, or a
signature after signer execution; it prevents later effects and candidate output,
without promising rollback of an already completed remote effect.

Changes to `assets.py` invalidate prior whole-file DAC evidence. Rerun the actual
DAC and full TLS/host identity matrix against the new bytes; previous proofs do
not transfer. Retained SQL, TLS and executable-copy ownership/privacy gates retain
their existing authority requirements.

Application OCI admission compares `config.User` with the explicit final-stage
`USER 10001:10001` in the hash-bound reviewed Dockerfile. Source labels alone
do not establish runtime identity. Inherited/named users, a different UID or
GID, and unsupported Dockerfile identity syntax are refused. The `rootfs` must
declare `type: layers` and one ordered SHA-256 diff-ID per manifest layer.
Each diff-ID is verified against the uncompressed tar stream, separately from
the descriptor digest of the stored (possibly compressed) blob.
Uncompressed tar and a single complete gzip stream are supported; zstd,
concatenated/trailing gzip data, sparse/global-PAX formats and PAX size
overrides are explicitly refused. Ordinary PAX path metadata and GNU long
names are bounded; no layer path or link is extracted onto the host.
Expanded content is limited to 2 GiB per layer and 8 GiB per image, with
100,000 headers per layer, 200,000 per image, 1 MiB per extension and 64 KiB
stream chunks. Existing stored-archive, metadata, member and closure limits
still apply. These are structural and material checks, not live execution or
authenticated GitHub source proof; local-context provenance remains refused.

| Required named inputs | Contract |
| --- | --- |
| `VPS_PROJECT`, `VPS_DOMAIN`, `VPS_ACME_EMAIL` | Unique local project, real public DNS pointing to this VPS, ACME account email |
| `POSTGRES_IMAGE`, `REDIS_IMAGE`, `QDRANT_IMAGE`, `MINIO_IMAGE`, `MC_IMAGE`, `CADDY_IMAGE` | Verified immutable refs at the exact official repositories in `deploy.INFRA`; no tags |
| `POSTGRES_VOLUME`, `REDIS_VOLUME`, `QDRANT_VOLUME`, `OBJECT_VOLUME`, `CADDY_VOLUME` | Five distinct **existing external** volumes prefixed with `<VPS_PROJECT>-`; review their inventory before reuse |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | PostgreSQL database and bootstrap administrator; cannot be the application/migration/readonly role |
| `RICK_EXTERNAL_DATABASE_DSN` | Separate pre-provisioned application role, `postgresql://...@postgres/...` |
| `RICK_PREFLIGHT_DATABASE_DSN` | Distinct least-privilege read-only role; only metadata/history/scope SELECT access |
| `RICK_MIGRATION_DATABASE_DSN` | Distinct migration owner role with reviewed DDL privileges; only passed to migration job |
| `REDIS_PASSWORD`, `RICK_REDIS_URL` | Protected Redis credential and internal authenticated `rediss://default:<encoded-password>@redis:6379/0` |
| `RICK_REDIS_REQUIRE_TLS`, `RICK_REDIS_REQUIRE_AUTH`, `RICK_REDIS_VERIFY_TLS`, `RICK_REDIS_TLS_CA_FILE` | Closed `true` settings and mounted `/tls/ca-bundle.crt`; native default Redis ACL username must be explicit |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Store administrator, passed only to MinIO server |
| `RICK_OBJECT_STORE_ACCESS_KEY_ID`, `RICK_OBJECT_STORE_SECRET_ACCESS_KEY` | Pre-provisioned application user restricted to the named bucket; cannot use root credentials |
| `TLS_STORE_CERT`, `TLS_STORE_KEY`, `TLS_STORE_CA` | Absolute existing certificate/key/CA-bundle files; cert SANs `objects.internal`, `vectors.internal`, `redis`; key protected and readable by the Caddy and Redis image users |
| `RICK_QDRANT_API_KEY`, `RICK_QDRANT_COLLECTION` | Private API key and existing/reviewed dense collection identity |
| `RICK_OBJECT_STORE_BUCKET`, `RICK_OBJECT_STORE_REGION` | Private S3 bucket and matching MinIO region |
| `RICK_COMPOSITION_CREATED_BY`, `RICK_WORKER_ID`, `RICK_WORKER_SCOPE_TENANT`, `RICK_WORKER_SCOPE_WORKSPACE`, `RICK_WORKER_SCOPE_COLLECTION` | Real provisioned actor and exact tenant/workspace/collection scope |
| `RICK_IDENTITY_POLICY` | User-selected `postgres-local-v1` for internal RICK accounts stored in PostgreSQL; live authentication, revocation and scope isolation remain required |
| `RICK_OIDC_ISSUER`, `RICK_OIDC_AUDIENCE`, `RICK_OIDC_JWKS_URL` | Empty for this built-in composition. Setting them is refused. Real OIDC requires an implemented and reviewed IdP composition and browser/session/revocation validation; these URLs alone do not enable it |
| `CORS_ALLOWED_ORIGINS` | Exactly `https://<VPS_DOMAIN>` |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Native `openai` or `anthropic` chat, HTTPS native endpoint and explicit account-authorized model/key |
| `RICK_EMBEDDING_PROVIDER`, `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` | Independent native OpenAI embeddings; explicit model/dimension matching the vector collection |
| `ANTHROPIC_VERSION`, `ANTHROPIC_MAX_TOKENS` | Native Anthropic API contract/token bound when selecting Anthropic chat |

All closed production, identity, canonical composition, cookie and clinical
settings in the template are mandatory, validated and reinforced in Compose.
Provider/IdP secrets are injected at runtime. Root-store credentials and
preflight/migration DSNs are excluded from API/worker environments; separate
one-shot jobs receive only their own fields. The provider model is explicitly
selected by the account owner; this document does not claim any external model
or provider gate has passed.

The CA bundle must contain **both** the internal store CA and system public
roots, so TLS verification continues to work for external provider and IdP DNS.
Mount it read-only; do not disable certificate verification. TLS edge uses Caddy
ACME on ports 80/443 with persistent certificates. Public stores and console
ports are never published. Route `/api/*` and `/health/*` to API, the remaining
paths to web. Configure the VPS firewall for SSH and 80/443 only. The frontend
and store networks are internal; API and worker both also join `outbound`,
allowing provider/IdP DNS and HTTPS. No services of other projects are controlled.

PostgreSQL/Redis use their included `pg_isready`/`redis-cli`; Redis enables AOF
and requires authentication and native TLS; plaintext Redis port is disabled. The declared Qdrant CPU Debian image uses bash
TCP HTTP readiness instead of assuming wget. The selected MinIO release must
include curl; its [official release Dockerfile](https://raw.githubusercontent.com/minio/minio/RELEASE.2025-02-28T09-55-16Z/Dockerfile.release)
includes it. The [Qdrant CPU Dockerfile](https://raw.githubusercontent.com/qdrant/qdrant/v1.12.5/Dockerfile)
uses Debian. The installer checks executable availability in the supplied
immutable images before starting stores. Application images retain their
Python/Node checks, with API readiness explicitly using Python. Restart, health,
stop and log bounds are specified; Compose does not restart an unhealthy running
process automatically, so monitor health and perform reviewed recovery.

## Reviewed assets and Linux ownership

The user selected `postgres-local-v1` for internal PostgreSQL accounts. No OIDC
integration is a prerequisite for that choice. Live authentication, revocation,
grants and scope isolation still require evidence; the choice does not approve
publication or deployment.

Review and install the host installer itself before invoking it. A root Python
installer executes host code before it can check a manifest: image signatures
cannot authenticate that code. Use an audited, protected installation tree,
with protected source files and directories controlled by the installer/release
administrator. Do not run root against a mutable developer checkout. Do not
modify the shared checkout to make a package pass validation; prepare a separate
protected copy through the release authority's normal installation procedure.

Every command requires two numeric identities, externally bound into the asset
proposal and its reviewed bundle identity:

- `--operations-user UID:GID`: nonzero UID and GID for **all** one-shot database
  and bootstrap jobs. API/worker/web retain their image non-root runtime. Root
  stages new snapshots under its own UID with the selected reader GID and 0440
  access. Example: installer `0:0`, jobs `20002:20002`.
- `--tls-user UID:GID`: explicit Redis/stores-TLS/edge reader. Root owns the
  captured private key and Caddyfiles and grants group read access to this GID.
  Root may select `0:0` or another provisioned reader, for example `20003:20003`.
  This store reader selection grants no permission to run mounted operation
  code as root. A root TLS reader is part of the trusted installer boundary.

The installer needs local Docker access; that access is privileged regardless
of its Unix UID. Selecting another UID/GID requires installer root privileges
for scoped `chown` and a forked DAC probe that drops supplementary groups, GID
and UID. It never creates host accounts or changes original files/volumes.
Pre-provision existing Redis/Caddy data for the selected reader and verify its
port/runtime capabilities in an isolated topology. Arbitrary UID changes do not
repair existing volume ownership. Freeze other operators during an operation.

Plans, policies, reports, retained SQL and operation scripts are mounted from
new root-owned **0440** files with reader-group access; retained SQL directories
are root-owned **0750** with the selected group. The
bundle's shared parent directories are search-only **0711** so selected readers
can traverse them without exposing file contents or directory listings to other
users. Only public certificate/CA bytes use **0444**, needed by application USER
10001. The key remains root-owned **0440** with access to its selected reader group. All asset mounts are
read-only; jobs also drop capabilities, disable privilege gain and have a
read-only root filesystem with a bounded-purpose temporary directory.

Ownership assignment and actual Linux read probes happen before Compose or
writer shutdown. For live operations, additional network-isolated image probes
read the exact bind destinations using the same numeric job user and selected
TLS readers before stopping writers or starting stores. A failed permission
probe refuses the operation. Successful local tests do not establish that these
selected-image probes ran on a target.

Create an **unapproved proposal** from the protected tree and actual local TLS
files, without Docker or network effects:

```sh
python3 infrastructure/vps/assets.py inventory \
  --config /etc/rick-vps/config.env --source-sha "$REVIEWED_SOURCE_SHA" \
  --operations-user "$REVIEWED_OPERATIONS_USER" --tls-user "$REVIEWED_TLS_USER" \
  --bundle-root /var/lib/rick-vps/bundles \
  --output /etc/rick-vps/assets-proposal.json
```

`rick.vps.assets/v1` retains `status: REVIEW_REQUIRED`. It includes the exact
config byte hash, source revision, both numeric users, retained bundle directory, all mounted repository
files and installer sources, original Compose/template, both Caddyfiles,
`db_guard.py`, `contracts.py`, `object-bootstrap.sh`, scope SQL, and separate
TLS cert/key/CA byte hashes. `bundle_id` is the SHA-256 of all other fields as
UTF-8 JSON with sorted keys and compact separators. No hash of a path string
substitutes for a hash of mounted content. Unknown mounts, extra inventory
entries, writable asset mounts and Compose includes/build/extends are refused.

The independent release reviewer must inspect those exact source bytes, Compose
mounts, image/asset relationship, identities, installed permissions and TLS
certificate identity. PEM certificates and every CA certificate are parsed;
OpenSSL verifies key/leaf public-key equality, server purpose, validity/trust
chain and exact SANs `objects.internal`, `vectors.internal`, `redis`. A public
0644 file cannot be admitted as a key even if its hash is supplied. Keys are never
printed or included in the review JSON. Inspect their public identity and byte
hash through the protected delivery mechanism.

Only the reviewer supplies `REVIEWED_ASSETS_SHA256` (hash of the proposal's exact
JSON bytes) and `REVIEWED_BUNDLE_ID` through the existing trusted release channel,
plus the selected users and retained bundle directory. Rename/copy the reviewed proposal to
`/etc/rick-vps/assets.json` without changing its bytes. Computing these values
locally is not approval, and the inventory command supplies no review decision.
An independently supplied asset hash/identity is required on **every** operation,
including `validate` and rollback. For rollback, review the mounted bundle against
the previous target manifest as well as the separately approved retained SQL.

The captured original Compose is placed under `infrastructure/vps` in a new
protected temporary tree, preserving its relative Caddy/script imports; scope
SQL is captured under `docs/operations`. All TLS path variables are rewritten
to captured copies. Pre-provision `--bundle-root /var/lib/rick-vps/bundles` outside the checkout,
owned by the installer/root, with no group/world write. Use root-owned 0711 search-only parents. Staging requires a root installer and
a distinct non-root operation UID. Jobs receive group read access (0440),
while root retains ownership of files and directories; retained SQL directories
use 0750 with the selected reader group. Readers cannot chmod or replace inputs.
An explicitly selected root TLS reader remains supported and is trusted as part
of the installer boundary. Symlink components, foreign owners, group/world-writable non-sticky ancestors
and observed parent replacement are refused. Directory and leaf descriptors
remain open through staging and effects; every command rechecks the component
bindings, ownership, links, permissions and leaf metadata. Writes use bound
directory descriptors. The trusted root-owned sticky `/tmp` exception supports
private disposable validation snapshots. This output directory is
bound in the reviewed asset proposal. Every live verb retains a uniquely named
protected bundle there, including on failure, so store/Caddy/TLS mount source
paths remain available across container restarts. `assets.json` in each bundle
records its reviewed identity. Only `validate` uses automatically removed
temporary assets; temporary Docker env files are never persistent mounts.
A change to an original after capture cannot enter a later mount or execution.
Operators must independently inspect actual container mount sources before
authorizing removal of a retired bundle. This tool never removes retained
bundles, old inputs or any other project's files.

## Independent installer and candidate admission

Run the operation entry point from an independently authenticated, protected
installer distribution. The launch bootstrap comprises `deploy.py`, `assets.py`,
`contracts.py` and `trusted_code.py`; its exact bytes, Python standard library
and PyYAML installation are host trust roots that must be authenticated **before
launch**, outside the process being authorized. A writable repository checkout
is not that distribution. Install under protected root-owned ancestors and
independently verify the reviewed source hashes. The input capture policy requires
trusted owners and a sole hard link for every public and private input, along
with protected ancestors; private originals additionally require no group/world
permissions. No runtime process may approve its own bootstrap.

The reviewed asset inventory now includes `check_release.py`,
`json_boundary.py`, the exact `rollout-policy.json`, all three Dockerfiles, and
the VPS admission/import closure. These shared sources are copied and hash
checked, never modified. The checker executes captured module bytes with its
JSON dependency supplied from the captured closure. Its JSON reads are limited
to the captured manifest and policy, and its Dockerfile checks use protected
snapshots. No admission check imports those modules or reopens policy from the
live repository. An unknown policy filename is refused.

All live verbs require `--admission-policy` and
`--trusted-admission-policy-sha256` from the independent release authority.
The `rick.vps.admission-policy/v1` JSON has exactly `schema`, `source_sha`,
`construction`, `tool_policy`, `quality`. `construction` maps api/worker/web to
`{"json": "<exact previously reviewed policy JSON bytes>", "sha256": "<reviewed hash>"}`;
`tool_policy` has that same entry shape. The construction contracts retain native
BuildKit wrapped locations, empty sink operations and optional root/compatibility
parameters. The reviewed recipe/source hashes remain mandatory.

The independently reviewed `rick.vps.tool-policy/v1` JSON has exactly:

- `schema` and `images`: the eight named immutable inputs from `publish_guard.INPUTS`.
- `buildx`: exactly reviewed `version` and binary `sha256`.
- `cosign_version`: `v2.5.3`, corresponding to the pinned installation action.
- `scan`: api and worker require `{"os_family":"debian","language_types":["python-pkg"]}`;
  web requires `{"os_family":"alpine","language_types":["node-pkg"]}`.

Administrators independently set `RICK_TOOL_POLICY_JSON` and
`RICK_TOOL_POLICY_SHA256` in GitHub as well as the existing construction policies
and immutable tool variables. The publisher refuses input drift before building
or scanning. Deploy admission compares the signed tool policy hash, actual Buildx
version/URL/checksum, base images and configured tools with those independent
inputs. Computing a hash of candidate output does not create a trusted policy.

`quality` is the exact independently inspected hosted attempt record:
`run_url`, positive numeric `run_id` and `run_attempt`, `head_sha`, `conclusion`,
`required_jobs`, `path`, `event`, `head_branch`, `head_repository`, `status` and
`job_conclusions`. The path is canonical quality.yml, branch main, repository
canonical, status completed and event push/workflow_dispatch. All eight required
construction jobs must have success conclusions. A later promotion failure
remains allowed for construction only. The signed predicate must equal this
record and its canonical JSON hash, and must carry the exact reviewed
construction, tool and scanner identities. Subject admission requires exactly
one intended GHCR repository name and digest. A signed unrelated subject or
missing policy/quality evidence is refused.

OCI input is an uncompressed, sole-link regular tar, at most 8 GiB, 4096 members
and 2 GiB per member; metadata is bounded to 16 MiB. Layout must be exactly
`imageLayoutVersion: 1.0.0`. Every member is inventoried; blob names and hashes,
referenced sizes, allowed directories and reachability must match. Unreferenced
blobs/manifests, unknown files/directories, links, extension/sparse headers,
duplicates, truncation and nonzero trailers are refused. These limits need real
BuildKit/Skopeo compatibility validation with the selected versions.

Trivy runs with `--list-all-pkgs`, no severity filter and `--exit-code 0`;
execution/database errors still fail the command, and report admission enforces
HIGH/CRITICAL/UNKNOWN refusal while allowing LOW/MEDIUM. A supported version-2 container-image report
must identify the sole config, detect the reviewed OS and include nonempty OS
and required application package inventories. Empty/missing Results, unsupported
analyses, missing package coverage, unknown vulnerabilities, HIGH/CRITICAL
findings and malformed reports refuse publication. Explicit EOSL/EOL,
unsupported OS flags and malformed lifecycle flags refuse coverage. Omitted
false flags remain compatible with native reports; omission is not independent
proof of OS lifecycle support or database health, which still require native
validation with the reviewed scanner and runtime. The signed predicate binds
these scan requirements and report hash. PostgreSQL runtime, readonly and
migration DSNs must target `postgres` on omitted/default port or explicit 5432;
other ports, an empty port and alternate endpoints are refused in both host
parsing and direct database jobs.

SPDX admission requires unique package/file IDs, versioned packages connected
through a closed document graph and file content checksums. A described FILE
aggregate may omit a version; a placeholder package may not. Every runtime
package admitted from Trivy must match a versioned SPDX package-manager purl:
Debian `deb/debian`, Alpine `apk/alpine`, Python `pypi`, or JavaScript `npm`.
Python names alone normalize case and runs of `-_.`; OS and npm names and all
versions match exactly, including OS epochs/revisions and npm scopes. A scanner
purl, when emitted, must agree with its package name/version/ecosystem.
Purl qualifiers do not replace these identities; extension subpaths and generic
embedded packages cannot stand in for installed distributions. Comparable
distribution inventories must reconcile in both directions; SPDX may include
additional supplementary packages/files. Cross-vendor alias/version variance is unproved and
is refused where these rules cannot establish coverage. Reconciliation runs
before registry authentication/copy and preserves the original subject, OCI
closure and independently reviewed policy gates. The supplied native local
diagnostic validates format only and never authenticates release authority.
In that diagnostic, Pillow subpaths refer to parent distribution versions and
remain supplementary, while the primary `pkg:pypi/pybind11` has no purl version
and reports `versionInfo: UNKNOWN`. Its structural SPDX document remains valid,
but runtime reconciliation conservatively refuses this unresolved identity;
an authenticated native scan/SBOM pair must resolve it before release admission.

For a fresh unavailable database, independently authorize
`rick.vps.fresh-inventory/v1` with exactly `schema`, `authorization:
CREATE_REVIEWED_EMPTY_DATABASE`, `source_sha`, `config_sha256`, `deployment`,
`database_state: ABSENT`, `absence_evidence`, `observed`. Deployment includes
project, DB name and the five named volumes. `absence_evidence` has a real
reviewed reference and SHA256 for offline proof that the prepared volumes have
no database/application data. `observed` has the **complete actual** output of
`docker volume inspect` for those five prepared external volumes, and
`containers: []` for the project. This tool cannot prove volume data absence from
Docker metadata; the independent offline absence review is essential.
Supply `--fresh-inventory /protected/location/fresh-inventory.json` and
`--trusted-fresh-inventory-sha256 "$REVIEWED_FRESH_SHA256"` only to preflight or
migrate. Current read-only volume/container observations must match exactly
before store startup. Generic connection failure is never accepted as absence.
The migration plan must independently authorize EMPTY state, and the newly
reachable DB must match it before SQL. Freeze external writers/operators during
all reviewed observation/quiescence windows; root remains the trusted actor.

## Inventory, authorized migration and install

External volumes are never silently created or deleted by this installer. For a
reviewed new installation, provision only the five named volumes explicitly.
For existing data, preserve the current names and contents. Never infer an absent/empty DB from a failed connection or from starting
PostgreSQL. A reachable database requires current READ ONLY inventory. An
unavailable fresh database requires the explicit reviewed absence inventory
described below, before any store startup. PostgreSQL/MinIO administrators must
pre-provision the database roles and scoped object credential separately; the
installer does not silently create users, change grants, repair history or
make buckets public. PostgreSQL readonly role should set
`default_transaction_read_only=on`; grant SELECT for history and scope checks,
including future tables owned by the migration role. Runtime role needs DML;
migration role owns reviewed schema changes. After migrations, apply reviewed
default/table grants and provision identity/scope before starting the graph.
Do not run PostgreSQL initialization scripts against existing data.

Use independently supplied hashes in every command. `validate` renders Compose
quietly and performs no image pulls/container changes:

```sh
python3 infrastructure/vps/deploy.py validate \
  --assets /etc/rick-vps/assets.json --trusted-assets-sha256 "$REVIEWED_ASSETS_SHA256" \
  --reviewed-bundle-id "$REVIEWED_BUNDLE_ID" \
  --operations-user "$REVIEWED_OPERATIONS_USER" --tls-user "$REVIEWED_TLS_USER" \
  --bundle-root /var/lib/rick-vps/bundles \
  --admission-policy /etc/rick-vps/admission.json \
  --trusted-admission-policy-sha256 "$REVIEWED_ADMISSION_SHA256" \
  --config /etc/rick-vps/config.env --trusted-config-sha256 "$REVIEWED_CONFIG_SHA256" \
  --manifest /etc/rick-vps/release.json --trusted-manifest-sha256 "$REVIEWED_RELEASE_SHA256"
```

`preflight` verifies real registry signatures/source attestations and image
capabilities, then queries the currently reachable database using the READ ONLY
job with `--no-deps`. It returns that observation without starting stores.
Only a separately authorized fresh absence inventory permits store startup
before the first database observation. It prints aggregate inventory and SQL
version/checksums, not user rows or credentials. It neither bootstraps buckets
or vectors nor applies migrations. Even preflight requires reviewed immutable
images/configuration; this is a live operation authorized by the operator.

```sh
python3 infrastructure/vps/deploy.py preflight \
  --assets /etc/rick-vps/assets.json --trusted-assets-sha256 "$REVIEWED_ASSETS_SHA256" \
  --reviewed-bundle-id "$REVIEWED_BUNDLE_ID" \
  --operations-user "$REVIEWED_OPERATIONS_USER" --tls-user "$REVIEWED_TLS_USER" \
  --bundle-root /var/lib/rick-vps/bundles \
  --admission-policy /etc/rick-vps/admission.json \
  --trusted-admission-policy-sha256 "$REVIEWED_ADMISSION_SHA256" \
  --config /etc/rick-vps/config.env --trusted-config-sha256 "$REVIEWED_CONFIG_SHA256" \
  --manifest /etc/rick-vps/release.json --trusted-manifest-sha256 "$REVIEWED_RELEASE_SHA256" \
  > /protected/location/preflight.json
```

Unknown/gapped/changed migration history, existing relations without history,
and historical checksums needing recognized canonical auto-repair are refused.
An already-applied 0007 with pending 0008 runs the existing aggregate scope
preflight SQL; conflicts stop execution. Earlier populated schemas need a
separate staged upgrade and scope review rather than this installer guessing
compatibility. The current full migration runner is reused only after explicit
authorization; this tool never invokes its historical repair branch.

For pending SQL, the authority must review preflight output, exact candidate SQL,
maintenance window, verified backup/restore of **all persistent stores**, and
schema compatibility. The private migration plan must have **exactly** these six
keys; no generated authorization template is supplied:

| Key | Required authorization/input |
| --- | --- |
| `schema` | `rick.vps.migration-plan/v1` |
| `authorization` | `APPLY_REVIEWED_SQL`, independently granted by the authority |
| `observed` | Complete READ ONLY `rick.vps.preflight/v1` object: exactly schema, read_only=true, database_state (EMPTY/EXISTING), history, pending |
| `maintenance_window` | Explicit boolean; true for EXISTING, false for EMPTY |
| `verified_backup_id` | Real nonblank verified backup ID for EXISTING; explicit empty string for EMPTY |
| `backward_compatible` | Explicit boolean true from review |

History/pending are ordered arrays of exact `version`/`sha256` objects; versions
are four digits, checksums 64 lowercase hex, and combined versions form a
contiguous sequence starting at 0001 without overlap. Pending must be nonempty.
EMPTY requires empty history. EXISTING requires nonempty history through at least
0007; earlier populated schemas require separate staged review as before.
The complete shape and applicable authorization are validated in `finish`
**before execute_operation and before writer stop**; the direct operation
boundary validates again. Missing keys, schema/read_only/state, wrong scalar or
row types, blank backup, false compatibility and incomplete existing/fresh
choices are refused offline. A correctly hashed partial JSON cannot authorize
effects. These syntax/authorization checks do not verify backup restoration or
schema compatibility; the independent review must establish those facts.

No default plan authorizes migration. Pass its independently reviewed byte hash:

```sh
python3 infrastructure/vps/deploy.py migrate \
  --assets /etc/rick-vps/assets.json --trusted-assets-sha256 "$REVIEWED_ASSETS_SHA256" \
  --reviewed-bundle-id "$REVIEWED_BUNDLE_ID" \
  --operations-user "$REVIEWED_OPERATIONS_USER" --tls-user "$REVIEWED_TLS_USER" \
  --bundle-root /var/lib/rick-vps/bundles \
  --admission-policy /etc/rick-vps/admission.json \
  --trusted-admission-policy-sha256 "$REVIEWED_ADMISSION_SHA256" \
  --config /etc/rick-vps/config.env --trusted-config-sha256 "$REVIEWED_CONFIG_SHA256" \
  --manifest /etc/rick-vps/release.json --trusted-manifest-sha256 "$REVIEWED_RELEASE_SHA256" \
  --plan /etc/rick-vps/migration-plan.json --plan-sha256 "$REVIEWED_PLAN_SHA256"
```

After complete offline plan admission, migration first obtains a **current**
READ ONLY observation and compares the entire reviewed state **before** stopping
edge/web/API/worker or starting persistent stores. An unavailable or changed
inventory refuses those effects. After quiescence it observes and authorizes
the state again, immediately before the migration job. The job repeats READ ONLY
authorization before invoking the canonical transactional/checksummed/advisory-locked
runner. A fresh authorized absence route checks current volume metadata and
absent project containers before startup, then compares the resulting database
inventory to the explicitly reviewed EMPTY plan before applying SQL. Freeze
other writers and other migration operators during this maintenance window.
If a check fails, writers remain stopped and volumes remain intact; investigate
protected diagnostics and take an explicit recovery decision. It never repairs
scope rows/history automatically or resumes writers after partial failure.

`install`/`upgrade` require the complete existing REC-33 rollout packet to pass,
actual signature/attestation verification and **zero pending SQL**. Then they run
object bucket bootstrap and vector bootstrap independently, and start services
with bounded `--wait`. A populated vector collection with mismatched dimensions
fails; no collection is dropped/rebuilt. Bucket bootstrap checks private access;
no anonymous ACL is granted. This workflow uses staging/canary evidence under
the existing release authority before production admission.

```sh
python3 infrastructure/vps/deploy.py install \
  --assets /etc/rick-vps/assets.json --trusted-assets-sha256 "$REVIEWED_ASSETS_SHA256" \
  --reviewed-bundle-id "$REVIEWED_BUNDLE_ID" \
  --operations-user "$REVIEWED_OPERATIONS_USER" --tls-user "$REVIEWED_TLS_USER" \
  --bundle-root /var/lib/rick-vps/bundles \
  --admission-policy /etc/rick-vps/admission.json \
  --trusted-admission-policy-sha256 "$REVIEWED_ADMISSION_SHA256" \
  --config /etc/rick-vps/config.env --trusted-config-sha256 "$REVIEWED_CONFIG_SHA256" \
  --manifest /etc/rick-vps/release.json --trusted-manifest-sha256 "$REVIEWED_RELEASE_SHA256"
```

Change `install` to `upgrade` for an approved new release. For rollback, provide
the **previous independently reviewed manifest and its hash**, configured volumes
unchanged, and verified schema backward-compatibility evidence. Change the verb
to `rollback`; only images change. No reverse SQL, volume deletion, `down -v`,
Docker prune or global cleanup exists. An incompatible schema demands reviewed
roll-forward or restore rather than an image rollback.

A newer retained schema requires a **separate** reviewed rollback policy;
the previous manifest's compatibility flag alone does not authorize newer SQL.
First use the currently installed reviewed release (whose image knows all
retained migrations) to collect READ ONLY schema evidence:

```sh
python3 infrastructure/vps/deploy.py preflight --retained-schema-inventory \
  --assets /etc/rick-vps/assets.json --trusted-assets-sha256 "$REVIEWED_ASSETS_SHA256" \
  --reviewed-bundle-id "$REVIEWED_BUNDLE_ID" \
  --operations-user "$REVIEWED_OPERATIONS_USER" --tls-user "$REVIEWED_TLS_USER" \
  --bundle-root /var/lib/rick-vps/bundles \
  --admission-policy /etc/rick-vps/admission.json \
  --trusted-admission-policy-sha256 "$REVIEWED_ADMISSION_SHA256" \
  --config /etc/rick-vps/config.env --trusted-config-sha256 "$REVIEWED_CONFIG_SHA256" \
  --manifest /etc/rick-vps/current-release.json --trusted-manifest-sha256 "$REVIEWED_CURRENT_RELEASE_SHA256" \
  > /protected/location/retained-inventory.json
```

This collection uses strict canonical history validation, requires no pending
SQL and emits `rick.vps.rollback-preflight/v1`, full history/checksums, relation
count, retained source SHA and `schema_catalog_sha256`. The catalog hash covers
public columns/defaults, constraints, indexes, functions/procedures, triggers
and views using `db_guard.ROLLBACK_CATALOG` and `catalog_digest`; definitions are
hashed, user rows are not read. Collection grants no compatibility approval.
Obtain the full numbered SQL and required `.sql.inc` artifacts from that
verified retained release, preserving their known source provenance. Independently
review them against the older images and actual schema, including application
behavior and verified restore evidence. This implementation does not assert
that migration 0009 is compatible with any older application.

The private `rick.vps.rollback-policy/v1` JSON must contain:

- `authorization: RETAIN_SCHEMA_IMAGE_ROLLBACK` from the release authority.
- `target_source_sha`, `target_images` (the complete service-to-immutable-ref
  map from the previous manifest), and `retained_source_sha` from the verified
  retained release. Revisions are full 40-character SHAs.
- `deployment`: exact `VPS_PROJECT`, `POSTGRES_DB` and all five configured
  `*_VOLUME` values. Database and volume reuse must match the reviewed inventory.
- `retained_artifacts`: the complete filename-to-SHA256 map for the reviewed SQL
  and required `.sql.inc` artifacts from that source.
- `observed`: the complete fresh retained inventory object described above.
- `compatibility`: `status: PASS`, the real review's `evidence` reference,
  `evidence_sha256` of its private JSON report, and explicit
  `target_schema_version` / `retained_schema_version` (for example `0008` /
  `0009` only when the authority actually approves that pair).

The separate `rick.vps.schema-compatibility/v1` report must contain `decision:
RETAIN_SCHEMA_IMAGE_ROLLBACK`, a real `reviewer`, substantive `analysis`, and
the exact policy's `target_source_sha`, `retained_source_sha`, `target_images`,
`retained_artifacts`, `target_schema_version`, `retained_schema_version`.
Both report bytes and policy bytes are hash bound; a reference string alone
cannot satisfy the guard. Supply the policy's independently reviewed hash:

```sh
python3 infrastructure/vps/deploy.py rollback \
  --assets /etc/rick-vps/assets.json --trusted-assets-sha256 "$REVIEWED_ASSETS_SHA256" \
  --reviewed-bundle-id "$REVIEWED_BUNDLE_ID" \
  --operations-user "$REVIEWED_OPERATIONS_USER" --tls-user "$REVIEWED_TLS_USER" \
  --bundle-root /var/lib/rick-vps/bundles \
  --admission-policy /etc/rick-vps/admission.json \
  --trusted-admission-policy-sha256 "$REVIEWED_ADMISSION_SHA256" \
  --config /etc/rick-vps/config.env --trusted-config-sha256 "$REVIEWED_CONFIG_SHA256" \
  --manifest /etc/rick-vps/previous-release.json --trusted-manifest-sha256 "$REVIEWED_PREVIOUS_RELEASE_SHA256" \
  --rollback-policy /protected/location/rollback-policy.json \
  --rollback-policy-sha256 "$REVIEWED_ROLLBACK_POLICY_SHA256" \
  --rollback-evidence /protected/location/compatibility-report.json \
  --retained-migrations /protected/location/retained-migrations
```

The older image runs `db-rollback-preflight` against captured read-only SQL/report
snapshots. Its own SQL must exactly match the retained inventory's prefix; the
retained inventory must be contiguous and its complete checksums/application
must match live history. The schema catalog and entire observed inventory must
also match the reviewed policy. Unknown history, wrong checksums, missing report,
pending SQL or schema drift are refused. Canonical `install`/`upgrade`/`migrate`
remain strict; they do not gain the rollback exception. No reverse SQL,
historical repair or automatic restore/destructive fallback is authorized.

## Lead integration and evidence limits

The owned local tests exercise refusals, immutable source/registry binding,
scan-before-copy behavior, READ ONLY ordering, explicit maintenance migration,
secret-free errors/environments and internal/outbound topology. Earlier Compose
quiet-render evidence used synthetic non-secret fixtures. The
current protected bundle and numeric UID changes have only offline validation
and command-boundary tests here; a current Docker render/image DAC probe was
not run in this sandbox. These checks do not establish live image health,
ACME/DNS, reachable providers/IdP,
existing production DB inventory, scan success, GHCR publication or promotion.

Lead integration TODOs (no edits made to their files):

1. **Current source guard:** `apps/api/src/core/config.py` now refuses production
   Professor mode only when **both** `locker_base_url` and `redis_url` are blank.
   Canonical Redis injection satisfies that lease-source condition; the legacy
   Locker-only blocker is obsolete. The installer still runs actual API and
   Redis settings validation inside the selected API image with `--network none`
   before starting stores. Source acceptance is not proof that a hosted image
   contains the guard or that native startup/composition succeeds.
2. Include this focused suite in the existing locked quality/static checks:
   `python -m pytest -q -p no:cacheprovider infrastructure/vps/tests`.
3. Keep canonical factories included in both application Dockerfiles and include
   the canonical migration runner/Qdrant bootstrap in API; web build internal URL
   must remain `http://api:8000`. Confirm the native canonical provider contract
   (`LLM_*` and independent `EMBEDDING_*`) in the parallel provider builder.
4. Protect main, workflow/tool variables and quality configuration against
   construction-authority changes. Review supplied tool/base/store digests,
   execute a real same-SHA quality and GHCR run, retain all actual artifacts, and
   exercise Skopeo's OCI/attestation digest preservation with those versions.
5. Complete existing controller/release-integrity/seal/reviewer/canary/rollback
   decisions and independently supply reviewed manifest/config/plan/assets hashes
   and bundle identities/users; review exact installer and mounted source bytes.
   Do not mark external gates PASS based on these local files.
6. Before production, run an isolated live topology/health test against chosen
   digests (including private bucket, vector schema, outbound provider/IdP TLS,
   role grants, migrations and recovery), then evaluate the actual VPS inventory.
   No hostname/key was supplied and no remote deployment is authorized here.

The selected local-account policy still needs live authentication, revocation
and scope/grant tests. Optional future IdP integration requires its own reviewed
composition. Live health/ACME/outbound TLS, actual scans/signatures,
provider account/model access and costs, database role/bucket provisioning,
retained-schema compatibility, backup/restore and release approval remain
external evidence requirements. No production PASS is claimed; a fresh
independent review must assess this remediation and then the hosted/live packet.

The bounded rework2 suite uses actual Linux file modes, directory descriptors,
parent replacement, TLS parsing and snapshot reads. The separate multi-UID test
(`root-owned inputs` readable by `20002`, denied to `10001`, then
readable by selected `10001` while still root-owned)
requires a disposable Linux test namespace with CAP_SETUID/CAP_CHOWN and both
UIDs mapped. This sandbox has only UID 1000 mapped and lacks the mapping helper;
that test is explicitly NOT_RUN/skipped. The same-UID snapshot read/mode unit test uses an explicitly simulated
installer seam; it is not separated-principal DAC evidence. Production staging
refuses an unprivileged installer. The root DAC test also requires chmod, writes
and replacement to fail as the actual operation reader; it uses virtual byte
markers and generates no TLS key.
The multi-UID test and selected-image DAC probes remain required evidence for
the next review; no mocked readability result substitutes for them.

In a separately authorized disposable Linux test namespace with those real
capabilities and both UID/GID pairs mapped, the exact multi-UID test is:

```sh
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -B -m pytest -q -p no:cacheprovider \
  infrastructure/vps/tests/test_rework2.py::test_linux_root_owned_snapshots_readable_by_selected_uid_and_immutable_to_reader
```

Run it with effective UID 0 inside that disposable namespace. It changes only
fresh test snapshot ownership; it creates no host accounts and uses no Docker.
This command is documentation of missing evidence, not a statement of execution.

### Formato nativo de BuildKit validado localmente

O contrato compara o objeto completo de parâmetros com a política revisada.
O formato gateway pode conter `root` e `compatibilityVersion`, além de omitir
campos vazios `secrets`/`ssh`; nenhum nível pode conter fontes locais, secrets
ou encaminhamento SSH. O LLB pode terminar em um vértice com `Op: {}`. O mapa
de origem usa wrappers `locations`, e fontes sem localização podem ter um
wrapper vazio. Hashes de receita, mapa e Dockerfile continuam obrigatórios.

A fixture nativa veio de um build OCI real local com SBOM/provenance v0.2.
Os testes de formato usam autoridade remota simulada e não aprovam essa
construção local. A construção autenticada do SHA GitHub, a revisão da política
e a assinatura dos digests ainda são provas separadas exigidas para liberação.


The v4 bounded builder run uses socket/process denial, virtual TLS byte markers,
actual tar/file parsing and command callbacks. Cryptographic TLS tests are
explicitly deselected; no keys, Docker, registry, sockets or ambient database
connections are used. This sandbox reports `/` and `/tmp` as unmapped UID 65534;
the offline runner records a narrowly scoped ancestor identity adapter for those
two host directories. It does not relax production owner rules. The separated-UID
DAC test and fresh child-process CLI test require Parent execution with real
mapped-root ownership. Fresh critic review and hosted/native OCI, scan and
signature evidence remain separate requirements, not local release approval.
