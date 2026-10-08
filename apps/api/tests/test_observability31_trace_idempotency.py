"""Tracing metadata must never become a document's idempotency key."""
from types import SimpleNamespace

import pytest

from services.postgres_ingestion import PostgresIngestionApplicationService
from services.ingestion_service import IngestionApplicationError
from test_postgres_ingestion import Objects, Queue


class RememberingQueue(Queue):
    def __init__(self):
        super().__init__()
        self.records = []

    def enqueue(self, **kwargs):
        result = super().enqueue(**kwargs)
        self.records.append(result)
        return result

    def get_by_idempotency(self, **scope):
        return next((row for row in self.records if all(getattr(row, field) == value for field, value in scope.items())), None)


@pytest.mark.parametrize('carrier', [
    {'traceparent': '00-' + 'a' * 32 + '-' + 'b' * 16 + '-01'},
    {'traceparent': '00-' + 'a' * 32 + '-' + 'b' * 16 + '-01', 'tracestate': 'vendor=value'},
    {'traceparent': '00-' + 'a' * 32 + '-' + 'b' * 16 + '-01', 'baggage': 'private=discarded'},
])
@pytest.mark.parametrize('explicit', [False, True])
def test_distinct_traced_uploads_preserve_idempotency_and_replay(carrier, explicit):
    queue = RememberingQueue()
    objects = Objects()
    service = PostgresIngestionApplicationService(queue=queue, object_store=objects)
    scope = dict(filename='guide.md', tenant_id='tenant-a', workspace_id='workspace-a', collection_id='guides')
    first = service.submit_upload(b'alpha', trace_context=carrier, **scope,
                                  **({'idempotency_key': 'upload-alpha'} if explicit else {}))
    first_key = queue.enqueues[0]['idempotency_key']
    if explicit:
        assert first_key == 'upload-alpha'
    second = service.submit_upload(b'beta', trace_context=carrier, **scope,
                                   **({'idempotency_key': 'upload-beta'} if explicit else {}))
    second_key = queue.enqueues[1]['idempotency_key']
    assert first_key != second_key
    assert first['job_id'] != second['job_id']
    if explicit:
        assert second_key == 'upload-beta'
    assert len(objects.puts) == 2
    assert all('baggage' not in row['payload'] for row in queue.enqueues)
    new_carrier = {'traceparent': '00-' + 'c' * 32 + '-' + 'd' * 16 + '-01'}
    replay = service.submit_upload(b'alpha', trace_context=new_carrier, idempotency_key=first_key, **scope)
    assert replay['job_id'] == first['job_id']
    assert len(queue.enqueues) == len(objects.puts) == 2
    assert queue.records[0].payload['traceparent'] == carrier['traceparent']
    with pytest.raises(IngestionApplicationError) as exc:
        service.submit_upload(b'changed', trace_context=new_carrier, idempotency_key=first_key, **scope)
    assert exc.value.code == 'conflict'
    assert len(queue.enqueues) == len(objects.puts) == 2
