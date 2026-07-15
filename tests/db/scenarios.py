from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

from .attribute_scenarios import (
    scenario_attribute_complete_empty,
    scenario_attribute_coverage_count,
    scenario_attribute_deleted_upstream,
    scenario_attribute_origin_missing,
    scenario_attribute_partial_retains_old,
    scenario_attribute_state_missing,
    scenario_attribute_state_transition,
    scenario_happy_lifecycle,
    scenario_materialization_digest_collision,
)
from .generation_scenarios import (
    scenario_price_only_no_requeue,
    scenario_relevant_content_change,
)
from .raw_scenarios import (
    scenario_corrupt_gzip,
    scenario_kill_before_rename,
    scenario_prune_active_attribute_origin,
    scenario_prune_active_raw,
    scenario_prune_materialization_origin,
    scenario_raw_sha_mismatch,
    scenario_request_manifest_key_leak,
    scenario_text_plain_raw,
)
from .source_scenarios import (
    scenario_bad_migration,
    scenario_canonical_key_order,
    scenario_canonical_media_equivalence,
    scenario_cross_operation_offer_key,
    scenario_cross_operation_request_sha,
    scenario_db_lock,
    scenario_duplicate_source_key,
    scenario_duplicate_window_page,
    scenario_fk,
    scenario_kill_before_pointer,
    scenario_missing_origin_page,
    scenario_quota_concurrent_ceiling,
    scenario_quota_crash_after_reserve,
    scenario_quota_retry_reservation,
    scenario_request_fingerprint_collision,
)

type ScenarioRunner = Callable[[Path], None]

SCENARIO_RUNNERS: Final[dict[str, ScenarioRunner]] = {
    "kill-before-rename": scenario_kill_before_rename,
    "kill-before-pointer": scenario_kill_before_pointer,
    "fk": scenario_fk,
    "duplicate-source-key": scenario_duplicate_source_key,
    "canonical-json-xml-equivalence": scenario_canonical_media_equivalence,
    "canonical-key-order-equivalence": scenario_canonical_key_order,
    "relevant-content-change": scenario_relevant_content_change,
    "price-only-no-requeue": scenario_price_only_no_requeue,
    "cross-operation-offer-key": scenario_cross_operation_offer_key,
    "attribute-origin-missing": scenario_attribute_origin_missing,
    "attribute-state-missing": scenario_attribute_state_missing,
    "attribute-state-transition": scenario_attribute_state_transition,
    "attribute-deleted-upstream": scenario_attribute_deleted_upstream,
    "attribute-complete-empty": scenario_attribute_complete_empty,
    "attribute-partial-page-retains-old": scenario_attribute_partial_retains_old,
    "attribute-coverage-count": scenario_attribute_coverage_count,
    "request-fingerprint-collision": scenario_request_fingerprint_collision,
    "duplicate-window-page": scenario_duplicate_window_page,
    "cross-operation-request-sha": scenario_cross_operation_request_sha,
    "quota-concurrent-ceiling": scenario_quota_concurrent_ceiling,
    "quota-crash-after-reserve": scenario_quota_crash_after_reserve,
    "quota-retry-reservation": scenario_quota_retry_reservation,
    "db-lock": scenario_db_lock,
    "bad-migration": scenario_bad_migration,
    "prune-active-raw": scenario_prune_active_raw,
    "prune-active-attribute-origin": scenario_prune_active_attribute_origin,
    "prune-materialization-origin": scenario_prune_materialization_origin,
    "missing-origin-page": scenario_missing_origin_page,
    "materialization-digest-collision": scenario_materialization_digest_collision,
    "raw-sha-mismatch": scenario_raw_sha_mismatch,
    "corrupt-gzip": scenario_corrupt_gzip,
    "text-plain-raw": scenario_text_plain_raw,
    "request-manifest-key-leak": scenario_request_manifest_key_leak,
}

HAPPY_RUNNER: Final[ScenarioRunner] = scenario_happy_lifecycle
