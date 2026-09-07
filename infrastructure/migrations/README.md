# `infrastructure/migrations`

`0001_control_plane.sql` is a reference Postgres migration for deployment
bookkeeping and job-control state. It is not wired to the root application or
a migration runner. Before promotion it needs a reviewed up/down or
roll-forward policy, checksum recording, backup, reconciliation,
lock/timeout behavior, and a restore drill. No migration was executed here.
