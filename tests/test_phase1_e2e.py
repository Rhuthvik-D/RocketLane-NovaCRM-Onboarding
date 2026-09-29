# End-to-end integration test validating Phase 1 foundation against live configurations and APIs.  # What: Module header; Why: Verifies Phase 1 end-to-end.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps and assertions.
import json  # What: Import json library; Why: Reads and inspects structured audit log lines.
import httpx  # What: Import httpx; Why: Validates external API credentials for Vapi and Slack.
import pytest  # What: Import pytest; Why: Runs assertions and test fixtures.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Tests live logging functionality.
from src.core.config import settings  # What: Import application settings; Why: Reads live configuration from .env.
from src.models.schemas import (  # What: Import domain models; Why: Verifies schemas across the pipeline.
    AuditActionStatus,  # What: Audit status enum; Why: Categorizes log outcomes.
    InboundEmailPayload,  # What: Inbound email model; Why: Tests email validation guardrail.
    PlanTier  # What: Plan tier enum; Why: Tests tier resolution and mapping.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Tests live provisioning and retries.


def test_e2e_configuration_loading() -> None:  # What: E2E config test; Why: Verifies that live credentials loaded from .env.
    """Validates that real credentials for Rocketlane, Voice AI, and Slack are loaded properly."""  # What: Docstring; Why: Explains test intent.
    assert settings.rocketlane_api_key.startswith("rl-")  # What: Assert Rocketlane key prefix; Why: Confirms user's real Rocketlane key loaded.
    assert len(settings.voice_ai_api_key) > 10  # What: Assert Voice AI key length; Why: Confirms Vapi key loaded.
    assert settings.slack_bot_token.startswith("xoxb-")  # What: Assert Slack token prefix; Why: Confirms Slack bot token loaded.


def test_e2e_schema_validation_guardrails() -> None:  # What: E2E schema test; Why: Enforces zero-assumption policy against guessing data.
    """Verifies that inbound email parser rejects missing or whitespace fields deterministically."""  # What: Docstring; Why: Explains test intent.
    # Healthy deal email should parse and produce SHA-256 idempotency key
    valid_email = InboundEmailPayload(  # What: Instantiate valid model; Why: Simulates healthy inbound AE email.
        message_id="msg_live_001",  # What: Message ID; Why: Identifies email.
        customer_name="Globex Corporation",  # What: Customer company; Why: Customer title.
        customer_contact_email="hank.scorpio@globex.com",  # What: Contact email; Why: Primary collaborator.
        ae_name="Homer Simpson",  # What: AE name; Why: Deal owner.
        ae_phone="+1-555-7334",  # What: AE phone; Why: Destination for Voice AI call.
        opportunity_url="https://novacrm.salesforce.com/opp/globex"  # What: SFDC link; Why: Context link.
    )  # What: End of valid model construction; Why: Ready for assertions.
    assert valid_email.customer_name == "Globex Corporation"  # What: Assert name; Why: Confirms name parsed.
    key = valid_email.generate_idempotency_key()  # What: Generate idempotency key; Why: Produces deterministic hash.
    assert len(key) == 64  # What: Assert 64 chars; Why: Confirms standard SHA-256 hex string length.

    # Empty customer name must raise validation error without guessing
    with pytest.raises(Exception):  # What: Assert exception raised; Why: Halts pipeline if customer name is omitted.
        InboundEmailPayload(  # What: Instantiate invalid model; Why: Simulates incomplete AE email.
            message_id="msg_live_002",  # What: Message ID; Why: Present.
            customer_name="   ",  # What: Whitespace string; Why: Violates zero-assumption guardrail.
            customer_contact_email="invalid@example.com",  # What: Email; Why: Present.
            ae_name="Homer Simpson",  # What: AE name; Why: Present.
            ae_phone="+1-555-7334"  # What: Phone; Why: Present.
        )  # What: End of invalid model construction; Why: Triggers validation error.


def test_e2e_audit_logging_integrity() -> None:  # What: E2E audit log test; Why: Verifies that structured logs meet assignment requirements.
    """Ensures that all mandatory audit fields (timestamp, inputs, outputs, rationale) persist to JSONL."""  # What: Docstring; Why: Explains test intent.
    correlation_id = f"deal_e2e_audit_{int(datetime.now().timestamp())}"  # What: Unique correlation ID; Why: Isolates test run.
    entry = audit_logger.log_action(  # What: Call log_action; Why: Records sample action.
        correlation_id=correlation_id,  # What: Unique deal ID; Why: Links all actions for this deal.
        agent_name="Agent1_Intake",  # What: Agent identifier; Why: Identifies executing agent.
        action="schema_validation",  # What: Action name; Why: Specifies operation.
        inputs={"customer_name": "Globex Corporation", "tier": "UNKNOWN"},  # What: Inputs dict; Why: Audits input arguments.
        outputs={"validation_result": "PASSED", "next_step": "VOICE_CONFIRMATION"},  # What: Outputs dict; Why: Audits outcome data.
        decision_rationale="All mandatory email fields present; dispatched outbound call for missing tier.",  # What: Rationale text; Why: Documents reason.
        status=AuditActionStatus.SUCCESS  # What: Status enum; Why: Records success state.
    )  # What: End of log_action call; Why: Persisted to disk and console.

    assert entry.decision_rationale != ""  # What: Assert rationale present; Why: Mandatory requirement.
    entries = audit_logger.get_entries_for_correlation(correlation_id)  # What: Query log entries; Why: Retrieves entries for deal.
    assert len(entries) >= 1  # What: Assert at least one entry found; Why: Confirms file persistence and retrieval.
    assert entries[0].agent_name == "Agent1_Intake"  # What: Assert agent name; Why: Confirms structured data integrity.


def test_e2e_rocketlane_live_provisioning_and_idempotency() -> None:  # What: Live Rocketlane integration test; Why: Verifies API project creation and duplicate guardrail.
    """Tests project creation against live Rocketlane API followed by idempotency duplicate prevention."""  # What: Docstring; Why: Explains test intent.
    client = RocketlaneClient(mock_mode=False)  # What: Instantiate client with mock_mode=False; Why: Hits live Rocketlane REST API.
    test_deal_key = f"e2e_idempotency_test_{int(datetime.now().timestamp())}"  # What: Unique test deal key; Why: Avoids conflicts with previous runs.

    # 1. Resolve request payload for 30-day Enterprise tier
    request_payload = client.resolve_tier_payload(  # What: Resolve tier payload; Why: Maps Enterprise tier to 30-day timeline.
        customer_name="Acme Enterprise Labs",  # What: Customer name; Why: Project title base.
        customer_email="admin@acmelabs.com",  # What: Customer email; Why: Primary collaborator.
        tier=PlanTier.ENTERPRISE,  # What: Enterprise tier enum; Why: Triggers 30-day template and dedicated CSM.
        idempotency_key=test_deal_key  # What: Unique test deal key; Why: Idempotency fingerprint.
    )  # What: End of resolution call; Why: Returns typed request payload.
    assert request_payload.duration_days == 30  # What: Assert 30-day timeline; Why: Enterprise SLA requirement.
    assert request_payload.csm_type == "Dedicated CSM"  # What: Assert dedicated CSM; Why: Enterprise staffing rule.

    # 2. First call: Provisions new project via live Rocketlane API
    first_response = client.create_project(request_payload, correlation_id="e2e_live_corr_1")  # What: Create project in Rocketlane; Why: Executes live POST /projects.
    assert first_response.is_duplicate is False  # What: Assert is_duplicate is False; Why: First creation must be a new project.
    assert first_response.project_id is not None  # What: Assert project ID exists; Why: Live Rocketlane project generated.
    assert "https://app.rocketlane.com/projects/" in first_response.portal_url  # What: Assert portal URL format; Why: Used in Slack topic.

    # 3. Second call: IDEMPOTENCY GUARDRAIL - should return existing project without creating duplicate
    second_response = client.create_project(request_payload, correlation_id="e2e_live_corr_2")  # What: Call create_project again with same key; Why: Simulates duplicate email.
    assert second_response.is_duplicate is True  # What: Assert is_duplicate is True; Why: Guardrail successfully prevented duplicate project.
    assert second_response.project_id == first_response.project_id  # What: Assert matching project ID; Why: Returned existing project reference.


def test_e2e_vapi_credentials_connectivity() -> None:  # What: Live Vapi assistant test; Why: Verifies Voice AI provider connectivity before Phase 2.
    """Verifies that the configured Voice AI credentials can access the target Vapi assistant."""  # What: Docstring; Why: Explains test intent.
    url = f"https://api.vapi.ai/assistant/{settings.voice_ai_agent_id}"  # What: Vapi assistant endpoint URL; Why: Target assistant configuration.
    headers = {"Authorization": f"Bearer {settings.voice_ai_api_key}"}  # What: Bearer token header; Why: Server-side private API key auth.
    with httpx.Client(timeout=10.0) as http_client:  # What: Context manager for HTTP client; Why: Performs GET request safely.
        response = http_client.get(url, headers=headers)  # What: Dispatch GET request; Why: Retrieves assistant details.
    assert response.status_code == 200  # What: Assert HTTP 200 OK; Why: Verifies Vapi credentials and assistant exist.
    data = response.json()  # What: Parse JSON response; Why: Inspects assistant metadata.
    assert data.get("id") == settings.voice_ai_agent_id  # What: Assert matching assistant ID; Why: Confirms correct assistant mapped.


def test_e2e_slack_credentials_connectivity() -> None:  # What: Live Slack credentials test; Why: Verifies Slack bot token before Phase 3.
    """Verifies that the configured Slack bot token is authenticated and authorized."""  # What: Docstring; Why: Explains test intent.
    url = "https://slack.com/api/auth.test"  # What: Slack auth.test endpoint URL; Why: Standard verification endpoint.
    headers = {"Authorization": f"Bearer {settings.slack_bot_token}"}  # What: Bearer token header; Why: Authenticates bot token.
    with httpx.Client(timeout=10.0) as http_client:  # What: Context manager for HTTP client; Why: Performs POST request safely.
        response = http_client.post(url, headers=headers)  # What: Dispatch POST request; Why: Tests Slack bot authentication.
    assert response.status_code == 200  # What: Assert HTTP 200 OK; Why: Confirms Slack API reached.
    data = response.json()  # What: Parse JSON response; Why: Inspects auth status.
    assert data.get("ok") is True  # What: Assert ok is True; Why: Confirms bot token is valid in the workspace.
