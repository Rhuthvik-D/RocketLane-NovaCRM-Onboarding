# End-to-end integration test validating Phase 4 Data QA stage-gating and Rocketlane native overdue automations.  # What: Module header; Why: Verifies Phase 4 multi-agent and platform integration.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps in test payloads.
import pytest  # What: Import pytest; Why: Test assertion and execution framework.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent 1; Why: Runs upstream deal intake.
from src.agents.agent2_communication import Agent2Communication  # What: Import Agent 2; Why: Runs downstream communications.
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper  # What: Import Agent 3; Why: Evaluates stage-gate verification.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Verifies audit trail continuity across all 3 agents.
from src.models.schemas import (  # What: Import domain models; Why: Typed models for test scenarios.
    DataMigrationSignOffPayload,  # What: Data QA sign-off payload; Why: Ingests migration metrics.
    OverdueEscalationTarget,  # What: SLA target enum; Why: Verifies PM vs Owner alerts.
    PlanTier,  # What: Plan tier enum; Why: Enterprise plan tier.
    VoiceCallResult,  # What: Voice call result model; Why: Telephony results.
    VoiceCallStatus  # What: Voice call status enum; Why: Confirmed status.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Mock client for fast testing.
from src.services.rocketlane_sla_automations import RocketlaneSLAEngine  # What: Import SLA engine; Why: Tests native platform rules.
from src.services.slack_client import SlackClient  # What: Import SlackClient; Why: Mock Slack client.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Mock voice client.


def test_e2e_phase4_full_lifecycle_data_migration_to_configuration_unlock() -> None:  # What: E2E full lifecycle test; Why: Verifies Agent 1 -> Agent 2 -> Agent 3 unlock.
    """Tests complete onboarding flow: Inbound deal -> Slack channel -> Data Migration sign-off -> Configuration unlocked."""  # What: Docstring; Why: Explains test intent.
    # 1. Initialize Agents 1, 2, and 3 with simulated integrations
    agent1 = Agent1Intake()  # What: Fresh Agent 1; Why: Deal intake.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock Rocketlane; Why: Fast deterministic test.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Telephony simulation.

    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Agent 2 with mock Slack; Why: Slack simulation.
    agent3 = Agent3DataQAGatekeeper(rocketlane=agent1.rocketlane, slack=agent2.slack_client)  # What: Agent 3 with shared clients; Why: Data QA gatekeeper.

    test_ts = int(datetime.now().timestamp())  # What: Timestamp; Why: Unique deal ID.
    corr_id = f"e2e_phase4_full_{test_ts}"  # What: Correlation ID; Why: Connects all 3 agents.

    # 2. Agent 1: Ingest deal and confirm Enterprise tier
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Unambiguous Enterprise confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Enterprise result.
            call_id=f"call_ent_{test_ts}",  # What: Call ID; Why: Telephony session ID.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Acme is confirmed on Enterprise plan.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.98  # What: High confidence; Why: Verified.
        )  # What: End of VoiceCallResult; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email = {  # What: Inbound raw email; Why: Enterprise deal payload.
        "message_id": f"msg_full_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": f"Stark Industries {test_ts}",  # What: Customer name; Why: Name to sanitize.
        "customer_contact_email": f"pepper_{test_ts}@stark.com",  # What: Customer contact; Why: Primary collaborator.
        "ae_name": "Tony Stark",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0900"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Ready.

    a1_result = agent1.process_deal(raw_email, correlation_id=corr_id)  # What: Process deal; Why: Runs Agent 1.
    assert a1_result.status == "SUCCESS"  # What: Assert Agent 1 success; Why: Upstream completed.
    project_id = a1_result.rocketlane_project.project_id  # What: Extract project ID; Why: Target project.

    # 3. Agent 2: Provision Slack channel and post welcome message
    a2_result = agent2.process_project_handoff(a1_result)  # What: Process handoff; Why: Runs Agent 2.
    assert a2_result.status == "SUCCESS"  # What: Assert Agent 2 success; Why: Channel provisioned.
    assert a2_result.provisioning_result is not None  # What: Assert Slack result; Why: Verified.

    # 4. Agent 3: Customer completes and verifies Data Migration
    sign_off = DataMigrationSignOffPayload(  # What: Sign-off payload; Why: Complete and verified migration proof.
        project_id=project_id,  # What: Project ID; Why: Target project.
        task_id=f"task_mig_{test_ts}",  # What: Task ID; Why: Migration task.
        customer_name=f"Stark Industries {test_ts}",  # What: Customer name; Why: Customer identity.
        records_migrated=15000,  # What: Migrated records; Why: Record volume.
        records_verified=15000,  # What: Verified records; Why: 100% parity.
        customer_sign_off_confirmed=True,  # What: Confirmed flag; Why: Customer authorized sign-off.
        sign_off_contact_email=f"pepper_{test_ts}@stark.com"  # What: Customer lead email; Why: Authorizer email.
    )  # What: End of sign-off payload; Why: Ready for gatekeeper.

    a3_result = agent3.evaluate_migration_sign_off(sign_off, correlation_id=corr_id)  # What: Evaluate sign-off; Why: Runs Agent 3.

    # 5. Assertions on successful stage-gate unlock
    assert a3_result.status == "VERIFIED_UNLOCKED"  # What: Assert status VERIFIED_UNLOCKED; Why: Criteria met.
    assert a3_result.is_configuration_unlocked is True  # What: Assert Configuration unlocked; Why: Milestone transition approved.
    assert a3_result.discrepancy_count == 0  # What: Assert zero discrepancy; Why: 100% parity.

    # 6. Verify end-to-end continuous audit trail across all 3 agents
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names; Why: Inspects executed events.

    assert "process_deal_started" in actions  # What: Assert deal start; Why: Agent 1 event.
    assert "agent1_workflow_completed" in actions  # What: Assert Agent 1 done; Why: Agent 1 event.
    assert "slack_channel_creation_started" in actions  # What: Assert Slack start; Why: Agent 2 event.
    assert "agent2_workflow_completed" in actions  # What: Assert Agent 2 done; Why: Agent 2 event.
    assert "data_qa_evaluation_started" in actions  # What: Assert Data QA start; Why: Agent 3 event.
    assert "data_qa_verification_passed_unlocked" in actions  # What: Assert QA unlock; Why: Agent 3 event.


def test_e2e_phase4_unverified_migration_strictly_blocked() -> None:  # What: Negative stage-gate test; Why: Proves unverified migrations cannot unlock Configuration.
    """Verifies that an unverified migration task completion attempt is strictly blocked by Agent 3."""  # What: Docstring; Why: Explains test intent.
    agent3 = Agent3DataQAGatekeeper(  # What: Instantiate Agent 3; Why: Isolated test.
        rocketlane=RocketlaneClient(mock_mode=True),  # What: Mock client; Why: Simulated execution.
        slack=SlackClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    )  # What: End of instantiation; Why: Ready.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.
    corr_id = f"e2e_phase4_blocked_{test_ts}"  # What: Unique correlation ID; Why: Connects audit records.

    # CSM attempts to complete Data Migration without customer verification sign-off
    unverified_payload = DataMigrationSignOffPayload(  # What: Unverified sign-off payload; Why: customer_sign_off_confirmed is False.
        project_id=f"proj_blocked_{test_ts}",  # What: Project ID; Why: Target project.
        task_id=f"task_mig_{test_ts}",  # What: Task ID; Why: Migration task.
        customer_name="Cyberdyne Systems",  # What: Customer name; Why: Deal identity.
        records_migrated=8500,  # What: Migrated records; Why: Records imported.
        records_verified=8500,  # What: Verified records; Why: Count matches.
        customer_sign_off_confirmed=False,  # What: Sign-off NOT confirmed; Why: Unverified state.
        sign_off_contact_email="admin@cyberdyne.com"  # What: Contact email; Why: Customer contact.
    )  # What: End of payload construction; Why: Ready.

    result = agent3.evaluate_migration_sign_off(unverified_payload, correlation_id=corr_id)  # What: Evaluate sign-off; Why: Runs Agent 3 gate.

    # Assertions on hard stage-gate lock
    assert result.status == "REJECTED_BLOCKED"  # What: Assert status REJECTED_BLOCKED; Why: Unverified sign-off caught.
    assert result.is_configuration_unlocked is False  # What: Assert Configuration strictly locked; Why: Prevents unverified configuration.
    assert result.csm_alert_sent is True  # What: Assert CSM alert sent; Why: Alerts team to obtain customer sign-off.

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names; Why: Inspects executed events.
    assert "data_qa_verification_blocked_unconfirmed" in actions  # What: Assert block logged; Why: Rejection captured.


def test_e2e_phase4_native_sla_overdue_escalations() -> None:  # What: SLA overdue test; Why: Verifies 1-day and 4-day native rules in E2E scenario.
    """Verifies that Rocketlane Native SLA rules correctly escalate 1-day overdue tasks to PM and 4-day tasks to Owner."""  # What: Docstring; Why: Explains test intent.
    sla_engine = RocketlaneSLAEngine()  # What: Instantiate SLA engine; Why: Evaluates native rules.
    test_ts = int(datetime.now().timestamp())  # What: Timestamp; Why: Unique ID.

    # Test Rule 1: 1 day overdue -> PM notified
    pm_alert = sla_engine.evaluate_task_overdue(  # What: Evaluate 1-day overdue task; Why: Tests Rule 1.
        task_id=f"t1_{test_ts}",  # What: Task ID; Why: Overdue task.
        task_name="Import Customer Contacts",  # What: Task name; Why: Display title.
        project_id=f"p_{test_ts}",  # What: Project ID; Why: Parent project.
        days_overdue=1,  # What: 1 day overdue; Why: Triggers Rule 1.
        is_completed=False,  # What: Open task; Why: In-progress.
        pm_email="pm.sarah@novacrm.com",  # What: PM email; Why: Expected PM.
        owner_email="rd3377@nyu.edu",  # What: Owner email; Why: Expected Owner.
        correlation_id=f"sla_1d_{test_ts}"  # What: Correlation ID; Why: Audit trace link.
    )  # What: End of evaluation; Why: Returns alert.
    assert pm_alert.alert_triggered is True  # What: Assert alert fired; Why: 1-day threshold reached.
    assert pm_alert.target == OverdueEscalationTarget.PROJECT_MANAGER  # What: Assert PM target; Why: Rule 1 routes to PM.
    assert pm_alert.recipient_label == "pm.sarah@novacrm.com"  # What: Assert PM recipient; Why: Correct role notified.

    # Test Rule 2: 4 days overdue -> Owner escalated
    owner_alert = sla_engine.evaluate_task_overdue(  # What: Evaluate 4-day overdue task; Why: Tests Rule 2.
        task_id=f"t2_{test_ts}",  # What: Task ID; Why: Critical task.
        task_name="Configure Custom Fields",  # What: Task name; Why: Display title.
        project_id=f"p_{test_ts}",  # What: Project ID; Why: Parent project.
        days_overdue=4,  # What: 4 days overdue; Why: Triggers Rule 2.
        is_completed=False,  # What: Open task; Why: In-progress.
        pm_email="pm.sarah@novacrm.com",  # What: PM email; Why: PM.
        owner_email="rd3377@nyu.edu",  # What: Owner email; Why: Expected Owner.
        correlation_id=f"sla_4d_{test_ts}"  # What: Correlation ID; Why: Audit trace link.
    )  # What: End of evaluation; Why: Returns alert.
    assert owner_alert.alert_triggered is True  # What: Assert alert fired; Why: 4-day critical threshold reached.
    assert owner_alert.target == OverdueEscalationTarget.PROJECT_OWNER  # What: Assert Owner target; Why: Rule 2 routes to Owner.
    assert owner_alert.recipient_label == "rd3377@nyu.edu"  # What: Assert Owner recipient; Why: Correct executive notified.
