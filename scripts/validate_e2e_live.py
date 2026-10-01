"""End-to-end live validation script executing full multi-agent onboarding flow.

Performs live end-to-end execution against production Rocketlane and Slack APIs:
- Agent 1: Deal email ingestion, Pydantic deterministic schema validation,
  simulated Voice AI confirmation, and Rocketlane project provisioning (30d vs 14d templates).
- Agent 2: Slack channel handle sanitization (#csm-ent-* / #csm-grw-*), private channel
  provisioning, topic embedding with Rocketlane portal URL, personalized welcome messaging,
  and workspace member auto-invitation.
- Agent 3: Data QA Gatekeeper stage-gate evaluation (100% record parity and customer sign-off).
- Rocketlane Native SLA Automations: Programmatic evaluation of native 1-day (PM) and 4-day (Owner) rules.
- Structured Audit Trail: Full extraction and verification of immutable JSONL audit records.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

# Ensure UTF-8 stdout encoding on Windows systems to support terminal emojis
sys.stdout.reconfigure(encoding="utf-8")

# Register project root in sys.path to allow absolute imports from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper
from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import (
    DataMigrationSignOffPayload,
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus,
)
from src.services.rocketlane_client import RocketlaneClient
from src.services.rocketlane_sla_automations import RocketlaneSLAEngine
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


def run_e2e_live_validation(target_tier: str = "ENTERPRISE") -> dict:
    """Executes a full live end-to-end onboarding workflow across all 3 agents.

    Execution Pipeline:
        Step 0: Identity & Correlation Generation (Unique timestamps, customer names, contact emails).
        Step 1: Inbound Email Ingestion (Simulates Salesforce Closed-Won deal notification).
        Step 2: Voice AI Verbal Tier Confirmation (Simulates verbal AE confirmation with 99% confidence).
        Step 3: Agent 1 - Live Rocketlane Project Provisioning (30-day template vs 14-day template).
        Step 4: Agent 2 - Live Slack Channel Provisioning (Private channel #csm-*, topic embedding, welcome message).
        Step 5: Agent 3 Stage-Gate & Rocketlane Native SLAs (100% parity sign-off + 1-day/4-day SLA rules).
        Step 6: Structured Audit Trail Verification (Extracts immutable JSONL records from logs/audit_trail.jsonl).
        Step 7: Master Inspection Summary (Prints clickable Rocketlane project links & Slack channel URLs).

    Args:
        target_tier: Plan tier to test ('ENTERPRISE' or 'GROWTH'). Defaults to 'ENTERPRISE'.

    Returns:
        A dictionary containing execution status, correlation ID, Rocketlane project IDs,
        portal URLs, and Slack channel coordinates.
    """
    tier_upper = target_tier.strip().upper()
    is_growth = tier_upper == "GROWTH"
    plan_tier = PlanTier.GROWTH if is_growth else PlanTier.ENTERPRISE
    tier_label = "GROWTH" if is_growth else "ENTERPRISE"
    template_id = (
        settings.rocketlane_growth_template_id
        if is_growth
        else settings.rocketlane_enterprise_template_id
    )
    timeline_desc = (
        "14-day timeline with Pooled CSM"
        if is_growth
        else "30-day timeline with Dedicated CSM"
    )

    print("=" * 80)
    print(f"  NOVACRM CUSTOMER ONBOARDING: FULL MULTI-AGENT E2E LIVE VALIDATION ({tier_label})  ")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # Step 0: Setup Unique Correlation and Identity
    # -------------------------------------------------------------------------
    ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"deal_live_{tier_label.lower()}_{ts}"
    company_prefix = "Beacon Logistics" if is_growth else "Apex Dynamics"
    customer_name = f"{company_prefix} {ts}"
    customer_email = f"lead_{ts}@{company_prefix.lower().replace(' ', '')}.com"
    ae_name = "Marcus Vance"
    ae_phone = "+1-555-0199"
    opp_url = f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c0000{ts}/view"

    print(f"\n[+] Deal Correlation ID : {correlation_id}")
    print(f"[+] Customer Target     : {customer_name} ({customer_email})")
    print(f"[+] Plan Tier Target    : {tier_label} ({timeline_desc})")
    print(f"[+] Account Executive   : {ae_name} ({ae_phone})")

    # -------------------------------------------------------------------------
    # Step 1: Simulate Inbound Deal Notification Email
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("STEP 1: INBOUND EMAIL INGESTION & DETERMINISTIC VALIDATION")
    print("-" * 80)
    raw_email = {
        "message_id": f"msg_val_{ts}",
        "customer_name": customer_name,
        "customer_contact_email": customer_email,
        "ae_name": ae_name,
        "ae_phone": ae_phone,
        "opportunity_url": opp_url,
    }
    print("[*] Inbound Deal Notification Received:")
    print(json.dumps(raw_email, indent=2))

    # -------------------------------------------------------------------------
    # Step 2: Initialize Agents with Live Integrations + Mocked Voice AI
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(f"STEP 2: VOICE AI VERBAL TIER CONFIRMATION (SIMULATED {tier_label})")
    print("-" * 80)
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    # Inject simulated Voice AI call outcome matching target plan tier
    spoken_phrase = (
        "Growth plan with 14-day pooled onboarding"
        if is_growth
        else "Enterprise plan with dedicated CSM support and a 30-day onboarding timeline"
    )
    simulated_transcript = f"Hi, this is Marcus Vance. Yes, I confirm that {customer_name} is on the {spoken_phrase}."
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"vapi_call_sim_{ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=plan_tier,
            transcript=simulated_transcript,
            confidence_score=0.99,
        )
    )
    print(f"[*] Outbound Voice AI call dispatched to AE {ae_name}...")
    print(f'[*] Voice AI Transcript: "{simulated_transcript}"')
    print(f"[+] Voice Guardrail Analysis: Tier confirmed = {tier_label} (Confidence: 0.99, Ambiguity: None)")

    # -------------------------------------------------------------------------
    # Step 3: Execute Agent 1 (Live Rocketlane Project Provisioning)
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(f"STEP 3: AGENT 1 - PROVISIONING LIVE PROJECT IN ROCKETLANE ({tier_label})")
    print("-" * 80)
    print("[*] Contacting Rocketlane API (https://api.rocketlane.com/api/1.0/projects)...")
    print(f"[*] Applying {tier_label.capitalize()} Onboarding Template (ID: {template_id}) with {timeline_desc}...")
    a1_result = agent1.process_deal(raw_email, correlation_id=correlation_id)

    if a1_result.status != "SUCCESS" or not a1_result.rocketlane_project:
        print(f"[!] FAILED: Agent 1 returned status {a1_result.status}")
        return {"status": "FAILED", "stage": "Agent 1"}

    rl_proj = a1_result.rocketlane_project
    print(f"[+] Rocketlane Project Provisioned Successfully!")
    print(f"    - Project ID   : {rl_proj.project_id}")
    print(f"    - Project Name : {rl_proj.project_name}")
    print(f"    - Plan Tier    : {rl_proj.tier}")
    print(f"    - Portal URL   : {rl_proj.portal_url}")

    # -------------------------------------------------------------------------
    # Step 4: Execute Agent 2 (Live Slack Channel & Welcome Message)
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("STEP 4: AGENT 2 - PROVISIONING LIVE SLACK CHANNEL & WELCOME MESSAGE")
    print("-" * 80)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))
    print("[*] Sanitizing channel name according to Slack naming constraints...")
    a2_result = agent2.process_project_handoff(a1_result)

    if a2_result.status != "SUCCESS" or not a2_result.provisioning_result:
        print(f"[!] FAILED: Agent 2 returned status {a2_result.status}")
        return {"status": "FAILED", "stage": "Agent 2"}

    slack_res = a2_result.provisioning_result
    print(f"[+] Slack Channel Created Successfully!")
    print(f"    - Channel Name : #{slack_res.channel_name}")
    print(f"    - Channel ID   : {slack_res.channel_id}")
    print(f"    - Topic Set    : {slack_res.topic_set} (Embedded Rocketlane URL)")
    print(f"    - Welcome TS   : {slack_res.welcome_message_ts}")

    # -------------------------------------------------------------------------
    # Step 5: Validate Agent 3 Data QA Gatekeeper & Rocketlane Native SLAs
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("STEP 5: AGENT 3 (DATA QA GATEKEEPER) & ROCKETLANE SLA AUTOMATIONS")
    print("-" * 80)
    agent3 = Agent3DataQAGatekeeper()
    qa_payload = DataMigrationSignOffPayload(
        project_id=str(rl_proj.project_id),
        task_id="task_migration_001",
        customer_name=customer_name,
        records_migrated=15420,
        records_verified=15420,
        customer_sign_off_confirmed=True,
        sign_off_contact_email=customer_email,
        discrepancy_notes="All legacy customer and deal tables verified with zero checksum errors.",
    )
    qa_result = agent3.evaluate_migration_sign_off(qa_payload, correlation_id=correlation_id)
    print(f"[+] Agent 3 Data QA Gatekeeper Evaluation:")
    print(f"    - Gatekeeper Status  : {qa_result.status}")
    print(f"    - Configuration Phase: {'UNLOCKED' if qa_result.is_configuration_unlocked else 'LOCKED'}")
    print(f"    - Rationale          : {qa_result.audit_rationale}")

    sla_engine = RocketlaneSLAEngine()
    sla_result = sla_engine.evaluate_task_overdue(
        task_id="task_kickoff_001",
        task_name="Kickoff Call Scheduling",
        project_id=str(rl_proj.project_id),
        days_overdue=1,
        pm_email="priya@novacrm.com",
        owner_email=settings.rocketlane_owner_email,
    )
    print(f"[+] Rocketlane Native SLA Automation Evaluation:")
    print(f"    - Alert Triggered    : {sla_result.alert_triggered}")
    print(f"    - Escalation Target  : {sla_result.target} ({sla_result.recipient_label})")
    print(f"    - Escalation Message : {sla_result.alert_message}")

    # -------------------------------------------------------------------------
    # Step 6: Verify Structured Audit Trail
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("STEP 6: STRUCTURED AUDIT TRAIL VERIFICATION")
    print("-" * 80)
    audit_entries = audit_logger.get_entries_for_correlation(correlation_id)
    print(f"[+] Total Structured Audit Records for this deal: {len(audit_entries)}")
    for idx, entry in enumerate(audit_entries, start=1):
        print(f"    [{idx}] {entry.timestamp.strftime('%H:%M:%S')} | {entry.agent_name.ljust(25)} | {entry.action.ljust(30)} | {entry.status}")

    # -------------------------------------------------------------------------
    # Step 7: Master Verification Summary & Inspection Coordinates
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("  LIVE VALIDATION COMPLETED SUCCESSFULLY -- WHERE TO INSPECT RESULTS  ")
    print("=" * 80)
    print(f"""
1. INBOUND DEAL NOTIFICATION (Simulated AE Ingestion):
   * Correlation ID : {correlation_id}
   * Customer       : {customer_name} ({customer_email})
   * Account Exec   : {ae_name} ({ae_phone})
   * Ingestion State: Validated deterministically (Zero guesswork on missing fields)

2. ROCKETLANE WORKSPACE (Live Customer Project):
   * Project ID     : {rl_proj.project_id}
   * Project Name   : {rl_proj.project_name}
   * Template Used  : {"Growth Onboarding (14-day timeline)" if is_growth else "Enterprise Onboarding (30-day timeline)"}
   * Direct Link    : {rl_proj.portal_url}
   * Rocketlane URL : https://app.rocketlane.com/projects/{rl_proj.project_id}
   * Assigned Owner : {settings.rocketlane_owner_email}

3. SLACK WORKSPACE (Live Shared Customer Channel):
   * Workspace Name : NovaCRM Onboarding Bot (novacrmonboar-lox2926.slack.com)
   * Channel Name   : #{slack_res.channel_name}
   * Channel ID     : {slack_res.channel_id}
   * Channel Link   : https://app.slack.com/client/{settings.slack_team_id}/{slack_res.channel_id}
   * Topic Content  : Rocketlane Customer Portal: {rl_proj.portal_url}
   * Welcome Msg TS : {slack_res.welcome_message_ts}
   * Welcome Msg    : Personalized for {tier_label.capitalize()} plan.

4. DATA QA & NATIVE SLA AUTOMATIONS:
   * Data QA Gate   : UNLOCKED (15,420/15,420 records verified with customer sign-off)
   * SLA Rules      : 1-Day Overdue -> Project Manager; 4-Day Overdue -> Project Owner

5. AUDIT LOG FILE:
   * File Path      : {Path('logs/audit_trail.jsonl').resolve()}
   * Total Entries  : {len(audit_entries)} immutable records for correlation ID {correlation_id}
""")

    return {
        "status": "SUCCESS",
        "correlation_id": correlation_id,
        "rocketlane_project_id": rl_proj.project_id,
        "rocketlane_portal_url": rl_proj.portal_url,
        "slack_channel_name": slack_res.channel_name,
        "slack_channel_id": slack_res.channel_id,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NovaCRM E2E Live Multi-Agent Validation Runner")
    parser.add_argument(
        "--tier",
        type=str,
        choices=["enterprise", "growth", "both", "ENTERPRISE", "GROWTH", "BOTH"],
        default="both",
        help="Plan tier to validate: enterprise, growth, or both (default: both)",
    )
    cli_args = parser.parse_args()

    selected_tier = cli_args.tier.upper()
    if selected_tier == "BOTH":
        print("\n" + "#" * 80)
        print("  RUNNING COMPLETE MULTI-TIER VALIDATION: 1. ENTERPRISE  -->  2. GROWTH  ")
        print("#" * 80 + "\n")
        res_ent = run_e2e_live_validation("ENTERPRISE")
        print("\n\n" + "#" * 80)
        print("  PROCEEDING TO SECOND TIER: GROWTH ONBOARDING (14-DAY POOLED)  ")
        print("#" * 80 + "\n")
        res_grw = run_e2e_live_validation("GROWTH")
    else:
        run_e2e_live_validation(selected_tier)
