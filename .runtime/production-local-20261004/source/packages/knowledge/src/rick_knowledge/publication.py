"""Durable, scoped publication authority, independent of a worker lease.

Pending receipts are written before the commit gate. Committed receipts must
be written by the adapter in the document transaction and remain immutable.
Reads never infer success from a pending receipt or an unavailable store.
"""
from rick_knowledge.fencing import ATTEMPT_METADATA_KEY, OwnershipLostError
from copy import deepcopy
from collections.abc import Mapping
import math
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


class PublicationStore:
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
        with self.mutation_guard('publication:' + job.job_id):
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
            # Only the first terminal transition may fill a missing finish.
            # Counters and attempt start facts were established before commit.
            for key in ('attempt', 'created_at', 'started_at', 'finished_at'):
                if key == 'finished_at' and saved[key] is None:
                    if candidate[key] is not None and (current['outcome'] == 'pending' or
                            job.status != {'committed': 'published', 'failed': 'failed', 'cancelled': 'cancelled'}[current['outcome']]):
                        raise OwnershipLostError('publication finish requires its terminal outcome')
                    continue
                if candidate[key] != saved[key]:
                    raise OwnershipLostError('publication snapshot facts are immutable')
            self._write_publication(dict(current, job_snapshot=candidate))

    def resolve_publication(self, record, outcome):
        if outcome not in {'committed', 'failed', 'cancelled'}:
            raise ValueError('invalid publication outcome')
        with self.mutation_guard('publication:' + record['job_id']):
            current = self.get_publication(record['job_id'], tenant_id=record['tenant_id'],
                workspace_id=record['workspace_id'], collection_id=record['collection_id'])
            if current is None or current['attempt_id'] != record['attempt_id']:
                raise OwnershipLostError('publication attempt changed')
            if current['outcome'] != 'pending':
                if current['outcome'] != outcome:
                    raise OwnershipLostError('publication outcome is immutable')
                return current
            self._write_publication(dict(current, outcome=outcome))
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
