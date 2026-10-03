"""Dedicated Edge Cases test suite verifying resilience, backoff retries, ambiguity guardrails, and stage-gates."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper
from src.core.audit_logger import audit_logger
from src.core.exceptions import RocketlaneAPIError
from src.models.schemas import (
    DataMigrationSignOffPayload,
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus
)
from src.services.rocketlane_client import RocketlaneClient
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


# ==============================================================================
# EDGE-1: ROCKETLANE TRANSIENT 500/503 RETRIES & RECOVERS VIA EXPONENTIAL BACKOFF
# ==============================================================================

def test_edge1_rocketlane_transient_500_retries_and_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that transient HTTP 500 server errors trigger Tenacity retries and self-heal on attempt 3."""
    client = RocketlaneClient(mock_mode=False, cache_file_path=tmp_path / "edge1_cache.json")
    attempts = {"count": 0}

    def mock_post_with_transient_failures(url: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            req = httpx.Request("POST", url)
            return httpx.Response(status_code=503, text="Service Temporarily Unavailable", request=req)
        req = httpx.Request("POST", url)
        return httpx.Response(status_code=200, json={"projectId": "5000000077777", "projectName": json.get("projectName", "Test")}, request=req)

    monkeypatch.setattr(client._client, "post", mock_post_with_transient_failures)

    # Execute project creation
    request_model = client.resolve_tier_payload("Transient Corp", "ops@transient.com", PlanTier.ENTERPRISE, "idemp_edge1_test")
    response = client.create_project(request_model, correlation_id="edge1_corr")

    # 1. Assert exactly 3 attempts executed
    assert attempts["count"] == 3
    assert response.project_id == "5000000077777"
    assert response.is_duplicate is False

    # 2. Assert downstream Agent 2 proceeds smoothly with recovered project
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))
    from src.models.schemas import Agent1Result, InboundEmailPayload
    fake_a1_result = Agent1Result(
        correlation_id="edge1_corr",
        status="SUCCESS",
        email_payload=InboundEmailPayload(message_id="msg_edge1_test", customer_name="Transient Corp", customer_contact_email="ops@transient.com", ae_name="Sam", ae_phone="+15550100"),
        rocketlane_project=response
    )
    a2_result = agent2.process_project_handoff(fake_a1_result)
    assert a2_result.status == "SUCCESS"
    print(f"\n[+] EDGE-1 PASSED: Rocketlane recovered after {attempts['count']} attempts via exponential backoff; Slack provisioned.")


# ==============================================================================
# EDGE-2: ROCKETLANE COMPLETE OUTAGE HALTS PIPELINE & BLOCKS SLACK
# ==============================================================================

def test_edge2_rocketlane_complete_outage_halts_and_blocks_slack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that persistent Rocketlane downtime exhausts retries, raises RocketlaneAPIError, and blocks Slack provisioning."""
    client = RocketlaneClient(mock_mode=False, cache_file_path=tmp_path / "edge2_cache.json")
    attempts = {"count": 0}

    def mock_post_persistent_failure(url: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        attempts["count"] += 1
        req = httpx.Request("POST", url)
        return httpx.Response(status_code=500, text="Internal Server Error: Database Unreachable", request=req)

    monkeypatch.setattr(client._client, "post", mock_post_persistent_failure)

    # 1. Attempt project creation and assert retry exhaustion raises RocketlaneAPIError
    request_model = client.resolve_tier_payload("Outage Corp", "admin@outage.com", PlanTier.GROWTH, "idemp_edge2_test")
    with pytest.raises(RocketlaneAPIError) as exc_info:
        client.create_project(request_model, correlation_id="edge2_corr")

    # 2. Verify exactly 3 attempts executed before raising
    assert attempts["count"] == 3
    assert exc_info.value.status_code == 500

    # 3. Verify failed deal was NOT cached (cache remains clean for re-drive)
    assert "idemp_edge2_test" not in client._idempotency_cache

    # 4. Verify downstream Agent 2 strictly refuses to create a Slack channel
    from src.models.schemas import Agent1Result
    failed_a1_result = Agent1Result(
        correlation_id="edge2_corr",
        status="HALTED_MISSING_DATA",
        rocketlane_project=None
    )
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))
    a2_result = agent2.process_project_handoff(failed_a1_result)
    assert a2_result.status == "SKIPPED_UNCONFIRMED"
    assert a2_result.provisioning_result is None
    print(f"\n[+] EDGE-2 PASSED: Persistent Rocketlane outage failed gracefully after {attempts['count']} retries; Zero phantom Slack channels created.")


# ==============================================================================
# EDGE-3: TELEPHONY AMBIGUITY HALTS PIPELINE & GENERATES ESCALATION TICKET
# ==============================================================================

def test_edge3_telephony_ambiguity_halts_and_creates_escalation_ticket(tmp_path: Path) -> None:
    """Verifies that non-committal AE verbal answers (hedge words) halt project creation and create an EscalationTicket."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True, cache_file_path=tmp_path / "edge3_cache.json")
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"edge3_amb_{test_ts}"

    # 1. Inbound raw email notification
    raw_email = {
        "message_id": f"msg_edge3_{test_ts}",
        "customer_name": f"Hedge Corp {test_ts}",
        "customer_contact_email": f"cfo_{test_ts}@hedgecorp.com",
        "ae_name": "Oliver Queen",
        "ae_phone": "+1-555-0811"
    }

    # 2. Inject ambiguous verbal confirmation with hedge words
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_edge3_{test_ts}",
            status=VoiceCallStatus.AMBIGUOUS,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="I think they might upgrade to Enterprise later, but maybe start with Growth? Not sure, let me check later.",
            confidence_score=0.45,
            escalation_reason="AE mentioned both Enterprise and Growth with explicit hedge keywords ('not sure', 'maybe')."
        )
    )

    # 3. Execute Agent 1 intake workflow
    a1_result = agent1.process_deal(raw_email, correlation_id=correlation_id)

    # 4. Assert zero-guesswork guardrail halts execution
    assert a1_result.status == "ESCALATED_VOICE_ISSUE"
    assert a1_result.rocketlane_project is None
    assert a1_result.escalation_ticket is not None
    assert a1_result.escalation_ticket.call_status == VoiceCallStatus.AMBIGUOUS
    assert "not sure" in a1_result.escalation_ticket.transcript.lower()

    # 5. Assert Agent 2 cleanly skips Slack provisioning
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SKIPPED_UNCONFIRMED"
    assert a2_result.provisioning_result is None
    print(f"\n[+] EDGE-3 PASSED: Ambiguous voice response halted pipeline; Escalation ticket '{a1_result.escalation_ticket.ticket_id}' generated.")


# ==============================================================================
# EDGE-4: TELEPHONY UNANSWERED / RING TIMEOUT HALTS & ESCALATES
# ==============================================================================

def test_edge4_telephony_unanswered_timeout_halts_and_escalates(tmp_path: Path) -> None:
    """Verifies that an unanswered call or ringing timeout halts project creation and routes deal to human CS queue."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True, cache_file_path=tmp_path / "edge4_cache.json")
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"edge4_unans_{test_ts}"

    # 1. Inbound raw email notification
    raw_email = {
        "message_id": f"msg_edge4_{test_ts}",
        "customer_name": f"Silent Corp {test_ts}",
        "customer_contact_email": f"ops_{test_ts}@silentcorp.com",
        "ae_name": "Barry Allen",
        "ae_phone": "+1-555-0999"
    }

    # 2. Inject unanswered telephony outcome
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_edge4_{test_ts}",
            status=VoiceCallStatus.UNANSWERED,
            confirmed_tier=PlanTier.UNKNOWN,
            transcript="",
            confidence_score=0.0,
            escalation_reason="AE did not answer the tier confirmation call after ringing timeout."
        )
    )

    # 3. Execute Agent 1 intake workflow
    a1_result = agent1.process_deal(raw_email, correlation_id=correlation_id)

    # 4. Assert zero-guesswork guardrail halts execution
    assert a1_result.status == "ESCALATED_VOICE_ISSUE"
    assert a1_result.rocketlane_project is None
    assert a1_result.escalation_ticket is not None
    assert a1_result.escalation_ticket.call_status == VoiceCallStatus.UNANSWERED

    # 5. Assert Agent 2 cleanly skips Slack provisioning
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SKIPPED_UNCONFIRMED"
    assert a2_result.provisioning_result is None
    print(f"\n[+] EDGE-4 PASSED: Unanswered call halted pipeline; Escalation ticket '{a1_result.escalation_ticket.ticket_id}' logged.")


# ==============================================================================
# EDGE-5: DUPLICATE DEAL IDEMPOTENCY PREVENTS DUPLICATE PROVISIONING
# ==============================================================================

def test_edge5_duplicate_deal_idempotency_prevents_duplicate_provisioning(tmp_path: Path) -> None:
    """Verifies that duplicate deal ingestion triggers idempotency cache, returning existing project and bypassing redundant work."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True, cache_file_path=tmp_path / "edge5_cache.json")
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id_1 = f"edge5_pass1_{test_ts}"
    correlation_id_2 = f"edge5_pass2_{test_ts}"

    raw_email = {
        "message_id": f"msg_edge5_{test_ts}",
        "customer_name": f"Dedupe Dynamics {test_ts}",
        "customer_contact_email": f"lead_{test_ts}@dedupedynamics.com",
        "ae_name": "Kara Danvers",
        "ae_phone": "+1-555-0377"
    }

    # 1. Pass 1: Initial successful provisioning
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(call_id=f"call_edge5_{test_ts}", status=VoiceCallStatus.CONFIRMED, confirmed_tier=PlanTier.GROWTH, transcript="Confirmed Growth.", confidence_score=0.98)
    )
    result_1 = agent1.process_deal(raw_email, correlation_id=correlation_id_1)
    assert result_1.status == "SUCCESS"
    first_project_id = result_1.rocketlane_project.project_id

    # 2. Pass 2: Duplicate deal ingestion with identical email payload
    result_2 = agent1.process_deal(raw_email, correlation_id=correlation_id_2)
    assert result_2.status == "IDEMPOTENT_DUPLICATE"
    assert result_2.rocketlane_project.project_id == first_project_id
    assert result_2.rocketlane_project.is_duplicate is True
    assert result_2.voice_result is None
    print(f"\n[+] EDGE-5 PASSED: Idempotency enforced. Reused project ID '{first_project_id}' without creating duplicate.")


# ==============================================================================
# EDGE-6: DATA QA GATEKEEPER BLOCKS UNVERIFIED OR DISCREPANT DATA MIGRATION
# ==============================================================================

def test_edge6_data_qa_gatekeeper_blocks_unverified_migration() -> None:
    """Verifies that Data QA Gatekeeper blocks downstream Configuration phase on record discrepancy or missing customer sign-off."""
    gatekeeper = Agent3DataQAGatekeeper(rocketlane=RocketlaneClient(mock_mode=True), slack=SlackClient(mock_mode=True))

    # -------------------------------------------------------------------------
    # Scenario 6A: Record Parity Discrepancy (10,000 migrated vs 9,850 verified)
    # -------------------------------------------------------------------------
    discrepant_payload = DataMigrationSignOffPayload(
        project_id="proj_qa_discrepant_01",
        task_id="task_qa_mig_01",
        customer_name="Parity Loss Inc",
        records_migrated=10000,
        records_verified=9850,
        customer_sign_off_confirmed=True,
        sign_off_contact_email="lead@parityloss.com"
    )

    result_6a = gatekeeper.evaluate_migration_sign_off(discrepant_payload, correlation_id="edge6_discrepancy")
    assert result_6a.status == "ESCALATED_DISCREPANCY"
    assert result_6a.is_configuration_unlocked is False
    assert result_6a.discrepancy_count == 150
    assert result_6a.csm_alert_sent is True

    # -------------------------------------------------------------------------
    # Scenario 6B: Missing Customer Sign-Off (Customer hasn't approved data)
    # -------------------------------------------------------------------------
    unapproved_payload = DataMigrationSignOffPayload(
        project_id="proj_qa_unapproved_02",
        task_id="task_qa_mig_02",
        customer_name="Hesitant Corp",
        records_migrated=5000,
        records_verified=5000,
        customer_sign_off_confirmed=False,
        sign_off_contact_email="vp@hesitant.com"
    )

    result_6b = gatekeeper.evaluate_migration_sign_off(unapproved_payload, correlation_id="edge6_unapproved")
    assert result_6b.status == "REJECTED_BLOCKED"
    assert result_6b.is_configuration_unlocked is False
    assert "Customer data verification sign-off is missing" in result_6b.audit_rationale

    print("\n[+] EDGE-6 PASSED: Data QA Gatekeeper strictly kept Configuration phase locked under both discrepancy and unapproved sign-off conditions.")
