"""Official Part 4 Automated Test Suite verifying Happy Path, Validation, Template Accuracy, and Edge Cases."""
from datetime import datetime, timezone
from typing import Any
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.core.audit_logger import audit_logger
from src.core.exceptions import RocketlaneAPIError
from src.models.schemas import (
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus
)
from src.services.rocketlane_client import RocketlaneClient
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


# ==============================================================================
# 1. HAPPY PATH TEST: Complete Enterprise Onboarding Flow
# ==============================================================================

def test_happy_path_enterprise() -> None:
    """A new Enterprise deal email arrives, Intake Agent parses it, voice call confirms tier, project created, and Slack channel provisioned."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))

    test_ts = int(datetime.now().timestamp())
    corr_id = f"part4_happy_ent_{test_ts}"

    # 1. Voice AI simulates AE verbally confirming Enterprise tier
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_ent_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Yes, confirming Stark Industries signed our Enterprise plan with 30-day onboarding.",
            confidence_score=0.99
        )
    )

    # 2. Inbound AE deal email arrives
    inbound_email: dict[str, Any] = {
        "message_id": f"msg_ent_{test_ts}",
        "customer_name": f"Stark Industries {test_ts}",
        "customer_contact_email": f"pepper_{test_ts}@starkindustries.com",
        "ae_name": "Tony Stark",
        "ae_phone": "+1-555-0199",
        "opportunity_url": "https://novacrm.salesforce.com/opp/001"
    }

    # 3. Agent 1 processes deal: Validation -> Voice Call -> Rocketlane Project
    a1_result = agent1.process_deal(inbound_email, correlation_id=corr_id)
    assert a1_result.status == "SUCCESS"
    assert a1_result.rocketlane_project is not None
    assert a1_result.rocketlane_project.tier == PlanTier.ENTERPRISE
    assert a1_result.rocketlane_project.template_id == "5000000095997"

    # 4. Agent 2 processes project handoff: Slack Channel -> Topic -> Welcome Message
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result is not None
    assert a2_result.provisioning_result.channel_name.startswith("csm-ent-stark-industries")
    assert a2_result.provisioning_result.topic_set is True
    assert a2_result.provisioning_result.welcome_message_ts is not None

    # 5. Verify continuous audit trail across both agents
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "process_deal_started" in actions
    assert "schema_validation_passed" in actions
    assert "voice_guardrail_passed" in actions
    assert "agent1_workflow_completed" in actions
    assert "process_handoff_started" in actions
    assert "slack_channel_creation_started" in actions
    assert "slack_topic_set" in actions
    assert "slack_welcome_message_posted" in actions
    assert "agent2_workflow_completed" in actions


# ==============================================================================
# 2. VALIDATION TEST: Rejection of Incomplete or Malformed Emails
# ==============================================================================

def test_validation_incomplete_email() -> None:
    """Intake Agent correctly rejects incomplete or malformed emails (missing customer name, no contact email, etc.)."""
    agent1 = Agent1Intake()
    test_ts = int(datetime.now().timestamp())

    # Case 2A: Missing customer_name
    missing_name_email = {
        "message_id": f"msg_noname_{test_ts}",
        "customer_contact_email": "ceo@unknown.com",
        "ae_name": "Jordan Bell",
        "ae_phone": "+1-555-0100"
    }
    res_a = agent1.process_deal(missing_name_email, correlation_id=f"val_noname_{test_ts}")
    assert res_a.status == "HALTED_MISSING_DATA"
    assert res_a.clarification_draft is not None
    assert "customer_name" in res_a.clarification_draft.missing_fields
    assert res_a.rocketlane_project is None

    # Case 2B: Missing customer_contact_email
    missing_email_email = {
        "message_id": f"msg_noemail_{test_ts}",
        "customer_name": "Wayne Enterprises",
        "ae_name": "Jordan Bell",
        "ae_phone": "+1-555-0100"
    }
    res_b = agent1.process_deal(missing_email_email, correlation_id=f"val_noemail_{test_ts}")
    assert res_b.status == "HALTED_MISSING_DATA"
    assert res_b.clarification_draft is not None
    assert "customer_contact_email" in res_b.clarification_draft.missing_fields
    assert res_b.rocketlane_project is None

    # Case 2C: Malformed customer email address (invalid syntax)
    malformed_email = {
        "message_id": f"msg_bademail_{test_ts}",
        "customer_name": "Wayne Enterprises",
        "customer_contact_email": "not-an-email-address",
        "ae_name": "Jordan Bell",
        "ae_phone": "+1-555-0100"
    }
    res_c = agent1.process_deal(malformed_email, correlation_id=f"val_bademail_{test_ts}")
    assert res_c.status == "HALTED_MISSING_DATA"
    assert res_c.clarification_draft is not None
    assert res_c.rocketlane_project is None

    # Case 2D: Whitespace-only string fields
    blank_name_email = {
        "message_id": f"msg_blank_{test_ts}",
        "customer_name": "   ",
        "customer_contact_email": "ceo@valid.com",
        "ae_name": "Jordan Bell",
        "ae_phone": "+1-555-0100"
    }
    res_d = agent1.process_deal(blank_name_email, correlation_id=f"val_blank_{test_ts}")
    assert res_d.status == "HALTED_MISSING_DATA"
    assert res_d.rocketlane_project is None


# ==============================================================================
# 3. TEMPLATE ACCURACY TEST: Enterprise vs Growth Tier Mapping
# ==============================================================================

def test_template_accuracy() -> None:
    """When AE confirms Enterprise, creates 30d template + dedicated CSM; when AE confirms Growth, creates 14d template + pooled CSM."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))

    test_ts = int(datetime.now().timestamp())

    # -------------------------------------------------------------------------
    # Scenario 3A: AE Confirms Enterprise Tier
    # -------------------------------------------------------------------------
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_ent_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Enterprise tier confirmed for 30 days.",
            confidence_score=0.98
        )
    )

    ent_email = {
        "message_id": f"msg_ent_{test_ts}",
        "customer_name": f"Enterprise Client {test_ts}",
        "customer_contact_email": f"lead_{test_ts}@entclient.com",
        "ae_name": "Gordon Gekko",
        "ae_phone": "+1-555-0200"
    }

    ent_a1 = agent1.process_deal(ent_email, correlation_id=f"tpl_ent_{test_ts}")
    ent_a2 = agent2.process_project_handoff(ent_a1)

    # Enterprise Assertions
    assert ent_a1.rocketlane_project.tier == PlanTier.ENTERPRISE
    assert ent_a1.rocketlane_project.template_id == "5000000095997"
    assert ent_a2.provisioning_result.channel_name.startswith("csm-ent-")
    assert "Enterprise Onboarding Program" in ent_a2.channel_payload.welcome_message
    assert "30-day timeline" in ent_a2.channel_payload.welcome_message
    assert "Sarah Connor" in ent_a2.channel_payload.welcome_message

    # -------------------------------------------------------------------------
    # Scenario 3B: AE Confirms Growth Tier
    # -------------------------------------------------------------------------
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_grw_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.GROWTH,
            transcript="Growth tier confirmed for 14 days.",
            confidence_score=0.97
        )
    )

    grw_email = {
        "message_id": f"msg_grw_{test_ts}",
        "customer_name": f"Growth Startup {test_ts}",
        "customer_contact_email": f"founder_{test_ts}@growthstartup.com",
        "ae_name": "Gordon Gekko",
        "ae_phone": "+1-555-0200"
    }

    grw_a1 = agent1.process_deal(grw_email, correlation_id=f"tpl_grw_{test_ts}")
    grw_a2 = agent2.process_project_handoff(grw_a1)

    # Growth Assertions
    assert grw_a1.rocketlane_project.tier == PlanTier.GROWTH
    assert grw_a1.rocketlane_project.template_id == "5000000096288"
    assert grw_a2.provisioning_result.channel_name.startswith("csm-grw-")
    assert "Growth Fast-Track Onboarding" in grw_a2.channel_payload.welcome_message
    assert "14-day timeline" in grw_a2.channel_payload.welcome_message
    assert "Pooled CSM Team" in grw_a2.channel_payload.welcome_message


# ==============================================================================
# 4. EDGE CASE TESTS: 500 Retry, Idempotency, Unanswered Call, Ambiguous Voice
# ==============================================================================

def test_edge_cases() -> None:
    """Verifies all 4 required edge cases: 1) Rocketlane API 500 retries, 2) Duplicate project idempotency, 3) AE unanswered call, 4) AE ambiguous response."""
    test_ts = int(datetime.now().timestamp())

    # -------------------------------------------------------------------------
    # Edge Case 4A: Upstream Rocketlane API Down (HTTP 500 & Retry Backoff)
    # -------------------------------------------------------------------------
    failing_client = RocketlaneClient(mock_mode=False)
    call_attempts = 0

    def mock_500_post(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_attempts
        call_attempts += 1
        raise RocketlaneAPIError("Rocketlane cloud backend down (HTTP 500)", status_code=500)

    failing_client._execute_http_post = mock_500_post

    with pytest.raises(RocketlaneAPIError) as exc_info:
        req = failing_client.resolve_tier_payload("Down Corp", "it@down.com", PlanTier.ENTERPRISE, "idemp_500")
        failing_client.create_project(req, correlation_id=f"edge_500_{test_ts}")

    assert exc_info.value.status_code == 500
    assert call_attempts == 1

    # -------------------------------------------------------------------------
    # Edge Case 4B: Existing Onboarding Project (Strict Idempotency Check)
    # -------------------------------------------------------------------------
    agent1_idemp = Agent1Intake()
    agent1_idemp.rocketlane = RocketlaneClient(mock_mode=True)
    agent1_idemp.voice_client = VoiceAIClient(mock_mode=True)

    agent1_idemp.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_first_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Confirmed Enterprise.",
            confidence_score=0.98
        )
    )

    duplicate_deal = {
        "message_id": f"msg_dup_{test_ts}",
        "customer_name": f"Duplicate Corp {test_ts}",
        "customer_contact_email": f"ceo_{test_ts}@duplicatecorp.com",
        "ae_name": "Jim Halpert",
        "ae_phone": "+1-555-0300"
    }

    # First submission: Provisions new project
    first_run = agent1_idemp.process_deal(duplicate_deal, correlation_id=f"idemp_run1_{test_ts}")
    assert first_run.status == "SUCCESS"
    first_project_id = first_run.rocketlane_project.project_id

    # Alter voice client to a failing outcome: If second run tries to dial AE, it would fail
    agent1_idemp.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_should_not_run",
            status=VoiceCallStatus.FAILED,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="Error",
            confidence_score=0.0
        )
    )

    # Second submission: Submits identical deal email
    second_run = agent1_idemp.process_deal(duplicate_deal, correlation_id=f"idemp_run2_{test_ts}")
    assert second_run.status == "IDEMPOTENT_DUPLICATE"
    assert second_run.rocketlane_project is not None
    assert second_run.rocketlane_project.project_id == first_project_id

    # -------------------------------------------------------------------------
    # Edge Case 4C: AE Does Not Answer the Phone Call (UNANSWERED)
    # -------------------------------------------------------------------------
    agent1_unans = Agent1Intake()
    agent1_unans.rocketlane = RocketlaneClient(mock_mode=True)
    agent1_unans.voice_client = VoiceAIClient(mock_mode=True)

    agent1_unans.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_unans_{test_ts}",
            status=VoiceCallStatus.UNANSWERED,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="",
            confidence_score=0.0,
            escalation_reason="AE did not answer the tier confirmation call after ringing timeout."
        )
    )

    unans_email = {
        "message_id": f"msg_unans_{test_ts}",
        "customer_name": f"Silent Corp {test_ts}",
        "customer_contact_email": f"ceo_{test_ts}@silentcorp.com",
        "ae_name": "Dwight Schrute",
        "ae_phone": "+1-555-0400"
    }

    unans_res = agent1_unans.process_deal(unans_email, correlation_id=f"edge_unans_{test_ts}")
    assert unans_res.status == "ESCALATED_VOICE_ISSUE"
    assert unans_res.escalation_ticket is not None
    assert unans_res.escalation_ticket.call_status == VoiceCallStatus.UNANSWERED
    assert unans_res.rocketlane_project is None

    # -------------------------------------------------------------------------
    # Edge Case 4D: AE Gives Ambiguous Response About Plan Tier
    # -------------------------------------------------------------------------
    agent1_ambig = Agent1Intake()
    agent1_ambig.rocketlane = RocketlaneClient(mock_mode=True)
    agent1_ambig.voice_client = VoiceAIClient(mock_mode=True)

    agent1_ambig.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_ambig_{test_ts}",
            status=VoiceCallStatus.AMBIGUOUS,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="I think they might be Enterprise, but maybe Growth, not sure yet.",
            confidence_score=0.40,
            escalation_reason="AE verbal response was ambiguous or contradictory."
        )
    )

    ambig_email = {
        "message_id": f"msg_ambig_{test_ts}",
        "customer_name": f"Hedge Corp {test_ts}",
        "customer_contact_email": f"ceo_{test_ts}@hedgecorp.com",
        "ae_name": "Ryan Howard",
        "ae_phone": "+1-555-0500"
    }

    ambig_res = agent1_ambig.process_deal(ambig_email, correlation_id=f"edge_ambig_{test_ts}")
    assert ambig_res.status == "ESCALATED_VOICE_ISSUE"
    assert ambig_res.escalation_ticket is not None
    assert ambig_res.escalation_ticket.call_status == VoiceCallStatus.AMBIGUOUS
    assert ambig_res.rocketlane_project is None
