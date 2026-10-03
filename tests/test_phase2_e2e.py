"""End-to-end integration test validating Phase 2 Agent 1 lifecycle against live integrations and guardrails."""
from datetime import datetime, timezone
import json
from typing import Any
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import (
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus
)
from src.services.rocketlane_client import RocketlaneClient
from src.services.voice_ai_client import VoiceAIClient


def test_e2e_agent1_happy_path_enterprise_live_provisioning() -> None:
    """Tests end-to-end Enterprise deal intake: email validation, verbal confirmation, and live Rocketlane project creation."""
    agent = Agent1Intake()
    agent.rocketlane = RocketlaneClient(mock_mode=False)
    agent.voice_client = VoiceAIClient(mock_mode=True)

    test_ts = int(datetime.now().timestamp())
    corr_id = f"e2e_agent1_ent_{test_ts}"

    # 1. Simulate AE verbally confirming Enterprise tier with high confidence
    agent.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_ent_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Hello, yes! Acme Enterprise is on the Enterprise tier with 30-day onboarding.",
            confidence_score=0.98
        )
    )

    raw_email: dict[str, Any] = {
        "message_id": f"msg_ent_{test_ts}",
        "customer_name": f"Acme Global Labs {test_ts}",
        "customer_contact_email": f"it_{test_ts}@acmeglobal.com",
        "ae_name": "Jordan Bell",
        "ae_phone": "+1-555-0199",
        "opportunity_url": "https://novacrm.salesforce.com/opp/001"
    }

    # 2. Execute complete Agent 1 lifecycle
    result = agent.process_deal(raw_email, correlation_id=corr_id)

    # 3. Assertions on successful outcome
    assert result.status == "SUCCESS"
    assert result.rocketlane_project is not None
    assert result.rocketlane_project.tier == PlanTier.ENTERPRISE
    assert result.rocketlane_project.project_id is not None
    assert "https://app.rocketlane.com/projects/" in result.rocketlane_project.portal_url

    # 4. Verify structured audit trail for this deal
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "process_deal_started" in actions
    assert "schema_validation_passed" in actions
    assert "voice_guardrail_passed" in actions
    assert "create_project_success" in actions
    assert "agent1_workflow_completed" in actions


def test_e2e_agent1_missing_fields_clarification_halt() -> None:
    """Guarantees that an email missing mandatory fields halts pipeline, generates clarification draft, and avoids live API calls."""
    agent = Agent1Intake()
    agent.rocketlane = RocketlaneClient(mock_mode=False)
    agent.voice_client = VoiceAIClient(mock_mode=True)

    test_ts = int(datetime.now().timestamp())
    corr_id = f"e2e_agent1_halt_{test_ts}"

    # Incomplete email missing AE phone and customer contact email
    incomplete_email: dict[str, Any] = {
        "message_id": f"msg_halt_{test_ts}",
        "customer_name": "Initech Corporation",
        "customer_contact_email": "",
        "ae_name": "Peter Gibbons",
        "ae_phone": "   "
    }

    result = agent.process_deal(incomplete_email, correlation_id=corr_id)

    assert result.status == "HALTED_MISSING_DATA"
    assert result.clarification_draft is not None
    assert "customer_contact_email" in result.clarification_draft.missing_fields
    assert "ae_phone" in result.clarification_draft.missing_fields
    assert result.rocketlane_project is None
    assert result.voice_result is None


def test_e2e_agent1_ambiguous_voice_escalation_guardrail() -> None:
    """Guarantees that an ambiguous AE verbal response triggers human escalation and halts Rocketlane project creation."""
    agent = Agent1Intake()
    agent.rocketlane = RocketlaneClient(mock_mode=False)
    agent.voice_client = VoiceAIClient(mock_mode=True)

    test_ts = int(datetime.now().timestamp())
    corr_id = f"e2e_agent1_amb_{test_ts}"

    # Configure ambiguous voice outcome
    agent.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_amb_{test_ts}",
            status=VoiceCallStatus.AMBIGUOUS,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="I'm not completely sure, maybe Enterprise? Let me double-check the Salesforce contract.",
            confidence_score=0.45,
            escalation_reason="AE response was non-committal and contained uncertainty phrase 'not sure'."
        )
    )

    raw_email: dict[str, Any] = {
        "message_id": f"msg_amb_{test_ts}",
        "customer_name": f"Hooli Ambiguity Test {test_ts}",
        "customer_contact_email": f"gavin_{test_ts}@hooli.com",
        "ae_name": "Gavin Belson",
        "ae_phone": "+1-555-0899"
    }

    result = agent.process_deal(raw_email, correlation_id=corr_id)

    assert result.status == "ESCALATED_VOICE_ISSUE"
    assert result.escalation_ticket is not None
    assert result.escalation_ticket.call_status == VoiceCallStatus.AMBIGUOUS
    assert result.rocketlane_project is None


def test_e2e_agent1_idempotency_prevents_duplicate_calls_and_projects() -> None:
    """Guarantees that resending the same deal returns existing project without re-dialing the AE or re-creating the Rocketlane project."""
    agent = Agent1Intake()
    agent.rocketlane = RocketlaneClient(mock_mode=False)
    agent.voice_client = VoiceAIClient(mock_mode=True)

    test_ts = int(datetime.now().timestamp())

    # 1. Configure initial confirmed Growth tier call
    agent.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_grw_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.GROWTH,
            transcript="Growth plan confirmed for 14 days.",
            confidence_score=0.96
        )
    )

    raw_email: dict[str, Any] = {
        "message_id": f"msg_idemp_{test_ts}",
        "customer_name": f"Dunder Mifflin {test_ts}",
        "customer_contact_email": f"jim_{test_ts}@dundermifflin.com",
        "ae_name": "Jim Halpert",
        "ae_phone": "+1-555-0777"
    }

    # 2. First Run: Provisions new live project
    first_result = agent.process_deal(raw_email, correlation_id=f"e2e_idemp_run1_{test_ts}")
    assert first_result.status == "SUCCESS"
    assert first_result.rocketlane_project is not None
    first_project_id = first_result.rocketlane_project.project_id

    # 3. Alter voice client simulation to failure: If second run tries to dial AE, it would fail
    agent.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_should_not_run",
            status=VoiceCallStatus.FAILED,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="Error",
            confidence_score=0.0
        )
    )

    # 4. Second Run: Submits duplicate email payload
    second_result = agent.process_deal(raw_email, correlation_id=f"e2e_idemp_run2_{test_ts}")

    # 5. Assertions: Second run caught by idempotency without re-dialing AE or creating project
    assert second_result.status == "IDEMPOTENT_DUPLICATE"
    assert second_result.rocketlane_project is not None
    assert second_result.rocketlane_project.project_id == first_project_id
