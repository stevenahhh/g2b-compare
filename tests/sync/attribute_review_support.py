from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.sources.thing_list import ThingListAdapter
from g2b_compare.sources.thing_list_evidence import AttributeEvidenceStore
from g2b_compare.sync.attribute_quota import AttributeQuotaGate
from tests.sources.test_thing_list import (
    FrozenQuotaClock,
    ResponseStub,
    attribute_manifest,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from g2b_compare.contracts.wire import Requester

LEDGER_INSERT = """INSERT INTO api_call_ledger(
    operation, attempted_at_utc, kst_date, status_code, reservation_state
) VALUES (?, ?, ?, 200, 'succeeded')"""
LATEST_RESERVATION = (
    "SELECT reservation_state FROM api_call_ledger ORDER BY id DESC LIMIT 1"
)


@dataclass(frozen=True, slots=True)
class LedgerRequester:
    database: Path
    response: ResponseStub
    dispatch_counts: list[int] = field(default_factory=list, compare=False)

    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> ResponseStub:
        _ = (url, params, follow_redirects)
        with connect(self.database) as connection:
            latest = query(
                connection,
                LATEST_RESERVATION,
            ).fetchone()
            count = query(
                connection,
                "SELECT COUNT(*) FROM api_call_ledger",
            ).fetchone()
        assert latest is not None
        assert as_text(latest[0]) == "reserved"
        assert count is not None
        self.dispatch_counts.append(as_int(count[0]))
        return self.response


def make_adapter(
    database: Path,
    raw_root: Path,
    requester: Requester,
    now: datetime,
) -> ThingListAdapter:
    database.parent.mkdir(parents=True, exist_ok=True)
    migrate(database)
    manifest = attribute_manifest()
    return ThingListAdapter(
        manifest,
        requester,
        "runtime-only",
        AttributeQuotaGate(
            IngestRepository(database),
            manifest,
            FrozenQuotaClock(now),
        ),
        AttributeEvidenceStore(database, raw_root),
    )
