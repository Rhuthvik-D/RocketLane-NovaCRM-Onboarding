from datetime import datetime, timezone
from email.message import EmailMessage
import os
from pathlib import Path
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper
from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import (
    DataMigrationSignOffPayload,
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus
)
from src.services.gmail_poller import GmailPoller
from src.services.rocketlane_client import RocketlaneClient
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


# ==============================================================================
# HP-1: LIVE CANONICAL ENTERPRISE TIER ONBOARDING (ROCKETLANE + SLACK LIVE)
# ==============================================================================

def test_hp1_canonical_enterprise_onboarding_live() -> None:
    """Ensures Enterprise deal creates an actual Rocketlane project (30d template 5000000095997) and real private Slack channel."""
    agent1 = Agent1Intake()  #
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"hp1_live_ent_{test_ts}"
    customer_name = f"Apex Dynamics {test_ts}"
    customer_email = f"alex.mercer_{test_ts}@apexdynamics.com"

    # 1. Inbound Enterprise Deal Notification Email Payload
    email_payload = {
        "message_id": f"msg_hp1_live_{test_ts}",
        "customer_name": customer_name,
        "customer_contact_email": customer_email,
        "ae_name": "Marcus Vance",
        "ae_phone": "+1-555-0199",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    # 2. Inject Simulated Verbal Confirmation (Enterprise 30-Day SLA)
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_hp1_live_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript=f"Hi, this is Marcus Vance. Yes, I confirm that {customer_name} is on the Enterprise plan with 30-day onboarding and dedicated CSM.",
            confidence_score=0.98
        )
    )

    # 3. Execute Agent 1: Ingests email, validates, and provisions LIVE Rocketlane project
    a1_result = agent1.process_deal(email_payload, correlation_id=correlation_id)
    assert a1_result.status == "SUCCESS"
    assert a1_result.rocketlane_project is not None
    assert a1_result.rocketlane_project.tier == PlanTier.ENTERPRISE
    assert a1_result.rocketlane_project.template_id == "5000000095997"
    assert "https://app.rocketlane.com/projects/" in a1_result.rocketlane_project.portal_url
    print(f"\n[+] LIVE ROCKETLANE ENTERPRISE PROJECT CREATED: {a1_result.rocketlane_project.portal_url}")

    # 4. Execute Agent 2: Provisions LIVE private Slack channel, sets topic, posts welcome
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result.channel_name.startswith("csm-ent-")
    assert a2_result.provisioning_result.channel_id.startswith("C")
    assert a2_result.provisioning_result.topic_set is True
    assert a2_result.provisioning_result.welcome_message_ts is not None
    print(f"[+] LIVE SLACK ENTERPRISE CHANNEL CREATED: #{a2_result.provisioning_result.channel_name} (ID: {a2_result.provisioning_result.channel_id})")


# ==============================================================================
# HP-2: LIVE CANONICAL GROWTH TIER ONBOARDING (ROCKETLANE + SLACK LIVE)
# ==============================================================================

def test_hp2_canonical_growth_onboarding_live() -> None:
    """Ensures Growth deal creates an actual Rocketlane project (14d template 5000000096288) and real private Slack channel."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"hp2_live_grw_{test_ts}"
    customer_name = f"Beacon Logistics {test_ts}"
    customer_email = f"ops_{test_ts}@beaconlogistics.io"

    # 1. Inbound Growth Deal Notification Email Payload
    email_payload = {
        "message_id": f"msg_hp2_live_{test_ts}",
        "customer_name": customer_name,
        "customer_contact_email": customer_email,
        "ae_name": "Elena Rostova",
        "ae_phone": "+1-555-0148",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    # 2. Inject Simulated Verbal Confirmation (Growth 14-Day SLA)
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_hp2_live_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.GROWTH,
            transcript=f"Hi! Yes, Beacon Logistics is on the standard Growth plan with 14-day onboarding and pooled CSM.",
            confidence_score=0.97
        )
    )

    # 3. Execute Agent 1: Ingests email, validates, and provisions LIVE Rocketlane project
    a1_result = agent1.process_deal(email_payload, correlation_id=correlation_id)
    assert a1_result.status == "SUCCESS"
    assert a1_result.rocketlane_project is not None
    assert a1_result.rocketlane_project.tier == PlanTier.GROWTH
    assert a1_result.rocketlane_project.template_id == "5000000096288"
    assert "https://app.rocketlane.com/projects/" in a1_result.rocketlane_project.portal_url
    print(f"\n[+] LIVE ROCKETLANE GROWTH PROJECT CREATED: {a1_result.rocketlane_project.portal_url}")

    # 4. Execute Agent 2: Provisions LIVE private Slack channel, sets topic, posts welcome
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SUCCESS"
    assert a2_result.provisioning_result.channel_name.startswith("csm-grw-")
    assert a2_result.provisioning_result.channel_id.startswith("C")
    assert a2_result.provisioning_result.topic_set is True
    assert a2_result.provisioning_result.welcome_message_ts is not None
    print(f"[+] LIVE SLACK GROWTH CHANNEL CREATED: #{a2_result.provisioning_result.channel_name} (ID: {a2_result.provisioning_result.channel_id})")


# ==============================================================================
# HP-3: LIVE GMAIL IMAP CLARIFICATION DRAFT STAGING & MULTI-TURN RESOLUTION
# ==============================================================================

def test_hp3_self_correcting_multi_turn_intake_recovery_live_gmail() -> None:
    """Guarantees incomplete deal stages an actual clarification draft in live Gmail [Gmail]/Drafts and resumes cleanly on reply."""
    poller = GmailPoller(mock_mode=False)
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"hp3_live_gmail_{test_ts}"
    customer_name = f"Horizon Health {test_ts}"

    # 1. Turn 1: Process incomplete deal email missing contact email and phone
    incomplete_deal = {
        "message_id": f"msg_hp3_live_{test_ts}",
        "customer_name": customer_name,
        "ae_name": "Sarah Connor",
        "ae_email": "sarah@novacrm.com",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    a1_turn1 = agent1.process_deal(incomplete_deal, correlation_id=correlation_id)
    assert a1_turn1.status == "HALTED_MISSING_DATA"
    assert a1_turn1.clarification_draft is not None
    assert "customer_contact_email" in a1_turn1.clarification_draft.missing_fields
    assert "ae_phone" in a1_turn1.clarification_draft.missing_fields

    # 2. Stage clarification draft directly into LIVE [Gmail]/Drafts via IMAP
    draft_staged = poller.stage_clarification_draft(
        draft=a1_turn1.clarification_draft,
        correlation_id=correlation_id,
        in_reply_to=f"<msg_hp3_live_{test_ts}@novacrm.com>",
        original_subject=f"[New Deal] {customer_name} Closed Won"
    )
    assert draft_staged is True
    print(f"\n[+] LIVE GMAIL CLARIFICATION DRAFT STAGED IN [Gmail]/Drafts FOR: {a1_turn1.clarification_draft.recipient_email}")

    # 3. Turn 2: Simulate AE reply providing the missing fields and resume pipeline
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_hp3_live_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript=f"Yes, Horizon Health is Enterprise tier with 30-day onboarding.",
            confidence_score=0.96
        )
    )

    merged_deal = {
        "message_id": f"msg_hp3_reply_{test_ts}",
        "customer_name": customer_name,
        "customer_contact_email": f"it-onboarding_{test_ts}@horizonhealth.org",
        "ae_name": "Sarah Connor",
        "ae_phone": "+1-555-0199",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    a1_turn2 = agent1.process_deal(merged_deal, correlation_id=f"{correlation_id}_resumed")
    assert a1_turn2.status == "SUCCESS"
    assert a1_turn2.rocketlane_project is not None
    print(f"[+] LIVE ROCKETLANE RECOVERED PROJECT CREATED: {a1_turn2.rocketlane_project.portal_url}")


# ==============================================================================
# HP-4: DOWNSTREAM STAGE-GATE QA UNLOCKING (AGENT 3 DATA QA GATEKEEPER)
# ==============================================================================

def test_hp4_downstream_stage_gate_qa_unlocking() -> None:
    """Guarantees Agent 3 verifies volume > 0, customer sign-off, and 0 discrepancy, cleanly unlocking Configuration."""
    agent3 = Agent3DataQAGatekeeper()
    correlation_id = f"hp4_qa_gate_live_{int(datetime.now().timestamp()) % 100000}"

    # Valid sign-off payload with 24,500 records migrated and 24,500 records verified
    sign_off_payload = DataMigrationSignOffPayload(
        project_id="5000000208003",
        task_id="task_migration_complete",
        customer_name="Apex Dynamics",
        records_migrated=24500,
        records_verified=24500,
        customer_sign_off_confirmed=True,
        sign_off_contact_email="it-director@apexdynamics.com",
        sign_off_timestamp="2026-09-29T12:00:00Z"
    )

    qa_result = agent3.evaluate_migration_sign_off(sign_off_payload, correlation_id=correlation_id)

    assert qa_result.status == "VERIFIED_UNLOCKED"
    assert qa_result.is_configuration_unlocked is True
    assert qa_result.discrepancy_count == 0
    assert qa_result.csm_alert_sent is False
    assert "Data migration fully verified" in qa_result.audit_rationale

    # Verify structured audit log entry exists
    audit_entries = audit_logger.get_entries_for_correlation(correlation_id)
    actions = [entry.action for entry in audit_entries]
    assert "data_qa_verification_passed_unlocked" in actions
    print(f"\n[+] DATA QA GATEKEEPER PASSED: Configuration phase unlocked for project '{sign_off_payload.project_id}'.")
