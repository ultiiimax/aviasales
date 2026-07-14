from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import registry

metadata = MetaData()
mapper_registry = registry(metadata=metadata)


households_table = Table(
    "households",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


users_table = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("display_name", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


household_memberships_table = Table(
    "household_memberships",
    metadata,
    Column("household_id", String(36), primary_key=True),
    Column("user_id", String(36), primary_key=True),
    Column("role", String(40), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("disabled_at", DateTime(timezone=True), nullable=True),
)


auth_invitations_table = Table(
    "auth_invitations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("invited_by_user_id", String(36), nullable=True, index=True),
    Column("role", String(40), nullable=False),
    Column("code_hash", String(64), nullable=False, unique=True),
    Column("recipient_label", String(160), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    Column("accepted_by_user_id", String(36), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)


auth_sessions_table = Table(
    "auth_sessions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)


watches_table = Table(
    "watches",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("owner_user_id", String(36), nullable=False),
    Column("origin", String(3), nullable=False),
    Column("destination", String(3), nullable=False),
    Column("departure_date", String(10), nullable=False),
    Column("return_date", String(10), nullable=True),
    Column("passengers", Integer, nullable=False, default=1),
    Column("currency", String(3), nullable=False, default="RUB"),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("paused_until", DateTime(timezone=True), nullable=True),
    Column("next_eligible_at", DateTime(timezone=True), nullable=True),
    Column("scan_interval_seconds", Integer, nullable=False, default=21600),
    Column("allowed_provider_ids", String(500), nullable=False, default=""),
    Column("last_scanned_at", DateTime(timezone=True), nullable=True),
    Column("last_scan_status", String(40), nullable=True),
    Column("last_scan_error_code", String(80), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("archived_at", DateTime(timezone=True), nullable=True),
    Column("archived_by_user_id", String(36), nullable=True),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    Column("deleted_by_user_id", String(36), nullable=True),
)


watch_scan_jobs_table = Table(
    "watch_scan_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("watch_id", String(36), nullable=False, index=True),
    Column("idempotency_key", String(240), nullable=False, unique=True),
    Column("status", String(40), nullable=False, index=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=3),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", String(80), nullable=True),
    Column("deadline_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("provider_ids", String(500), nullable=False),
    Column("provider_denials", String(2000), nullable=False, default="{}"),
    Column("error_code", String(80), nullable=True),
    Column("error_message", String(500), nullable=True),
)


price_snapshots_table = Table(
    "price_snapshots",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("watch_id", String(36), nullable=False, index=True),
    Column("provider_id", String(80), nullable=False),
    Column("itinerary_fingerprint", String(160), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("amount_minor", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("freshness", String(20), nullable=False),
    Column("requires_live_confirmation", Boolean, nullable=False),
)


alert_dedupe_entries_table = Table(
    "alert_dedupe_entries",
    metadata,
    Column("dedupe_key", String(240), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("watch_id", String(36), nullable=False, index=True),
    Column("itinerary_fingerprint", String(160), nullable=False),
    Column("reason", String(40), nullable=False),
    Column("sent_at", DateTime(timezone=True), nullable=False),
)


user_action_grants_table = Table(
    "user_action_grants",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("provider_id", String(80), nullable=False, index=True),
    Column("action_type", String(80), nullable=False),
    Column("request_fingerprint", String(160), nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("source", String(40), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
)


live_observations_table = Table(
    "live_observations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("grant_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("source_id", String(80), nullable=False, index=True),
    Column("search_intent_hash", String(160), nullable=False),
    Column("status", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("error_code", String(80), nullable=True),
    Column("error_message", String(500), nullable=True),
)


live_observation_offers_table = Table(
    "live_observation_offers",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("observation_id", String(36), nullable=False, index=True),
    Column("provider_id", String(80), nullable=False),
    Column("provider_offer_id", String(160), nullable=False),
    Column("origin", String(3), nullable=False),
    Column("destination", String(3), nullable=False),
    Column("departure_date", String(10), nullable=False),
    Column("return_date", String(10), nullable=True),
    Column("amount_minor", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("passengers", Integer, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("freshness", String(30), nullable=False),
    Column("requires_live_confirmation", Boolean, nullable=False),
    Column("baggage_summary", String(240), nullable=True),
)


live_observation_idempotency_table = Table(
    "live_observation_idempotency",
    metadata,
    Column("dedupe_key", String(300), primary_key=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("idempotency_key", String(240), nullable=False),
    Column("observation_id", String(36), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


browser_observation_jobs_table = Table(
    "browser_observation_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("source_id", String(80), nullable=False, index=True),
    Column("search_id", String(160), nullable=False, index=True),
    Column("search_intent_hash", String(160), nullable=False),
    Column("idempotency_key", String(240), nullable=False),
    Column("grant_id", String(36), nullable=False, index=True),
    Column("origin", String(3), nullable=False),
    Column("destination", String(3), nullable=False),
    Column("departure_date", String(10), nullable=False),
    Column("return_date", String(10), nullable=True),
    Column("passengers", Integer, nullable=False),
    Column("adults", Integer, nullable=False),
    Column("children", Integer, nullable=False),
    Column("infants", Integer, nullable=False),
    Column("trip_type", String(40), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("status", String(40), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("last_attempted_at", DateTime(timezone=True), nullable=True),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", String(80), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("waiting_since", DateTime(timezone=True), nullable=True),
    Column("operator_resume_requested_at", DateTime(timezone=True), nullable=True),
    Column("operator_abort_requested_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("error_code", String(80), nullable=True),
    Column("error_message", String(500), nullable=True),
)


browser_observed_offers_table = Table(
    "browser_observed_offers",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("search_id", String(160), nullable=False, index=True),
    Column("source_id", String(80), nullable=False, index=True),
    Column("source_name", String(120), nullable=False),
    Column("provider_offer_id", String(160), nullable=False),
    Column("origin", String(3), nullable=False),
    Column("destination", String(3), nullable=False),
    Column("departure_date", String(10), nullable=True),
    Column("return_date", String(10), nullable=True),
    Column("amount_minor", Integer, nullable=True),
    Column("currency", String(3), nullable=True),
    Column("passengers", Integer, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("final_url", String(1000), nullable=False),
    Column("display_url", String(240), nullable=False),
    Column("freshness", String(40), nullable=False),
    Column("confidence", String(20), nullable=False),
    Column("parser_version", String(120), nullable=False),
    Column("parser_warnings_json", String(1000), nullable=False),
    Column("airline_name", String(160), nullable=True),
    Column("airline_iata", String(3), nullable=True),
    Column("flight_number", String(40), nullable=True),
    Column("departure_time_local", String(40), nullable=True),
    Column("arrival_time_local", String(40), nullable=True),
    Column("duration_minutes", Integer, nullable=True),
    Column("stops", Integer, nullable=True),
    Column("baggage_summary", String(240), nullable=True),
    Column("seller_name", String(160), nullable=True),
    Column("requires_external_confirmation", Boolean, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)


deal_candidates_table = Table(
    "deal_candidates",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("search_id", String(160), nullable=False, index=True),
    Column("source_id", String(80), nullable=False, index=True),
    Column("discovered_url", String(1000), nullable=False),
    Column("title", String(240), nullable=False),
    Column("summary", String(1000), nullable=False),
    Column("extracted_origin", String(3), nullable=True),
    Column("extracted_destination", String(3), nullable=True),
    Column("extracted_departure_window", String(120), nullable=True),
    Column("extracted_price_minor_units", Integer, nullable=True),
    Column("currency", String(3), nullable=True),
    Column("confidence", String(20), nullable=False),
    Column("discovered_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("requires_manual_verification", Boolean, nullable=False),
    Column("raw_ref", String(240), nullable=True),
)


deal_discovery_jobs_table = Table(
    "deal_discovery_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("search_id", String(160), nullable=False, index=True),
    Column("idempotency_key", String(240), nullable=False, unique=True),
    Column("status", String(40), nullable=False, index=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=3),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", String(80), nullable=True),
    Column("deadline_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("search_intent_json", String(2000), nullable=False),
    Column("limit", Integer, nullable=False, default=5),
    Column("result_count", Integer, nullable=False, default=0),
    Column("error_code", String(80), nullable=True),
    Column("error_message", String(500), nullable=True),
)


manual_price_confirmations_table = Table(
    "manual_price_confirmations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("target_kind", String(80), nullable=False, index=True),
    Column("target_id", String(160), nullable=False, index=True),
    Column("source_id", String(80), nullable=False, index=True),
    Column("status", String(40), nullable=False, index=True),
    Column("amount_minor", Integer, nullable=True),
    Column("currency", String(3), nullable=True),
    Column("note", String(500), nullable=True),
    Column("confirmed_at", DateTime(timezone=True), nullable=False),
)


source_health_events_table = Table(
    "source_health_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("source_id", String(80), nullable=False, index=True),
    Column("event_type", String(80), nullable=False, index=True),
    Column("status", String(40), nullable=False, index=True),
    Column("message", String(500), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("cooldown_until", DateTime(timezone=True), nullable=True),
)


worker_heartbeats_table = Table(
    "worker_heartbeats",
    metadata,
    Column("worker_id", String(120), primary_key=True),
    Column("role", String(80), nullable=False, index=True),
    Column("status", String(40), nullable=False, index=True),
    Column("current_phase", String(80), nullable=False),
    Column("current_job_kind", String(80), nullable=True),
    Column("current_job_id", String(80), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("stopping_at", DateTime(timezone=True), nullable=True),
    Column("stopped_at", DateTime(timezone=True), nullable=True),
    Column("last_summary_json", String(4000), nullable=False, default="{}"),
)


worker_control_table = Table(
    "worker_control",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("drain_requested", Boolean, nullable=False, default=False),
    Column("reason", String(500), nullable=True),
    Column("requested_by_household_id", String(36), nullable=True),
    Column("requested_by_user_id", String(36), nullable=True),
    Column("requested_at", DateTime(timezone=True), nullable=True),
    Column("cleared_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


telegram_update_dedupe_table = Table(
    "telegram_update_dedupe",
    metadata,
    Column("update_id", Integer, primary_key=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
)


telegram_link_codes_table = Table(
    "telegram_link_codes",
    metadata,
    Column("code", String(32), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
)


telegram_accounts_table = Table(
    "telegram_accounts",
    metadata,
    Column("user_id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("telegram_user_id", Integer, nullable=False, unique=True),
    Column("chat_id", Integer, nullable=False),
    Column("linked_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)


telegram_notification_outbox_table = Table(
    "telegram_notification_outbox",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("chat_id", Integer, nullable=True),
    Column("kind", String(60), nullable=False),
    Column("dedupe_key", String(240), nullable=False, unique=True),
    Column("payload_json", String(4000), nullable=False),
    Column("status", String(40), nullable=False, index=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", String(80), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("sent_at", DateTime(timezone=True), nullable=True),
    Column("error_code", String(80), nullable=True),
    Column("error_message", String(500), nullable=True),
)


airports_table = Table(
    "airports",
    metadata,
    Column("iata_code", String(3), primary_key=True),
    Column("name", String(240), nullable=False),
    Column("municipality", String(160), nullable=False),
    Column("country_code", String(2), nullable=False, index=True),
    Column("latitude", Float, nullable=False),
    Column("longitude", Float, nullable=False),
    Column("airport_type", String(40), nullable=False, index=True),
    Column("active", Boolean, nullable=False),
    Column("scheduled_service", Boolean, nullable=False),
    Column(
        "commercial_provenance",
        String(120),
        nullable=False,
    ),
    Column("keywords", String(500), nullable=False, default=""),
    Column("imported_at", DateTime(timezone=True), nullable=False),
)


airport_import_runs_table = Table(
    "airport_import_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("source", String(80), nullable=False, index=True),
    Column("source_path", String(500), nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("rows_seen", Integer, nullable=False),
    Column("rows_imported", Integer, nullable=False),
)


agent_audit_events_table = Table(
    "agent_audit_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=True, index=True),
    Column("user_id", String(36), nullable=True, index=True),
    Column("event_type", String(80), nullable=False),
    Column("tool_name", String(120), nullable=False),
    Column("summary", String(500), nullable=False),
    Column("policy_decision", String(120), nullable=False),
    Column("related_id", String(120), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


audit_events_table = Table(
    "audit_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("actor_user_id", String(36), nullable=True, index=True),
    Column("action", String(80), nullable=False, index=True),
    Column("entity_type", String(80), nullable=False),
    Column("entity_id", String(36), nullable=False, index=True),
    Column("summary", String(500), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


agent_search_plans_table = Table(
    "agent_search_plans",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column("created_by_user_id", String(36), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


agent_search_plan_revisions_table = Table(
    "agent_search_plan_revisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "plan_id",
        String(36),
        ForeignKey("agent_search_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("household_id", String(36), nullable=False, index=True),
    Column("source_revision_id", String(36), nullable=True),
    Column("revision_number", Integer, nullable=False),
    Column("state", String(40), nullable=False, index=True),
    Column("plan_json", Text, nullable=False),
    Column("scope_snapshot_json", Text, nullable=False),
    Column("capability_snapshot_json", Text, nullable=False),
    Column("cost_model_snapshot_json", Text, nullable=False),
    Column("parser_version", String(120), nullable=False),
    Column("planner_version", String(120), nullable=False),
    Column("estimated_calendar_searches", Integer, nullable=True),
    Column("estimated_exact_searches", Integer, nullable=True),
    Column("estimated_logical_operations", Integer, nullable=True),
    Column("estimated_http_attempts", Integer, nullable=True),
    Column("estimated_deadline_seconds", Integer, nullable=True),
    Column("content_hash", String(71), nullable=False),
    Column("clone_idempotency_key", String(240), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("superseded_at", DateTime(timezone=True), nullable=True),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("plan_id", "revision_number", name="uq_agent_plan_revision_number"),
    UniqueConstraint("plan_id", "content_hash", name="uq_agent_plan_revision_hash"),
    CheckConstraint(
        "state IN ('draft', 'awaiting_approval', 'superseded', 'consumed', 'expired')",
        name="ck_agent_plan_revision_state",
    ),
    CheckConstraint(
        "state != 'awaiting_approval' OR ("
        "estimated_calendar_searches IS NOT NULL AND estimated_calendar_searches >= 0 AND "
        "estimated_exact_searches IS NOT NULL AND estimated_exact_searches >= 0 AND "
        "estimated_logical_operations IS NOT NULL AND estimated_logical_operations > 0 AND "
        "estimated_logical_operations = "
        "estimated_calendar_searches + estimated_exact_searches AND "
        "estimated_http_attempts IS NOT NULL AND estimated_http_attempts > 0 AND "
        "estimated_deadline_seconds IS NOT NULL AND estimated_deadline_seconds > 0)",
        name="ck_agent_plan_revision_estimates",
    ),
)

Index(
    "ix_agent_plan_revision_clone_idempotency",
    agent_search_plan_revisions_table.c.household_id,
    agent_search_plan_revisions_table.c.clone_idempotency_key,
    unique=True,
    sqlite_where=agent_search_plan_revisions_table.c.clone_idempotency_key.is_not(None),
    postgresql_where=agent_search_plan_revisions_table.c.clone_idempotency_key.is_not(None),
)


agent_plan_execution_approvals_table = Table(
    "agent_plan_execution_approvals",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column(
        "plan_id",
        String(36),
        ForeignKey("agent_search_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column(
        "revision_id",
        String(36),
        ForeignKey("agent_search_plan_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("approved_by_user_id", String(36), nullable=False),
    Column("revision_content_hash", String(71), nullable=False),
    Column("approved_by_session_id", String(36), nullable=False),
    Column("approved_budget_json", Text, nullable=False),
    Column("approved_strategies_json", Text, nullable=False),
    Column("risk_warning_versions_json", Text, nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    Column("run_id", String(36), nullable=True),
    UniqueConstraint("run_id", name="uq_agent_approval_run"),
)


agent_plan_runs_table = Table(
    "agent_plan_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("household_id", String(36), nullable=False, index=True),
    Column(
        "plan_id",
        String(36),
        ForeignKey("agent_search_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column(
        "revision_id",
        String(36),
        ForeignKey("agent_search_plan_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column(
        "approval_id",
        String(36),
        ForeignKey("agent_plan_execution_approvals.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("execute_idempotency_key", String(240), nullable=False),
    Column("status", String(40), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("deadline_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("cancel_requested_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error_code", String(80), nullable=True),
    Column("error_message", String(500), nullable=True),
    UniqueConstraint(
        "household_id",
        "execute_idempotency_key",
        name="uq_agent_run_execute_idempotency",
    ),
    UniqueConstraint("approval_id", name="uq_agent_run_approval"),
    CheckConstraint(
        "status IN ('queued', 'running', 'cancel_requested', "
        "'completed', 'partial', 'failed', 'cancelled')",
        name="ck_agent_plan_run_status",
    ),
    CheckConstraint(
        "(started_at IS NULL OR started_at >= created_at) AND "
        "(cancel_requested_at IS NULL OR cancel_requested_at >= created_at) AND "
        "(finished_at IS NULL OR finished_at >= created_at) AND "
        "(finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at) AND "
        "(finished_at IS NULL OR cancel_requested_at IS NULL OR "
        "finished_at >= cancel_requested_at)",
        name="ck_agent_plan_run_chronology",
    ),
)

Index(
    "ix_agent_plan_one_active_run",
    agent_plan_runs_table.c.plan_id,
    unique=True,
    sqlite_where=text("status IN ('queued', 'running', 'cancel_requested')"),
    postgresql_where=text("status IN ('queued', 'running', 'cancel_requested')"),
)
