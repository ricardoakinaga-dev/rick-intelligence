"""First terminal transitions must produce a persistable chronological snapshot."""
import pytest
from types import SimpleNamespace

from rick_ingestion.jobs import IngestionJob
from rick_knowledge.publication import publication_snapshot


@pytest.mark.parametrize('terminal', ['failed', 'cancelled'])
@pytest.mark.parametrize('started', [None, 12.0])
def test_terminal_snapshot_is_chronological_and_preserves_existing_start(monkeypatch, terminal, started):
    ticks = iter([20.0, 21.0])

    def clock():
        return next(ticks)

    job = IngestionJob(tenant_id='t', workspace_id='w', collection_id='c',
                       created_at=10.0, started_at=started,
                       status='queued' if started is None else 'validating',
                       metadata={'publication_attempt': 'a' * 32})
    monkeypatch.setattr('rick_ingestion.jobs.time', SimpleNamespace(time=clock))
    job.transition(terminal)
    snapshot = publication_snapshot(job)
    assert snapshot['created_at'] == 10.0
    assert snapshot['started_at'] is not None
    assert snapshot['created_at'] <= snapshot['started_at'] <= snapshot['finished_at']
    if started is not None:
        assert snapshot['started_at'] == started
    assert job.status == terminal
