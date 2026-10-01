# Unit test suite verifying Agent 3 Data QA Gatekeeper logic and Rocketlane native overdue SLA rules.  # What: Module header; Why: Verifies Phase 4 components.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps in test payloads.
import pytest  # What: Import pytest; Why: Test assertion and execution framework.
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper  # What: Import Agent 3; Why: Unit under test.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Verifies structured audit entries.
from src.models.schemas import (  # What: Import domain models; Why: Typed models for test scenarios.
    DataMigrationSignOffPayload,  # What: Sign-off payload schema; Why: Input model for testing.
    OverdueEscalationTarget  # What: Escalation target enum; Why: Verifies PM vs Owner routing.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Mock client injection.
from src.services.rocketlane_sla_automations import RocketlaneSLAEngine  # What: Import SLA engine; Why: Tests native platform rules.
from src.services.slack_client import SlackClient  # What: Import SlackClient; Why: Mock Slack injection.


def test_data_qa_happy_path_verified_unlocks_configuration() -> None:  # What: Happy path Data QA test; Why: Verifies phase unlock on verified migration.
    """Verifies that 100% record parity and confirmed customer sign-off unlocks the downstream Configuration phase."""  # What: Docstring; Why: Explains test intent.
    agent = Agent3DataQAGatekeeper(  # What: Instantiate Agent 3 with mock clients; Why: Isolated unit test.
        rocketlane=RocketlaneClient(mock_mode=True),  # What: Mock Rocketlane client; Why: Simulated execution.
        slack=SlackClient(mock_mode=True)  # What: Mock Slack client; Why: Simulated notification.
    )  # What: End of Agent 3 instantiation; Why: Ready for test.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp integer; Why: Unique deal ID.
    corr_id = f"test_qa_happy_{test_ts}"  # What: Unique correlation ID; Why: Connects audit records.

    payload = DataMigrationSignOffPayload(  # What: Valid sign-off payload; Why: Complete and verified migration proof.
        project_id=f"proj_{test_ts}",  # What: Project ID; Why: Target project.
        task_id=f"task_mig_{test_ts}",  # What: Task ID; Why: Data migration task ID.
        customer_name="Acme Enterprise Labs",  # What: Customer name; Why: Customer identity.
        records_migrated=5000,  # What: Migrated records; Why: Record volume.
        records_verified=5000,  # What: Verified records; Why: Exactly matches migrated count.
        customer_sign_off_confirmed=True,  # What: Confirmed flag; Why: Customer verified data.
        sign_off_contact_email="it.director@acmelabs.com",  # What: Contact email; Why: Customer authorizer.
        discrepancy_notes=None  # What: No discrepancies; Why: Clean migration.
    )  # What: End of payload construction; Why: Ready for evaluation.

    result = agent.evaluate_migration_sign_off(payload, correlation_id=corr_id)  # What: Call evaluate_migration_sign_off; Why: Runs gatekeeping logic.

    assert result.status == "VERIFIED_UNLOCKED"  # What: Assert status VERIFIED_UNLOCKED; Why: Criteria fully met.
    assert result.is_configuration_unlocked is True  # What: Assert Configuration phase unlocked; Why: Milestone transition approved.
    assert result.discrepancy_count == 0  # What: Assert zero discrepancy; Why: 100% data parity.
    assert result.csm_alert_sent is False  # What: Assert no alert sent; Why: Successful transition.

    # Verify structured audit trail for this evaluation
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names list; Why: Inspects executed events.
    assert "data_qa_evaluation_started" in actions  # What: Assert start logged; Why: Start captured.
    assert "data_qa_verification_passed_unlocked" in actions  # What: Assert unlock logged; Why: Phase unlock captured.


def test_data_qa_blocks_when_customer_sign_off_missing() -> None:  # What: Negative test for unconfirmed sign-off; Why: Enforces hard stage-gate.
    """Verifies that missing customer verification sign-off strictly blocks the Configuration phase and alerts the CSM."""  # What: Docstring; Why: Explains test intent.
    agent = Agent3DataQAGatekeeper(  # What: Instantiate Agent 3; Why: Isolated unit test.
        rocketlane=RocketlaneClient(mock_mode=True),  # What: Mock client; Why: Simulated execution.
        slack=SlackClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    )  # What: End of instantiation; Why: Ready.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.
    corr_id = f"test_qa_no_signoff_{test_ts}"  # What: Unique correlation ID; Why: Connects audit records.

    # CSM attempts to mark Data Migration complete, but customer hasn't verified
    payload = DataMigrationSignOffPayload(  # What: Unverified sign-off payload; Why: customer_sign_off_confirmed is False.
        project_id=f"proj_{test_ts}",  # What: Project ID; Why: Target project.
        task_id=f"task_mig_{test_ts}",  # What: Task ID; Why: Data migration task ID.
        customer_name="Beta Startups Inc",  # What: Customer name; Why: Deal identity.
        records_migrated=1200,  # What: Migrated records; Why: Volume imported.
        records_verified=1200,  # What: Verified records; Why: Matches count.
        customer_sign_off_confirmed=False,  # What: Sign-off NOT confirmed; Why: Simulates Priya's core pain point.
        sign_off_contact_email="lead@betastartups.com"  # What: Contact email; Why: Customer contact.
    )  # What: End of payload construction; Why: Ready.

    result = agent.evaluate_migration_sign_off(payload, correlation_id=corr_id)  # What: Call evaluate_migration_sign_off; Why: Evaluates gate.

    assert result.status == "REJECTED_BLOCKED"  # What: Assert status REJECTED_BLOCKED; Why: Missing customer confirmation.
    assert result.is_configuration_unlocked is False  # What: Assert Configuration strictly locked; Why: Stage-gate blocks downstream work.
    assert result.csm_alert_sent is True  # What: Assert CSM alert sent; Why: Alerts CSM lead to obtain customer verification.

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names; Why: Inspects executed events.
    assert "data_qa_verification_blocked_unconfirmed" in actions  # What: Assert block logged; Why: Rejection captured.


def test_data_qa_escalates_on_record_count_discrepancy() -> None:  # What: Discrepancy escalation test; Why: Detects data loss during import.
    """Verifies that record count discrepancies (e.g. 5,000 migrated vs 4,800 verified) auto-escalate to CS Ops and lock the phase."""  # What: Docstring; Why: Explains test intent.
    agent = Agent3DataQAGatekeeper(  # What: Instantiate Agent 3; Why: Isolated unit test.
        rocketlane=RocketlaneClient(mock_mode=True),  # What: Mock client; Why: Simulated execution.
        slack=SlackClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    )  # What: End of instantiation; Why: Ready.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.
    corr_id = f"test_qa_discrepancy_{test_ts}"  # What: Correlation ID; Why: Connects audit records.

    # 5,000 migrated but only 4,800 verified (200 records lost/dropped)
    payload = DataMigrationSignOffPayload(  # What: Discrepancy payload; Why: Records mismatch.
        project_id=f"proj_{test_ts}",  # What: Project ID; Why: Target project.
        task_id=f"task_mig_{test_ts}",  # What: Task ID; Why: Data migration task ID.
        customer_name="Delta Financial",  # What: Customer name; Why: Deal identity.
        records_migrated=5000,  # What: 5,000 migrated; Why: Source record count.
        records_verified=4800,  # What: 4,800 verified; Why: 200 records missing.
        customer_sign_off_confirmed=True,  # What: Sign-off true; Why: Even with sign-off, mismatch must be blocked.
        sign_off_contact_email="ops@deltafin.com",  # What: Contact email; Why: Customer contact.
        discrepancy_notes="200 lead records failed custom validation."  # What: Discrepancy notes; Why: Error details.
    )  # What: End of payload construction; Why: Ready.

    result = agent.evaluate_migration_sign_off(payload, correlation_id=corr_id)  # What: Call evaluate_migration_sign_off; Why: Evaluates gate.

    assert result.status == "ESCALATED_DISCREPANCY"  # What: Assert status ESCALATED_DISCREPANCY; Why: Discrepancy caught.
    assert result.is_configuration_unlocked is False  # What: Assert Configuration strictly locked; Why: Prevents configuring with corrupted data.
    assert result.discrepancy_count == 200  # What: Assert 200 mismatched records; Why: Accurate difference calculation.
    assert result.csm_alert_sent is True  # What: Assert alert sent; Why: Alerts CS Ops to resolve data parity.

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names; Why: Inspects executed events.
    assert "data_qa_verification_escalated_discrepancy" in actions  # What: Assert discrepancy logged; Why: Escalation captured.


def test_data_qa_blocks_on_zero_records_migrated() -> None:  # What: Zero-volume check test; Why: Prevents empty migrations.
    """Verifies that an attempt to sign off with zero migrated records is immediately halted."""  # What: Docstring; Why: Explains test intent.
    agent = Agent3DataQAGatekeeper(  # What: Instantiate Agent 3; Why: Isolated unit test.
        rocketlane=RocketlaneClient(mock_mode=True),  # What: Mock client; Why: Simulated execution.
        slack=SlackClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    )  # What: End of instantiation; Why: Ready.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.
    payload = DataMigrationSignOffPayload(  # What: Zero-record payload; Why: Non-positive record count.
        project_id=f"proj_{test_ts}",  # What: Project ID; Why: Target project.
        task_id=f"task_mig_{test_ts}",  # What: Task ID; Why: Migration task.
        customer_name="Zero Corp",  # What: Customer name; Why: Deal identity.
        records_migrated=0,  # What: Zero records; Why: Invalid volume.
        records_verified=0,  # What: Zero verified; Why: Invalid volume.
        customer_sign_off_confirmed=True,  # What: Sign-off true; Why: Even with sign-off, zero records must fail.
        sign_off_contact_email="lead@zerocorp.com"  # What: Contact email; Why: Customer contact.
    )  # What: End of payload construction; Why: Ready.

    result = agent.evaluate_migration_sign_off(payload, correlation_id=f"test_qa_zero_{test_ts}")  # What: Call evaluate_migration_sign_off; Why: Evaluates gate.

    assert result.status == "REJECTED_BLOCKED"  # What: Assert status REJECTED_BLOCKED; Why: Zero records cannot be approved.
    assert result.is_configuration_unlocked is False  # What: Assert Configuration locked; Why: Prevents unlock.


def test_rocketlane_native_sla_1_day_overdue_notifies_pm() -> None:  # What: SLA Rule 1 test; Why: Verifies 1-day overdue routes to Project Manager.
    """Verifies that Rocketlane Native SLA Rule 1 notifies the Project Manager when a task is overdue by 1 day."""  # What: Docstring; Why: Explains test intent.
    engine = RocketlaneSLAEngine()  # What: Instantiate Rocketlane SLA engine; Why: Evaluates native platform rules.
    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.
    corr_id = f"test_sla_1day_{test_ts}"  # What: Unique correlation ID; Why: Connects audit records.

    alert = engine.evaluate_task_overdue(  # What: Call evaluate_task_overdue; Why: Evaluates task SLA state.
        task_id=f"task_1day_{test_ts}",  # What: Task ID; Why: Overdue task.
        task_name="Kickoff Call & Scope Alignment",  # What: Task name; Why: Display title.
        project_id=f"proj_{test_ts}",  # What: Project ID; Why: Parent project.
        days_overdue=1,  # What: 1 day overdue; Why: Triggers Rule 1.
        is_completed=False,  # What: Task open; Why: In-progress task.
        pm_email="sarah.connor@novacrm.com",  # What: PM email; Why: Expected recipient.
        owner_email="rd3377@nyu.edu",  # What: Owner email; Why: Executive contact.
        correlation_id=corr_id  # What: Correlation ID; Why: Audit trace link.
    )  # What: End of evaluation call; Why: Returns alert model.

    assert alert.alert_triggered is True  # What: Assert alert fired; Why: 1-day threshold reached.
    assert alert.target == OverdueEscalationTarget.PROJECT_MANAGER  # What: Assert PM target; Why: Rule 1 routes to Project Manager.
    assert alert.recipient_label == "sarah.connor@novacrm.com"  # What: Assert PM recipient; Why: Correct role notified.
    assert "1 day(s) overdue" in alert.alert_message  # What: Assert message text; Why: Clear SLA warning.

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names; Why: Inspects executed events.
    assert "sla_overdue_pm_notified" in actions  # What: Assert PM alert logged; Why: 1-day event captured.


def test_rocketlane_native_sla_4_days_overdue_notifies_owner() -> None:  # What: SLA Rule 2 test; Why: Verifies 4-day overdue escalates to Project Owner.
    """Verifies that Rocketlane Native SLA Rule 2 escalates to the Project Owner when a task is overdue by 4 days."""  # What: Docstring; Why: Explains test intent.
    engine = RocketlaneSLAEngine()  # What: Instantiate Rocketlane SLA engine; Why: Evaluates native platform rules.
    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.
    corr_id = f"test_sla_4day_{test_ts}"  # What: Unique correlation ID; Why: Connects audit records.

    alert = engine.evaluate_task_overdue(  # What: Call evaluate_task_overdue; Why: Evaluates task SLA state.
        task_id=f"task_4day_{test_ts}",  # What: Task ID; Why: Critical overdue task.
        task_name="Data Migration Parity Check",  # What: Task name; Why: Display title.
        project_id=f"proj_{test_ts}",  # What: Project ID; Why: Parent project.
        days_overdue=4,  # What: 4 days overdue; Why: Triggers Rule 2.
        is_completed=False,  # What: Task open; Why: In-progress task.
        pm_email="sarah.connor@novacrm.com",  # What: PM email; Why: Project manager.
        owner_email="rd3377@nyu.edu",  # What: Owner email; Why: Expected recipient.
        correlation_id=corr_id  # What: Correlation ID; Why: Audit trace link.
    )  # What: End of evaluation call; Why: Returns alert model.

    assert alert.alert_triggered is True  # What: Assert alert fired; Why: 4-day critical threshold reached.
    assert alert.target == OverdueEscalationTarget.PROJECT_OWNER  # What: Assert Owner target; Why: Rule 2 routes to Project Owner.
    assert alert.recipient_label == "rd3377@nyu.edu"  # What: Assert Owner recipient; Why: Correct executive notified.
    assert "4 days overdue" in alert.alert_message  # What: Assert message text; Why: Critical alert text.

    # Verify audit trail
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names; Why: Inspects executed events.
    assert "sla_overdue_owner_escalated" in actions  # What: Assert Owner alert logged; Why: 4-day critical event captured.


def test_rocketlane_native_sla_not_overdue_no_alert() -> None:  # What: On-time task test; Why: Verifies tasks within SLA window do not alert.
    """Verifies that on-schedule tasks (days_overdue == 0) do not trigger any SLA alerts."""  # What: Docstring; Why: Explains test intent.
    engine = RocketlaneSLAEngine()  # What: Instantiate SLA engine; Why: Evaluates native platform rules.
    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.

    alert = engine.evaluate_task_overdue(  # What: Call evaluate_task_overdue; Why: Evaluates on-time task.
        task_id=f"task_ontime_{test_ts}",  # What: Task ID; Why: Task on schedule.
        task_name="System Configuration",  # What: Task name; Why: Display title.
        project_id=f"proj_{test_ts}",  # What: Project ID; Why: Parent project.
        days_overdue=0,  # What: 0 days overdue; Why: On schedule.
        is_completed=False  # What: Open task; Why: In-progress.
    )  # What: End of evaluation call; Why: Returns alert model.

    assert alert.alert_triggered is False  # What: Assert no alert triggered; Why: Task is on schedule.
    assert alert.target is None  # What: Assert target is None; Why: No recipient.


def test_rocketlane_native_sla_completed_task_no_alert() -> None:  # What: Completed task test; Why: Verifies completed tasks never alert regardless of due date.
    """Verifies that completed tasks do not trigger SLA alerts even if original due date has passed."""  # What: Docstring; Why: Explains test intent.
    engine = RocketlaneSLAEngine()  # What: Instantiate SLA engine; Why: Evaluates native platform rules.
    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.

    alert = engine.evaluate_task_overdue(  # What: Call evaluate_task_overdue; Why: Evaluates closed task.
        task_id=f"task_done_{test_ts}",  # What: Task ID; Why: Finished task.
        task_name="Kickoff Call",  # What: Task name; Why: Display title.
        project_id=f"proj_{test_ts}",  # What: Project ID; Why: Parent project.
        days_overdue=5,  # What: 5 days past due date; Why: Date passed.
        is_completed=True  # What: is_completed is True; Why: Finished task.
    )  # What: End of evaluation call; Why: Returns alert model.

    assert alert.alert_triggered is False  # What: Assert no alert triggered; Why: Closed tasks satisfy SLA.
    assert alert.target is None  # What: Assert target is None; Why: No recipient.


def test_rocketlane_native_sla_export_platform_rules() -> None:  # What: Platform rule export test; Why: Verifies declarative platform configuration.
    """Verifies that export_platform_rules returns the 2 codified native automation specifications."""  # What: Docstring; Why: Explains test intent.
    engine = RocketlaneSLAEngine()  # What: Instantiate SLA engine; Why: Accesses platform rule specs.
    rules = engine.export_platform_rules()  # What: Export rules list; Why: Inspects declarative specs.

    assert len(rules) == 2  # What: Assert exactly 2 rules; Why: 1-day and 4-day rules.
    rule_ids = [r["rule_id"] for r in rules]  # What: Extract rule IDs; Why: Inspects rule identifiers.
    assert "rule_sla_1day_pm" in rule_ids  # What: Assert Rule 1 ID; Why: PM warning rule present.
    assert "rule_sla_4day_owner" in rule_ids  # What: Assert Rule 2 ID; Why: Owner escalation rule present.


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

