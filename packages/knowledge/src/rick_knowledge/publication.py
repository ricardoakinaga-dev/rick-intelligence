"""Durable, scoped publication authority, independent of a worker lease.

Pending receipts are written before the commit gate. Committed receipts must
be written by the adapter in the document transaction and remain immutable.
Reads never infer success from a pending receipt or an unavailable store.
"""
from rick_knowledge.fencing import ATTEMPT_METADATA_KEY, OwnershipLostError
from copy import deepcopy
from collections.abc import Mapping
import math
import json
import time
from rick_knowledge.json_boundary import encode_metadata


def require_publication_identities(*values):
    if not all(isinstance(v, str) and v.strip() and len(v) <= 256 for v in values):
        raise ValueError('publication identities must be nonblank bounded strings')


def validate_publication_snapshot(snapshot, *, attempt_id, document_attempt):
    """Validate receipt facts and the owner of a deduplicated document."""
    if not isinstance(snapshot, Mapping) or not {'attempt', 'created_at', 'started_at', 'finished_at', 'metadata', 'heartbeats'} <= snapshot.keys():
        raise ValueError('invalid publication snapshot')
    attempt = snapshot.get('attempt')
    if type(attempt) is not int or not 1 <= attempt <= 64:
        raise ValueError('invalid publication attempt count')
    for name in ('created_at', 'started_at', 'finished_at'):
        value = snapshot.get(name)
        if value is None and name != 'created_at':
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid publication timestamp')
    created, started, finished = (snapshot.get(k) for k in ('created_at', 'started_at', 'finished_at'))
    if (started is not None and started < created) or (finished is not None and finished < (started if started is not None else created)):
        raise ValueError('publication timestamps are out of order')
    metadata = snapshot.get('metadata')
    if not isinstance(metadata, Mapping) or metadata.get('publication_attempt') != attempt_id:
        raise OwnershipLostError('publication snapshot attempt changed')
    document_owner = metadata.get('published_document_attempt', attempt_id)
    # Published legacy documents can lack an ingestion owner. Their verified
    # deduplication receipt uses its own token; pending recovery still cannot
    # infer document ownership from that token.
    legacy_dedup = metadata.get('deduplicated') is True and document_owner is None and document_attempt == attempt_id
    if document_owner != document_attempt and not legacy_dedup:
        raise OwnershipLostError('publication snapshot document attempt changed')
    queue_attempt = metadata.get('queue_attempt', attempt)
    if type(queue_attempt) is not int or queue_attempt != attempt:
        raise ValueError('publication queue attempt changed')
    encode_metadata(snapshot)


def publication_snapshot(job, *, document_attempt=None):
    snapshot = {key: deepcopy(getattr(job, key)) for key in (
        'attempt', 'created_at', 'started_at', 'finished_at', 'metadata', 'heartbeats')}
    attempt_id = job.metadata['publication_attempt']
    if document_attempt is not None and snapshot['metadata'].get('deduplicated') is True:
        snapshot['metadata'].setdefault('published_document_attempt', document_attempt)
    validate_publication_snapshot(snapshot, attempt_id=attempt_id,
        document_attempt=document_attempt if document_attempt is not None else
        job.metadata.get('published_document_attempt', attempt_id))
    return snapshot


# Provider outputs are business recovery data, not public job metadata. Keep a
# separate bounded encoding so the metadata limit is not silently enlarged.
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024


def encode_checkpoint(record):
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > MAX_CHECKPOINT_BYTES:
        raise ValueError('ingestion checkpoint exceeds its size limit')
    return encoded


class PublicationStore:
    def _publication_commit_time(self):
        return time.time()

    def _committed_publication(self, current):
        return self._terminal_publication(current, "committed")

    def _terminal_publication(self, current, outcome):
        """Stamp only a new decision, using the trusted adapter's clock.

        This is the decision time persisted with the effect, not a later
        acknowledgement time. A regressed clock leaves finish unknown.
        """
        candidate = deepcopy(current)
        saved = candidate['job_snapshot']
        validate_publication_snapshot(saved, attempt_id=current['attempt_id'],
                                      document_attempt=current['document_attempt'])
        if current['outcome'] != 'pending':
            raise OwnershipLostError('completion requires a pending decision')
        if saved['finished_at'] is None:
            finished = self._publication_commit_time()
            lower = saved['started_at'] if saved['started_at'] is not None else saved['created_at']
            if type(finished) in (int, float) and math.isfinite(finished) and finished >= lower:
                saved['finished_at'] = finished
        candidate['outcome'] = outcome
        return candidate

    def _checkpoint_supplies_finish(self, current, finished):
        checkpoint = self.get_ingestion_checkpoint(current['job_id'], tenant_id=current['tenant_id'],
            workspace_id=current['workspace_id'], collection_id=current['collection_id'])
        return (checkpoint is not None and checkpoint['attempt_id'] == current['attempt_id']
            and checkpoint['state'] == current['outcome']
            and checkpoint['document_id'] == current['document_id']
            and all(checkpoint['job_snapshot'][key] == current['job_snapshot'][key]
                    for key in ('attempt', 'created_at', 'started_at'))
            and checkpoint['job_snapshot']['finished_at'] == finished)

    def get_ingestion_checkpoint(self, job_id, *, tenant_id, workspace_id, collection_id):
        require_publication_identities(job_id, tenant_id, workspace_id, collection_id)
        record = self._read_ingestion_checkpoint(job_id, tenant_id, workspace_id, collection_id)
        if record is not None:
            if tuple(record[k] for k in ('job_id', 'tenant_id', 'workspace_id', 'collection_id')) != (
                    job_id, tenant_id, workspace_id, collection_id):
                raise OwnershipLostError('checkpoint scope changed')
            validate_publication_snapshot(record['job_snapshot'], attempt_id=record['attempt_id'],
                                          document_attempt=record['job_snapshot']['metadata'].get('published_document_attempt', record['attempt_id']))
            encode_checkpoint(record)
        return record

    @staticmethod
    def _check_checkpoint_facts(current, job):
        saved = current['job_snapshot']
        for key in ('attempt', 'created_at', 'started_at'):
            if key == 'started_at' and saved[key] is None:
                continue
            if getattr(job, key) != saved[key]:
                raise OwnershipLostError('checkpoint attempt facts changed')

    def begin_ingestion_checkpoint(self, job):
        require_publication_identities(job.job_id, job.tenant_id, job.workspace_id,
                                       job.collection_id, job.metadata['publication_attempt'])
        snapshot = publication_snapshot(job)
        with self.ingestion_checkpoint_guard(job):
            current = self.get_ingestion_checkpoint(job.job_id, tenant_id=job.tenant_id,
                workspace_id=job.workspace_id, collection_id=job.collection_id)
            if current is not None:
                if current['attempt_id'] == job.metadata['publication_attempt']:
                    self._check_checkpoint_facts(current, job)
                    return current
                if (job.attempt != current['job_snapshot']['attempt'] + 1 or
                        current['state'] in {'committed', 'cancelled'}):
                    raise OwnershipLostError('checkpoint retry must advance the current attempt')
            record = dict(job_id=job.job_id, tenant_id=job.tenant_id, workspace_id=job.workspace_id,
                collection_id=job.collection_id, attempt_id=job.metadata['publication_attempt'],
                document_id=None, fingerprint=None, state='active', cancel_requested=False,
                job_snapshot=snapshot, artifacts={})
            self._write_ingestion_checkpoint(record)
            return record

    def save_ingestion_checkpoint(self, job, *, fingerprint, artifacts):
        # The short datastore transaction fences both output writes and public
        # cancellation. No document lock is held during provider I/O.
        encode_checkpoint(artifacts)
        with self.ingestion_checkpoint_guard(job):
            current = self.get_ingestion_checkpoint(job.job_id, tenant_id=job.tenant_id,
                workspace_id=job.workspace_id, collection_id=job.collection_id)
            if current is None or current['attempt_id'] != job.metadata['publication_attempt'] or current['state'] != 'active':
                raise OwnershipLostError('checkpoint attempt changed')
            self._check_checkpoint_facts(current, job)
            if current['fingerprint'] is not None and (current['fingerprint'] != fingerprint or current['document_id'] != job.document_id):
                raise OwnershipLostError('checkpoint content or processing contract changed')
            if current['cancel_requested']:
                job.cancel_requested = True
                return current
            # Same-attempt lease transfers must not let a returning former
            # worker truncate or replace already durable provider outputs.
            # Pending calls can still execute more than once; persisted facts
            # only advance by an identical vector prefix.
            for key, saved in current['artifacts'].items():
                proposed = artifacts.get(key)
                if key == 'vectors' and isinstance(saved, list) and isinstance(proposed, list):
                    unchanged = len(proposed) >= len(saved) and proposed[:len(saved)] == saved
                else:
                    unchanged = key in artifacts and proposed == saved
                if not unchanged:
                    raise OwnershipLostError('completed checkpoint output changed')
            candidate = dict(current, document_id=job.document_id, fingerprint=fingerprint,
                             job_snapshot=publication_snapshot(job), artifacts=deepcopy(artifacts))
            self._write_ingestion_checkpoint(candidate)
            return candidate

    def finish_ingestion_checkpoint(self, job):
        with self.ingestion_checkpoint_guard(job):
            current = self.get_ingestion_checkpoint(job.job_id, tenant_id=job.tenant_id,
                workspace_id=job.workspace_id, collection_id=job.collection_id)
            if current is None:
                return
            if current['attempt_id'] != job.metadata['publication_attempt']:
                raise OwnershipLostError('checkpoint attempt changed')
            self._check_checkpoint_facts(current, job)
            if current['job_snapshot']['finished_at'] is not None and job.finished_at != current['job_snapshot']['finished_at']:
                raise OwnershipLostError('checkpoint finish is immutable')
            state = {'published': 'committed', 'failed': 'failed', 'cancelled': 'cancelled'}[job.status]
            if state in {'committed', 'cancelled', 'failed'}:
                receipt = self.get_publication(job.job_id, tenant_id=job.tenant_id,
                    workspace_id=job.workspace_id, collection_id=job.collection_id)
                if (receipt is not None and receipt['attempt_id'] == current['attempt_id']
                        and receipt['outcome'] != state):
                    raise OwnershipLostError('checkpoint outcome requires decision authority')
                if (receipt is not None and receipt['attempt_id'] == current['attempt_id']
                        and receipt['outcome'] == state
                        and job.finished_at != receipt['job_snapshot']['finished_at']
                        and not (receipt['job_snapshot']['finished_at'] is None
                            and current['state'] == state
                            and current['job_snapshot']['finished_at'] is not None
                            and current['job_snapshot']['finished_at'] == job.finished_at)):
                    raise OwnershipLostError('checkpoint finish requires completion authority')
            if current['state'] != 'active' and current['state'] != state:
                raise OwnershipLostError('checkpoint outcome is immutable')
            self._write_ingestion_checkpoint(dict(current, state=state, artifacts={},
                job_snapshot=publication_snapshot(job), cancel_requested=current['cancel_requested'] or job.cancel_requested))

    def repair_deduplicated_checkpoint(self, job):
        """Fill only the missing identity left by the historical dedup producer.

        No caller snapshot supplies facts. The confirmed receipt and terminal
        checkpoint must agree exactly, and only document_id can change.
        """
        with self.mutation_guard('publication:' + job.job_id), self.ingestion_checkpoint_guard(job):
            scope = dict(tenant_id=job.tenant_id, workspace_id=job.workspace_id,
                         collection_id=job.collection_id)
            current = self.get_ingestion_checkpoint(job.job_id, **scope)
            receipt = self.get_publication(job.job_id, **scope)
            if (current is None or receipt is None
                    or current['state'] != 'committed' or receipt['outcome'] != 'committed'
                    or current['attempt_id'] != receipt['attempt_id']
                    or current['document_id'] is not None
                    or current['fingerprint'] is not None or current['artifacts'] != {}
                    or current['cancel_requested'] != receipt['cancel_requested']
                    or current['job_snapshot'] != receipt['job_snapshot']
                    or receipt['job_snapshot']['metadata'].get('deduplicated') is not True):
                return False
            self._write_ingestion_checkpoint(dict(current, document_id=receipt['document_id']))
            return True

    def request_ingestion_cancel(self, job):
        """Persist cancellation for the current canonical attempt before intent.

        An older receipt is never a source of the current attempt token. A
        matching committed receipt wins without receiving a cancellation flag.
        """
        require_publication_identities(job.job_id, job.tenant_id, job.workspace_id,
                                       job.collection_id, job.metadata['publication_attempt'])
        with self.ingestion_checkpoint_guard(job):
            receipt = self.get_publication(job.job_id, tenant_id=job.tenant_id,
                workspace_id=job.workspace_id, collection_id=job.collection_id)
            if receipt is not None and receipt['outcome'] == 'committed':
                return
            current = self.begin_ingestion_checkpoint(job)
            if current['state'] == 'committed':
                return
            self._write_ingestion_checkpoint(dict(current, cancel_requested=True))
            if (receipt is not None and receipt['outcome'] == 'pending' and
                    receipt['attempt_id'] == current['attempt_id'] and
                    receipt['job_snapshot']['attempt'] == job.attempt):
                self._mark_publication_cancel(job)

    def begin_publication(self, job, *, document_attempt=None, ready_count=0):
        attempt = job.metadata['publication_attempt']
        document_attempt = attempt if document_attempt is None else document_attempt
        require_publication_identities(job.job_id, job.tenant_id, job.workspace_id,
            job.collection_id, job.document_id, attempt, document_attempt)
        if type(ready_count) is not int or not 0 <= ready_count <= 100_000:
            raise ValueError('invalid ready point count')
        if type(job.attempt) is not int or job.attempt < 1:
            raise ValueError('invalid publication attempt count')
        record = dict(job_id=job.job_id, tenant_id=job.tenant_id,
                      workspace_id=job.workspace_id, collection_id=job.collection_id,
                      document_id=job.document_id, attempt_id=attempt,
                      document_attempt=document_attempt, outcome='pending',
                      cancel_requested=False, ready_count=ready_count,
                      job_snapshot=publication_snapshot(job, document_attempt=document_attempt))
        with self.mutation_guard('publication:' + job.job_id), self.ingestion_checkpoint_guard(job):
            checkpoint = self.get_ingestion_checkpoint(job.job_id, tenant_id=job.tenant_id,
                workspace_id=job.workspace_id, collection_id=job.collection_id)
            if checkpoint is not None:
                if checkpoint['attempt_id'] != attempt or checkpoint['job_snapshot']['attempt'] != job.attempt:
                    raise OwnershipLostError('publication checkpoint attempt changed')
                record['cancel_requested'] = bool(checkpoint['cancel_requested'])
            previous = self.get_publication(job.job_id, tenant_id=job.tenant_id,
                workspace_id=job.workspace_id, collection_id=job.collection_id)
            if previous is not None:
                if previous['attempt_id'] == attempt:
                    if previous['document_id'] != record['document_id'] or previous['document_attempt'] != document_attempt:
                        raise OwnershipLostError('publication identity changed within attempt')
                    if previous['job_snapshot']['attempt'] != job.attempt:
                        raise OwnershipLostError('publication count changed within attempt')
                    return
                if previous['outcome'] != 'failed':
                    raise OwnershipLostError('publication recovery must precede a new attempt')
                previous_attempt = (previous.get('job_snapshot') or {}).get('attempt')
                if previous_attempt is not None and job.attempt != previous_attempt + 1:
                    raise OwnershipLostError('publication retry must advance exactly one attempt')
            if job.finished_at is not None:
                raise OwnershipLostError('new publication cannot import a caller finish')
            self._write_publication(record)

    def get_publication(self, job_id, *, tenant_id, workspace_id, collection_id):
        require_publication_identities(job_id, tenant_id, workspace_id, collection_id)
        return self._read_publication(job_id, tenant_id, workspace_id, collection_id)

    def save_publication_snapshot(self, job):
        with self.mutation_guard('publication:' + job.job_id):
            current = self.get_publication(job.job_id, tenant_id=job.tenant_id,
                workspace_id=job.workspace_id, collection_id=job.collection_id)
            if current is None or current['attempt_id'] != job.metadata['publication_attempt']:
                raise OwnershipLostError('publication attempt changed')
            if current['document_id'] != job.document_id:
                raise OwnershipLostError('publication document changed')
            saved = current['job_snapshot']
            validate_publication_snapshot(saved, attempt_id=current['attempt_id'], document_attempt=current['document_attempt'])
            candidate = publication_snapshot(job, document_attempt=current['document_attempt'])
            # A matching terminal checkpoint may supply a projection finish,
            # but cannot backfill an immutable historical receipt.
            for key in ('attempt', 'created_at', 'started_at', 'finished_at'):
                if key == 'finished_at' and saved[key] is None:
                    if candidate[key] is not None and (current['outcome'] == 'pending' or
                            job.status != {'committed': 'published', 'failed': 'failed', 'cancelled': 'cancelled'}[current['outcome']] or
                            not self._checkpoint_supplies_finish(current, candidate[key])):
                        raise OwnershipLostError('publication finish requires its terminal outcome')
                    candidate[key] = None
                    continue
                if candidate[key] != saved[key]:
                    raise OwnershipLostError('publication snapshot facts are immutable')
            self._write_publication(dict(current, job_snapshot=candidate))

    def resolve_publication(self, record, outcome):
        if outcome not in {'committed', 'failed', 'cancelled'}:
            raise ValueError('invalid publication outcome')
        with self.mutation_guard('publication:' + record['job_id']), self.publication_decision_guard(record):
            current = self.get_publication(record['job_id'], tenant_id=record['tenant_id'],
                workspace_id=record['workspace_id'], collection_id=record['collection_id'])
            if current is None or current['attempt_id'] != record['attempt_id']:
                raise OwnershipLostError('publication attempt changed')
            if current['outcome'] != 'pending':
                if current['outcome'] != outcome:
                    raise OwnershipLostError('publication outcome is immutable')
                return current
            self._write_publication(self._terminal_publication(current, outcome))
            return self.get_publication(record['job_id'], tenant_id=record['tenant_id'],
                workspace_id=record['workspace_id'], collection_id=record['collection_id'])

    def request_publication_cancel(self, job):
        """Persist a cancellation request; an owned commit still wins."""
        # This flag has no authority to mutate document effects. Do not wait
        # on the document fence: its owner may be awaiting cancellation while
        # recovering an acknowledgement. The adapter updates only this flag.
        require_publication_identities(job.job_id, job.tenant_id, job.workspace_id,
            job.collection_id, job.metadata['publication_attempt'])
        self._mark_publication_cancel(job)

    def _publication_matches(self, record, document):
        return (document is not None and record['document_id'] == document.document_id
                and record['tenant_id'] == document.tenant_id
                and record['workspace_id'] == document.workspace_id
                and record['collection_id'] == document.collection_id
                and record['document_attempt'] == document.metadata.get(ATTEMPT_METADATA_KEY))
