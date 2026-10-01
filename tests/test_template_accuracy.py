# Dedicated test suite validating template accuracy, staffing model assignment, and wire compliance.  # What: Module header; Why: Proves zero tier mix-ups and strict template mapping.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Generates timestamps for collision-free testing.
from pathlib import Path  # What: Import Path class; Why: Resolves temporary file cache paths.
from typing import Any  # What: Import Any; Why: Type annotations for payload inspection.
import pytest  # What: Import pytest; Why: Test assertion and execution framework.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent 1; Why: Runs intake and live Rocketlane project creation.
from src.agents.agent2_communication import Agent2Communication  # What: Import Agent 2; Why: Runs Slack channel provisioning and messaging.
from src.core.config import settings  # What: Import settings; Why: Retrieves configured template IDs and credentials.
from src.models.schemas import PlanTier, VoiceCallResult, VoiceCallStatus  # What: Import domain models; Why: Type contracts for tiers and voice calls.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Evaluates template resolution and live provisioning.
from src.services.slack_client import SlackClient  # What: Import SlackClient; Why: Evaluates live Slack channel creation and copy formatting.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Telephony client for simulating verbal tier confirmation.


# ==============================================================================
# TA-1: LIVE CANONICAL ENTERPRISE TEMPLATE & DEDICATED STAFFING ACCURACY
# ==============================================================================

def test_ta1_enterprise_template_and_staffing_accuracy_live() -> None:  # What: Test TA-1; Why: Proves live Enterprise onboarding maps to 30d template and Dedicated CSM.
    """Verifies Enterprise deal maps strictly to 30-day template 5000000095997 and Dedicated CSM across Rocketlane and Slack."""  # What: Docstring; Why: Documents TA-1 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion and provisioning orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Hits real Rocketlane REST API.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Simulated Voice AI; Why: Simulates verified Enterprise verbal response.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))  # What: LIVE Slack client; Why: Hits real Slack Web API.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate 5-digit unique timestamp; Why: Prevents resource collisions.
    correlation_id = f"ta1_live_ent_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.
    customer_name = f"Enterprise Apex {test_ts}"  # What: Customer company name; Why: Name to provision.
    customer_email = f"lead_{test_ts}@enterpriseapex.com"  # What: Contact email; Why: Primary collaborator.

    # 1. Inbound deal email payload
    email_payload = {  # What: Raw email dictionary; Why: Simulates incoming Enterprise deal notification.
        "message_id": f"msg_ta1_live_{test_ts}",  # What: Unique message ID; Why: Email identifier.
        "customer_name": customer_name,  # What: Customer name; Why: Extracted customer entity.
        "customer_contact_email": customer_email,  # What: Contact email; Why: Collaborator email.
        "ae_name": "Marcus Vance",  # What: Account Executive name; Why: Deal owner.
        "ae_phone": "+1-555-0199",  # What: AE phone; Why: Used for voice call.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: CRM record.
    }  # What: End of email payload; Why: Complete input dictionary.

    # 2. Inject verified Enterprise voice confirmation
    agent1.voice_client.set_simulation_outcome(  # What: Inject simulation outcome; Why: Verifies Enterprise tier verbally.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Model representing phone call outcome.
            call_id=f"call_ta1_live_{test_ts}",  # What: Call ID; Why: Telephony identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Confirmed status; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan tier.
            transcript=f"I confirm that {customer_name} is on the Enterprise tier with 30-day onboarding.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.99  # What: 99% confidence score; Why: High confidence passes guardrail.
        )  # What: End of VoiceCallResult; Why: Configured telephony result.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # 3. Execute Agent 1: Live Rocketlane project creation with Enterprise template
    a1_result = agent1.process_deal(email_payload, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Provisions live project.
    assert a1_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Ingestion succeeded.
    assert a1_result.rocketlane_project is not None  # What: Assert project exists; Why: Confirms project provisioned in Rocketlane.
    assert a1_result.rocketlane_project.tier == PlanTier.ENTERPRISE  # What: Assert Enterprise tier; Why: Correct tier mapped.
    assert a1_result.rocketlane_project.template_id == "5000000095997"  # What: Assert Enterprise template ID; Why: 30-day Enterprise template applied.
    assert "https://app.rocketlane.com/projects/" in a1_result.rocketlane_project.portal_url  # What: Assert portal URL format; Why: Real workspace link.
    print(f"\n[+] LIVE ROCKETLANE ENTERPRISE PROJECT: {a1_result.rocketlane_project.portal_url}")  # What: Print project link; Why: Terminal visibility.

    # 4. Execute Agent 2: Live Slack channel and Enterprise roadmap verification
    a2_result = agent2.process_project_handoff(a1_result)  # What: Process handoff via Agent 2; Why: Creates Slack channel and welcome message.
    assert a2_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Communication setup succeeded.
    assert a2_result.provisioning_result.channel_name.startswith("csm-ent-")  # What: Assert Enterprise prefix; Why: Verifies channel naming convention.
    assert a2_result.provisioning_result.channel_id.startswith("C")  # What: Assert real Slack channel ID; Why: Real conversation ID from Slack API.
    assert "Plan: ENTERPRISE" in a2_result.channel_payload.topic  # What: Assert Enterprise in topic; Why: Clarifies tier in Slack header.
    assert "Enterprise Onboarding Program" in a2_result.channel_payload.welcome_message  # What: Assert Enterprise program name; Why: High-touch messaging.
    assert "30-day timeline" in a2_result.channel_payload.welcome_message  # What: Assert 30-day timeline; Why: Enforces 30-day SLA in welcome message.
    assert "Dedicated Customer Success Manager" in a2_result.channel_payload.welcome_message  # What: Assert Dedicated CSM; Why: Dedicated staffing model announced.
    assert "calendly.com/novacrm-enterprise/kickoff" in a2_result.channel_payload.welcome_message  # What: Assert Calendly link; Why: Executive kickoff scheduling.
    print(f"[+] LIVE SLACK ENTERPRISE CHANNEL: #{a2_result.provisioning_result.channel_name} (ID: {a2_result.provisioning_result.channel_id})")  # What: Print Slack link; Why: Terminal visibility.


# ==============================================================================
# TA-2: LIVE CANONICAL GROWTH TEMPLATE & POOLED STAFFING ACCURACY
# ==============================================================================

def test_ta2_growth_template_and_staffing_accuracy_live() -> None:  # What: Test TA-2; Why: Proves live Growth onboarding maps to 14d template and Pooled CSM.
    """Verifies Growth deal maps strictly to 14-day template 5000000096288 and Pooled CSM across Rocketlane and Slack."""  # What: Docstring; Why: Documents TA-2 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion and provisioning orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Hits real Rocketlane REST API.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Simulated Voice AI; Why: Simulates verified Growth verbal response.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))  # What: LIVE Slack client; Why: Hits real Slack Web API.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate 5-digit unique timestamp; Why: Prevents resource collisions.
    correlation_id = f"ta2_live_grw_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.
    customer_name = f"Growth Velocity {test_ts}"  # What: Customer company name; Why: Name to provision.
    customer_email = f"team_{test_ts}@growthvelocity.io"  # What: Contact email; Why: Primary collaborator.

    # 1. Inbound deal email payload
    email_payload = {  # What: Raw email dictionary; Why: Simulates incoming Growth deal notification.
        "message_id": f"msg_ta2_live_{test_ts}",  # What: Unique message ID; Why: Email identifier.
        "customer_name": customer_name,  # What: Customer name; Why: Extracted customer entity.
        "customer_contact_email": customer_email,  # What: Contact email; Why: Collaborator email.
        "ae_name": "Elena Rostova",  # What: Account Executive name; Why: Deal owner.
        "ae_phone": "+1-555-0244",  # What: AE phone; Why: Used for voice call.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: CRM record.
    }  # What: End of email payload; Why: Complete input dictionary.

    # 2. Inject verified Growth voice confirmation
    agent1.voice_client.set_simulation_outcome(  # What: Inject simulation outcome; Why: Verifies Growth tier verbally.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Model representing phone call outcome.
            call_id=f"call_ta2_live_{test_ts}",  # What: Call ID; Why: Telephony identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Confirmed status; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.GROWTH,  # What: Growth tier; Why: Selected plan tier.
            transcript=f"Hi, Elena confirming that {customer_name} is on the Growth fast-track plan.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.97  # What: 97% confidence score; Why: High confidence passes guardrail.
        )  # What: End of VoiceCallResult; Why: Configured telephony result.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # 3. Execute Agent 1: Live Rocketlane project creation with Growth template
    a1_result = agent1.process_deal(email_payload, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Provisions live project.
    assert a1_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Ingestion succeeded.
    assert a1_result.rocketlane_project is not None  # What: Assert project exists; Why: Confirms project provisioned in Rocketlane.
    assert a1_result.rocketlane_project.tier == PlanTier.GROWTH  # What: Assert Growth tier; Why: Correct tier mapped.
    assert a1_result.rocketlane_project.template_id == "5000000096288"  # What: Assert Growth template ID; Why: 14-day Growth template applied.
    assert "https://app.rocketlane.com/projects/" in a1_result.rocketlane_project.portal_url  # What: Assert portal URL format; Why: Real workspace link.
    print(f"\n[+] LIVE ROCKETLANE GROWTH PROJECT: {a1_result.rocketlane_project.portal_url}")  # What: Print project link; Why: Terminal visibility.

    # 4. Execute Agent 2: Live Slack channel and Growth roadmap verification
    a2_result = agent2.process_project_handoff(a1_result)  # What: Process handoff via Agent 2; Why: Creates Slack channel and welcome message.
    assert a2_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Communication setup succeeded.
    assert a2_result.provisioning_result.channel_name.startswith("csm-grw-")  # What: Assert Growth prefix; Why: Verifies channel naming convention.
    assert a2_result.provisioning_result.channel_id.startswith("C")  # What: Assert real Slack channel ID; Why: Real conversation ID from Slack API.
    assert "Plan: GROWTH" in a2_result.channel_payload.topic  # What: Assert Growth in topic; Why: Clarifies tier in Slack header.
    assert "Growth Fast-Track Onboarding" in a2_result.channel_payload.welcome_message  # What: Assert Growth program name; Why: Fast-track messaging.
    assert "14-day timeline" in a2_result.channel_payload.welcome_message  # What: Assert 14-day timeline; Why: Enforces 14-day SLA in welcome message.
    assert "Pooled Customer Success Team" in a2_result.channel_payload.welcome_message  # What: Assert Pooled CSM; Why: Pooled staffing model announced.
    assert "Weekly Live Office Hours" in a2_result.channel_payload.welcome_message  # What: Assert Office Hours; Why: Group enablement sessions announced.
    assert "docs.novacrm.com/getting-started" in a2_result.channel_payload.welcome_message  # What: Assert docs link; Why: Self-serve knowledge base link.
    print(f"[+] LIVE SLACK GROWTH CHANNEL: #{a2_result.provisioning_result.channel_name} (ID: {a2_result.provisioning_result.channel_id})")  # What: Print Slack link; Why: Terminal visibility.


# ==============================================================================
# TA-3: STRICT ZERO-GUESSWORK GUARDRAIL ON UNVERIFIED OR UNKNOWN TIER
# ==============================================================================

def test_ta3_unverified_tier_strictly_rejects_without_template_fallback() -> None:  # What: Test TA-3; Why: Proves unverified tier strictly halts without guessing a template.
    """Guarantees that resolve_tier_payload raises ValueError when given PlanTier.UNKNOWN, preventing template guesswork."""  # What: Docstring; Why: Documents TA-3 intent.
    client = RocketlaneClient(mock_mode=True)  # What: Client instance; Why: Tests deterministic template resolver.

    # 1. Attempt to resolve payload with unverified UNKNOWN tier
    with pytest.raises(ValueError) as exc_info:  # What: Assert ValueError raised; Why: System must strictly refuse to guess.
        client.resolve_tier_payload(  # What: Call resolve_tier_payload; Why: Validates tier mapping pre-condition.
            customer_name="Phantom Corp",  # What: Customer name; Why: Valid customer string.
            customer_email="contact@phantomcorp.com",  # What: Customer email; Why: Valid contact string.
            tier=PlanTier.UNKNOWN,  # What: Unverified UNKNOWN tier; Why: Simulates failed or unconfirmed telephony call.
            idempotency_key="key_unknown_tier_guard"  # What: Idempotency key; Why: Request identifier.
        )  # What: End of call; Why: Triggers exception.

    # 2. Assert exception details enforce zero-guesswork mandate
    assert "Cannot provision project for unverified or unsupported tier" in str(exc_info.value)  # What: Assert error message text; Why: Explains rejection rationale clearly.
    assert "UNKNOWN" in str(exc_info.value)  # What: Assert UNKNOWN in message; Why: Identifies offending tier state.
    print("\n[+] TA-3 PASSED: System strictly refused to provision template for PlanTier.UNKNOWN")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# TA-4: TEMPLATE BOUNDARY ISOLATION & ANTI-CROSS-CONTAMINATION
# ==============================================================================

def test_ta4_template_boundary_isolation_and_cross_contamination() -> None:  # What: Test TA-4; Why: Proves Enterprise and Growth configurations and messaging never cross-contaminate.
    """Verifies that Enterprise and Growth templates, durations, CSM models, and copy are mutually exclusive."""  # What: Docstring; Why: Documents TA-4 intent.
    client = RocketlaneClient(mock_mode=True)  # What: Client instance; Why: Tests template matrix definitions.
    comm_agent = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Communication agent; Why: Tests message generation isolation.

    ent_req = client.resolve_tier_payload("Acme Ent", "acme@ent.com", PlanTier.ENTERPRISE, "key_ent_iso")  # What: Resolve Enterprise request; Why: Enterprise parameters.
    grw_req = client.resolve_tier_payload("Beta Grw", "beta@grw.com", PlanTier.GROWTH, "key_grw_iso")  # What: Resolve Growth request; Why: Growth parameters.

    # 1. Assert template ID and timeline mutual exclusivity
    assert ent_req.template_id != grw_req.template_id  # What: Assert distinct template IDs; Why: Enterprise and Growth must use separate templates.
    assert ent_req.template_id == "5000000095997"  # What: Assert Enterprise template; Why: 30-day enterprise template ID.
    assert grw_req.template_id == "5000000096288"  # What: Assert Growth template; Why: 14-day growth template ID.
    assert ent_req.duration_days == 30  # What: Assert Enterprise 30d; Why: 30-day timeline requirement.
    assert grw_req.duration_days == 14  # What: Assert Growth 14d; Why: 14-day timeline requirement.
    assert ent_req.csm_type == "Dedicated CSM"  # What: Assert Dedicated CSM; Why: Enterprise staffing model.
    assert grw_req.csm_type == "Pooled CSM"  # What: Assert Pooled CSM; Why: Growth staffing model.

    # 2. Generate welcome messages for both tiers
    ent_msg = comm_agent.format_welcome_message("Acme Ent", PlanTier.ENTERPRISE, "https://app.rocketlane.com/projects/ent1", ent_req.csm_assigned)  # What: Enterprise message; Why: Content check.
    grw_msg = comm_agent.format_welcome_message("Beta Grw", PlanTier.GROWTH, "https://app.rocketlane.com/projects/grw1", grw_req.csm_assigned)  # What: Growth message; Why: Content check.

    # 3. Assert zero copy leakage from Growth into Enterprise
    assert "Pooled Customer Success Team" not in ent_msg  # What: Assert no pooled CSM in Enterprise; Why: High-touch account gets dedicated lead.
    assert "Weekly Live Office Hours" not in ent_msg  # What: Assert no office hours in Enterprise; Why: Enterprise has private kickoff calls.
    assert "14-day timeline" not in ent_msg  # What: Assert no 14d in Enterprise; Why: Enterprise gets 30-day SLA.

    # 4. Assert zero copy leakage from Enterprise into Growth
    assert "Dedicated Customer Success Manager" not in grw_msg  # What: Assert no dedicated CSM in Growth; Why: Growth uses shared pool.
    assert "calendly.com/novacrm-enterprise" not in grw_msg  # What: Assert no Enterprise Calendly in Growth; Why: Growth uses standard office hours.
    assert "30-day timeline" not in grw_msg  # What: Assert no 30d in Growth; Why: Growth gets 14-day SLA.

    print("\n[+] TA-4 PASSED: Enterprise and Growth configurations and communications are strictly isolated with zero cross-contamination.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# TA-5: ROCKETLANE API PAYLOAD STRUCTURE & TEMPLATE SOURCE WIRE COMPLIANCE
# ==============================================================================

def test_ta5_rocketlane_template_source_schema_wire_compliance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # What: Test TA-5; Why: Proves Rocketlane REST POST payload complies with template import schema.
    """Verifies that the JSON wire payload sent to Rocketlane /projects formats templateId as integer and startDate in ISO format."""  # What: Docstring; Why: Documents TA-5 intent.
    client = RocketlaneClient(mock_mode=False, cache_file_path=tmp_path / "ta5_cache.json")  # What: Isolated cache client; Why: Prevents idempotency hits from previous runs.
    captured_payloads: list[dict[str, Any]] = []  # What: Payload capture list; Why: Intercepts POST body before HTTP transmission.
    unique_ts = int(datetime.now().timestamp() * 1000)  # What: High-resolution timestamp; Why: Guarantees unique wire test keys.

    # Monkeypatch private HTTP execution to capture wire payload without duplicating 35-second cloud clones
    def fake_execute_post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:  # What: Interceptor function; Why: Records wire payload and returns mock response.
        captured_payloads.append(payload)  # What: Append payload; Why: Stores wire body for assertion.
        return {  # What: Return simulated successful project response; Why: Allows create_project to complete cleanly.
            "projectId": "5000000099999",  # What: Simulated project ID; Why: Valid return shape.
            "projectName": payload.get("projectName", "Test Project"),  # What: Project name; Why: Echoes name.
            "status": "ACTIVE"  # What: Project status; Why: Standard active status.
        }  # What: End of mock response dictionary; Why: Complete mock response.

    monkeypatch.setattr(client, "_execute_http_post", fake_execute_post)  # What: Apply monkeypatch; Why: Intercepts live network call.

    # 1. Dispatch Enterprise project creation
    ent_key = f"idemp_wire_ent_{unique_ts}"  # What: Unique Enterprise test key; Why: Ensures fresh wire request.
    ent_request = client.resolve_tier_payload("OmniCorp", "alex@omnicorp.com", PlanTier.ENTERPRISE, ent_key)  # What: Build Enterprise request; Why: Enterprise payload.
    client.create_project(ent_request, correlation_id="ta5_wire_ent")  # What: Call create_project; Why: Triggers payload compilation.

    # 2. Dispatch Growth project creation
    grw_key = f"idemp_wire_grw_{unique_ts}"  # What: Unique Growth test key; Why: Ensures fresh wire request.
    grw_request = client.resolve_tier_payload("MiniCorp", "bob@minicorp.com", PlanTier.GROWTH, grw_key)  # What: Build Growth request; Why: Growth payload.
    client.create_project(grw_request, correlation_id="ta5_wire_grw")  # What: Call create_project; Why: Triggers payload compilation.

    # 3. Assert Enterprise wire schema compliance
    assert len(captured_payloads) == 2  # What: Assert 2 payloads captured; Why: One for Enterprise, one for Growth.
    ent_wire = captured_payloads[0]  # What: Extract Enterprise wire payload; Why: Inspects Enterprise JSON structure.
    assert ent_wire["projectName"] == "OmniCorp - Onboarding (ENTERPRISE)"  # What: Assert project name; Why: Standardized project title.
    assert ent_wire["customer"]["companyName"] == "OmniCorp"  # What: Assert company name; Why: Matches customer object spec.
    assert ent_wire["autoCreateCompany"] is True  # What: Assert autoCreateCompany True; Why: Required for automatic customer creation.
    assert ent_wire["externalReferenceId"] == ent_key  # What: Assert external reference ID; Why: Rocketlane cloud deduplication key.
    assert "sources" in ent_wire  # What: Assert sources field exists; Why: Template import envelope.
    assert len(ent_wire["sources"]) == 1  # What: Assert single source; Why: One template applied.
    assert ent_wire["sources"][0]["templateId"] == 5000000095997  # What: Assert integer template ID; Why: Rocketlane API rejects string template IDs.
    assert isinstance(ent_wire["sources"][0]["templateId"], int)  # What: Assert strict int type; Why: Wire type integrity.
    assert len(ent_wire["sources"][0]["startDate"].split("-")) == 3  # What: Assert YYYY-MM-DD date format; Why: Required ISO date string.

    # 4. Assert Growth wire schema compliance
    grw_wire = captured_payloads[1]  # What: Extract Growth wire payload; Why: Inspects Growth JSON structure.
    assert grw_wire["projectName"] == "MiniCorp - Onboarding (GROWTH)"  # What: Assert project name; Why: Standardized project title.
    assert grw_wire["customer"]["companyName"] == "MiniCorp"  # What: Assert company name; Why: Matches customer object spec.
    assert grw_wire["externalReferenceId"] == grw_key  # What: Assert external reference ID; Why: Rocketlane cloud deduplication key.
    assert grw_wire["sources"][0]["templateId"] == 5000000096288  # What: Assert integer template ID; Why: Rocketlane API rejects string template IDs.
    assert isinstance(grw_wire["sources"][0]["templateId"], int)  # What: Assert strict int type; Why: Wire type integrity.

    print("\n[+] TA-5 PASSED: Rocketlane wire payloads strictly comply with templateId integer typing and ISO date schema.")  # What: Print confirmation; Why: Terminal visibility.
