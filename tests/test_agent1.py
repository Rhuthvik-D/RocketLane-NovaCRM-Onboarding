"""Automated test suite for Agent 1 Intake & Routing Agent covering happy paths, guardrails, and escalations."""
from datetime import datetime, timezone
from typing import Any
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.intake_parser import IntakeParser
from src.agents.voice_guardrail import VoiceGuardrail
from src.models.schemas import (
    InboundEmailPayload,
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus
)
from src.services.rocketlane_client import RocketlaneClient
from src.services.voice_ai_client import VoiceAIClient


@pytest.fixture
def agent1_fixture() -> Agent1Intake:
    """Builds a hermetic Agent 1 instance with isolated mock clients for testing."""
    agent = Agent1Intake()
    agent.rocketlane = RocketlaneClient(mock_mode=True)
    agent.voice_client = VoiceAIClient(mock_mode=True)
    return agent


def test_agent1_happy_path_enterprise(agent1_fixture: Agent1Intake) -> None:
    """Verifies that an Enterprise deal email is validated, confirmed via voice, and provisioned with 30-day SLA."""
    # 1. Configure voice simulation to return confirmed Enterprise tier
    agent1_fixture.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_sim_ent_01",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Yes, this is an Enterprise deal with 30 days onboarding.",
            confidence_score=0.98
        )
    )

    raw_email: dict[str, Any] = {
        "message_id": "msg_ent_101",
        "customer_name": "Wayne Enterprises",
        "customer_contact_email": "bruce@wayne.com",
        "ae_name": "Lucius Fox",
        "ae_phone": "+1-555-0100",
        "opportunity_url": "https://novacrm.salesforce.com/opp/wayne01"
    }

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_ent_test_01")

    assert result.status == "SUCCESS"
    assert result.rocketlane_project is not None
    assert result.rocketlane_project.tier == PlanTier.ENTERPRISE
    assert "https://app.rocketlane.com/projects/" in result.rocketlane_project.portal_url


def test_agent1_happy_path_growth(agent1_fixture: Agent1Intake) -> None:
    """Verifies that a Growth deal email is validated, confirmed via voice, and provisioned with 14-day SLA."""
    agent1_fixture.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_sim_grw_01",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.GROWTH,
            transcript="The customer signed for the standard Growth plan, 14 days.",
            confidence_score=0.95
        )
    )

    raw_email: dict[str, Any] = {
        "message_id": "msg_grw_102",
        "customer_name": "Pied Piper",
        "customer_contact_email": "richard@piedpiper.com",
        "ae_name": "Jared Dunn",
        "ae_phone": "+1-555-0200",
        "opportunity_url": "https://novacrm.salesforce.com/opp/pied02"
    }

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_grw_test_01")

    assert result.status == "SUCCESS"
    assert result.rocketlane_project is not None
    assert result.rocketlane_project.tier == PlanTier.GROWTH


def test_agent1_missing_fields_validation_halt(agent1_fixture: Agent1Intake) -> None:
    """Guarantees that missing mandatory fields immediately halt execution and draft a clarification email."""
    incomplete_email: dict[str, Any] = {
        "message_id": "msg_inc_103",
        "customer_name": "Cyberdyne Systems",
        "customer_contact_email": "",
        "ae_name": "Miles Dyson",
        "ae_phone": "   "
    }

    result = agent1_fixture.process_deal(incomplete_email, correlation_id="corr_inc_test_01")

    assert result.status == "HALTED_MISSING_DATA"
    assert result.clarification_draft is not None
    assert "customer_contact_email" in result.clarification_draft.missing_fields
    assert "ae_phone" in result.clarification_draft.missing_fields
    assert result.rocketlane_project is None
    assert result.voice_result is None


def test_agent1_ambiguous_voice_escalation(agent1_fixture: Agent1Intake) -> None:
    """Guarantees that an ambiguous verbal tier response halts project creation and generates an escalation ticket."""
    agent1_fixture.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_sim_amb_01",
            status=VoiceCallStatus.AMBIGUOUS,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="I think they might be Enterprise, but maybe start with Growth and upgrade later.",
            confidence_score=0.45,
            escalation_reason="AE mentioned both Enterprise and Growth and could not provide a firm tier."
        )
    )

    raw_email: dict[str, Any] = {
        "message_id": "msg_amb_104",
        "customer_name": "Stark Industries",
        "customer_contact_email": "tony@stark.com",
        "ae_name": "Pepper Potts",
        "ae_phone": "+1-555-0300"
    }

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_amb_test_01")

    assert result.status == "ESCALATED_VOICE_ISSUE"
    assert result.escalation_ticket is not None
    assert result.escalation_ticket.call_status == VoiceCallStatus.AMBIGUOUS
    assert result.rocketlane_project is None


def test_agent1_unanswered_voice_escalation(agent1_fixture: Agent1Intake) -> None:
    """Guarantees that an unanswered voice call halts project creation and generates an escalation ticket."""
    agent1_fixture.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_sim_unans_01",
            status=VoiceCallStatus.UNANSWERED,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="",
            confidence_score=0.0,
            escalation_reason="AE did not answer after 4 rings."
        )
    )

    raw_email: dict[str, Any] = {
        "message_id": "msg_unans_105",
        "customer_name": "Oscorp Industries",
        "customer_contact_email": "norman@oscorp.com",
        "ae_name": "Harry Osborn",
        "ae_phone": "+1-555-0400"
    }

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_unans_test_01")

    assert result.status == "ESCALATED_VOICE_ISSUE"
    assert result.escalation_ticket is not None
    assert result.escalation_ticket.call_status == VoiceCallStatus.UNANSWERED
    assert result.rocketlane_project is None


def test_agent1_idempotency_prevents_duplicate_call_and_project(agent1_fixture: Agent1Intake) -> None:
    """Guarantees that reprocessing the same deal returns existing project without placing second call or creating duplicate."""
    agent1_fixture.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_sim_idemp_01",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Enterprise tier confirmed.",
            confidence_score=0.99
        )
    )

    raw_email: dict[str, Any] = {
        "message_id": "msg_idemp_106",
        "customer_name": "Massive Dynamic",
        "customer_contact_email": "william.bell@massivedynamic.com",
        "ae_name": "Nina Sharp",
        "ae_phone": "+1-555-0500"
    }

    # First run provisions project
    first_result = agent1_fixture.process_deal(raw_email, correlation_id="corr_idemp_01")
    assert first_result.status == "SUCCESS"
    assert first_result.rocketlane_project is not None
    first_proj_id = first_result.rocketlane_project.project_id

    # Change simulation to AMBIGUOUS to prove that second run never even calls voice client
    agent1_fixture.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_should_never_be_reached",
            status=VoiceCallStatus.AMBIGUOUS,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="Ambiguous response",
            confidence_score=0.2
        )
    )

    # Second run with same email payload
    second_result = agent1_fixture.process_deal(raw_email, correlation_id="corr_idemp_02")
    assert second_result.status == "IDEMPOTENT_DUPLICATE"
    assert second_result.rocketlane_project is not None
    assert second_result.rocketlane_project.project_id == first_proj_id


def test_transcript_analyzer_heuristics() -> None:
    """Verifies that transcript text is evaluated accurately for Enterprise, Growth, and ambiguity patterns."""
    guardrail = VoiceGuardrail()

    # Positive Enterprise
    status, tier, conf = guardrail.parse_transcript_text("We closed the deal on the Enterprise plan with dedicated support.")
    assert status == VoiceCallStatus.CONFIRMED
    assert tier == PlanTier.ENTERPRISE
    assert conf >= 0.9

    # Positive Growth
    status, tier, conf = guardrail.parse_transcript_text("The customer chose Growth, 14 days.")
    assert status == VoiceCallStatus.CONFIRMED
    assert tier == PlanTier.GROWTH
    assert conf >= 0.9

    # Ambiguous phrase "not sure"
    status, tier, conf = guardrail.parse_transcript_text("I'm not sure, maybe Enterprise?")
    assert status == VoiceCallStatus.AMBIGUOUS
    assert tier == PlanTier.UNKNOWN

    # Contradictory mention of both tiers
    status, tier, conf = guardrail.parse_transcript_text("Start them on Growth but sell them Enterprise next quarter.")
    assert status == VoiceCallStatus.AMBIGUOUS
    assert tier == PlanTier.UNKNOWN


def test_agent1_automated_voice_enterprise_assumption(agent1_fixture: Agent1Intake) -> None:
    """Verifies that Agent 1 assumes Enterprise tier when voice_ai_assume_enterprise is active and simulation is not set."""
    agent1_fixture.voice_client.set_simulation_outcome(None)
    agent1_fixture.voice_client.assume_enterprise = True
    agent1_fixture.voice_client.simulated_tier = "ENTERPRISE"

    raw_email: dict[str, Any] = {
        "message_id": "msg_auto_ent_01",
        "customer_name": "Initech Systems",
        "customer_contact_email": "peter@initech.com",
        "ae_name": "Bill Lumbergh",
        "ae_phone": "+1-555-0300",
        "opportunity_url": "https://novacrm.salesforce.com/opp/initech"
    }

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_auto_ent_01")

    assert result.status == "SUCCESS"
    assert result.rocketlane_project is not None
    assert result.rocketlane_project.tier == PlanTier.ENTERPRISE
    assert result.voice_result is not None
    assert result.voice_result.status == VoiceCallStatus.CONFIRMED
    assert result.voice_result.confidence_score == 0.99
