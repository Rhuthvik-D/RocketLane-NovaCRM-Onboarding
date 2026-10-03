"""End-to-end integration test validating Phase 4 Data QA stage-gating and Rocketlane native overdue automations."""
from datetime import datetime, timezone
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper
from src.core.audit_logger import audit_logger
from src.models.schemas import (
    DataMigrationSignOffPayload,
    OverdueEscalationTarget,
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus
)
from src.services.rocketlane_client import RocketlaneClient
from src.services.rocketlane_sla_automations import RocketlaneSLAEngine
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


def test_e2e_phase4_full_lifecycle_data_migration_to_configuration_unlock() -> None:
    """Tests complete onboarding flow: Inbound deal -> Slack channel -> Data Migration sign-off -> Configuration unlocked."""
    # 1. Initialize Agents 1, 2, and 3 with simulated integrations
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))
    agent3 = Agent3DataQAGatekeeper(rocketlane=agent1.rocketlane, slack=agent2.slack_client)

    test_ts = int(datetime.now().timestamp())
    corr_id = f"e2e_phase4_full_{test_ts}"

    # 2. Agent 1: Ingest deal and confirm Enterprise tier
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_ent_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Acme is confirmed on Enterprise plan.",
            confidence_score=0.98
        )
    )

    raw_email = {
        "message_id": f"msg_full_{test_ts}",
        "customer_name": f"Stark Industries {test_ts}",
        "customer_contact_email": f"pepper_{test_ts}@stark.com",
        "ae_name": "Tony Stark",
        "ae_phone": "+1-555-0900"
    }

    a1_result = agent1.process_deal(raw_email, correlation_id=corr_id)
    assert a1_result.status == "SUCCESS"
    project_id = a1_result.rocketlane_project.project_id

    # 3. Agent 2: Provision Slack channel and post welcome message
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result is not None

    # 4. Agent 3: Customer completes and verifies Data Migration
    sign_off = DataMigrationSignOffPayload(
        project_id=project_id,
        task_id=f"task_mig_{test_ts}",
        customer_name=f"Stark Industries {test_ts}",
        records_migrated=15000,
        records_verified=15000,
        customer_sign_off_confirmed=True,
        sign_off_contact_email=f"pepper_{test_ts}@stark.com"
    )

    a3_result = agent3.evaluate_migration_sign_off(sign_off, correlation_id=corr_id)

    # 5. Assertions on successful stage-gate unlock
    assert a3_result.status == "VERIFIED_UNLOCKED"
    assert a3_result.is_configuration_unlocked is True
    assert a3_result.discrepancy_count == 0

    # 6. Verify end-to-end continuous audit trail across all 3 agents
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]

    assert "process_deal_started" in actions
    assert "agent1_workflow_completed" in actions
    assert "slack_channel_creation_started" in actions
    assert "agent2_workflow_completed" in actions
    assert "data_qa_evaluation_started" in actions
    assert "data_qa_verification_passed_unlocked" in actions


def test_e2e_phase4_unverified_migration_strictly_blocked() -> None:
    """Verifies that an unverified migration task completion attempt is strictly blocked by Agent 3."""
    agent3 = Agent3DataQAGatekeeper(
        rocketlane=RocketlaneClient(mock_mode=True),
        slack=SlackClient(mock_mode=True)
    )

    test_ts = int(datetime.now().timestamp())
    corr_id = f"e2e_phase4_blocked_{test_ts}"

    # CSM attempts to complete Data Migration without customer verification sign-off
    unverified_payload = DataMigrationSignOffPayload(
        project_id=f"proj_blocked_{test_ts}",
        task_id=f"task_mig_{test_ts}",
        customer_name="Cyberdyne Systems",
        records_migrated=8500,
        records_verified=8500,
        customer_sign_off_confirmed=False,
        sign_off_contact_email="admin@cyberdyne.com"
    )

    result = agent3.evaluate_migration_sign_off(unverified_payload, correlation_id=corr_id)

    # Assertions on hard stage-gate lock
    assert result.status == "REJECTED_BLOCKED"
    assert result.is_configuration_unlocked is False
    assert result.csm_alert_sent is True

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "data_qa_verification_blocked_unconfirmed" in actions


def test_e2e_phase4_native_sla_overdue_escalations() -> None:
    """Verifies that Rocketlane Native SLA rules correctly escalate 1-day overdue tasks to PM and 4-day tasks to Owner."""
    sla_engine = RocketlaneSLAEngine()
    test_ts = int(datetime.now().timestamp())

    # Test Rule 1: 1 day overdue -> PM notified
    pm_alert = sla_engine.evaluate_task_overdue(
        task_id=f"t1_{test_ts}",
        task_name="Import Customer Contacts",
        project_id=f"p_{test_ts}",
        days_overdue=1,
        is_completed=False,
        pm_email="pm.sarah@novacrm.com",
        owner_email="rd3377@nyu.edu",
        correlation_id=f"sla_1d_{test_ts}"
    )
    assert pm_alert.alert_triggered is True
    assert pm_alert.target == OverdueEscalationTarget.PROJECT_MANAGER
    assert pm_alert.recipient_label == "pm.sarah@novacrm.com"

    # Test Rule 2: 4 days overdue -> Owner escalated
    owner_alert = sla_engine.evaluate_task_overdue(
        task_id=f"t2_{test_ts}",
        task_name="Configure Custom Fields",
        project_id=f"p_{test_ts}",
        days_overdue=4,
        is_completed=False,
        pm_email="pm.sarah@novacrm.com",
        owner_email="rd3377@nyu.edu",
        correlation_id=f"sla_4d_{test_ts}"
    )
    assert owner_alert.alert_triggered is True
    assert owner_alert.target == OverdueEscalationTarget.PROJECT_OWNER
    assert owner_alert.recipient_label == "rd3377@nyu.edu"
