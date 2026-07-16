"""add isolated hidden-city research ledger kinds

Revision ID: 0027_agent_hidden_city_research
Revises: 0026_agent_booking_action_descriptors
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_agent_hidden_city_research"
down_revision: str | Sequence[str] | None = "0026_agent_booking_action_descriptors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND_CHECK = (
    "operation_kind IN ('scope_freeze', 'calendar_search', 'exact_start', "
    "'exact_poll', 'suggest_discovery', 'hidden_city_discovery', "
    "'comparison', 'composition', 'ranking', 'analysis')"
)
_OLD_KIND_CHECK = (
    "operation_kind IN ('scope_freeze', 'calendar_search', 'exact_start', "
    "'exact_poll', 'suggest_discovery', 'comparison', 'composition', "
    "'ranking', 'analysis')"
)
_PROVIDER_CHECK = (
    "(operation_kind IN ('calendar_search', 'exact_start', 'exact_poll', "
    "'suggest_discovery', 'hidden_city_discovery') AND provider_id IS NOT NULL) OR "
    "(operation_kind IN ('scope_freeze', 'comparison', 'composition', "
    "'ranking', 'analysis') AND provider_id IS NULL)"
)
_OLD_PROVIDER_CHECK = (
    "(operation_kind IN ('calendar_search', 'exact_start', 'exact_poll', "
    "'suggest_discovery') AND provider_id IS NOT NULL) OR "
    "(operation_kind IN ('scope_freeze', 'comparison', 'composition', "
    "'ranking', 'analysis') AND provider_id IS NULL)"
)
_LOGICAL_CHECK = (
    "(operation_kind IN ('calendar_search', 'exact_start', 'suggest_discovery', "
    "'hidden_city_discovery') "
    "AND consumes_logical_unit IS TRUE AND logical_root_operation_id IS NULL) OR "
    "(operation_kind = 'exact_poll' AND consumes_logical_unit IS FALSE "
    "AND logical_root_operation_id IS NOT NULL) OR "
    "(operation_kind IN ('scope_freeze', 'comparison', 'composition', "
    "'ranking', 'analysis') AND consumes_logical_unit IS FALSE "
    "AND logical_root_operation_id IS NULL)"
)
_OLD_LOGICAL_CHECK = (
    "(operation_kind IN ('calendar_search', 'exact_start', 'suggest_discovery') "
    "AND consumes_logical_unit IS TRUE AND logical_root_operation_id IS NULL) OR "
    "(operation_kind = 'exact_poll' AND consumes_logical_unit IS FALSE "
    "AND logical_root_operation_id IS NOT NULL) OR "
    "(operation_kind IN ('scope_freeze', 'comparison', 'composition', "
    "'ranking', 'analysis') AND consumes_logical_unit IS FALSE "
    "AND logical_root_operation_id IS NULL)"
)


def upgrade() -> None:
    _replace_checks(
        kind_check=_KIND_CHECK,
        provider_check=_PROVIDER_CHECK,
        logical_check=_LOGICAL_CHECK,
    )


def downgrade() -> None:
    _replace_checks(
        kind_check=_OLD_KIND_CHECK,
        provider_check=_OLD_PROVIDER_CHECK,
        logical_check=_OLD_LOGICAL_CHECK,
    )


def _replace_checks(
    *,
    kind_check: str,
    provider_check: str,
    logical_check: str,
) -> None:
    with op.batch_alter_table("agent_run_operations") as batch:
        batch.drop_constraint("ck_agent_run_operation_kind", type_="check")
        batch.drop_constraint("ck_agent_run_operation_provider", type_="check")
        batch.drop_constraint("ck_agent_run_operation_logical_shape", type_="check")
        batch.create_check_constraint("ck_agent_run_operation_kind", kind_check)
        batch.create_check_constraint("ck_agent_run_operation_provider", provider_check)
        batch.create_check_constraint("ck_agent_run_operation_logical_shape", logical_check)
