# End-to-end integration test validating Phase 2 Agent 1 lifecycle against live integrations and guardrails.  # What: Module header; Why: Verifies Phase 2 end-to-end.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps in test fixtures.
import json  # What: Import json library; Why: Reads and inspects structured audit log records.
from typing import Any  # What: Import Any; Why: Type annotations for payload dictionaries.
import pytest  # What: Import pytest; Why: Test assertions and test suite execution.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent1Intake; Why: Tests complete Agent 1 orchestrator.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Verifies audit log trail.
from src.core.config import settings  # What: Import application settings; Why: Reads live configuration and keys.
from src.models.schemas import (  # What: Import domain models; Why: Typed models for test scenarios.
    PlanTier,  # What: Plan tier enum; Why: Enterprise and Growth tiers.
    VoiceCallResult,  # What: Voice call result model; Why: Telephony results.
    VoiceCallStatus  # What: Voice call status enum; Why: Telephony statuses.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Live Rocketlane client.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Telephony client.


def test_e2e_agent1_happy_path_enterprise_live_provisioning() -> None:  # What: Live Enterprise E2E test; Why: Verifies complete flow with live Rocketlane project creation.
    """Tests end-to-end Enterprise deal intake: email validation, verbal confirmation, and live Rocketlane project creation."""  # What: Docstring; Why: Documents test intent.
    agent = Agent1Intake()  # What: Instantiate fresh Agent1Intake; Why: Clean agent instance.
    agent.rocketlane = RocketlaneClient(mock_mode=False)  # What: Use live Rocketlane client; Why: Verifies live project creation.
    agent.voice_client = VoiceAIClient(mock_mode=True)  # What: Use controlled voice simulation; Why: Deterministic verbal confirmation test.

    test_ts = int(datetime.now().timestamp())  # What: Capture current timestamp integer; Why: Generates unique test identifiers.
    corr_id = f"e2e_agent1_ent_{test_ts}"  # What: Unique correlation ID; Why: Tracks deal in audit logs.

    # 1. Simulate AE verbally confirming Enterprise tier with high confidence
    agent.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Injects unambiguous verbal confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Enterprise result.
            call_id=f"call_ent_{test_ts}",  # What: Call ID; Why: Telephony session ID.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Hello, yes! Acme Enterprise is on the Enterprise tier with 30-day onboarding.",  # What: Verbal confirmation transcript; Why: Proof.
            confidence_score=0.98  # What: High confidence; Why: Passes voice guardrail.
        )  # What: End of VoiceCallResult instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email: dict[str, Any] = {  # What: Inbound raw email dictionary; Why: Healthy AE notification email.
        "message_id": f"msg_ent_{test_ts}",  # What: Message ID; Why: Unique email identifier.
        "customer_name": f"Acme Global Labs {test_ts}",  # What: Dynamic customer name; Why: Avoids namespace collisions in Rocketlane.
        "customer_contact_email": f"it_{test_ts}@acmeglobal.com",  # What: Unique customer contact email; Why: Primary collaborator.
        "ae_name": "Jordan Bell",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0199",  # What: AE phone; Why: Destination number for Voice AI call.
        "opportunity_url": "https://novacrm.salesforce.com/opp/001"  # What: SFDC link; Why: Context link.
    }  # What: End of raw email dictionary; Why: Valid payload.

    # 2. Execute complete Agent 1 lifecycle
    result = agent.process_deal(raw_email, correlation_id=corr_id)  # What: Execute process_deal; Why: Runs end-to-end Agent 1 pipeline.

    # 3. Assertions on successful outcome
    assert result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Verifies pipeline completed normally.
    assert result.rocketlane_project is not None  # What: Assert project exists; Why: Live project created in Rocketlane.
    assert result.rocketlane_project.tier == PlanTier.ENTERPRISE  # What: Assert Enterprise tier; Why: Enterprise template applied.
    assert result.rocketlane_project.project_id is not None  # What: Assert project ID; Why: Rocketlane assigned project ID.
    assert "https://app.rocketlane.com/projects/" in result.rocketlane_project.portal_url  # What: Assert portal URL; Why: Valid Rocketlane workspace link.

    # 4. Verify structured audit trail for this deal
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names; Why: Checks that all lifecycle steps were audited.
    assert "process_deal_started" in actions  # What: Assert start logged; Why: Initial event captured.
    assert "schema_validation_passed" in actions  # What: Assert schema passed logged; Why: Validation captured.
    assert "voice_guardrail_passed" in actions  # What: Assert voice passed logged; Why: Telephony evaluation captured.
    assert "create_project_success" in actions  # What: Assert project created logged; Why: Rocketlane API call captured.
    assert "agent1_workflow_completed" in actions  # What: Assert completion logged; Why: Full lifecycle audited.


def test_e2e_agent1_missing_fields_clarification_halt() -> None:  # What: Validation halt E2E test; Why: Verifies zero-assumption policy.
    """Guarantees that an email missing mandatory fields halts pipeline, generates clarification draft, and avoids live API calls."""  # What: Docstring; Why: Documents test intent.
    agent = Agent1Intake()  # What: Instantiate fresh Agent1Intake; Why: Clean agent instance.
    agent.rocketlane = RocketlaneClient(mock_mode=False)  # What: Live Rocketlane client; Why: Ensures no live calls are made on failure.
    agent.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock voice client; Why: Ensures no voice call is made.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique test run.
    corr_id = f"e2e_agent1_halt_{test_ts}"  # What: Unique correlation ID; Why: Audit trace.

    # Incomplete email missing AE phone and customer contact email
    incomplete_email: dict[str, Any] = {  # What: Incomplete raw email dictionary; Why: Missing mandatory fields.
        "message_id": f"msg_halt_{test_ts}",  # What: Message ID; Why: Present.
        "customer_name": "Initech Corporation",  # What: Customer name; Why: Present.
        "customer_contact_email": "",  # What: Blank contact email; Why: Must fail deterministic validator.
        "ae_name": "Peter Gibbons",  # What: AE name; Why: Present.
        "ae_phone": "   "  # What: Whitespace phone; Why: Must fail deterministic validator.
    }  # What: End of incomplete dictionary; Why: Invalid payload.

    result = agent.process_deal(incomplete_email, correlation_id=corr_id)  # What: Execute process_deal; Why: Tests validation guardrail.

    assert result.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED_MISSING_DATA; Why: Pipeline stopped.
    assert result.clarification_draft is not None  # What: Assert clarification draft created; Why: Human-in-the-loop email generated.
    assert "customer_contact_email" in result.clarification_draft.missing_fields  # What: Assert missing email flagged; Why: Correct field identified.
    assert "ae_phone" in result.clarification_draft.missing_fields  # What: Assert missing phone flagged; Why: Correct field identified.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Zero-assumption guardrail upheld.
    assert result.voice_result is None  # What: Assert no voice call made; Why: Did not dial phone on invalid data.


def test_e2e_agent1_ambiguous_voice_escalation_guardrail() -> None:  # What: Ambiguity escalation E2E test; Why: Verifies voice guardrail prevents assuming tier.
    """Guarantees that an ambiguous AE verbal response triggers human escalation and halts Rocketlane project creation."""  # What: Docstring; Why: Documents test intent.
    agent = Agent1Intake()  # What: Instantiate fresh Agent1Intake; Why: Clean agent instance.
    agent.rocketlane = RocketlaneClient(mock_mode=False)  # What: Live Rocketlane client; Why: Ensures no project created.
    agent.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock voice client; Why: Injects ambiguous response.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique identifier.
    corr_id = f"e2e_agent1_amb_{test_ts}"  # What: Correlation ID; Why: Audit trace.

    # Configure ambiguous voice outcome
    agent.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Simulates uncertain AE response.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Low-confidence ambiguous outcome.
            call_id=f"call_amb_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.AMBIGUOUS,  # What: Status AMBIGUOUS; Why: Uncertain response.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN; Why: No tier confirmed.
            transcript="I'm not completely sure, maybe Enterprise? Let me double-check the Salesforce contract.",  # What: Transcript; Why: Clear ambiguity hedge.
            confidence_score=0.45,  # What: Low confidence; Why: Below 0.8 threshold.
            escalation_reason="AE response was non-committal and contained uncertainty phrase 'not sure'."  # What: Reason; Why: Detailed rationale.
        )  # What: End of VoiceCallResult instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email: dict[str, Any] = {  # What: Valid raw email dictionary; Why: Healthy email so validation passes.
        "message_id": f"msg_amb_{test_ts}",  # What: Message ID; Why: Email ID.
        "customer_name": f"Hooli Ambiguity Test {test_ts}",  # What: Customer name; Why: Test company.
        "customer_contact_email": f"gavin_{test_ts}@hooli.com",  # What: Contact email; Why: Primary collaborator.
        "ae_name": "Gavin Belson",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0899"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Valid payload.

    result = agent.process_deal(raw_email, correlation_id=corr_id)  # What: Execute process_deal; Why: Evaluates voice guardrail.

    assert result.status == "ESCALATED_VOICE_ISSUE"  # What: Assert status ESCALATED_VOICE_ISSUE; Why: Pipeline halted for human review.
    assert result.escalation_ticket is not None  # What: Assert ticket created; Why: Escalation ticket generated for CS team.
    assert result.escalation_ticket.call_status == VoiceCallStatus.AMBIGUOUS  # What: Assert call status AMBIGUOUS; Why: Categorized accurately.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: System never guesses a tier on ambiguity.


def test_e2e_agent1_idempotency_prevents_duplicate_calls_and_projects() -> None:  # What: Idempotency E2E test; Why: Verifies duplicate deal prevention.
    """Guarantees that resending the same deal returns existing project without re-dialing the AE or re-creating the Rocketlane project."""  # What: Docstring; Why: Documents test intent.
    agent = Agent1Intake()  # What: Instantiate fresh Agent1Intake; Why: Clean agent instance.
    agent.rocketlane = RocketlaneClient(mock_mode=False)  # What: Live Rocketlane client; Why: Tests live idempotency cache.
    agent.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock voice client; Why: Telephony simulation.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique identifier.

    # 1. Configure initial confirmed Growth tier call
    agent.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: First run confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Confirmed Growth result.
            call_id=f"call_grw_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.GROWTH,  # What: Growth tier; Why: Selected plan.
            transcript="Growth plan confirmed for 14 days.",  # What: Transcript; Why: Verbal proof.
            confidence_score=0.96  # What: High confidence; Why: Passes guardrail.
        )  # What: End of VoiceCallResult instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email: dict[str, Any] = {  # What: Raw deal email dictionary; Why: Deal payload to duplicate.
        "message_id": f"msg_idemp_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": f"Dunder Mifflin {test_ts}",  # What: Customer name; Why: Company title.
        "customer_contact_email": f"jim_{test_ts}@dundermifflin.com",  # What: Contact email; Why: Collaborator email.
        "ae_name": "Jim Halpert",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0777"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Valid payload.

    # 2. First Run: Provisions new live project
    first_result = agent.process_deal(raw_email, correlation_id=f"e2e_idemp_run1_{test_ts}")  # What: First run; Why: Creates project.
    assert first_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Initial run succeeded.
    assert first_result.rocketlane_project is not None  # What: Assert project exists; Why: Live project created.
    first_project_id = first_result.rocketlane_project.project_id  # What: Store initial project ID; Why: For comparison.

    # 3. Alter voice client simulation to failure: If second run tries to dial AE, it would fail
    agent.voice_client.set_simulation_outcome(  # What: Set failing simulation outcome; Why: Proves telephony is skipped.
        VoiceCallResult(  # What: Dummy failing result; Why: Should never be invoked.
            call_id="call_should_not_run",  # What: Call ID; Why: Identifies failure.
            status=VoiceCallStatus.FAILED,  # What: Status FAILED; Why: Failure state.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Unknown tier; Why: Guardrail trigger.
            transcript="Error",  # What: Error text; Why: Context.
            confidence_score=0.0  # What: Zero confidence; Why: Failure.
        )  # What: End of failing result; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Overwritten.

    # 4. Second Run: Submits duplicate email payload
    second_result = agent.process_deal(raw_email, correlation_id=f"e2e_idemp_run2_{test_ts}")  # What: Second run; Why: Simulates duplicate deal email.

    # 5. Assertions: Second run caught by idempotency without re-dialing AE or creating project
    assert second_result.status == "IDEMPOTENT_DUPLICATE"  # What: Assert status IDEMPOTENT_DUPLICATE; Why: Deduplication guardrail succeeded.
    assert second_result.rocketlane_project is not None  # What: Assert project returned; Why: Returns existing project reference.
    assert second_result.rocketlane_project.project_id == first_project_id  # What: Assert matching project ID; Why: Guaranteed identical project.
