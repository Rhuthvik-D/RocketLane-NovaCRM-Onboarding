# Automated unit tests for Phase 1 foundational components: Schemas, Audit Logger, and Rocketlane Client.  # What: Module header; Why: Verifies foundation.
import json  # What: Import json library; Why: Used to inspect serialized audit log contents.
from pathlib import Path  # What: Import Path class; Why: Creates isolated temporary paths for test logs.
import pytest  # What: Import pytest framework; Why: Runs test fixtures, assertions, and test cases.
from pydantic import ValidationError  # What: Import ValidationError; Why: Verifies that invalid inputs raise schema validation errors.
from src.core.audit_logger import AuditLogger  # What: Import AuditLogger class; Why: Tests structured logging in isolated test instance.
from src.core.exceptions import RocketlaneAPIError  # What: Import RocketlaneAPIError; Why: Tests API failure exception handling.
from src.models.schemas import (  # What: Import domain models; Why: Instantiates test fixtures and asserts schema outputs.
    AuditActionStatus,  # What: Audit status enum; Why: Asserts log status.
    InboundEmailPayload,  # What: Inbound email schema; Why: Tests deterministic parsing.
    PlanTier  # What: Plan tier enum; Why: Tests template mapping logic.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Tests API client behavior.


def test_inbound_email_valid_parsing() -> None:  # What: Test valid email payload; Why: Verifies healthy inputs parse successfully.
    """Ensures valid inbound email payload passes validation and produces deterministic hash."""  # What: Docstring; Why: Documents test intent.
    payload = InboundEmailPayload(  # What: Instantiate valid payload; Why: Simulates complete AE notification email.
        message_id="msg_1001",  # What: Message ID string; Why: Unique email identifier.
        customer_name="Acme Corporation",  # What: Customer company name; Why: Name for project.
        customer_contact_email="it@acme.com",  # What: Contact email; Why: Primary email address.
        ae_name="Jordan Bell",  # What: AE name; Why: Account executive owner.
        ae_phone="+1-555-0199",  # What: Phone number; Why: Destination for Voice AI call.
        opportunity_url="https://novacrm.salesforce.com/opp/001"  # What: SFDC link; Why: Context link.
    )  # What: End of payload construction; Why: Ready for assertion.
    assert payload.customer_name == "Acme Corporation"  # What: Assert customer name; Why: Confirms stored name matches input.
    assert payload.generate_idempotency_key() is not None  # What: Assert key exists; Why: Verifies deterministic key generation.
    assert len(payload.generate_idempotency_key()) == 64  # What: Assert SHA-256 length; Why: SHA-256 produces 64 hex characters.


def test_inbound_email_rejects_blank_strings() -> None:  # What: Test validation guardrail; Why: Enforces zero-assumption policy on missing data.
    """Guarantees that whitespace-only or empty strings are rejected with validation error."""  # What: Docstring; Why: Documents test intent.
    with pytest.raises(ValidationError):  # What: Assert ValidationError raised; Why: System must halt on missing/empty customer name.
        InboundEmailPayload(  # What: Instantiate invalid payload; Why: Simulates AE email omitting customer name.
            message_id="msg_1002",  # What: Message ID; Why: Valid message ID.
            customer_name="   ",  # What: Whitespace string; Why: Must fail deterministic blank string validator.
            customer_contact_email="contact@example.com",  # What: Valid email; Why: Field present.
            ae_name="Jordan Bell",  # What: Valid AE; Why: Field present.
            ae_phone="+1-555-0199"  # What: Valid phone; Why: Field present.
        )  # What: End of invalid instantiation; Why: Triggers ValidationError.


def test_audit_logger_records_and_retrieves_entries(tmp_path: Path) -> None:  # What: Test audit logger; Why: Verifies structured logging requirement.
    """Verifies that audit logger writes structured JSONL to disk with all required fields."""  # What: Docstring; Why: Documents test intent.
    test_log_file = tmp_path / "test_audit.jsonl"  # What: Create temporary file path; Why: Isolates test from production logs.
    logger = AuditLogger(log_path=test_log_file)  # What: Instantiate isolated logger; Why: Writes to temporary test path.

    entry = logger.log_action(  # What: Call log_action; Why: Records sample action.
        correlation_id="deal_test_123",  # What: Correlation ID; Why: Tracks deal session.
        agent_name="TestAgent",  # What: Agent name; Why: Identifies actor.
        action="test_action_run",  # What: Action name; Why: Identifies operation.
        inputs={"param": "value"},  # What: Sample inputs; Why: Verifies inputs captured.
        outputs={"result": "ok"},  # What: Sample outputs; Why: Verifies outputs captured.
        decision_rationale="Tested logging subsystem",  # What: Rationale string; Why: Verifies rationale captured.
        status=AuditActionStatus.SUCCESS  # What: Status enum; Why: Verifies status captured.
    )  # What: End of logging call; Why: Writes to test log file.

    assert test_log_file.exists()  # What: Assert file exists; Why: Verifies file creation.
    entries = logger.get_entries_for_correlation("deal_test_123")  # What: Query log entries; Why: Verifies retrieval by correlation ID.
    assert len(entries) == 1  # What: Assert single entry retrieved; Why: Only one entry was written for this deal.
    assert entries[0].agent_name == "TestAgent"  # What: Assert agent name; Why: Confirms field integrity.
    assert entries[0].decision_rationale == "Tested logging subsystem"  # What: Assert rationale; Why: Proves decision reason preserved.

    # Log an escalation action to verify dual persistence to dedicated escalation file
    esc_entry = logger.log_action(  # What: Log escalation action; Why: Tests escalation mirror to dedicated file.
        correlation_id="deal_test_esc_456",  # What: Correlation ID; Why: Identifies escalation deal.
        agent_name="VoiceGuardrail",  # What: Agent name; Why: Identifies guardrail.
        action="voice_guardrail_escalated_ambiguity",  # What: Action name; Why: Escalation action.
        inputs={"transcript": "maybe enterprise"},  # What: Sample inputs; Why: Transcript data.
        outputs={"ticket_id": "esc_test_456", "reason": "Ambiguous response"},  # What: Outputs with ticket_id; Why: Escalation payload.
        decision_rationale="AE was ambiguous",  # What: Decision rationale; Why: Explains escalation.
        status=AuditActionStatus.ESCALATED  # What: Escalated status; Why: Triggers dual file writing.
    )  # What: End of escalation logging call; Why: Writes to both audit and escalation files.

    assert logger.escalation_path.exists()  # What: Assert escalation file created; Why: Confirms dedicated file persistence.
    esc_entries = logger.get_escalation_entries()  # What: Retrieve escalation entries; Why: Reads from dedicated file.
    assert len(esc_entries) == 1  # What: Assert single escalation retrieved; Why: Only one escalation was logged.
    assert esc_entries[0].outputs["ticket_id"] == "esc_test_456"  # What: Assert ticket ID matches; Why: Confirms ticket data integrity.
    all_deal_entries = logger.get_entries_for_correlation("deal_test_esc_456")  # What: Query audit log for deal; Why: Verifies audit log retained record.
    assert len(all_deal_entries) == 1  # What: Assert audit log contains escalation; Why: Confirms not removed from audit log.


def test_rocketlane_template_resolution() -> None:  # What: Test template mapping; Why: Verifies 30-day Enterprise vs 14-day Growth rules.
    """Verifies that plan tiers correctly resolve to respective templates, SLAs, and staffing."""  # What: Docstring; Why: Documents test intent.
    client = RocketlaneClient(mock_mode=True)  # What: Instantiate client in mock mode; Why: Offline testing.

    # Enterprise tier test
    ent_request = client.resolve_tier_payload(  # What: Resolve Enterprise payload; Why: Tests Enterprise mapping.
        customer_name="Acme Corp",  # What: Customer name; Why: Customer title.
        customer_email="admin@acme.com",  # What: Customer email; Why: Contact email.
        tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Should trigger 30-day template.
        idempotency_key="key_ent_1"  # What: Idempotency key; Why: Attached to request.
    )  # What: End of resolution call; Why: Returns request model.
    assert ent_request.duration_days == 30  # What: Assert 30 days; Why: Enterprise SLA requirement.
    assert ent_request.template_id == client.TIER_CONFIG[PlanTier.ENTERPRISE]["template_id"]  # What: Assert template ID; Why: Validates against configured template ID.
    assert ent_request.csm_type == "Dedicated CSM"  # What: Assert dedicated CSM; Why: Enterprise staffing rule.

    # Growth tier test
    growth_request = client.resolve_tier_payload(  # What: Resolve Growth payload; Why: Tests Growth mapping.
        customer_name="Beta Startup",  # What: Customer name; Why: Customer title.
        customer_email="admin@beta.com",  # What: Customer email; Why: Contact email.
        tier=PlanTier.GROWTH,  # What: Growth tier; Why: Should trigger 14-day template.
        idempotency_key="key_growth_1"  # What: Idempotency key; Why: Attached to request.
    )  # What: End of resolution call; Why: Returns request model.
    assert growth_request.duration_days == 14  # What: Assert 14 days; Why: Growth SLA requirement.
    assert growth_request.template_id == client.TIER_CONFIG[PlanTier.GROWTH]["template_id"]  # What: Assert template ID; Why: Validates against configured template ID.
    assert growth_request.csm_type == "Pooled CSM"  # What: Assert pooled CSM; Why: Growth staffing rule.


def test_rocketlane_client_idempotency() -> None:  # What: Test idempotency guardrail; Why: Verifies duplicate requests do not create duplicate projects.
    """Guarantees that repeated project creation calls with the same key return cached instance."""  # What: Docstring; Why: Documents test intent.
    client = RocketlaneClient(mock_mode=True)  # What: Instantiate client in mock mode; Why: Uses internal cache.
    req = client.resolve_tier_payload(  # What: Build request payload; Why: Sample request to test deduplication.
        customer_name="Delta Logistics",  # What: Customer name; Why: Test company.
        customer_email="ops@delta.com",  # What: Customer email; Why: Test contact.
        tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Target tier.
        idempotency_key="key_delta_idempotent_test"  # What: Static key; Why: Tests duplicate protection.
    )  # What: End of payload construction; Why: Ready for execution.

    first_resp = client.create_project(req, correlation_id="corr_001")  # What: First project creation call; Why: Should provision new project.
    assert first_resp.is_duplicate is False  # What: Assert is_duplicate is False; Why: Initial creation is not a duplicate.

    second_resp = client.create_project(req, correlation_id="corr_002")  # What: Second project creation call with same key; Why: Should hit idempotency cache.
    assert second_resp.is_duplicate is True  # What: Assert is_duplicate is True; Why: Confirms duplicate was recognized.
    assert second_resp.project_id == first_resp.project_id  # What: Assert same project ID returned; Why: Proves no second project was created.


def test_rocketlane_client_retries_on_500(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # What: Test retry logic; Why: Verifies exponential backoff on HTTP 500.
    """Verifies that HTTP 500 server errors trigger tenacity retries up to maximum attempt limit."""  # What: Docstring; Why: Documents test intent.
    client = RocketlaneClient(mock_mode=False, cache_file_path=tmp_path / "retry_cache.json")  # What: Instantiate client with isolated test cache; Why: Routes through _execute_http_post without cache collision.
    attempts = {"count": 0}  # What: Mutable counter dict; Why: Tracks how many times HTTP post is attempted.

    def mock_post_with_failures(*args, **kwargs):  # What: Mock function; Why: Simulates 2 failures followed by 1 success.
        attempts["count"] += 1  # What: Increment attempt counter; Why: Records attempt count.
        if attempts["count"] < 3:  # What: Check if under 3 attempts; Why: Simulates transient 500 errors first.
            class Mock500Response:  # What: Dummy response object; Why: Emulates httpx.Response for 500 status.
                status_code = 500  # What: Status code 500; Why: Server error.
                text = "Internal Server Error"  # What: Response text; Why: Error message.
            return Mock500Response()  # What: Return dummy 500 response; Why: Triggers retry logic.
        class Mock200Response:  # What: Dummy response object; Why: Emulates httpx.Response for 200 status.
            status_code = 200  # What: Status code 200; Why: Successful response.
            text = '{"id": "proj_recovered_500", "url": "https://app.rocketlane.com/projects/proj_recovered_500"}'  # What: JSON text; Why: Payload.
            def json(self):  # What: json method; Why: Returns dict.
                return {"id": "proj_recovered_500", "url": "https://app.rocketlane.com/projects/proj_recovered_500"}  # What: Return dict; Why: Mock project.
        return Mock200Response()  # What: Return 200 response on 3rd attempt; Why: Verifies successful recovery.

    monkeypatch.setattr(client._client, "post", mock_post_with_failures)  # What: Monkeypatch client.post; Why: Injects mock response generator.

    req = client.resolve_tier_payload(  # What: Build request payload; Why: Input for create_project.
        customer_name="Retry Corp",  # What: Customer name; Why: Company name.
        customer_email="admin@retry.com",  # What: Customer email; Why: Contact.
        tier=PlanTier.GROWTH,  # What: Growth tier; Why: Selected tier.
        idempotency_key="key_retry_test_1"  # What: Unique key; Why: Idempotency key.
    )  # What: End of request construction; Why: Ready for execution.

    resp = client.create_project(req, correlation_id="corr_retry_test")  # What: Execute create_project; Why: Triggers retried HTTP call.
    assert attempts["count"] == 3  # What: Assert 3 attempts made; Why: Proves tenacity retried twice and succeeded on 3rd attempt.
    assert resp.project_id == "proj_recovered_500"  # What: Assert recovered project ID; Why: Confirms successful result returned.


def test_rocketlane_client_idempotency_file_persistence(tmp_path: Path) -> None:  # What: Persistence test; Why: Verifies idempotency survives across client instances and process restarts.
    """Guarantees that idempotency cache persists to local JSON file and survives client re-instantiation."""  # What: Docstring; Why: Explains test intent.
    cache_file = tmp_path / "idempotency_cache.json"  # What: Create temporary cache file path; Why: Isolates test from live cache.
    client1 = RocketlaneClient(mock_mode=True, cache_file_path=cache_file)  # What: First client instance; Why: Creates project and writes cache to disk.
    req = client1.resolve_tier_payload(  # What: Build request payload; Why: Test deal data.
        customer_name="Persistent Corp",  # What: Customer name; Why: Test company name.
        customer_email="admin@persistent.com",  # What: Customer email; Why: Contact email.
        tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan tier.
        idempotency_key="key_persistent_test_001"  # What: Static key; Why: Unique idempotency key.
    )  # What: End of payload construction; Why: Ready for execution.

    resp1 = client1.create_project(req, correlation_id="corr_p1")  # What: First creation call; Why: Provisions and writes to cache file.
    assert resp1.is_duplicate is False  # What: Assert first creation is not duplicate; Why: Fresh project.
    assert cache_file.exists()  # What: Assert cache file created on disk; Why: Proves local file persistence.

    # Re-instantiate client simulating process restart
    client2 = RocketlaneClient(mock_mode=True, cache_file_path=cache_file)  # What: Second client instance; Why: Reads existing cache file from disk.
    resp2 = client2.create_project(req, correlation_id="corr_p2")  # What: Second creation call with identical key; Why: Must detect duplicate from disk cache.
    assert resp2.is_duplicate is True  # What: Assert is_duplicate is True; Why: Proves idempotency survived restart.
    assert resp2.project_id == resp1.project_id  # What: Assert project ID matches; Why: Reuses same project.


def test_rocketlane_client_self_healing_cloud_reconciliation_on_400_duplicate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # What: Self-healing cloud test; Why: Verifies cloud recovery on duplicate externalReferenceId HTTP 400.
    """Verifies that Rocketlane HTTP 400 'Invalid External Reference Key' triggers cloud query and updates local cache."""  # What: Docstring; Why: Documents test intent.
    cache_file = tmp_path / "self_heal_cache.json"  # What: Isolated cache file; Why: Prevents test pollution.
    client = RocketlaneClient(mock_mode=False, cache_file_path=cache_file)  # What: Client in live mode; Why: Exercises _execute_http_post and reconciliation.

    # 1. Mock post to return 400 Invalid External Reference Key specified
    class Mock400DuplicateResponse:  # What: Dummy HTTP response; Why: Emulates Rocketlane duplicate key 400.
        status_code = 400  # What: HTTP 400; Why: Rocketlane client error status.
        text = '{"errors":[{"code":"INVALID_INPUTS","reason":"Bad Request: Invalid External Reference Key specified"}]}'  # What: Rocketlane collision payload; Why: Exact error string returned by API.
        def json(self):  # What: JSON helper; Why: Returns dict.
            return {"errors": [{"code": "INVALID_INPUTS", "reason": "Bad Request: Invalid External Reference Key specified"}]}  # What: Error dictionary; Why: Parsed JSON.

    # 2. Mock get to return the existing cloud project matching externalReferenceId
    class Mock200QueryResponse:  # What: Dummy HTTP response for GET /projects; Why: Emulates Rocketlane query result.
        status_code = 200  # What: HTTP 200; Why: Successful query.
        text = '{"data":[{"projectId": 5000000208093, "projectName": "CyberScript Systems - Onboarding (ENTERPRISE)"}]}'  # What: Query response JSON text; Why: Contains matching project.
        def json(self):  # What: JSON helper; Why: Returns dict.
            return {"data": [{"projectId": 5000000208093, "projectName": "CyberScript Systems - Onboarding (ENTERPRISE)"}]}  # What: Parsed dictionary; Why: Wraps project in data list.

    monkeypatch.setattr(client._client, "post", lambda *args, **kwargs: Mock400DuplicateResponse())  # What: Patch post method; Why: Returns 400 collision.
    monkeypatch.setattr(client._client, "get", lambda *args, **kwargs: Mock200QueryResponse())  # What: Patch get method; Why: Returns existing project.

    req = client.resolve_tier_payload(  # What: Build create request; Why: Request payload.
        customer_name="CyberScript Systems",  # What: Customer name; Why: Company name.
        customer_email="sarah@cyberscript.com",  # What: Customer email; Why: Contact.
        tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected tier.
        idempotency_key="d7fcf2a9c598d37763531f3fb12f85a7aae9f46783df76e1755d504bed430a5c"  # What: Colliding key; Why: Exact key in collision.
    )  # What: End of request construction; Why: Ready for execution.

    resp = client.create_project(req, correlation_id="corr_heal_001")  # What: Call create_project; Why: Triggers self-healing flow.
    assert resp.is_duplicate is True  # What: Assert is_duplicate is True; Why: Reconciled from cloud.
    assert resp.project_id == "5000000208093"  # What: Assert project ID; Why: Matches cloud project.
    assert resp.project_name == "CyberScript Systems - Onboarding (ENTERPRISE)"  # What: Assert project name; Why: Restored from cloud.
    assert cache_file.exists()  # What: Assert cache file written; Why: Confirms disk persistence.

    # 3. Subsequent call should hit cache without network calls
    resp2 = client.create_project(req, correlation_id="corr_heal_002")  # What: Call create_project again; Why: Must hit local cache.
    assert resp2.is_duplicate is True  # What: Assert duplicate; Why: Cached hit.
    assert resp2.project_id == "5000000208093"  # What: Assert project ID; Why: Cached ID returned.


