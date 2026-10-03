"""End-to-end integration test validating Phase 3 Agent 1 -> Agent 2 complete handoff lifecycle."""
from datetime import datetime, timezone
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.core.audit_logger import audit_logger
from src.models.schemas import (
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus
)
from src.services.rocketlane_client import RocketlaneClient
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


def test_e2e_phase3_enterprise_intake_to_slack_provisioning() -> None:
    """Tests complete lifecycle: Enterprise deal email -> Voice AI confirmation -> Rocketlane project -> Slack channel & kickoff message."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))

    test_ts = int(datetime.now().timestamp())
    corr_id = f"e2e_phase3_ent_{test_ts}"

    # 1. Configure Voice AI to simulate clear Enterprise verbal confirmation
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_ent_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Yes, confirming Wayne Enterprises is on the Enterprise tier with 30-day onboarding.",
            confidence_score=0.99
        )
    )

    raw_email = {
        "message_id": f"msg_ent_{test_ts}",
        "customer_name": f"Wayne Enterprises {test_ts}",
        "customer_contact_email": f"bruce_{test_ts}@wayneenterprises.com",
        "ae_name": "Lucius Fox",
        "ae_phone": "+1-555-0199"
    }

    # 2. Execute Agent 1 (Intake & Routing)
    a1_result = agent1.process_deal(raw_email, correlation_id=corr_id)
    assert a1_result.status == "SUCCESS"
    assert a1_result.rocketlane_project is not None
    assert a1_result.rocketlane_project.tier == PlanTier.ENTERPRISE

    # 3. Execute Agent 2 (Communication Agent)
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result is not None
    assert a2_result.provisioning_result.channel_name.startswith("csm-ent-wayne-enterprises")
    assert a2_result.provisioning_result.topic_set is True
    assert a2_result.provisioning_result.welcome_message_ts is not None

    # 4. Verify continuous audit trail across both agents
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]

    # Agent 1 actions
    assert "process_deal_started" in actions
    assert "schema_validation_passed" in actions
    assert "voice_guardrail_passed" in actions
    assert "agent1_workflow_completed" in actions

    # Agent 2 actions
    assert "process_handoff_started" in actions
    assert "slack_channel_creation_started" in actions
    assert "slack_topic_set" in actions
    assert "slack_welcome_message_posted" in actions
    assert "agent2_workflow_completed" in actions


def test_e2e_phase3_growth_intake_to_slack_provisioning() -> None:
    """Tests complete lifecycle: Growth deal email -> Voice AI confirmation -> Rocketlane project -> Slack channel & kickoff message."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))

    test_ts = int(datetime.now().timestamp())
    corr_id = f"e2e_phase3_grw_{test_ts}"

    # 1. Configure Voice AI to simulate clear Growth verbal confirmation
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_grw_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.GROWTH,
            transcript="Acme is definitely on the Growth plan with 14-day onboarding.",
            confidence_score=0.97
        )
    )

    raw_email = {
        "message_id": f"msg_grw_{test_ts}",
        "customer_name": f"Pied Piper {test_ts}",
        "customer_contact_email": f"richard_{test_ts}@piedpiper.com",
        "ae_name": "Jared Dunn",
        "ae_phone": "+1-555-0200"
    }

    # 2. Execute Agent 1
    a1_result = agent1.process_deal(raw_email, correlation_id=corr_id)
    assert a1_result.status == "SUCCESS"
    assert a1_result.rocketlane_project is not None
    assert a1_result.rocketlane_project.tier == PlanTier.GROWTH

    # 3. Execute Agent 2
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result is not None
    assert a2_result.provisioning_result.channel_name.startswith("csm-grw-pied-piper")
    assert "Pooled CSM Team" in a2_result.channel_payload.welcome_message


def test_e2e_phase3_guardrail_prevents_slack_on_missing_email_data() -> None:
    """Verifies that missing inbound email fields prevent both project provisioning and Slack channel creation."""
    agent1 = Agent1Intake()
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))

    test_ts = int(datetime.now().timestamp())
    corr_id = f"e2e_phase3_missing_{test_ts}"

    # Incomplete email missing customer_name
    bad_email = {
        "message_id": f"msg_bad_{test_ts}",
        "customer_contact_email": "ceo@unknown.com",
        "ae_name": "Tom Davis",
        "ae_phone": "+1-555-0300"
    }

    # Agent 1 halts
    a1_result = agent1.process_deal(bad_email, correlation_id=corr_id)
    assert a1_result.status == "HALTED_MISSING_DATA"
    assert a1_result.rocketlane_project is None

    # Agent 2 skips
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SKIPPED_UNCONFIRMED"
    assert a2_result.provisioning_result is None


def test_e2e_phase3_live_slack_channel_creation() -> None:
    """Provisions a live, real Slack channel in the configured Slack workspace and posts the kickoff welcome message."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    # Initialize Agent 2 with mock_mode=False to hit the live Slack Web API
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))

    test_ts = int(datetime.now().timestamp()) % 10000
    corr_id = f"e2e_live_slack_{test_ts}"

    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_live_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Confirmed Enterprise tier for Acme.",
            confidence_score=0.99
        )
    )

    raw_email = {
        "message_id": f"msg_live_{test_ts}",
        "customer_name": f"Nova Customer {test_ts}",
        "customer_contact_email": f"csm_{test_ts}@novacustomer.com",
        "ae_name": "Sarah Jenkins",
        "ae_phone": "+1-555-0155"
    }

    a1_result = agent1.process_deal(raw_email, correlation_id=corr_id)
    assert a1_result.status == "SUCCESS"

    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result is not None
    assert a2_result.provisioning_result.is_mock is False
    assert a2_result.provisioning_result.channel_id.startswith("C")
    assert a2_result.provisioning_result.welcome_message_ts is not None
