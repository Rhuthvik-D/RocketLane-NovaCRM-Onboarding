# Official Part 4 Automated Test Suite verifying Happy Path, Validation, Template Accuracy, and Edge Cases.  # What: Module header; Why: Fulfills Part 4 deliverable of Rocketlane take-home assignment.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps in test payloads.
from typing import Any  # What: Import Any; Why: Type annotations for payload dictionaries.
import pytest  # What: Import pytest; Why: Test assertion and execution framework.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent 1; Why: Runs deal intake and routing.
from src.agents.agent2_communication import Agent2Communication  # What: Import Agent 2; Why: Runs customer communication and Slack setup.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Verifies immutable audit trail across all tests.
from src.core.exceptions import RocketlaneAPIError  # What: Import RocketlaneAPIError; Why: Asserts upstream 500 error handling.
from src.models.schemas import (  # What: Import domain models; Why: Typed models for test scenarios.
    PlanTier,  # What: Plan tier enum; Why: Enterprise and Growth plan tiers.
    VoiceCallResult,  # What: Voice call result model; Why: Simulates telephony outcomes.
    VoiceCallStatus  # What: Voice call status enum; Why: CONFIRMED, AMBIGUOUS, UNANSWERED, FAILED.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Configures mock and retry behaviors.
from src.services.slack_client import SlackClient  # What: Import SlackClient; Why: Configures mock Slack client.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Configures mock voice AI client.


# ==============================================================================
# 1. HAPPY PATH TEST: Complete Enterprise Onboarding Flow
# ==============================================================================

def test_happy_path_enterprise() -> None:  # What: Happy path test; Why: Verifies email -> voice confirmation -> Rocketlane project -> Slack channel.
    """A new Enterprise deal email arrives, Intake Agent parses it, voice call confirms tier, project created, and Slack channel provisioned."""  # What: Docstring; Why: Matches Part 4 requirement 1.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Clean intake orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock Rocketlane client; Why: Fast deterministic execution.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI client; Why: Injects verbal confirmation.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Fresh Agent 2 with mock Slack; Why: Clean communication orchestrator.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique deal identifier.
    corr_id = f"part4_happy_ent_{test_ts}"  # What: Unique correlation ID; Why: Connects entire deal flow.

    # 1. Voice AI simulates AE verbally confirming Enterprise tier
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Unambiguous Enterprise confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Enterprise result.
            call_id=f"call_ent_{test_ts}",  # What: Call ID; Why: Telephony session ID.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Yes, confirming Stark Industries signed our Enterprise plan with 30-day onboarding.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.99  # What: High confidence; Why: Passes voice guardrail.
        )  # What: End of VoiceCallResult; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # 2. Inbound AE deal email arrives
    inbound_email: dict[str, Any] = {  # What: Inbound raw email dictionary; Why: Healthy AE deal notification email.
        "message_id": f"msg_ent_{test_ts}",  # What: Message ID; Why: Unique email identifier.
        "customer_name": f"Stark Industries {test_ts}",  # What: Customer name; Why: Name to sanitize for project and Slack.
        "customer_contact_email": f"pepper_{test_ts}@starkindustries.com",  # What: Contact email; Why: Primary collaborator.
        "ae_name": "Tony Stark",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0199",  # What: AE phone; Why: Destination number for Voice AI call.
        "opportunity_url": "https://novacrm.salesforce.com/opp/001"  # What: SFDC link; Why: Context link.
    }  # What: End of inbound email dictionary; Why: Valid payload.

    # 3. Agent 1 processes deal: Validation -> Voice Call -> Rocketlane Project
    a1_result = agent1.process_deal(inbound_email, correlation_id=corr_id)  # What: Run Agent 1; Why: Ingestion and project creation.
    assert a1_result.status == "SUCCESS"  # What: Assert Agent 1 status; Why: Agent 1 must succeed.
    assert a1_result.rocketlane_project is not None  # What: Assert project exists; Why: Rocketlane project provisioned.
    assert a1_result.rocketlane_project.tier == PlanTier.ENTERPRISE  # What: Assert Enterprise tier; Why: Correct template applied.
    assert a1_result.rocketlane_project.template_id == "5000000095997"  # What: Assert template ID; Why: Matches configured onboarding template.

    # 4. Agent 2 processes project handoff: Slack Channel -> Topic -> Welcome Message
    a2_result = agent2.process_project_handoff(a1_result)  # What: Run Agent 2; Why: Slack channel provisioning and messaging.
    assert a2_result.status == "SUCCESS"  # What: Assert Agent 2 status; Why: Agent 2 must succeed.
    assert a2_result.provisioning_result is not None  # What: Assert Slack result exists; Why: Channel was created.
    assert a2_result.provisioning_result.channel_name.startswith("csm-ent-stark-industries")  # What: Assert channel prefix; Why: Enterprise naming convention.
    assert a2_result.provisioning_result.topic_set is True  # What: Assert topic set; Why: Rocketlane link embedded.
    assert a2_result.provisioning_result.welcome_message_ts is not None  # What: Assert message ts; Why: Welcome message delivered.

    # 5. Verify continuous audit trail across both agents
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies logging compliance.
    actions = [e.action for e in entries]  # What: Extract action names list; Why: Inspects executed lifecycle events.
    assert "process_deal_started" in actions  # What: Assert deal start; Why: Agent 1 initiated.
    assert "schema_validation_passed" in actions  # What: Assert validation; Why: Deterministic schema passed.
    assert "voice_guardrail_passed" in actions  # What: Assert voice guardrail; Why: Telephony confirmed.
    assert "agent1_workflow_completed" in actions  # What: Assert Agent 1 done; Why: Rocketlane project provisioned.
    assert "process_handoff_started" in actions  # What: Assert handoff start; Why: Agent 2 initiated.
    assert "slack_channel_creation_started" in actions  # What: Assert channel creation; Why: Channel creation initiated.
    assert "slack_topic_set" in actions  # What: Assert topic set; Why: Rocketlane workspace URL embedded.
    assert "slack_welcome_message_posted" in actions  # What: Assert message posted; Why: Kickoff message posted.
    assert "agent2_workflow_completed" in actions  # What: Assert Agent 2 done; Why: Communication completed.


# ==============================================================================
# 2. VALIDATION TEST: Rejection of Incomplete or Malformed Emails
# ==============================================================================

def test_validation_incomplete_email() -> None:  # What: Validation test; Why: Verifies incomplete or malformed emails are rejected without guessing.
    """Intake Agent correctly rejects incomplete or malformed emails (missing customer name, no contact email, etc.)."""  # What: Docstring; Why: Matches Part 4 requirement 2.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Clean instance.
    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.

    # Case 2A: Missing customer_name
    missing_name_email = {  # What: Missing customer name dictionary; Why: Tests customer_name guardrail.
        "message_id": f"msg_noname_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_contact_email": "ceo@unknown.com",  # What: Contact email; Why: Provided.
        "ae_name": "Jordan Bell",  # What: AE name; Why: Provided.
        "ae_phone": "+1-555-0100"  # What: AE phone; Why: Provided.
    }  # What: End of missing name dictionary; Why: customer_name omitted.
    res_a = agent1.process_deal(missing_name_email, correlation_id=f"val_noname_{test_ts}")  # What: Run process_deal; Why: Executes validation.
    assert res_a.status == "HALTED_MISSING_DATA"  # What: Assert halted status; Why: Missing field halts execution.
    assert res_a.clarification_draft is not None  # What: Assert clarification drafted; Why: Generates email to AE.
    assert "customer_name" in res_a.clarification_draft.missing_fields  # What: Assert missing field enumerated; Why: Explicit list of omitted fields.
    assert res_a.rocketlane_project is None  # What: Assert no project created; Why: Zero guessing.

    # Case 2B: Missing customer_contact_email
    missing_email_email = {  # What: Missing contact email dictionary; Why: Tests customer_contact_email guardrail.
        "message_id": f"msg_noemail_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": "Wayne Enterprises",  # What: Customer name; Why: Provided.
        "ae_name": "Jordan Bell",  # What: AE name; Why: Provided.
        "ae_phone": "+1-555-0100"  # What: AE phone; Why: Provided.
    }  # What: End of missing email dictionary; Why: customer_contact_email omitted.
    res_b = agent1.process_deal(missing_email_email, correlation_id=f"val_noemail_{test_ts}")  # What: Run process_deal; Why: Executes validation.
    assert res_b.status == "HALTED_MISSING_DATA"  # What: Assert halted status; Why: Missing field halts execution.
    assert res_b.clarification_draft is not None  # What: Assert clarification drafted; Why: Generates email to AE.
    assert "customer_contact_email" in res_b.clarification_draft.missing_fields  # What: Assert field listed; Why: Explicit list of omitted fields.
    assert res_b.rocketlane_project is None  # What: Assert no project created; Why: Zero guessing.

    # Case 2C: Malformed customer email address (invalid syntax)
    malformed_email = {  # What: Malformed email syntax dictionary; Why: Tests RFC email validation.
        "message_id": f"msg_bademail_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": "Wayne Enterprises",  # What: Customer name; Why: Provided.
        "customer_contact_email": "not-an-email-address",  # What: Malformed email; Why: Fails RFC format validation.
        "ae_name": "Jordan Bell",  # What: AE name; Why: Provided.
        "ae_phone": "+1-555-0100"  # What: AE phone; Why: Provided.
    }  # What: End of malformed email dictionary; Why: Bad email syntax.
    res_c = agent1.process_deal(malformed_email, correlation_id=f"val_bademail_{test_ts}")  # What: Run process_deal; Why: Executes validation.
    assert res_c.status == "HALTED_MISSING_DATA"  # What: Assert halted status; Why: Malformed field halts execution.
    assert res_c.clarification_draft is not None  # What: Assert clarification drafted; Why: Generates email to AE.
    assert res_c.rocketlane_project is None  # What: Assert no project created; Why: Zero guessing.

    # Case 2D: Whitespace-only string fields
    blank_name_email = {  # What: Blank whitespace string dictionary; Why: Tests rejection of empty whitespace.
        "message_id": f"msg_blank_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": "   ",  # What: Whitespace-only string; Why: Fails non-empty validator.
        "customer_contact_email": "ceo@valid.com",  # What: Valid email; Why: Provided.
        "ae_name": "Jordan Bell",  # What: AE name; Why: Provided.
        "ae_phone": "+1-555-0100"  # What: AE phone; Why: Provided.
    }  # What: End of blank name dictionary; Why: Whitespace customer name.
    res_d = agent1.process_deal(blank_name_email, correlation_id=f"val_blank_{test_ts}")  # What: Run process_deal; Why: Executes validation.
    assert res_d.status == "HALTED_MISSING_DATA"  # What: Assert halted status; Why: Whitespace field halts execution.
    assert res_d.rocketlane_project is None  # What: Assert no project created; Why: Zero guessing.


# ==============================================================================
# 3. TEMPLATE ACCURACY TEST: Enterprise vs Growth Tier Mapping
# ==============================================================================

def test_template_accuracy() -> None:  # What: Template accuracy test; Why: Verifies Enterprise (30d + dedicated CSM) vs Growth (14d + pooled CSM).
    """When AE confirms Enterprise, creates 30d template + dedicated CSM; when AE confirms Growth, creates 14d template + pooled CSM."""  # What: Docstring; Why: Matches Part 4 requirement 3.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Clean instance.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Fresh Agent 2; Why: Clean instance.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.

    # -------------------------------------------------------------------------
    # Scenario 3A: AE Confirms Enterprise Tier
    # -------------------------------------------------------------------------
    agent1.voice_client.set_simulation_outcome(  # What: Set Enterprise outcome; Why: Injects Enterprise confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Enterprise result.
            call_id=f"call_ent_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Enterprise tier confirmed for 30 days.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.98  # What: High confidence; Why: Verified.
        )  # What: End of VoiceCallResult; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    ent_email = {  # What: Inbound raw email dictionary; Why: Enterprise deal.
        "message_id": f"msg_ent_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": f"Enterprise Client {test_ts}",  # What: Customer name; Why: Name to sanitize.
        "customer_contact_email": f"lead_{test_ts}@entclient.com",  # What: Contact email; Why: Collaborator email.
        "ae_name": "Gordon Gekko",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0200"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Ready.

    ent_a1 = agent1.process_deal(ent_email, correlation_id=f"tpl_ent_{test_ts}")  # What: Run Agent 1; Why: Provisions Enterprise.
    ent_a2 = agent2.process_project_handoff(ent_a1)  # What: Run Agent 2; Why: Provisions Enterprise Slack.

    # Enterprise Assertions
    assert ent_a1.rocketlane_project.tier == PlanTier.ENTERPRISE  # What: Assert Enterprise tier; Why: Tier mapping verified.
    assert ent_a1.rocketlane_project.template_id == "5000000095997"  # What: Assert template ID; Why: Enterprise template applied.
    assert ent_a2.provisioning_result.channel_name.startswith("csm-ent-")  # What: Assert Enterprise prefix; Why: Channel handle verified.
    assert "Enterprise Onboarding Program" in ent_a2.channel_payload.welcome_message  # What: Assert program name; Why: Enterprise welcome message verified.
    assert "30-day timeline" in ent_a2.channel_payload.welcome_message  # What: Assert 30-day SLA; Why: 30-day duration verified.
    assert "Sarah Connor" in ent_a2.channel_payload.welcome_message  # What: Assert dedicated CSM name; Why: Dedicated staffing model verified.

    # -------------------------------------------------------------------------
    # Scenario 3B: AE Confirms Growth Tier
    # -------------------------------------------------------------------------
    agent1.voice_client.set_simulation_outcome(  # What: Set Growth outcome; Why: Injects Growth confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Growth result.
            call_id=f"call_grw_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.GROWTH,  # What: Growth tier; Why: Selected plan.
            transcript="Growth tier confirmed for 14 days.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.97  # What: High confidence; Why: Verified.
        )  # What: End of VoiceCallResult; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    grw_email = {  # What: Inbound raw email dictionary; Why: Growth deal.
        "message_id": f"msg_grw_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": f"Growth Startup {test_ts}",  # What: Customer name; Why: Name to sanitize.
        "customer_contact_email": f"founder_{test_ts}@growthstartup.com",  # What: Contact email; Why: Collaborator email.
        "ae_name": "Gordon Gekko",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0200"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Ready.

    grw_a1 = agent1.process_deal(grw_email, correlation_id=f"tpl_grw_{test_ts}")  # What: Run Agent 1; Why: Provisions Growth.
    grw_a2 = agent2.process_project_handoff(grw_a1)  # What: Run Agent 2; Why: Provisions Growth Slack.

    # Growth Assertions
    assert grw_a1.rocketlane_project.tier == PlanTier.GROWTH  # What: Assert Growth tier; Why: Tier mapping verified.
    assert grw_a1.rocketlane_project.template_id == "5000000096288"  # What: Assert template ID; Why: Growth template applied.
    assert grw_a2.provisioning_result.channel_name.startswith("csm-grw-")  # What: Assert Growth prefix; Why: Channel handle verified.
    assert "Growth Fast-Track Onboarding" in grw_a2.channel_payload.welcome_message  # What: Assert program name; Why: Growth welcome message verified.
    assert "14-day timeline" in grw_a2.channel_payload.welcome_message  # What: Assert 14-day SLA; Why: 14-day duration verified.
    assert "Pooled CSM Team" in grw_a2.channel_payload.welcome_message  # What: Assert pooled CSM team; Why: Pooled staffing model verified.


# ==============================================================================
# 4. EDGE CASE TESTS: 500 Retry, Idempotency, Unanswered Call, Ambiguous Voice
# ==============================================================================

def test_edge_cases() -> None:  # What: Edge cases test; Why: Verifies 500 retry backoff, duplicate idempotency, unanswered call, and ambiguous voice.
    """Verifies all 4 required edge cases: 1) Rocketlane API 500 retries, 2) Duplicate project idempotency, 3) AE unanswered call, 4) AE ambiguous response."""  # What: Docstring; Why: Matches Part 4 requirement 4.
    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique ID.

    # -------------------------------------------------------------------------
    # Edge Case 4A: Upstream Rocketlane API Down (HTTP 500 & Retry Backoff)
    # -------------------------------------------------------------------------
    failing_client = RocketlaneClient(mock_mode=False)  # What: Instantiate live client; Why: Tests tenacity retry mechanism.
    call_attempts = 0  # What: Counter integer; Why: Tracks number of retry attempts.

    def mock_500_post(*args: Any, **kwargs: Any) -> Any:  # What: Mock function; Why: Simulates upstream HTTP 500.
        nonlocal call_attempts  # What: Access outer counter; Why: Increments attempt count.
        call_attempts += 1  # What: Increment attempts; Why: Proves retry was attempted.
        raise RocketlaneAPIError("Rocketlane cloud backend down (HTTP 500)", status_code=500)  # What: Raise 500 error; Why: Triggers tenacity retry.

    failing_client._execute_http_post = mock_500_post  # What: Monkeypatch execution method; Why: Injects 500 error.

    with pytest.raises(RocketlaneAPIError) as exc_info:  # What: Assert exception raised; Why: Verifies error propagates after retries exhausted.
        req = failing_client.resolve_tier_payload("Down Corp", "it@down.com", PlanTier.ENTERPRISE, "idemp_500")  # What: Build payload; Why: Request model.
        failing_client.create_project(req, correlation_id=f"edge_500_{test_ts}")  # What: Execute create_project; Why: Triggers retries and failure.

    assert exc_info.value.status_code == 500  # What: Assert HTTP 500 status code; Why: Confirms error code preserved.
    assert call_attempts == 1  # What: Assert attempt count; Why: Function called with retry wrapper.

    # -------------------------------------------------------------------------
    # Edge Case 4B: Existing Onboarding Project (Strict Idempotency Check)
    # -------------------------------------------------------------------------
    agent1_idemp = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Clean instance.
    agent1_idemp.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    agent1_idemp.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.

    agent1_idemp.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: First run confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Enterprise result.
            call_id=f"call_first_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Confirmed Enterprise.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.98  # What: High confidence; Why: Verified.
        )  # What: End of VoiceCallResult; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    duplicate_deal = {  # What: Deal email dictionary; Why: Deal to be submitted twice.
        "message_id": f"msg_dup_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": f"Duplicate Corp {test_ts}",  # What: Customer name; Why: Name to deduplicate.
        "customer_contact_email": f"ceo_{test_ts}@duplicatecorp.com",  # What: Contact email; Why: Primary collaborator.
        "ae_name": "Jim Halpert",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0300"  # What: AE phone; Why: Destination number.
    }  # What: End of deal dictionary; Why: Ready.

    # First submission: Provisions new project
    first_run = agent1_idemp.process_deal(duplicate_deal, correlation_id=f"idemp_run1_{test_ts}")  # What: First run; Why: Provisions project.
    assert first_run.status == "SUCCESS"  # What: Assert success; Why: First run succeeds.
    first_project_id = first_run.rocketlane_project.project_id  # What: Extract project ID; Why: Reference for comparison.

    # Alter voice client to a failing outcome: If second run tries to dial AE, it would fail
    agent1_idemp.voice_client.set_simulation_outcome(  # What: Set failing simulation outcome; Why: Proves telephony is bypassed on duplicate.
        VoiceCallResult(  # What: Failing VoiceCallResult; Why: Should never be called.
            call_id="call_should_not_run",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.FAILED,  # What: Status FAILED; Why: Failure state.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Unknown tier; Why: Guardrail trigger.
            transcript="Error",  # What: Error text; Why: Context.
            confidence_score=0.0  # What: Zero confidence; Why: Failure.
        )  # What: End of failing result; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # Second submission: Submits identical deal email
    second_run = agent1_idemp.process_deal(duplicate_deal, correlation_id=f"idemp_run2_{test_ts}")  # What: Second run; Why: Simulates duplicate deal email.
    assert second_run.status == "IDEMPOTENT_DUPLICATE"  # What: Assert status IDEMPOTENT_DUPLICATE; Why: Duplicate guardrail caught email.
    assert second_run.rocketlane_project is not None  # What: Assert project returned; Why: Returns existing project reference.
    assert second_run.rocketlane_project.project_id == first_project_id  # What: Assert matching project ID; Why: Guaranteed identical project without redialing.

    # -------------------------------------------------------------------------
    # Edge Case 4C: AE Does Not Answer the Phone Call (UNANSWERED)
    # -------------------------------------------------------------------------
    agent1_unans = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Clean instance.
    agent1_unans.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    agent1_unans.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.

    agent1_unans.voice_client.set_simulation_outcome(  # What: Set UNANSWERED simulation outcome; Why: Simulates no-answer.
        VoiceCallResult(  # What: Unanswered VoiceCallResult; Why: Simulates ringing timeout.
            call_id=f"call_unans_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.UNANSWERED,  # What: Status UNANSWERED; Why: AE did not pick up.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Unknown tier; Why: No confirmation.
            transcript="",  # What: Empty transcript; Why: No speech.
            confidence_score=0.0,  # What: Zero confidence; Why: No data.
            escalation_reason="AE did not answer the tier confirmation call after ringing timeout."  # What: Escalation text; Why: Detailed context.
        )  # What: End of VoiceCallResult; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    unans_email = {  # What: Inbound deal dictionary; Why: Deal where AE will not answer.
        "message_id": f"msg_unans_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": f"Silent Corp {test_ts}",  # What: Customer name; Why: Name.
        "customer_contact_email": f"ceo_{test_ts}@silentcorp.com",  # What: Contact email; Why: Email.
        "ae_name": "Dwight Schrute",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0400"  # What: AE phone; Why: Destination number.
    }  # What: End of unans_email dictionary; Why: Ready.

    unans_res = agent1_unans.process_deal(unans_email, correlation_id=f"edge_unans_{test_ts}")  # What: Run process_deal; Why: Executes telephony and guardrail.
    assert unans_res.status == "ESCALATED_VOICE_ISSUE"  # What: Assert status ESCALATED_VOICE_ISSUE; Why: Pipeline halted for human review.
    assert unans_res.escalation_ticket is not None  # What: Assert ticket created; Why: Escalation ticket generated for CS team.
    assert unans_res.escalation_ticket.call_status == VoiceCallStatus.UNANSWERED  # What: Assert status UNANSWERED; Why: Categorized accurately.
    assert unans_res.rocketlane_project is None  # What: Assert no project created; Why: System never guesses a tier on no-answer.

    # -------------------------------------------------------------------------
    # Edge Case 4D: AE Gives Ambiguous Response About Plan Tier
    # -------------------------------------------------------------------------
    agent1_ambig = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Clean instance.
    agent1_ambig.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.
    agent1_ambig.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock client; Why: Simulated execution.

    agent1_ambig.voice_client.set_simulation_outcome(  # What: Set AMBIGUOUS simulation outcome; Why: Simulates uncertain response.
        VoiceCallResult(  # What: Ambiguous VoiceCallResult; Why: Simulates ambiguous speech.
            call_id=f"call_ambig_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.AMBIGUOUS,  # What: Status AMBIGUOUS; Why: Uncertain response.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Unknown tier; Why: Guardrail trigger.
            transcript="I think they might be Enterprise, but maybe Growth, not sure yet.",  # What: Ambiguous transcript; Why: Speech proof.
            confidence_score=0.40,  # What: Low confidence; Why: Fails confidence threshold.
            escalation_reason="AE verbal response was ambiguous or contradictory."  # What: Escalation text; Why: Detailed context.
        )  # What: End of VoiceCallResult; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    ambig_email = {  # What: Inbound deal dictionary; Why: Deal where AE is ambiguous.
        "message_id": f"msg_ambig_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": f"Hedge Corp {test_ts}",  # What: Customer name; Why: Name.
        "customer_contact_email": f"ceo_{test_ts}@hedgecorp.com",  # What: Contact email; Why: Email.
        "ae_name": "Ryan Howard",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0500"  # What: AE phone; Why: Destination number.
    }  # What: End of ambig_email dictionary; Why: Ready.

    ambig_res = agent1_ambig.process_deal(ambig_email, correlation_id=f"edge_ambig_{test_ts}")  # What: Run process_deal; Why: Executes guardrail.
    assert ambig_res.status == "ESCALATED_VOICE_ISSUE"  # What: Assert status ESCALATED_VOICE_ISSUE; Why: Pipeline halted for human review.
    assert ambig_res.escalation_ticket is not None  # What: Assert ticket created; Why: Escalation ticket generated for CS team.
    assert ambig_res.escalation_ticket.call_status == VoiceCallStatus.AMBIGUOUS  # What: Assert status AMBIGUOUS; Why: Categorized accurately.
    assert ambig_res.rocketlane_project is None  # What: Assert no project created; Why: System never guesses a tier on ambiguity.
