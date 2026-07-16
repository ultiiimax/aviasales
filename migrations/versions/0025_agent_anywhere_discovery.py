"""enable bounded provider-backed anywhere discovery operations

Revision ID: 0025_agent_anywhere_discovery
Revises: 0024_agent_execution_ledger
"""

from __future__ import annotations

from alembic import op

revision = "0025_agent_anywhere_discovery"
down_revision = "0024_agent_execution_ledger"
branch_labels = None
depends_on = None

_KIND_CHECK = (
    "operation_kind IN ('scope_freeze', 'calendar_search', 'exact_start', "
    "'exact_poll', 'suggest_discovery', 'comparison', 'composition', "
    "'ranking', 'analysis')"
)
_PROVIDER_CHECK = (
    "(operation_kind IN ('calendar_search', 'exact_start', 'exact_poll', "
    "'suggest_discovery') AND provider_id IS NOT NULL) OR "
    "(operation_kind IN ('scope_freeze', 'comparison', 'composition', "
    "'ranking', 'analysis') AND provider_id IS NULL)"
)
_LOGICAL_CHECK = (
    "(operation_kind IN ('calendar_search', 'exact_start', 'suggest_discovery') "
    "AND consumes_logical_unit IS TRUE AND logical_root_operation_id IS NULL) OR "
    "(operation_kind = 'exact_poll' AND consumes_logical_unit IS FALSE "
    "AND logical_root_operation_id IS NOT NULL) OR "
    "(operation_kind IN ('scope_freeze', 'comparison', 'composition', "
    "'ranking', 'analysis') AND consumes_logical_unit IS FALSE "
    "AND logical_root_operation_id IS NULL)"
)

_OLD_KIND_CHECK = (
    "operation_kind IN ('scope_freeze', 'calendar_search', 'exact_start', "
    "'exact_poll', 'comparison', 'composition', 'ranking', 'analysis')"
)
_OLD_PROVIDER_CHECK = (
    "(operation_kind IN ('calendar_search', 'exact_start', 'exact_poll') "
    "AND provider_id IS NOT NULL) OR "
    "(operation_kind IN ('scope_freeze', 'comparison', 'composition', "
    "'ranking', 'analysis') AND provider_id IS NULL)"
)
_OLD_LOGICAL_CHECK = (
    "(operation_kind IN ('calendar_search', 'exact_start') "
    "AND consumes_logical_unit IS TRUE AND logical_root_operation_id IS NULL) OR "
    "(operation_kind = 'exact_poll' AND consumes_logical_unit IS FALSE "
    "AND logical_root_operation_id IS NOT NULL) OR "
    "(operation_kind IN ('scope_freeze', 'comparison', 'composition', "
    "'ranking', 'analysis') AND consumes_logical_unit IS FALSE "
    "AND logical_root_operation_id IS NULL)"
)


def upgrade() -> None:
    _replace_operation_checks(
        kind_check=_KIND_CHECK,
        provider_check=_PROVIDER_CHECK,
        logical_check=_LOGICAL_CHECK,
    )


def downgrade() -> None:
    _replace_operation_checks(
        kind_check=_OLD_KIND_CHECK,
        provider_check=_OLD_PROVIDER_CHECK,
        logical_check=_OLD_LOGICAL_CHECK,
    )


def _replace_operation_checks(
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
