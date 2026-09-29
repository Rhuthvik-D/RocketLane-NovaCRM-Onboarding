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
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Simulated Voice AI; Why: Vapi outbound PSTN skipped due to carrier limits.
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
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC opportunity link; Why: CRM context.
    }  

    # 2. Inject Simulated Verbal Confirmation (Enterprise 30-Day SLA)
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Injects verified Enterprise verbal response.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Telephony result model.
            call_id=f"call_hp1_live_{test_ts}",  # What: Call ID; Why: Telephony identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Confirmed status; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan tier.
            transcript=f"Hi, this is Marcus Vance. Yes, I confirm that {customer_name} is on the Enterprise plan with 30-day onboarding and dedicated CSM.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.98  # What: 98% confidence score; Why: High confidence passes guardrail without ambiguity.
        )  # What: End of VoiceCallResult; Why: Configured result.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # 3. Execute Agent 1: Ingests email, validates, and provisions LIVE Rocketlane project
    a1_result = agent1.process_deal(email_payload, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Provisions live project.
    assert a1_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Pipeline succeeded without halting.
    assert a1_result.rocketlane_project is not None  # What: Assert project exists; Why: Project provisioned in Rocketlane.
    assert a1_result.rocketlane_project.tier == PlanTier.ENTERPRISE  # What: Assert Enterprise tier; Why: Correct plan tier mapped.
    assert a1_result.rocketlane_project.template_id == "5000000095997"  # What: Assert Enterprise template ID; Why: 30-day template applied.
    assert "https://app.rocketlane.com/projects/" in a1_result.rocketlane_project.portal_url  # What: Assert live URL format; Why: Real Rocketlane workspace link.
    print(f"\n[+] LIVE ROCKETLANE ENTERPRISE PROJECT CREATED: {a1_result.rocketlane_project.portal_url}")  # What: Print project link; Why: Terminal visibility for Loom demo.

    # 4. Execute Agent 2: Provisions LIVE private Slack channel, sets topic, posts welcome
    a2_result = agent2.process_project_handoff(a1_result)  # What: Process handoff via Agent 2; Why: Creates Slack channel and welcome message.
    assert a2_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Communication setup succeeded.
    assert a2_result.provisioning_result.channel_name.startswith("csm-ent-")  # What: Assert Enterprise channel prefix; Why: Verifies channel naming convention.
    assert a2_result.provisioning_result.channel_id.startswith("C")  # What: Assert real Slack channel ID; Why: Real conversation ID from Slack API.
    assert a2_result.provisioning_result.topic_set is True  # What: Assert topic set; Why: Rocketlane link embedded.
    assert a2_result.provisioning_result.welcome_message_ts is not None  # What: Assert message timestamp; Why: Welcome message delivered to real channel.
    print(f"[+] LIVE SLACK ENTERPRISE CHANNEL CREATED: #{a2_result.provisioning_result.channel_name} (ID: {a2_result.provisioning_result.channel_id})")  # What: Print Slack link; Why: Terminal visibility for Loom demo.


# ==============================================================================
# HP-2: LIVE CANONICAL GROWTH TIER ONBOARDING (ROCKETLANE + SLACK LIVE)
# ==============================================================================

def test_hp2_canonical_growth_onboarding_live() -> None:  # What: Live Growth test; Why: Proves real Rocketlane Growth project and real Slack channel creation.
    """Ensures Growth deal creates an actual Rocketlane project (14d template 5000000096288) and real private Slack channel."""  # What: Docstring; Why: Documents live HP-2 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Clean intake orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Hits real Rocketlane REST API.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Simulated Voice AI; Why: Vapi outbound PSTN skipped due to carrier limits.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))  # What: LIVE Slack client; Why: Hits real Slack Web API.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate 5-digit unique timestamp; Why: Prevents naming collisions.
    correlation_id = f"hp2_live_grw_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.
    customer_name = f"Beacon Logistics {test_ts}"  # What: Customer company name; Why: Name to provision.
    customer_email = f"ops_{test_ts}@beaconlogistics.io"  # What: Customer contact email; Why: Primary collaborator.

    # 1. Inbound Growth Deal Notification Email Payload
    email_payload = {  # What: Valid raw email dictionary; Why: Simulates clean Growth deal notification.
        "message_id": f"msg_hp2_live_{test_ts}",  # What: Unique message ID; Why: Email identifier.
        "customer_name": customer_name,  # What: Customer company name; Why: Name to provision.
        "customer_contact_email": customer_email,  # What: Customer contact email; Why: Primary collaborator.
        "ae_name": "Elena Rostova",  # What: Account Executive name; Why: Deal owner.
        "ae_phone": "+1-555-0148",  # What: AE phone number; Why: Telephony destination.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC opportunity link; Why: CRM context.
    }  # What: End of email payload; Why: Complete deal payload.

    # 2. Inject Simulated Verbal Confirmation (Growth 14-Day SLA)
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Injects verified Growth verbal response.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Telephony result model.
            call_id=f"call_hp2_live_{test_ts}",  # What: Call ID; Why: Telephony identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Confirmed status; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.GROWTH,  # What: Growth tier; Why: Selected plan tier.
            transcript=f"Hi! Yes, Beacon Logistics is on the standard Growth plan with 14-day onboarding and pooled CSM.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.97  # What: 97% confidence score; Why: High confidence passes guardrail without ambiguity.
        )  # What: End of VoiceCallResult; Why: Configured result.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # 3. Execute Agent 1: Ingests email, validates, and provisions LIVE Rocketlane project
    a1_result = agent1.process_deal(email_payload, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Provisions live project.
    assert a1_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Pipeline succeeded without halting.
    assert a1_result.rocketlane_project is not None  # What: Assert project exists; Why: Project provisioned in Rocketlane.
    assert a1_result.rocketlane_project.tier == PlanTier.GROWTH  # What: Assert Growth tier; Why: Correct plan tier mapped.
    assert a1_result.rocketlane_project.template_id == "5000000096288"  # What: Assert Growth template ID; Why: 14-day template applied.
    assert "https://app.rocketlane.com/projects/" in a1_result.rocketlane_project.portal_url  # What: Assert live URL format; Why: Real Rocketlane workspace link.
    print(f"\n[+] LIVE ROCKETLANE GROWTH PROJECT CREATED: {a1_result.rocketlane_project.portal_url}")  # What: Print project link; Why: Terminal visibility for Loom demo.

    # 4. Execute Agent 2: Provisions LIVE private Slack channel, sets topic, posts welcome
    a2_result = agent2.process_project_handoff(a1_result)  # What: Process handoff via Agent 2; Why: Creates Slack channel and welcome message.
    assert a2_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Communication setup succeeded.
    assert a2_result.provisioning_result.channel_name.startswith("csm-grw-")  # What: Assert Growth channel prefix; Why: Verifies channel naming convention.
    assert a2_result.provisioning_result.channel_id.startswith("C")  # What: Assert real Slack channel ID; Why: Real conversation ID from Slack API.
    assert a2_result.provisioning_result.topic_set is True  # What: Assert topic set; Why: Rocketlane link embedded.
    assert a2_result.provisioning_result.welcome_message_ts is not None  # What: Assert message timestamp; Why: Welcome message delivered to real channel.
    print(f"[+] LIVE SLACK GROWTH CHANNEL CREATED: #{a2_result.provisioning_result.channel_name} (ID: {a2_result.provisioning_result.channel_id})")  # What: Print Slack link; Why: Terminal visibility for Loom demo.


# ==============================================================================
# HP-3: LIVE GMAIL IMAP CLARIFICATION DRAFT STAGING & MULTI-TURN RESOLUTION
# ==============================================================================

def test_hp3_self_correcting_multi_turn_intake_recovery_live_gmail() -> None:  # What: Live Gmail draft test; Why: Proves human-in-the-loop draft staging in [Gmail]/Drafts.
    """Guarantees incomplete deal stages an actual clarification draft in live Gmail [Gmail]/Drafts and resumes cleanly on reply."""  # What: Docstring; Why: Documents live HP-3 intent.
    poller = GmailPoller(mock_mode=False)  # What: LIVE GmailPoller; Why: Connects over TLS to live Gmail IMAP inbox.
    agent1 = Agent1Intake()  # What: Fresh Agent 1; Why: Clean intake orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Provisions real project on recovery.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Simulated Voice AI; Why: Telephony confirmation simulation.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate unique timestamp; Why: Prevents naming collisions.
    correlation_id = f"hp3_live_gmail_{test_ts}"  # What: Correlation ID; Why: Deal tracking.
    customer_name = f"Horizon Health {test_ts}"  # What: Customer name; Why: Name to provision.

    # 1. Turn 1: Process incomplete deal email missing contact email and phone
    incomplete_deal = {  # What: Incomplete raw email dictionary; Why: Missing contact email and AE phone.
        "message_id": f"msg_hp3_live_{test_ts}",  # What: Unique message ID; Why: Email ID.
        "customer_name": customer_name,  # What: Customer name; Why: Present.
        "ae_name": "Sarah Connor",  # What: AE name; Why: Present.
        "ae_email": "sarah@novacrm.com",  # What: AE email; Why: Recipient for clarification draft.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: Present.
    }  # What: End of incomplete deal dictionary; Why: Missing required fields.

    a1_turn1 = agent1.process_deal(incomplete_deal, correlation_id=correlation_id)  # What: Process Turn 1 via Agent 1; Why: Tests deterministic validation halt.
    assert a1_turn1.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED; Why: Incomplete data halts pipeline without guessing.
    assert a1_turn1.clarification_draft is not None  # What: Assert draft generated; Why: Clarification draft created for AE.
    assert "customer_contact_email" in a1_turn1.clarification_draft.missing_fields  # What: Assert missing email flagged; Why: Correct field identified.
    assert "ae_phone" in a1_turn1.clarification_draft.missing_fields  # What: Assert missing phone flagged; Why: Correct field identified.

    # 2. Stage clarification draft directly into LIVE [Gmail]/Drafts via IMAP
    draft_staged = poller.stage_clarification_draft(  # What: Call live stage_clarification_draft; Why: Appends draft to real [Gmail]/Drafts over TLS.
        draft=a1_turn1.clarification_draft,  # What: Inbound draft model; Why: Clarification text.
        correlation_id=correlation_id,  # What: Correlation ID; Why: Connects to deal trail.
        in_reply_to=f"<msg_hp3_live_{test_ts}@novacrm.com>",  # What: Message ID header; Why: Standard RFC 2822 threading.
        original_subject=f"[New Deal] {customer_name} Closed Won"  # What: Original subject line; Why: Used by poller to compute Re: subject.
    )  # What: End of live stage call; Why: Appended to live Gmail folder.
    assert draft_staged is True  # What: Assert draft staged True; Why: Confirms IMAP APPEND succeeded on live Gmail.
    print(f"\n[+] LIVE GMAIL CLARIFICATION DRAFT STAGED IN [Gmail]/Drafts FOR: {a1_turn1.clarification_draft.recipient_email}")  # What: Print confirmation; Why: Terminal visibility.

    # 3. Turn 2: Simulate AE reply providing the missing fields and resume pipeline
    agent1.voice_client.set_simulation_outcome(  # What: Set voice outcome; Why: Injects confirmed call for resumed pipeline.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified confirmation result.
            call_id=f"call_hp3_live_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan tier.
            transcript=f"Yes, Horizon Health is Enterprise tier with 30-day onboarding.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.96  # What: High confidence score; Why: Valid confirmation.
        )  # What: End of VoiceCallResult; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    merged_deal = {  # What: Merged complete deal dictionary; Why: Combines Turn 1 with AE reply.
        "message_id": f"msg_hp3_reply_{test_ts}",  # What: Unique reply message ID; Why: Email ID.
        "customer_name": customer_name,  # What: Customer name; Why: Identity preserved.
        "customer_contact_email": f"it-onboarding_{test_ts}@horizonhealth.org",  # What: Newly provided contact email; Why: Resolves missing email.
        "ae_name": "Sarah Connor",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0199",  # What: Newly provided AE phone; Why: Resolves missing phone.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: Context link.
    }  # What: End of merged deal dictionary; Why: Fully populated payload.

    a1_turn2 = agent1.process_deal(merged_deal, correlation_id=f"{correlation_id}_resumed")  # What: Process merged deal; Why: Resumes pipeline.
    assert a1_turn2.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Validated and provisioned successfully.
    assert a1_turn2.rocketlane_project is not None  # What: Assert project exists; Why: Real project provisioned.
    print(f"[+] LIVE ROCKETLANE RECOVERED PROJECT CREATED: {a1_turn2.rocketlane_project.portal_url}")  # What: Print project link; Why: Terminal visibility.


# ==============================================================================
# HP-4: DOWNSTREAM STAGE-GATE QA UNLOCKING (AGENT 3 DATA QA GATEKEEPER)
# ==============================================================================

def test_hp4_downstream_stage_gate_qa_unlocking() -> None:  # What: Test HP-4; Why: Verifies Agent 3 unlocks Configuration when migration is 100% verified.
    """Guarantees Agent 3 verifies volume > 0, customer sign-off, and 0 discrepancy, cleanly unlocking Configuration."""  # What: Docstring; Why: Documents HP-4 intent.
    agent3 = Agent3DataQAGatekeeper()  # What: Instantiate Agent 3 Data QA Gatekeeper; Why: Evaluates stage-gate criteria.
    correlation_id = f"hp4_qa_gate_live_{int(datetime.now().timestamp()) % 100000}"  # What: Correlation ID; Why: Tracks QA evaluation in audit logs.

    # Valid sign-off payload with 24,500 records migrated and 24,500 records verified
    sign_off_payload = DataMigrationSignOffPayload(  # What: Instantiate sign-off payload; Why: Input for Agent 3.
        project_id="5000000208003",  # What: Real Rocketlane project ID; Why: Target project.
        task_id="task_migration_complete",  # What: Rocketlane migration task ID; Why: Target task.
        customer_name="Apex Dynamics",  # What: Customer company name; Why: Customer identity.
        records_migrated=24500,  # What: Migrated record count (positive); Why: Passes volume check.
        records_verified=24500,  # What: Verified record count (equal to migrated); Why: Passes 100% record parity check.
        customer_sign_off_confirmed=True,  # What: Customer sign-off confirmation; Why: Passes explicit sign-off check.
        sign_off_contact_email="it-director@apexdynamics.com",  # What: Customer authorized signer email; Why: Authenticates sign-off.
        sign_off_timestamp="2026-09-29T12:00:00Z"  # What: Sign-off timestamp; Why: Audit proof of approval.
    )  # What: End of sign-off payload instantiation; Why: Ready.

    qa_result = agent3.evaluate_migration_sign_off(sign_off_payload, correlation_id=correlation_id)  # What: Run gatekeeper evaluation; Why: Evaluates criteria.

    assert qa_result.status == "VERIFIED_UNLOCKED"  # What: Assert status VERIFIED_UNLOCKED; Why: Passes all 3 gatekeeper checks.
    assert qa_result.is_configuration_unlocked is True  # What: Assert Configuration unlocked; Why: Downstream phase unblocked.
    assert qa_result.discrepancy_count == 0  # What: Assert zero discrepancy; Why: 100% parity verified.
    assert qa_result.csm_alert_sent is False  # What: Assert no blocker alert sent; Why: Clean verification requires no escalation.
    assert "Data migration fully verified" in qa_result.audit_rationale  # What: Assert success rationale; Why: Documents verification reason.

    # Verify structured audit log entry exists
    audit_entries = audit_logger.get_entries_for_correlation(correlation_id)  # What: Query audit logs; Why: Verifies audit trail using proper method.
    actions = [entry.action for entry in audit_entries]  # What: Extract action names list; Why: Checks logged actions.
    assert "data_qa_verification_passed_unlocked" in actions  # What: Assert unlock action recorded; Why: Proves audit compliance.
    print(f"\n[+] DATA QA GATEKEEPER PASSED: Configuration phase unlocked for project '{sign_off_payload.project_id}'.")  # What: Print confirmation; Why: Terminal visibility.
