"""Unit test suite verifying Agent 3 Data QA Gatekeeper logic and Rocketlane native overdue SLA rules."""
from datetime import datetime, timezone
import pytest
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper
from src.core.audit_logger import audit_logger
from src.models.schemas import (
    DataMigrationSignOffPayload,
    OverdueEscalationTarget
)
from src.services.rocketlane_client import RocketlaneClient
from src.services.rocketlane_sla_automations import RocketlaneSLAEngine
from src.services.slack_client import SlackClient


def test_data_qa_happy_path_verified_unlocks_configuration() -> None:
    """Verifies that 100% record parity and confirmed customer sign-off unlocks the downstream Configuration phase."""
    agent = Agent3DataQAGatekeeper(
        rocketlane=RocketlaneClient(mock_mode=True),
        slack=SlackClient(mock_mode=True)
    )

    test_ts = int(datetime.now().timestamp())
    corr_id = f"test_qa_happy_{test_ts}"

    payload = DataMigrationSignOffPayload(
        project_id=f"proj_{test_ts}",
        task_id=f"task_mig_{test_ts}",
        customer_name="Acme Enterprise Labs",
        records_migrated=5000,
        records_verified=5000,
        customer_sign_off_confirmed=True,
        sign_off_contact_email="it.director@acmelabs.com",
        discrepancy_notes=None
    )

    result = agent.evaluate_migration_sign_off(payload, correlation_id=corr_id)

    assert result.status == "VERIFIED_UNLOCKED"
    assert result.is_configuration_unlocked is True
    assert result.discrepancy_count == 0
    assert result.csm_alert_sent is False

    # Verify structured audit trail for this evaluation
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "data_qa_evaluation_started" in actions
    assert "data_qa_verification_passed_unlocked" in actions


def test_data_qa_blocks_when_customer_sign_off_missing() -> None:
    """Verifies that missing customer verification sign-off strictly blocks the Configuration phase and alerts the CSM."""
    agent = Agent3DataQAGatekeeper(
        rocketlane=RocketlaneClient(mock_mode=True),
        slack=SlackClient(mock_mode=True)
    )

    test_ts = int(datetime.now().timestamp())
    corr_id = f"test_qa_no_signoff_{test_ts}"

    # CSM attempts to mark Data Migration complete, but customer hasn't verified
    payload = DataMigrationSignOffPayload(
        project_id=f"proj_{test_ts}",
        task_id=f"task_mig_{test_ts}",
        customer_name="Beta Startups Inc",
        records_migrated=1200,
        records_verified=1200,
        customer_sign_off_confirmed=False,
        sign_off_contact_email="lead@betastartups.com"
    )

    result = agent.evaluate_migration_sign_off(payload, correlation_id=corr_id)

    assert result.status == "REJECTED_BLOCKED"
    assert result.is_configuration_unlocked is False
    assert result.csm_alert_sent is True

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "data_qa_verification_blocked_unconfirmed" in actions


def test_data_qa_escalates_on_record_count_discrepancy() -> None:
    """Verifies that record count discrepancies (e.g. 5,000 migrated vs 4,800 verified) auto-escalate to CS Ops and lock the phase."""
    agent = Agent3DataQAGatekeeper(
        rocketlane=RocketlaneClient(mock_mode=True),
        slack=SlackClient(mock_mode=True)
    )

    test_ts = int(datetime.now().timestamp())
    corr_id = f"test_qa_discrepancy_{test_ts}"

    # 5,000 migrated but only 4,800 verified (200 records lost/dropped)
    payload = DataMigrationSignOffPayload(
        project_id=f"proj_{test_ts}",
        task_id=f"task_mig_{test_ts}",
        customer_name="Delta Financial",
        records_migrated=5000,
        records_verified=4800,
        customer_sign_off_confirmed=True,
        sign_off_contact_email="ops@deltafin.com",
        discrepancy_notes="200 lead records failed custom validation."
    )

    result = agent.evaluate_migration_sign_off(payload, correlation_id=corr_id)

    assert result.status == "ESCALATED_DISCREPANCY"
    assert result.is_configuration_unlocked is False
    assert result.discrepancy_count == 200
    assert result.csm_alert_sent is True

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "data_qa_verification_escalated_discrepancy" in actions


def test_data_qa_blocks_on_zero_records_migrated() -> None:
    """Verifies that an attempt to sign off with zero migrated records is immediately halted."""
    agent = Agent3DataQAGatekeeper(
        rocketlane=RocketlaneClient(mock_mode=True),
        slack=SlackClient(mock_mode=True)
    )

    test_ts = int(datetime.now().timestamp())
    payload = DataMigrationSignOffPayload(
        project_id=f"proj_{test_ts}",
        task_id=f"task_mig_{test_ts}",
        customer_name="Zero Corp",
        records_migrated=0,
        records_verified=0,
        customer_sign_off_confirmed=True,
        sign_off_contact_email="lead@zerocorp.com"
    )

    result = agent.evaluate_migration_sign_off(payload, correlation_id=f"test_qa_zero_{test_ts}")

    assert result.status == "REJECTED_BLOCKED"
    assert result.is_configuration_unlocked is False


def test_rocketlane_native_sla_1_day_overdue_notifies_pm() -> None:
    """Verifies that Rocketlane Native SLA Rule 1 notifies the Project Manager when a task is overdue by 1 day."""
    engine = RocketlaneSLAEngine()
    test_ts = int(datetime.now().timestamp())
    corr_id = f"test_sla_1day_{test_ts}"

    alert = engine.evaluate_task_overdue(
        task_id=f"task_1day_{test_ts}",
        task_name="Kickoff Call & Scope Alignment",
        project_id=f"proj_{test_ts}",
        days_overdue=1,
        is_completed=False,
        pm_email="sarah.connor@novacrm.com",
        owner_email="rd3377@nyu.edu",
        correlation_id=corr_id
    )

    assert alert.alert_triggered is True
    assert alert.target == OverdueEscalationTarget.PROJECT_MANAGER
    assert alert.recipient_label == "sarah.connor@novacrm.com"
    assert "1 day(s) overdue" in alert.alert_message

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "sla_overdue_pm_notified" in actions


def test_rocketlane_native_sla_4_days_overdue_notifies_owner() -> None:
    """Verifies that Rocketlane Native SLA Rule 2 escalates to the Project Owner when a task is overdue by 4 days."""
    engine = RocketlaneSLAEngine()
    test_ts = int(datetime.now().timestamp())
    corr_id = f"test_sla_4day_{test_ts}"

    alert = engine.evaluate_task_overdue(
        task_id=f"task_4day_{test_ts}",
        task_name="Data Migration Parity Check",
        project_id=f"proj_{test_ts}",
        days_overdue=4,
        is_completed=False,
        pm_email="sarah.connor@novacrm.com",
        owner_email="rd3377@nyu.edu",
        correlation_id=corr_id
    )

    assert alert.alert_triggered is True
    assert alert.target == OverdueEscalationTarget.PROJECT_OWNER
    assert alert.recipient_label == "rd3377@nyu.edu"
    assert "4 days overdue" in alert.alert_message

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "sla_overdue_owner_escalated" in actions


def test_rocketlane_native_sla_not_overdue_no_alert() -> None:
    """Verifies that on-schedule tasks (days_overdue == 0) do not trigger any SLA alerts."""
    engine = RocketlaneSLAEngine()
    test_ts = int(datetime.now().timestamp())

    alert = engine.evaluate_task_overdue(
        task_id=f"task_ontime_{test_ts}",
        task_name="System Configuration",
        project_id=f"proj_{test_ts}",
        days_overdue=0,
        is_completed=False
    )

    assert alert.alert_triggered is False
    assert alert.target is None


def test_rocketlane_native_sla_completed_task_no_alert() -> None:
    """Verifies that completed tasks do not trigger SLA alerts even if original due date has passed."""
    engine = RocketlaneSLAEngine()
    test_ts = int(datetime.now().timestamp())

    alert = engine.evaluate_task_overdue(
        task_id=f"task_done_{test_ts}",
        task_name="Kickoff Call",
        project_id=f"proj_{test_ts}",
        days_overdue=5,
        is_completed=True
    )

    assert alert.alert_triggered is False
    assert alert.target is None


def test_rocketlane_native_sla_export_platform_rules() -> None:
    """Verifies that export_platform_rules returns the 2 codified native automation specifications."""
    engine = RocketlaneSLAEngine()
    rules = engine.export_platform_rules()

    assert len(rules) == 2
    rule_ids = [r["rule_id"] for r in rules]
    assert "rule_sla_1day_pm" in rule_ids
    assert "rule_sla_4day_owner" in rule_ids


def test_data_qa_rejects_non_migration_task_by_name() -> None:
    """Verifies that submitting a non-migration task name (e.g. Kickoff) trips the Semantic Guardrail."""
    agent = Agent3DataQAGatekeeper(
        rocketlane=RocketlaneClient(mock_mode=True),
        slack=SlackClient(mock_mode=True),
    )
    test_ts = int(datetime.now().timestamp())
    corr_id = f"test_qa_semantic_name_{test_ts}"

    payload = DataMigrationSignOffPayload(
        project_id=f"proj_{test_ts}",
        task_id=f"task_5000_{test_ts}",
        task_name="Schedule kick-off meeting",  # Non-migration task!
        customer_name="Apex Dynamics",
        records_migrated=1000,
        records_verified=1000,
        customer_sign_off_confirmed=True,
        sign_off_contact_email="it@apexdynamics.com",
    )

    result = agent.evaluate_migration_sign_off(payload, correlation_id=corr_id)

    assert result.status == "REJECTED_BLOCKED"
    assert result.is_configuration_unlocked is False
    assert "not a data migration task" in result.audit_rationale or "unrelated" in result.audit_rationale

    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "data_qa_verification_blocked_invalid_task" in actions


def test_data_qa_rejects_non_migration_task_by_id() -> None:
    """Verifies that submitting a task ID indicating an unrelated milestone trips the guardrail."""
    agent = Agent3DataQAGatekeeper(
        rocketlane=RocketlaneClient(mock_mode=True),
        slack=SlackClient(mock_mode=True),
    )
    test_ts = int(datetime.now().timestamp())
    corr_id = f"test_qa_semantic_id_{test_ts}"

    payload = DataMigrationSignOffPayload(
        project_id=f"proj_{test_ts}",
        task_id="task_kickoff_meeting_999",  # Non-migration task ID!
        customer_name="Apex Dynamics",
        records_migrated=1000,
        records_verified=1000,
        customer_sign_off_confirmed=True,
        sign_off_contact_email="it@apexdynamics.com",
    )

    result = agent.evaluate_migration_sign_off(payload, correlation_id=corr_id)

    assert result.status == "REJECTED_BLOCKED"
    assert result.is_configuration_unlocked is False
    assert "unrelated" in result.audit_rationale

    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "data_qa_verification_blocked_invalid_task" in actions
