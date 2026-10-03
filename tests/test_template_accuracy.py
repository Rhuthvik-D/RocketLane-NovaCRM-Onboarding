"""Dedicated test suite validating template accuracy, staffing model assignment, and wire compliance."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.core.config import settings
from src.models.schemas import PlanTier, VoiceCallResult, VoiceCallStatus
from src.services.rocketlane_client import RocketlaneClient
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


# ==============================================================================
# TA-1: LIVE CANONICAL ENTERPRISE TEMPLATE & DEDICATED STAFFING ACCURACY
# ==============================================================================

def test_ta1_enterprise_template_and_staffing_accuracy_live() -> None:
    """Verifies Enterprise deal maps strictly to 30-day template 5000000095997 and Dedicated CSM across Rocketlane and Slack."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"ta1_live_ent_{test_ts}"
    customer_name = f"Enterprise Apex {test_ts}"
    customer_email = f"lead_{test_ts}@enterpriseapex.com"

    # 1. Inbound deal email payload
    email_payload = {
        "message_id": f"msg_ta1_live_{test_ts}",
        "customer_name": customer_name,
        "customer_contact_email": customer_email,
        "ae_name": "Marcus Vance",
        "ae_phone": "+1-555-0199",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    # 2. Inject verified Enterprise voice confirmation
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_ta1_live_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript=f"I confirm that {customer_name} is on the Enterprise tier with 30-day onboarding.",
            confidence_score=0.99
        )
    )

    # 3. Execute Agent 1: Live Rocketlane project creation with Enterprise template
    a1_result = agent1.process_deal(email_payload, correlation_id=correlation_id)
    assert a1_result.status == "SUCCESS"
    assert a1_result.rocketlane_project is not None
    assert a1_result.rocketlane_project.tier == PlanTier.ENTERPRISE
    assert a1_result.rocketlane_project.template_id == "5000000095997"
    assert "https://app.rocketlane.com/projects/" in a1_result.rocketlane_project.portal_url
    print(f"\n[+] LIVE ROCKETLANE ENTERPRISE PROJECT: {a1_result.rocketlane_project.portal_url}")

    # 4. Execute Agent 2: Live Slack channel and Enterprise roadmap verification
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result.channel_name.startswith("csm-ent-")
    assert a2_result.provisioning_result.channel_id.startswith("C")
    assert "Plan: ENTERPRISE" in a2_result.channel_payload.topic
    assert "Enterprise Onboarding Program" in a2_result.channel_payload.welcome_message
    assert "30-day timeline" in a2_result.channel_payload.welcome_message
    assert "Dedicated Customer Success Manager" in a2_result.channel_payload.welcome_message
    assert "calendly.com/novacrm-enterprise/kickoff" in a2_result.channel_payload.welcome_message
    print(f"[+] LIVE SLACK ENTERPRISE CHANNEL: #{a2_result.provisioning_result.channel_name} (ID: {a2_result.provisioning_result.channel_id})")


# ==============================================================================
# TA-2: LIVE CANONICAL GROWTH TEMPLATE & POOLED STAFFING ACCURACY
# ==============================================================================

def test_ta2_growth_template_and_staffing_accuracy_live() -> None:
    """Verifies Growth deal maps strictly to 14-day template 5000000096288 and Pooled CSM across Rocketlane and Slack."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"ta2_live_grw_{test_ts}"
    customer_name = f"Growth Velocity {test_ts}"
    customer_email = f"team_{test_ts}@growthvelocity.io"

    # 1. Inbound deal email payload
    email_payload = {
        "message_id": f"msg_ta2_live_{test_ts}",
        "customer_name": customer_name,
        "customer_contact_email": customer_email,
        "ae_name": "Elena Rostova",
        "ae_phone": "+1-555-0244",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    # 2. Inject verified Growth voice confirmation
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_ta2_live_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.GROWTH,
            transcript=f"Hi, Elena confirming that {customer_name} is on the Growth fast-track plan.",
            confidence_score=0.97
        )
    )

    # 3. Execute Agent 1: Live Rocketlane project creation with Growth template
    a1_result = agent1.process_deal(email_payload, correlation_id=correlation_id)
    assert a1_result.status == "SUCCESS"
    assert a1_result.rocketlane_project is not None
    assert a1_result.rocketlane_project.tier == PlanTier.GROWTH
    assert a1_result.rocketlane_project.template_id == "5000000096288"
    assert "https://app.rocketlane.com/projects/" in a1_result.rocketlane_project.portal_url
    print(f"\n[+] LIVE ROCKETLANE GROWTH PROJECT: {a1_result.rocketlane_project.portal_url}")

    # 4. Execute Agent 2: Live Slack channel and Growth roadmap verification
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result.channel_name.startswith("csm-grw-")
    assert a2_result.provisioning_result.channel_id.startswith("C")
    assert "Plan: GROWTH" in a2_result.channel_payload.topic
    assert "Growth Fast-Track Onboarding" in a2_result.channel_payload.welcome_message
    assert "14-day timeline" in a2_result.channel_payload.welcome_message
    assert "Pooled Customer Success Team" in a2_result.channel_payload.welcome_message
    assert "Weekly Live Office Hours" in a2_result.channel_payload.welcome_message
    assert "docs.novacrm.com/getting-started" in a2_result.channel_payload.welcome_message
    print(f"[+] LIVE SLACK GROWTH CHANNEL: #{a2_result.provisioning_result.channel_name} (ID: {a2_result.provisioning_result.channel_id})")


# ==============================================================================
# TA-3: STRICT ZERO-GUESSWORK GUARDRAIL ON UNVERIFIED OR UNKNOWN TIER
# ==============================================================================

def test_ta3_unverified_tier_strictly_rejects_without_template_fallback() -> None:
    """Guarantees that resolve_tier_payload raises ValueError when given PlanTier.UNKNOWN, preventing template guesswork."""
    client = RocketlaneClient(mock_mode=True)

    # 1. Attempt to resolve payload with unverified UNKNOWN tier
    with pytest.raises(ValueError) as exc_info:
        client.resolve_tier_payload(
            customer_name="Phantom Corp",
            customer_email="contact@phantomcorp.com",
            tier=PlanTier.UNKNOWN,
            idempotency_key="key_unknown_tier_guard"
        )

    # 2. Assert exception details enforce zero-guesswork mandate
    assert "Cannot provision project for unverified or unsupported tier" in str(exc_info.value)
    assert "UNKNOWN" in str(exc_info.value)
    print("\n[+] TA-3 PASSED: System strictly refused to provision template for PlanTier.UNKNOWN")


# ==============================================================================
# TA-4: TEMPLATE BOUNDARY ISOLATION & ANTI-CROSS-CONTAMINATION
# ==============================================================================

def test_ta4_template_boundary_isolation_and_cross_contamination() -> None:
    """Verifies that Enterprise and Growth templates, durations, CSM models, and copy are mutually exclusive."""
    client = RocketlaneClient(mock_mode=True)
    comm_agent = Agent2Communication(client=SlackClient(mock_mode=True))

    ent_req = client.resolve_tier_payload("Acme Ent", "acme@ent.com", PlanTier.ENTERPRISE, "key_ent_iso")
    grw_req = client.resolve_tier_payload("Beta Grw", "beta@grw.com", PlanTier.GROWTH, "key_grw_iso")

    # 1. Assert template ID and timeline mutual exclusivity
    assert ent_req.template_id != grw_req.template_id
    assert ent_req.template_id == "5000000095997"
    assert grw_req.template_id == "5000000096288"
    assert ent_req.duration_days == 30
    assert grw_req.duration_days == 14
    assert ent_req.csm_type == "Dedicated CSM"
    assert grw_req.csm_type == "Pooled CSM"

    # 2. Generate welcome messages for both tiers
    ent_msg = comm_agent.format_welcome_message("Acme Ent", PlanTier.ENTERPRISE, "https://app.rocketlane.com/projects/ent1", ent_req.csm_assigned)
    grw_msg = comm_agent.format_welcome_message("Beta Grw", PlanTier.GROWTH, "https://app.rocketlane.com/projects/grw1", grw_req.csm_assigned)

    # 3. Assert zero copy leakage from Growth into Enterprise
    assert "Pooled Customer Success Team" not in ent_msg
    assert "Weekly Live Office Hours" not in ent_msg
    assert "14-day timeline" not in ent_msg

    # 4. Assert zero copy leakage from Enterprise into Growth
    assert "Dedicated Customer Success Manager" not in grw_msg
    assert "calendly.com/novacrm-enterprise" not in grw_msg
    assert "30-day timeline" not in grw_msg

    print("\n[+] TA-4 PASSED: Enterprise and Growth configurations and communications are strictly isolated with zero cross-contamination.")


# ==============================================================================
# TA-5: ROCKETLANE API PAYLOAD STRUCTURE & TEMPLATE SOURCE WIRE COMPLIANCE
# ==============================================================================

def test_ta5_rocketlane_template_source_schema_wire_compliance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verifies that the JSON wire payload sent to Rocketlane /projects formats templateId as integer and startDate in ISO format."""
    client = RocketlaneClient(mock_mode=False, cache_file_path=tmp_path / "ta5_cache.json")
    captured_payloads: list[dict[str, Any]] = []
    unique_ts = int(datetime.now().timestamp() * 1000)

    # Monkeypatch private HTTP execution to capture wire payload without duplicating 35-second cloud clones
    def fake_execute_post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured_payloads.append(payload)
        return {
            "projectId": "5000000099999",
            "projectName": payload.get("projectName", "Test Project"),
            "status": "ACTIVE"
        }

    monkeypatch.setattr(client, "_execute_http_post", fake_execute_post)

    # 1. Dispatch Enterprise project creation
    ent_key = f"idemp_wire_ent_{unique_ts}"
    ent_request = client.resolve_tier_payload("OmniCorp", "alex@omnicorp.com", PlanTier.ENTERPRISE, ent_key)
    client.create_project(ent_request, correlation_id="ta5_wire_ent")

    # 2. Dispatch Growth project creation
    grw_key = f"idemp_wire_grw_{unique_ts}"
    grw_request = client.resolve_tier_payload("MiniCorp", "bob@minicorp.com", PlanTier.GROWTH, grw_key)
    client.create_project(grw_request, correlation_id="ta5_wire_grw")

    # 3. Assert Enterprise wire schema compliance
    assert len(captured_payloads) == 2
    ent_wire = captured_payloads[0]
    assert ent_wire["projectName"] == "OmniCorp - Onboarding (ENTERPRISE)"
    assert ent_wire["customer"]["companyName"] == "OmniCorp"
    assert ent_wire["autoCreateCompany"] is True
    assert ent_wire["externalReferenceId"] == ent_key
    assert "sources" in ent_wire
    assert len(ent_wire["sources"]) == 1
    assert ent_wire["sources"][0]["templateId"] == 5000000095997
    assert isinstance(ent_wire["sources"][0]["templateId"], int)
    assert len(ent_wire["sources"][0]["startDate"].split("-")) == 3

    # 4. Assert Growth wire schema compliance
    grw_wire = captured_payloads[1]
    assert grw_wire["projectName"] == "MiniCorp - Onboarding (GROWTH)"
    assert grw_wire["customer"]["companyName"] == "MiniCorp"
    assert grw_wire["externalReferenceId"] == grw_key
    assert grw_wire["sources"][0]["templateId"] == 5000000096288
    assert isinstance(grw_wire["sources"][0]["templateId"], int)

    print("\n[+] TA-5 PASSED: Rocketlane wire payloads strictly comply with templateId integer typing and ISO date schema.")
