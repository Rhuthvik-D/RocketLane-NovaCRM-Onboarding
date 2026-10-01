# Dedicated Edge Cases test suite verifying resilience, backoff retries, ambiguity guardrails, and stage-gates.  # What: Module header; Why: Proves failure handling and edge case boundaries.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps in test payloads.
from pathlib import Path  # What: Import Path class; Why: Resolves isolated test cache paths.
from typing import Any  # What: Import Any; Why: Type annotations for payload objects.
import httpx  # What: Import httpx; Why: Emulates low-level HTTP responses and network exceptions.
import pytest  # What: Import pytest; Why: Test assertion and execution framework.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent 1; Why: Evaluates intake pipeline edge cases.
from src.agents.agent2_communication import Agent2Communication  # What: Import Agent 2; Why: Evaluates communication agent error boundaries.
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper  # What: Import Agent 3; Why: Evaluates data migration stage-gates.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits failure entries.
from src.core.exceptions import RocketlaneAPIError  # What: Import RocketlaneAPIError; Why: Asserted on upstream outages.
from src.models.schemas import (  # What: Import domain models; Why: Type contracts across test cases.
    DataMigrationSignOffPayload,  # What: Sign-off payload schema; Why: Input for Data QA stage-gate.
    PlanTier,  # What: Plan tier enum; Why: Subscription tiers.
    VoiceCallResult,  # What: Voice call result model; Why: Simulates telephony responses.
    VoiceCallStatus  # What: Voice call status enum; Why: AMBIGUOUS, UNANSWERED, and CONFIRMED states.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Tests retry backoff and idempotency.
from src.services.slack_client import SlackClient  # What: Import SlackClient; Why: Tests Slack skipping on upstream failure.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Simulates phone call outcomes.


# ==============================================================================
# EDGE-1: ROCKETLANE TRANSIENT 500/503 RETRIES & RECOVERS VIA EXPONENTIAL BACKOFF
# ==============================================================================

def test_edge1_rocketlane_transient_500_retries_and_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # What: Test EDGE-1; Why: Proves transient 500 errors trigger exponential backoff and recover.
    """Verifies that transient HTTP 500 server errors trigger Tenacity retries and self-heal on attempt 3."""  # What: Docstring; Why: Documents EDGE-1 intent.
    client = RocketlaneClient(mock_mode=False, cache_file_path=tmp_path / "edge1_cache.json")  # What: Client with isolated cache; Why: Ensures fresh execution path.
    attempts = {"count": 0}  # What: Attempt counter dict; Why: Tracks HTTP dispatch attempts.

    def mock_post_with_transient_failures(url: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:  # What: Mock HTTP POST function; Why: Simulates 2 failures followed by 1 recovery.
        attempts["count"] += 1  # What: Increment attempt counter; Why: Records attempt count.
        if attempts["count"] < 3:  # What: Check if under 3 attempts; Why: Simulates transient 500/503 errors on attempts 1 and 2.
            req = httpx.Request("POST", url)  # What: Create dummy request; Why: Required by httpx.Response.
            return httpx.Response(status_code=503, text="Service Temporarily Unavailable", request=req)  # What: Return HTTP 503 response; Why: Triggers retry logic.
        req = httpx.Request("POST", url)  # What: Create dummy request; Why: Required by httpx.Response.
        return httpx.Response(status_code=200, json={"projectId": "5000000077777", "projectName": json.get("projectName", "Test")}, request=req)  # What: Return HTTP 200 response; Why: Proves recovery.

    monkeypatch.setattr(client._client, "post", mock_post_with_transient_failures)  # What: Monkeypatch httpx post; Why: Injects transient failure behavior.

    # Execute project creation
    request_model = client.resolve_tier_payload("Transient Corp", "ops@transient.com", PlanTier.ENTERPRISE, "idemp_edge1_test")  # What: Build request; Why: Test payload.
    response = client.create_project(request_model, correlation_id="edge1_corr")  # What: Call create_project; Why: Triggers retried POST.

    # 1. Assert exactly 3 attempts executed
    assert attempts["count"] == 3  # What: Assert 3 attempts; Why: Proves exponential backoff retried twice before succeeding.
    assert response.project_id == "5000000077777"  # What: Assert project ID; Why: Proves successful recovery on attempt 3.
    assert response.is_duplicate is False  # What: Assert newly created; Why: Not a duplicate.

    # 2. Assert downstream Agent 2 proceeds smoothly with recovered project
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Mock Slack client; Why: Evaluates Agent 2 handoff.
    from src.models.schemas import Agent1Result, InboundEmailPayload  # What: Import schemas; Why: Builds Agent 1 handoff fixture.
    fake_a1_result = Agent1Result(  # What: Construct handoff payload; Why: Feeds recovered project to Agent 2.
        correlation_id="edge1_corr",  # What: Correlation ID; Why: Deal trace.
        status="SUCCESS",  # What: Success status; Why: Recovered successfully.
        email_payload=InboundEmailPayload(message_id="msg_edge1_test", customer_name="Transient Corp", customer_contact_email="ops@transient.com", ae_name="Sam", ae_phone="+15550100"),  # What: Email payload with message_id; Why: Complete validated payload schema.
        rocketlane_project=response  # What: Attach recovered project; Why: Project workspace data.
    )  # What: End of fixture; Why: Ready for handoff.
    a2_result = agent2.process_project_handoff(fake_a1_result)  # What: Execute Agent 2; Why: Verifies Slack provisioning proceeds.
    assert a2_result.status == "SUCCESS"  # What: Assert Agent 2 SUCCESS; Why: Downstream unaffected by transient upstream glitch.
    print(f"\n[+] EDGE-1 PASSED: Rocketlane recovered after {attempts['count']} attempts via exponential backoff; Slack provisioned.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# EDGE-2: ROCKETLANE COMPLETE OUTAGE HALTS PIPELINE & BLOCKS SLACK
# ==============================================================================

def test_edge2_rocketlane_complete_outage_halts_and_blocks_slack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # What: Test EDGE-2; Why: Proves persistent Rocketlane outage halts pipeline without creating phantom Slack channels.
    """Verifies that persistent Rocketlane downtime exhausts retries, raises RocketlaneAPIError, and blocks Slack provisioning."""  # What: Docstring; Why: Documents EDGE-2 intent.
    client = RocketlaneClient(mock_mode=False, cache_file_path=tmp_path / "edge2_cache.json")  # What: Client with isolated cache; Why: Ensures fresh state.
    attempts = {"count": 0}  # What: Attempt counter dict; Why: Tracks HTTP dispatch attempts.

    def mock_post_persistent_failure(url: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:  # What: Mock function; Why: Simulates persistent 500 server crash across all retries.
        attempts["count"] += 1  # What: Increment attempt counter; Why: Records attempt count.
        req = httpx.Request("POST", url)  # What: Create dummy request; Why: Required by httpx.Response.
        return httpx.Response(status_code=500, text="Internal Server Error: Database Unreachable", request=req)  # What: Return 500 response; Why: Simulates persistent server outage.

    monkeypatch.setattr(client._client, "post", mock_post_persistent_failure)  # What: Monkeypatch httpx post; Why: Injects persistent failure behavior.

    # 1. Attempt project creation and assert retry exhaustion raises RocketlaneAPIError
    request_model = client.resolve_tier_payload("Outage Corp", "admin@outage.com", PlanTier.GROWTH, "idemp_edge2_test")  # What: Build request; Why: Test payload.
    with pytest.raises(RocketlaneAPIError) as exc_info:  # What: Assert RocketlaneAPIError raised; Why: System must fail fast on persistent downtime.
        client.create_project(request_model, correlation_id="edge2_corr")  # What: Call create_project; Why: Triggers retry exhaustion.

    # 2. Verify exactly 3 attempts executed before raising
    assert attempts["count"] == 3  # What: Assert 3 attempts; Why: Maximum retry limit respected.
    assert exc_info.value.status_code == 500  # What: Assert 500 status code; Why: Confirms error context preserved.

    # 3. Verify failed deal was NOT cached (cache remains clean for re-drive)
    assert "idemp_edge2_test" not in client._idempotency_cache  # What: Assert key not in cache; Why: Prevents caching broken states.

    # 4. Verify downstream Agent 2 strictly refuses to create a Slack channel
    from src.models.schemas import Agent1Result  # What: Import Agent1Result; Why: Simulates failed upstream result.
    failed_a1_result = Agent1Result(  # What: Construct unconfirmed result; Why: Simulates failed Agent 1 state.
        correlation_id="edge2_corr",  # What: Correlation ID; Why: Deal trace.
        status="HALTED_MISSING_DATA",  # What: Halted status; Why: Upstream failed.
        rocketlane_project=None  # What: None project; Why: Project was never created due to outage.
    )  # What: End of failed result; Why: Fixture ready.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Agent 2 instance; Why: Tests precondition guardrail.
    a2_result = agent2.process_project_handoff(failed_a1_result)  # What: Call Agent 2 handoff; Why: Tests Slack safety.
    assert a2_result.status == "SKIPPED_UNCONFIRMED"  # What: Assert SKIPPED; Why: Zero phantom Slack channels created when Rocketlane is down.
    assert a2_result.provisioning_result is None  # What: Assert None result; Why: Proves no Slack channel created.
    print(f"\n[+] EDGE-2 PASSED: Persistent Rocketlane outage failed gracefully after {attempts['count']} retries; Zero phantom Slack channels created.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# EDGE-3: TELEPHONY AMBIGUITY HALTS PIPELINE & GENERATES ESCALATION TICKET
# ==============================================================================

def test_edge3_telephony_ambiguity_halts_and_creates_escalation_ticket(tmp_path: Path) -> None:  # What: Test EDGE-3; Why: Proves ambiguous voice confirmation triggers human escalation and halts pipeline.
    """Verifies that non-committal AE verbal answers (hedge words) halt project creation and create an EscalationTicket."""  # What: Docstring; Why: Documents EDGE-3 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=True, cache_file_path=tmp_path / "edge3_cache.json")  # What: Mock Rocketlane client; Why: Proves no project created.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Injects ambiguous telephony outcome.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Mock Slack client; Why: Evaluates downstream skipping.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate timestamp; Why: Unique identifier.
    correlation_id = f"edge3_amb_{test_ts}"  # What: Correlation ID; Why: Tracks deal.

    # 1. Inbound raw email notification
    raw_email = {  # What: Valid email dictionary; Why: Deal email with omitted tier.
        "message_id": f"msg_edge3_{test_ts}",  # What: Message ID; Why: Email identifier.
        "customer_name": f"Hedge Corp {test_ts}",  # What: Customer company; Why: Deal name.
        "customer_contact_email": f"cfo_{test_ts}@hedgecorp.com",  # What: Contact email; Why: Collaborator email.
        "ae_name": "Oliver Queen",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0811"  # What: AE phone; Why: Dial target.
    }  # What: End of email dictionary; Why: Complete email payload.

    # 2. Inject ambiguous verbal confirmation with hedge words
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Injects non-committal speech response.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Ambiguous telephony model.
            call_id=f"call_edge3_{test_ts}",  # What: Call ID; Why: Call reference.
            status=VoiceCallStatus.AMBIGUOUS,  # What: Status AMBIGUOUS; Why: Uncertain response.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN; Why: No firm tier agreed.
            transcript="I think they might upgrade to Enterprise later, but maybe start with Growth? Not sure, let me check later.",  # What: Ambiguous speech transcript; Why: Contains multiple hedge keywords.
            confidence_score=0.45,  # What: 45% low confidence; Why: Fails confidence threshold.
            escalation_reason="AE mentioned both Enterprise and Growth with explicit hedge keywords ('not sure', 'maybe')."  # What: Reason; Why: Detailed rationale.
        )  # What: End of VoiceCallResult; Why: Ambiguous fixture ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # 3. Execute Agent 1 intake workflow
    a1_result = agent1.process_deal(raw_email, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Evaluates voice guardrail.

    # 4. Assert zero-guesswork guardrail halts execution
    assert a1_result.status == "ESCALATED_VOICE_ISSUE"  # What: Assert status ESCALATED_VOICE_ISSUE; Why: Pipeline halted for human review.
    assert a1_result.rocketlane_project is None  # What: Assert project is None; Why: Zero Rocketlane projects created on ambiguity.
    assert a1_result.escalation_ticket is not None  # What: Assert ticket exists; Why: Structured ticket dispatched for human CS Ops review.
    assert a1_result.escalation_ticket.call_status == VoiceCallStatus.AMBIGUOUS  # What: Assert AMBIGUOUS status; Why: Correctly categorized ticket.
    assert "not sure" in a1_result.escalation_ticket.transcript.lower()  # What: Assert hedge words in ticket transcript; Why: Provides proof to human reviewer.

    # 5. Assert Agent 2 cleanly skips Slack provisioning
    a2_result = agent2.process_project_handoff(a1_result)  # What: Call Agent 2 handoff; Why: Tests downstream protection.
    assert a2_result.status == "SKIPPED_UNCONFIRMED"  # What: Assert SKIPPED; Why: Slack provisioning skipped on unconfirmed deals.
    assert a2_result.provisioning_result is None  # What: Assert None result; Why: Zero Slack channels created.
    print(f"\n[+] EDGE-3 PASSED: Ambiguous voice response halted pipeline; Escalation ticket '{a1_result.escalation_ticket.ticket_id}' generated.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# EDGE-4: TELEPHONY UNANSWERED / RING TIMEOUT HALTS & ESCALATES
# ==============================================================================

def test_edge4_telephony_unanswered_timeout_halts_and_escalates(tmp_path: Path) -> None:  # What: Test EDGE-4; Why: Proves unanswered voice call triggers human escalation without guessing.
    """Verifies that an unanswered call or ringing timeout halts project creation and routes deal to human CS queue."""  # What: Docstring; Why: Documents EDGE-4 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=True, cache_file_path=tmp_path / "edge4_cache.json")  # What: Mock Rocketlane client; Why: Proves no project created.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Injects unanswered telephony outcome.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Mock Slack client; Why: Evaluates downstream skipping.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate timestamp; Why: Unique identifier.
    correlation_id = f"edge4_unans_{test_ts}"  # What: Correlation ID; Why: Tracks deal.

    # 1. Inbound raw email notification
    raw_email = {  # What: Valid email dictionary; Why: Deal email with omitted tier.
        "message_id": f"msg_edge4_{test_ts}",  # What: Message ID; Why: Email identifier.
        "customer_name": f"Silent Corp {test_ts}",  # What: Customer company; Why: Deal name.
        "customer_contact_email": f"ops_{test_ts}@silentcorp.com",  # What: Contact email; Why: Collaborator email.
        "ae_name": "Barry Allen",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0999"  # What: AE phone; Why: Dial target.
    }  # What: End of email dictionary; Why: Complete email payload.

    # 2. Inject unanswered telephony outcome
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Injects unanswered telephony state.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Unanswered telephony model.
            call_id=f"call_edge4_{test_ts}",  # What: Call ID; Why: Call reference.
            status=VoiceCallStatus.UNANSWERED,  # What: Status UNANSWERED; Why: Phone rang with no answer.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN; Why: No confirmation possible.
            transcript="",  # What: Empty transcript; Why: Voicemail / no speech.
            confidence_score=0.0,  # What: Zero confidence; Why: No audio data.
            escalation_reason="AE did not answer the tier confirmation call after ringing timeout."  # What: Reason; Why: Detailed rationale.
        )  # What: End of VoiceCallResult; Why: Unanswered fixture ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # 3. Execute Agent 1 intake workflow
    a1_result = agent1.process_deal(raw_email, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Evaluates voice guardrail.

    # 4. Assert zero-guesswork guardrail halts execution
    assert a1_result.status == "ESCALATED_VOICE_ISSUE"  # What: Assert status ESCALATED_VOICE_ISSUE; Why: Pipeline halted for human review.
    assert a1_result.rocketlane_project is None  # What: Assert project is None; Why: Zero Rocketlane projects created on unanswered call.
    assert a1_result.escalation_ticket is not None  # What: Assert ticket exists; Why: Structured ticket dispatched for human CS Ops review.
    assert a1_result.escalation_ticket.call_status == VoiceCallStatus.UNANSWERED  # What: Assert UNANSWERED status; Why: Correctly categorized ticket.

    # 5. Assert Agent 2 cleanly skips Slack provisioning
    a2_result = agent2.process_project_handoff(a1_result)  # What: Call Agent 2 handoff; Why: Tests downstream protection.
    assert a2_result.status == "SKIPPED_UNCONFIRMED"  # What: Assert SKIPPED; Why: Slack provisioning skipped on unconfirmed deals.
    assert a2_result.provisioning_result is None  # What: Assert None result; Why: Zero Slack channels created.
    print(f"\n[+] EDGE-4 PASSED: Unanswered call halted pipeline; Escalation ticket '{a1_result.escalation_ticket.ticket_id}' logged.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# EDGE-5: DUPLICATE DEAL IDEMPOTENCY PREVENTS DUPLICATE PROVISIONING
# ==============================================================================

def test_edge5_duplicate_deal_idempotency_prevents_duplicate_provisioning(tmp_path: Path) -> None:  # What: Test EDGE-5; Why: Proves duplicate deal emails reuse existing project and prevent duplicate creation.
    """Verifies that duplicate deal ingestion triggers idempotency cache, returning existing project and bypassing redundant work."""  # What: Docstring; Why: Documents EDGE-5 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=True, cache_file_path=tmp_path / "edge5_cache.json")  # What: Isolated cache client; Why: Enforces fresh idempotency store.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Simulates confirmed call.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate timestamp; Why: Unique identifier.
    correlation_id_1 = f"edge5_pass1_{test_ts}"  # What: First correlation ID; Why: Initial run trace.
    correlation_id_2 = f"edge5_pass2_{test_ts}"  # What: Second correlation ID; Why: Duplicate run trace.

    raw_email = {  # What: Valid email dictionary; Why: Deal email payload.
        "message_id": f"msg_edge5_{test_ts}",  # What: Identical message ID; Why: Simulates re-sent deal notification.
        "customer_name": f"Dedupe Dynamics {test_ts}",  # What: Customer company; Why: Deal identity.
        "customer_contact_email": f"lead_{test_ts}@dedupedynamics.com",  # What: Contact email; Why: Primary collaborator.
        "ae_name": "Kara Danvers",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0377"  # What: AE phone; Why: Dial target.
    }  # What: End of email dictionary; Why: Complete payload.

    # 1. Pass 1: Initial successful provisioning
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Injects confirmed Growth tier.
        VoiceCallResult(call_id=f"call_edge5_{test_ts}", status=VoiceCallStatus.CONFIRMED, confirmed_tier=PlanTier.GROWTH, transcript="Confirmed Growth.", confidence_score=0.98)  # What: Confirmed result; Why: Valid confirmation.
    )  # What: End of set_simulation_outcome; Why: Ready.
    result_1 = agent1.process_deal(raw_email, correlation_id=correlation_id_1)  # What: First pass execution; Why: Initial project creation.
    assert result_1.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Initial creation succeeded.
    first_project_id = result_1.rocketlane_project.project_id  # What: Store first project ID; Why: Reference for comparison.

    # 2. Pass 2: Duplicate deal ingestion with identical email payload
    result_2 = agent1.process_deal(raw_email, correlation_id=correlation_id_2)  # What: Second pass execution; Why: Tests idempotency deduplication.
    assert result_2.status == "IDEMPOTENT_DUPLICATE"  # What: Assert status IDEMPOTENT_DUPLICATE; Why: Recognized as duplicate deal.
    assert result_2.rocketlane_project.project_id == first_project_id  # What: Assert matching project ID; Why: Reused original project without creating new one.
    assert result_2.rocketlane_project.is_duplicate is True  # What: Assert is_duplicate is True; Why: Correctly flagged as duplicate entity.
    assert result_2.voice_result is None  # What: Assert no voice call placed on pass 2; Why: Voice AI skipped entirely on duplicate hit.
    print(f"\n[+] EDGE-5 PASSED: Idempotency enforced. Reused project ID '{first_project_id}' without creating duplicate.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# EDGE-6: DATA QA GATEKEEPER BLOCKS UNVERIFIED OR DISCREPANT DATA MIGRATION
# ==============================================================================

def test_edge6_data_qa_gatekeeper_blocks_unverified_migration() -> None:  # What: Test EDGE-6; Why: Proves Data QA Gatekeeper enforces parity and sign-off before unlocking Configuration.
    """Verifies that Data QA Gatekeeper blocks downstream Configuration phase on record discrepancy or missing customer sign-off."""  # What: Docstring; Why: Documents EDGE-6 intent.
    gatekeeper = Agent3DataQAGatekeeper(rocketlane=RocketlaneClient(mock_mode=True), slack=SlackClient(mock_mode=True))  # What: Agent 3 instance; Why: Tests stage-gate rules.

    # -------------------------------------------------------------------------
    # Scenario 6A: Record Parity Discrepancy (10,000 migrated vs 9,850 verified)
    # -------------------------------------------------------------------------
    discrepant_payload = DataMigrationSignOffPayload(  # What: Discrepant payload model; Why: Inbound webhook with parity mismatch.
        project_id="proj_qa_discrepant_01",  # What: Project ID; Why: Target project.
        task_id="task_qa_mig_01",  # What: Task ID; Why: Migration task.
        customer_name="Parity Loss Inc",  # What: Customer name; Why: Project identity.
        records_migrated=10000,  # What: 10,000 records migrated; Why: Total records transferred.
        records_verified=9850,  # What: 9,850 records verified; Why: 150 records missing verification.
        customer_sign_off_confirmed=True,  # What: Sign-off True; Why: Isolates discrepancy rule from sign-off rule.
        sign_off_contact_email="lead@parityloss.com"  # What: Sign-off email; Why: Contact lead.
    )  # What: End of discrepant payload; Why: Fixture ready.

    result_6a = gatekeeper.evaluate_migration_sign_off(discrepant_payload, correlation_id="edge6_discrepancy")  # What: Evaluate 6A; Why: Enforces parity rule.
    assert result_6a.status == "ESCALATED_DISCREPANCY"  # What: Assert status ESCALATED_DISCREPANCY; Why: Mismatch triggers escalation.
    assert result_6a.is_configuration_unlocked is False  # What: Assert Configuration strictly locked; Why: Prevents advancing with corrupted data.
    assert result_6a.discrepancy_count == 150  # What: Assert 150 missing records; Why: Accurate calculation of mismatch.
    assert result_6a.csm_alert_sent is True  # What: Assert CSM alert sent; Why: Alerts CS Ops to fix data.

    # -------------------------------------------------------------------------
    # Scenario 6B: Missing Customer Sign-Off (Customer hasn't approved data)
    # -------------------------------------------------------------------------
    unapproved_payload = DataMigrationSignOffPayload(  # What: Unapproved payload model; Why: Inbound webhook with missing customer sign-off.
        project_id="proj_qa_unapproved_02",  # What: Project ID; Why: Target project.
        task_id="task_qa_mig_02",  # What: Task ID; Why: Migration task.
        customer_name="Hesitant Corp",  # What: Customer name; Why: Project identity.
        records_migrated=5000,  # What: 5,000 records migrated; Why: Clean volume.
        records_verified=5000,  # What: 5,000 records verified; Why: 100% parity.
        customer_sign_off_confirmed=False,  # What: Sign-off False; Why: Customer has not confirmed sign-off.
        sign_off_contact_email="vp@hesitant.com"  # What: Sign-off email; Why: Contact lead.
    )  # What: End of unapproved payload; Why: Fixture ready.

    result_6b = gatekeeper.evaluate_migration_sign_off(unapproved_payload, correlation_id="edge6_unapproved")  # What: Evaluate 6B; Why: Enforces explicit sign-off rule.
    assert result_6b.status == "REJECTED_BLOCKED"  # What: Assert status REJECTED_BLOCKED; Why: Missing sign-off blocks phase transition.
    assert result_6b.is_configuration_unlocked is False  # What: Assert Configuration strictly locked; Why: Prevents unverified go-lives.
    assert "Customer data verification sign-off is missing" in result_6b.audit_rationale  # What: Assert rationale text; Why: Explains blocker clearly.

    print("\n[+] EDGE-6 PASSED: Data QA Gatekeeper strictly kept Configuration phase locked under both discrepancy and unapproved sign-off conditions.")  # What: Print confirmation; Why: Terminal visibility.
