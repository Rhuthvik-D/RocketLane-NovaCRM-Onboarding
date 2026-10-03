"""Automated unit tests for Phase 1 foundational components: Schemas, Audit Logger, and Rocketlane Client."""
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from src.core.audit_logger import AuditLogger
from src.core.exceptions import RocketlaneAPIError
from src.models.schemas import (
    AuditActionStatus,
    InboundEmailPayload,
    PlanTier
)
from src.services.rocketlane_client import RocketlaneClient


def test_inbound_email_valid_parsing() -> None:
    """Ensures valid inbound email payload passes validation and produces deterministic hash."""
    payload = InboundEmailPayload(
        message_id="msg_1001",
        customer_name="Acme Corporation",
        customer_contact_email="it@acme.com",
        ae_name="Jordan Bell",
        ae_phone="+1-555-0199",
        opportunity_url="https://novacrm.salesforce.com/opp/001"
    )
    assert payload.customer_name == "Acme Corporation"
    assert payload.generate_idempotency_key() is not None
    assert len(payload.generate_idempotency_key()) == 64


def test_inbound_email_rejects_blank_strings() -> None:
    """Guarantees that whitespace-only or empty strings are rejected with validation error."""
    with pytest.raises(ValidationError):
        InboundEmailPayload(
            message_id="msg_1002",
            customer_name="   ",
            customer_contact_email="contact@example.com",
            ae_name="Jordan Bell",
            ae_phone="+1-555-0199"
        )


def test_audit_logger_records_and_retrieves_entries(tmp_path: Path) -> None:
    """Verifies that audit logger writes structured JSONL to disk with all required fields."""
    test_log_file = tmp_path / "test_audit.jsonl"
    logger = AuditLogger(log_path=test_log_file)

    entry = logger.log_action(
        correlation_id="deal_test_123",
        agent_name="TestAgent",
        action="test_action_run",
        inputs={"param": "value"},
        outputs={"result": "ok"},
        decision_rationale="Tested logging subsystem",
        status=AuditActionStatus.SUCCESS
    )

    assert test_log_file.exists()
    entries = logger.get_entries_for_correlation("deal_test_123")
    assert len(entries) == 1
    assert entries[0].agent_name == "TestAgent"
    assert entries[0].decision_rationale == "Tested logging subsystem"

    # Log an escalation action to verify dual persistence to dedicated escalation file
    esc_entry = logger.log_action(
        correlation_id="deal_test_esc_456",
        agent_name="VoiceGuardrail",
        action="voice_guardrail_escalated_ambiguity",
        inputs={"transcript": "maybe enterprise"},
        outputs={"ticket_id": "esc_test_456", "reason": "Ambiguous response"},
        decision_rationale="AE was ambiguous",
        status=AuditActionStatus.ESCALATED
    )

    assert logger.escalation_path.exists()
    esc_entries = logger.get_escalation_entries()
    assert len(esc_entries) == 1
    assert esc_entries[0].outputs["ticket_id"] == "esc_test_456"
    all_deal_entries = logger.get_entries_for_correlation("deal_test_esc_456")
    assert len(all_deal_entries) == 1


def test_rocketlane_template_resolution() -> None:
    """Verifies that plan tiers correctly resolve to respective templates, SLAs, and staffing."""
    client = RocketlaneClient(mock_mode=True)

    # Enterprise tier test
    ent_request = client.resolve_tier_payload(
        customer_name="Acme Corp",
        customer_email="admin@acme.com",
        tier=PlanTier.ENTERPRISE,
        idempotency_key="key_ent_1"
    )
    assert ent_request.duration_days == 30
    assert ent_request.template_id == client.TIER_CONFIG[PlanTier.ENTERPRISE]["template_id"]
    assert ent_request.csm_type == "Dedicated CSM"

    # Growth tier test
    growth_request = client.resolve_tier_payload(
        customer_name="Beta Startup",
        customer_email="admin@beta.com",
        tier=PlanTier.GROWTH,
        idempotency_key="key_growth_1"
    )
    assert growth_request.duration_days == 14
    assert growth_request.template_id == client.TIER_CONFIG[PlanTier.GROWTH]["template_id"]
    assert growth_request.csm_type == "Pooled CSM"


def test_rocketlane_client_idempotency() -> None:
    """Guarantees that repeated project creation calls with the same key return cached instance."""
    client = RocketlaneClient(mock_mode=True)
    req = client.resolve_tier_payload(
        customer_name="Delta Logistics",
        customer_email="ops@delta.com",
        tier=PlanTier.ENTERPRISE,
        idempotency_key="key_delta_idempotent_test"
    )

    first_resp = client.create_project(req, correlation_id="corr_001")
    assert first_resp.is_duplicate is False

    second_resp = client.create_project(req, correlation_id="corr_002")
    assert second_resp.is_duplicate is True
    assert second_resp.project_id == first_resp.project_id


def test_rocketlane_client_retries_on_500(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verifies that HTTP 500 server errors trigger tenacity retries up to maximum attempt limit."""
    client = RocketlaneClient(mock_mode=False, cache_file_path=tmp_path / "retry_cache.json")
    attempts = {"count": 0}

    def mock_post_with_failures(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            class Mock500Response:
                status_code = 500
                text = "Internal Server Error"
            return Mock500Response()
        class Mock200Response:
            status_code = 200
            text = '{"id": "proj_recovered_500", "url": "https://app.rocketlane.com/projects/proj_recovered_500"}'
            def json(self):
                return {"id": "proj_recovered_500", "url": "https://app.rocketlane.com/projects/proj_recovered_500"}
        return Mock200Response()

    monkeypatch.setattr(client._client, "post", mock_post_with_failures)

    req = client.resolve_tier_payload(
        customer_name="Retry Corp",
        customer_email="admin@retry.com",
        tier=PlanTier.GROWTH,
        idempotency_key="key_retry_test_1"
    )

    resp = client.create_project(req, correlation_id="corr_retry_test")
    assert attempts["count"] == 3
    assert resp.project_id == "proj_recovered_500"


def test_rocketlane_client_idempotency_file_persistence(tmp_path: Path) -> None:
    """Guarantees that idempotency cache persists to local JSON file and survives client re-instantiation."""
    cache_file = tmp_path / "idempotency_cache.json"
    client1 = RocketlaneClient(mock_mode=True, cache_file_path=cache_file)
    req = client1.resolve_tier_payload(
        customer_name="Persistent Corp",
        customer_email="admin@persistent.com",
        tier=PlanTier.ENTERPRISE,
        idempotency_key="key_persistent_test_001"
    )

    resp1 = client1.create_project(req, correlation_id="corr_p1")
    assert resp1.is_duplicate is False
    assert cache_file.exists()

    # Re-instantiate client simulating process restart
    client2 = RocketlaneClient(mock_mode=True, cache_file_path=cache_file)
    resp2 = client2.create_project(req, correlation_id="corr_p2")
    assert resp2.is_duplicate is True
    assert resp2.project_id == resp1.project_id


def test_rocketlane_client_self_healing_cloud_reconciliation_on_400_duplicate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verifies that Rocketlane HTTP 400 'Invalid External Reference Key' triggers cloud query and updates local cache."""
    cache_file = tmp_path / "self_heal_cache.json"
    client = RocketlaneClient(mock_mode=False, cache_file_path=cache_file)

    # 1. Mock post to return 400 Invalid External Reference Key specified
    class Mock400DuplicateResponse:
        status_code = 400
        text = '{"errors":[{"code":"INVALID_INPUTS","reason":"Bad Request: Invalid External Reference Key specified"}]}'
        def json(self):
            return {"errors": [{"code": "INVALID_INPUTS", "reason": "Bad Request: Invalid External Reference Key specified"}]}

    # 2. Mock get to return the existing cloud project matching externalReferenceId
    class Mock200QueryResponse:
        status_code = 200
        text = '{"data":[{"projectId": 5000000208093, "projectName": "CyberScript Systems - Onboarding (ENTERPRISE)"}]}'
        def json(self):
            return {"data": [{"projectId": 5000000208093, "projectName": "CyberScript Systems - Onboarding (ENTERPRISE)"}]}

    monkeypatch.setattr(client._client, "post", lambda *args, **kwargs: Mock400DuplicateResponse())
    monkeypatch.setattr(client._client, "get", lambda *args, **kwargs: Mock200QueryResponse())

    req = client.resolve_tier_payload(
        customer_name="CyberScript Systems",
        customer_email="sarah@cyberscript.com",
        tier=PlanTier.ENTERPRISE,
        idempotency_key="d7fcf2a9c598d37763531f3fb12f85a7aae9f46783df76e1755d504bed430a5c"
    )

    resp = client.create_project(req, correlation_id="corr_heal_001")
    assert resp.is_duplicate is True
    assert resp.project_id == "5000000208093"
    assert resp.project_name == "CyberScript Systems - Onboarding (ENTERPRISE)"
    assert cache_file.exists()

    # 3. Subsequent call should hit cache without network calls
    resp2 = client.create_project(req, correlation_id="corr_heal_002")
    assert resp2.is_duplicate is True
    assert resp2.project_id == "5000000208093"
