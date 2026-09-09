# REC-33 static rollout runbook

This runbook defines the operator-owned evidence needed to promote the API,
worker, and web images. It was not executed in this workspace. Every command
below is an example for a controlled build host; the local validation command
only reads files.

## 1. Resolve immutable inputs

Use a registry mirror approved by the release owner and resolve exact
multi-architecture base references. Do not put credentials in this repository.
The four resolved values must end with a lowercase SHA-256 digest:

```text
PYTHON_IMAGE=python:3.12.3-slim-bookworm@sha256:<64-lowercase-hex>
NODE_BUILD_IMAGE=node:22.19.0-alpine@sha256:<64-lowercase-hex>
NODE_RUNTIME_IMAGE=node:22.19.0-alpine@sha256:<64-lowercase-hex>
```

Record these values in `release-manifest.json` under `base_images` with status
`CAPTURED`. The example values above are placeholders and must never be used
as credentials or treated as evidence.

## 2. Build with no secrets

Capture the source revision before building. Build from the repository root so
the Dockerfiles can copy only the reviewed application and package paths:

```bash
git rev-parse HEAD
docker buildx build \
  --file infrastructure/docker/api.Dockerfile \
  --build-arg PYTHON_IMAGE="$PYTHON_IMAGE" \
  --tag registry.example/rick-intelligence/api:<source-revision> \
  --provenance=true --sbom=true --load .

docker buildx build \
  --file infrastructure/docker/worker.Dockerfile \
  --build-arg PYTHON_IMAGE="$PYTHON_IMAGE" \
  --tag registry.example/rick-intelligence/worker:<source-revision> \
  --provenance=true --sbom=true --load .

docker buildx build \
  --file infrastructure/docker/web.Dockerfile \
  --build-arg NODE_BUILD_IMAGE="$NODE_BUILD_IMAGE" \
  --build-arg NODE_RUNTIME_IMAGE="$NODE_RUNTIME_IMAGE" \
  --tag registry.example/rick-intelligence/web:<source-revision> \
  --provenance=true --sbom=true --load .
```

These Dockerfiles do not copy `.env` files and do not use build-time
credentials. Provider keys, database DSNs, Redis passwords, OIDC secrets, and
object-store keys must be injected by the runtime secret manager. The worker
also needs a separately reviewed `RICK_WORKER_COMPOSITION=module:factory`.
The API needs `RICK_API_COMPOSITION=module:factory`; its factory receives the
validated `ApiSettings` and returns `ExternalCompositionInputs`. The worker and
API factories own all external client construction; their launchers refuse to
start without the required composition.

## 3. Capture digest and scan evidence

Record the immutable output digest for each image. A tag alone is not a
release identity:

```bash
docker image inspect --format '{{index .RepoDigests 0}}' <image-tag>
trivy image --format json --output <service>-trivy.json <image-ref>@<digest>
syft <image-ref>@<digest> -o cyclonedx-json=<service>-sbom.json
```

The scan gate is zero `CRITICAL` and zero `HIGH`, with the policy in
`rollout-policy.json`; unresolved findings are not silently ignored. Attach
the report and SBOM references to the image record and set `scan.status` to
`PASS` only after an operator reviews them.

## 4. Verify signature and provenance

Sign the exact immutable digest through the approved keyless identity or key
policy, then verify that same digest in the promotion environment:

```bash
cosign sign --yes <image-ref>@<digest>
cosign verify \
  --certificate-identity-regexp '<approved-identity-regexp>' \
  --certificate-oidc-issuer '<approved-issuer>' \
  <image-ref>@<digest>
```

Record the verification bundle/reference, certificate identity, issuer, and
the digest that was verified. Never record a private key, token, or certificate
secret in the manifest.

## 5. Canary

Deploy all three exact digests to an isolated staging/canary slice. Supply
runtime secrets through the secret manager and use disposable or approved
staging data. The canary window is at least 15 minutes and 100 requests, with
readiness continuously true, 5xx rate at most 1%, p95 latency at most 1500 ms,
and no dead-letter growth. Exercise API readiness, web login, a grounded chat
request, and one worker job only after the external dependencies and worker
composition are approved.

Record the window, sample size, alert snapshot, image digests, and operator in
the manifest. A canary status of `PASS` is runtime evidence and cannot be
inferred from this static directory.

## 6. Rollback

Retain the previous release digests before changing traffic. If a canary
trigger fires, stop promotion, route traffic to the previous immutable API,
worker, and web digests, and capture the recovery time. Do not delete volumes
or data during image rollback. If migrations are not backward-compatible,
follow the migration roll-forward/reconciliation plan instead of guessing at
a database rollback.

Record the previous release digest, trigger, decision, recovery time, and
migration compatibility result. Set `rollback.status` and
`migration_compatibility` to `PASS` only after a controlled rehearsal or live
incident record has been reviewed.

## 7. Static gate

After filling a candidate packet, run:

```bash
python3 infrastructure/docker/check_release.py --mode candidate \
  --manifest infrastructure/docker/release-manifest.json
```

This command checks shape, digest equality, required evidence fields, policy
thresholds, non-root Dockerfile contracts, and secret-boundary rules. It does
not build images, contact a registry, execute a scanner, verify a signature,
start a container, run a canary, or perform rollback. Those claims require
the external evidence referenced by the packet.
