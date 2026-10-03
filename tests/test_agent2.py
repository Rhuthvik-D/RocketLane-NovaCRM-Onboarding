"""Unit test suite verifying Agent 2 Communication Agent logic, Slack client resilience, and template personalization."""
from datetime import datetime, timezone
import pytest
from src.agents.agent2_communication import Agent2Communication
from src.core.audit_logger import audit_logger
from src.models.schemas import (
    Agent1Result,
    InboundEmailPayload,
    PlanTier,
    RocketlaneProjectResponse,
    SlackChannelPayload
)
from src.services.slack_client import SlackClient


def test_channel_name_sanitization_rules() -> None:
    """Verifies that customer names with spaces, special characters, and excessive length are properly sanitized."""
    agent = Agent2Communication(client=SlackClient(mock_mode=True))

    # 1. Enterprise prefix with spaces and punctuation
    ent_name = agent.sanitize_channel_name("Acme & Sons, Inc.", PlanTier.ENTERPRISE)
    assert ent_name == "#csm-ent-acme-sons-inc"

    # 2. Growth prefix with uppercase and numbers
    grw_name = agent.sanitize_channel_name("BetaTech 2026 Solutions", PlanTier.GROWTH)
    assert grw_name == "#csm-grw-betatech-2026-solutions"

    # 3. Excessive length exceeding Slack's 80-character maximum
    long_company = "A" * 100
    truncated_name = agent.sanitize_channel_name(long_company, PlanTier.ENTERPRISE)
    assert len(truncated_name) <= 81
    assert truncated_name.startswith("#csm-ent-")

    # 4. Fallback for names composed purely of special characters
    fallback_name = agent.sanitize_channel_name("$$$ ### @@@", PlanTier.ENTERPRISE)
    assert fallback_name == "#csm-ent-customer"


def test_channel_topic_embedding_rocketlane_url() -> None:
    """Verifies that the channel topic embeds the Rocketlane project workspace URL and customer plan tier."""
    agent = Agent2Communication(client=SlackClient(mock_mode=True))
    portal_url = "https://app.rocketlane.com/projects/5000000099999"
    topic = agent.format_channel_topic(portal_url, PlanTier.ENTERPRISE)

    assert portal_url in topic
    assert "ENTERPRISE" in topic
    assert "NovaCRM Customer Onboarding" in topic


def test_welcome_message_personalization_enterprise() -> None:
    """Verifies that Enterprise welcome message includes dedicated CSM, 30-day roadmap, and kickoff call link."""
    agent = Agent2Communication(client=SlackClient(mock_mode=True))
    msg = agent.format_welcome_message(
        customer_name="Acme Global",
        tier=PlanTier.ENTERPRISE,
        portal_url="https://app.rocketlane.com/projects/123",
        csm_name="Sarah Connor (Enterprise Lead)"
    )

    assert "Acme Global" in msg
    assert "Enterprise Onboarding Program" in msg
    assert "30-day timeline" in msg
    assert "Sarah Connor (Enterprise Lead)" in msg
    assert "Phase 1: Kickoff & Architecture Discovery" in msg
    assert "Phase 2: Data Migration & Verification" in msg
    assert "calendly.com/novacrm-enterprise/kickoff" in msg


def test_welcome_message_personalization_growth() -> None:
    """Verifies that Growth welcome message includes pooled CSM team, 14-day roadmap, and weekly office hours."""
    agent = Agent2Communication(client=SlackClient(mock_mode=True))
    msg = agent.format_welcome_message(
        customer_name="Beta Startups",
        tier=PlanTier.GROWTH,
        portal_url="https://app.rocketlane.com/projects/456",
        csm_name="Pooled CSM Team"
    )

    assert "Beta Startups" in msg
    assert "Growth Fast-Track Onboarding" in msg
    assert "14-day timeline" in msg
    assert "Pooled CSM Team" in msg
    assert "Weekly Live Office Hours" in msg
    assert "docs.novacrm.com/getting-started" in msg


def test_agent2_skips_when_agent1_halted_missing_data() -> None:
    """Verifies that Agent 2 halts and skips Slack provisioning if Agent 1 was halted due to missing email data."""
    agent = Agent2Communication(client=SlackClient(mock_mode=True))
    corr_id = f"test_a2_skip_missing_{int(datetime.now().timestamp())}"

    unconfirmed_result = Agent1Result(
        correlation_id=corr_id,
        status="HALTED_MISSING_DATA",
        rocketlane_project=None
    )

    result = agent.process_project_handoff(unconfirmed_result)

    assert result.status == "SKIPPED_UNCONFIRMED"
    assert result.provisioning_result is None
    assert "Slack provisioning skipped" in (result.error_message or "")


def test_agent2_skips_when_agent1_escalated_voice_issue() -> None:
    """Verifies that Agent 2 skips Slack provisioning if Agent 1 was escalated due to ambiguous or failed telephony."""
    agent = Agent2Communication(client=SlackClient(mock_mode=True))
    corr_id = f"test_a2_skip_voice_{int(datetime.now().timestamp())}"

    escalated_result = Agent1Result(
        correlation_id=corr_id,
        status="ESCALATED_VOICE_ISSUE",
        rocketlane_project=None
    )

    result = agent.process_project_handoff(escalated_result)

    assert result.status == "SKIPPED_UNCONFIRMED"
    assert result.provisioning_result is None


def test_agent2_happy_path_enterprise_mock_provisioning() -> None:
    """Verifies that a successful Agent 1 Enterprise result triggers channel creation, topic setting, and welcome message."""
    agent = Agent2Communication(client=SlackClient(mock_mode=True))
    corr_id = f"test_a2_happy_ent_{int(datetime.now().timestamp())}"

    # Build confirmed Agent 1 Enterprise outcome
    agent1_result = Agent1Result(
        correlation_id=corr_id,
        status="SUCCESS",
        email_payload=InboundEmailPayload(
            message_id="msg_123",
            customer_name="Globex Corporation",
            customer_contact_email="it@globex.com",
            ae_name="Hank Scorpio",
            ae_phone="+1-555-0100"
        ),
        rocketlane_project=RocketlaneProjectResponse(
            project_id="5000000088888",
            project_name="Globex Corporation - Onboarding (ENTERPRISE)",
            tier=PlanTier.ENTERPRISE,
            template_id="5000000095997",
            portal_url="https://app.rocketlane.com/projects/5000000088888",
            is_duplicate=False
        )
    )

    result = agent.process_project_handoff(agent1_result)

    # Assertions on successful Agent 2 execution
    assert result.status == "SUCCESS"
    assert result.provisioning_result is not None
    assert result.provisioning_result.channel_name == "csm-ent-globex-corporation"
    assert result.provisioning_result.channel_id.startswith("C_MOCK_")
    assert result.provisioning_result.topic_set is True
    assert result.provisioning_result.welcome_message_ts is not None

    # Verify structured audit trail for this deal
    entries = audit_logger.get_entries_for_correlation(corr_id)
    actions = [e.action for e in entries]
    assert "process_handoff_started" in actions
    assert "slack_channel_creation_started" in actions
    assert "slack_topic_set" in actions
    assert "slack_welcome_message_posted" in actions
    assert "agent2_workflow_completed" in actions
