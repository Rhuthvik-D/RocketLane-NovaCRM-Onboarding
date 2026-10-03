"""End-to-end integration test validating Phase 1 foundation against live configurations and APIs."""
from datetime import datetime, timezone
import json
import httpx
import pytest
from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import (
    AuditActionStatus,
    InboundEmailPayload,
    PlanTier
)
from src.services.rocketlane_client import RocketlaneClient


def test_e2e_configuration_loading() -> None:
    """Validates that real credentials for Rocketlane, Voice AI, and Slack are loaded properly."""
    assert settings.rocketlane_api_key.startswith("rl-")
    assert len(settings.voice_ai_api_key) > 10
    assert settings.slack_bot_token.startswith("xoxb-")


def test_e2e_schema_validation_guardrails() -> None:
    """Verifies that inbound email parser rejects missing or whitespace fields deterministically."""
    # Healthy deal email should parse and produce SHA-256 idempotency key
    valid_email = InboundEmailPayload(
        message_id="msg_live_001",
        customer_name="Globex Corporation",
        customer_contact_email="hank.scorpio@globex.com",
        ae_name="Homer Simpson",
        ae_phone="+1-555-7334",
        opportunity_url="https://novacrm.salesforce.com/opp/globex"
    )
    assert valid_email.customer_name == "Globex Corporation"
    key = valid_email.generate_idempotency_key()
    assert len(key) == 64

    # Empty customer name must raise validation error without guessing
    with pytest.raises(Exception):
        InboundEmailPayload(
            message_id="msg_live_002",
            customer_name="   ",
            customer_contact_email="invalid@example.com",
            ae_name="Homer Simpson",
            ae_phone="+1-555-7334"
        )


def test_e2e_audit_logging_integrity() -> None:
    """Ensures that all mandatory audit fields (timestamp, inputs, outputs, rationale) persist to JSONL."""
    correlation_id = f"deal_e2e_audit_{int(datetime.now().timestamp())}"
    entry = audit_logger.log_action(
        correlation_id=correlation_id,
        agent_name="Agent1_Intake",
        action="schema_validation",
        inputs={"customer_name": "Globex Corporation", "tier": "UNKNOWN"},
        outputs={"validation_result": "PASSED", "next_step": "VOICE_CONFIRMATION"},
        decision_rationale="All mandatory email fields present; dispatched outbound call for missing tier.",
        status=AuditActionStatus.SUCCESS
    )

    assert entry.decision_rationale != ""
    entries = audit_logger.get_entries_for_correlation(correlation_id)
    assert len(entries) >= 1
    assert entries[0].agent_name == "Agent1_Intake"


def test_e2e_rocketlane_live_provisioning_and_idempotency() -> None:
    """Tests project creation against live Rocketlane API followed by idempotency duplicate prevention."""
    client = RocketlaneClient(mock_mode=False)
    test_deal_key = f"e2e_idempotency_test_{int(datetime.now().timestamp())}"

    # 1. Resolve request payload for 30-day Enterprise tier
    request_payload = client.resolve_tier_payload(
        customer_name="Acme Enterprise Labs",
        customer_email="admin@acmelabs.com",
        tier=PlanTier.ENTERPRISE,
        idempotency_key=test_deal_key
    )
    assert request_payload.duration_days == 30
    assert request_payload.csm_type == "Dedicated CSM"

    # 2. First call: Provisions new project via live Rocketlane API
    first_response = client.create_project(request_payload, correlation_id="e2e_live_corr_1")
    assert first_response.is_duplicate is False
    assert first_response.project_id is not None
    assert "https://app.rocketlane.com/projects/" in first_response.portal_url

    # 3. Second call: IDEMPOTENCY GUARDRAIL - should return existing project without creating duplicate
    second_response = client.create_project(request_payload, correlation_id="e2e_live_corr_2")
    assert second_response.is_duplicate is True
    assert second_response.project_id == first_response.project_id


def test_e2e_vapi_credentials_connectivity() -> None:
    """Verifies that the configured Voice AI credentials can access the target Vapi assistant."""
    url = f"https://api.vapi.ai/assistant/{settings.voice_ai_agent_id}"
    headers = {"Authorization": f"Bearer {settings.voice_ai_api_key}"}
    with httpx.Client(timeout=10.0) as http_client:
        response = http_client.get(url, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("id") == settings.voice_ai_agent_id


def test_e2e_slack_credentials_connectivity() -> None:
    """Verifies that the configured Slack bot token is authenticated and authorized."""
    url = "https://slack.com/api/auth.test"
    headers = {"Authorization": f"Bearer {settings.slack_bot_token}"}
    with httpx.Client(timeout=10.0) as http_client:
        response = http_client.post(url, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
