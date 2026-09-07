# Reference image boundary

The reference compose topology consumes immutable API, worker, and web image
digests. This repository does not yet ship reviewed production Dockerfiles:
external-store adapters, dependency locking, image scanning/signing, and the
runtime-user contract remain open. Docker/Compose was unavailable here, so
image build, scan, signature verification, and runtime smoke evidence are
`NOT_RUN`.
