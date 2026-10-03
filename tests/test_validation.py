"""Dedicated Live Proof-of-Functionality test suite for email schema validation and clarification guardrails."""
from datetime import datetime, timezone
from email.message import EmailMessage
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import InboundEmailPayload, PlanTier
from src.services.gmail_poller import GmailPoller
from src.services.rocketlane_client import RocketlaneClient
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


# ==============================================================================
# VAL-1: MISSING CUSTOMER NAME GUARDRAIL & LIVE GMAIL DRAFT STAGING
# ==============================================================================

def test_val1_missing_customer_name_halts_and_stages_draft() -> None:
    """Guarantees that an email missing customer_name halts execution, creates no Rocketlane project, and stages draft in [Gmail]/Drafts."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    poller = GmailPoller(mock_mode=False)

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"val1_noname_{test_ts}"

    # Inbound email completely omitting customer_name
    missing_name_email = {
        "message_id": f"msg_val1_{test_ts}",
        "customer_contact_email": f"ceo_{test_ts}@acmecorp.com",
        "ae_name": "Jordan Bell",
        "ae_email": "jordan@novacrm.com",
        "ae_phone": "+1-555-0100",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    # Execute Agent 1 validation
    result = agent1.process_deal(missing_name_email, correlation_id=correlation_id)

    # 1. Assert pipeline halted with zero guesswork
    assert result.status == "HALTED_MISSING_DATA"
    assert result.rocketlane_project is None
    assert result.voice_result is None
    assert result.clarification_draft is not None
    assert "customer_name" in result.clarification_draft.missing_fields
    assert result.clarification_draft.recipient_email == "jordan@novacrm.com"

    # 2. Stage clarification draft directly into LIVE [Gmail]/Drafts via IMAP
    draft_staged = poller.stage_clarification_draft(
        draft=result.clarification_draft,
        correlation_id=correlation_id,
        in_reply_to=f"<msg_val1_{test_ts}@novacrm.com>",
        original_subject="[New Deal] Closed Won Opportunity"
    )
    assert draft_staged is True
    print(f"\n[+] VAL-1 PASSED: Halted on missing customer_name; Draft staged in [Gmail]/Drafts for {result.clarification_draft.recipient_email}")


# ==============================================================================
# VAL-2: MISSING CUSTOMER CONTACT EMAIL GUARDRAIL & DOWNSTREAM SKIPPING
# ==============================================================================

def test_val2_missing_contact_email_halts_and_skips_slack() -> None:
    """Guarantees that an email missing customer_contact_email halts Agent 1 and causes Agent 2 to skip Slack provisioning."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"val2_noemail_{test_ts}"
    customer_name = f"Wayne Enterprises {test_ts}"

    # Inbound email completely omitting customer_contact_email
    missing_email_deal = {
        "message_id": f"msg_val2_{test_ts}",
        "customer_name": customer_name,
        "ae_name": "Lucius Fox",
        "ae_email": "lucius@novacrm.com",
        "ae_phone": "+1-555-0299",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    # Execute Agent 1 validation
    a1_result = agent1.process_deal(missing_email_deal, correlation_id=correlation_id)
    assert a1_result.status == "HALTED_MISSING_DATA"
    assert a1_result.rocketlane_project is None
    assert "customer_contact_email" in a1_result.clarification_draft.missing_fields

    # Execute Agent 2 handoff: Must skip cleanly without creating a live Slack channel
    a2_result = agent2.process_project_handoff(a1_result)
    assert a2_result.status == "SKIPPED_UNCONFIRMED"
    assert a2_result.provisioning_result is None
    assert "Slack provisioning skipped" in (a2_result.error_message or "")
    print(f"\n[+] VAL-2 PASSED: Halted on missing contact email; Agent 2 cleanly skipped live Slack channel provisioning.")


# ==============================================================================
# VAL-3: MISSING AE PHONE NUMBER GUARDRAIL (CANNOT EXECUTE VOICE CONFIRMATION)
# ==============================================================================

def test_val3_missing_ae_phone_blocks_telephony() -> None:
    """Guarantees that an email missing ae_phone halts pipeline and avoids attempting unroutable phone calls."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"val3_nophone_{test_ts}"

    # Inbound email completely omitting ae_phone
    missing_phone_deal = {
        "message_id": f"msg_val3_{test_ts}",
        "customer_name": f"Stark Industries {test_ts}",
        "customer_contact_email": f"pepper_{test_ts}@stark.com",
        "ae_name": "Tony Stark",
        "ae_email": "tony@novacrm.com",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    result = agent1.process_deal(missing_phone_deal, correlation_id=correlation_id)
    assert result.status == "HALTED_MISSING_DATA"
    assert result.rocketlane_project is None
    assert result.voice_result is None
    assert "ae_phone" in result.clarification_draft.missing_fields
    print(f"\n[+] VAL-3 PASSED: Halted on missing ae_phone; Voice AI outbound telephony safely suppressed.")


# ==============================================================================
# VAL-4: MALFORMED EMAIL FORMAT SYNTAX REJECTION (RFC VIOLATION)
# ==============================================================================

def test_val4_malformed_email_syntax_rejected() -> None:
    """Guarantees that an email with invalid syntax fails Pydantic validation and triggers a clarification request."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"val4_bademail_{test_ts}"

    # Inbound email with syntactically malformed customer contact email
    malformed_email_deal = {
        "message_id": f"msg_val4_{test_ts}",
        "customer_name": f"Cyberdyne Systems {test_ts}",
        "customer_contact_email": "invalid-email-address-without-at-or-domain",
        "ae_name": "Miles Dyson",
        "ae_phone": "+1-555-0199",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    result = agent1.process_deal(malformed_email_deal, correlation_id=correlation_id)
    assert result.status == "HALTED_MISSING_DATA"
    assert result.rocketlane_project is None
    assert "customer_contact_email" in result.clarification_draft.missing_fields
    print(f"\n[+] VAL-4 PASSED: Malformed email syntax rejected cleanly; Pipeline halted without guessing.")


# ==============================================================================
# VAL-5: WHITESPACE-ONLY / EMPTY STRING REJECTION
# ==============================================================================

def test_val5_whitespace_only_fields_rejected() -> None:
    """Guarantees that whitespace-only strings fail non-empty validation and halt project creation."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"val5_whitespace_{test_ts}"

    # Inbound email with whitespace customer name and phone
    whitespace_deal = {
        "message_id": f"msg_val5_{test_ts}",
        "customer_name": "     ",
        "customer_contact_email": f"ops_{test_ts}@validcorp.com",
        "ae_name": "Jordan Bell",
        "ae_phone": "   \t  \n  ",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    result = agent1.process_deal(whitespace_deal, correlation_id=correlation_id)
    assert result.status == "HALTED_MISSING_DATA"
    assert result.rocketlane_project is None
    assert "customer_name" in result.clarification_draft.missing_fields
    assert "ae_phone" in result.clarification_draft.missing_fields
    print(f"\n[+] VAL-5 PASSED: Whitespace-only fields rejected cleanly; System refuses to create blank entities.")


# ==============================================================================
# VAL-6: MULTIPLE MISSING FIELDS CONSOLIDATION & AUDIT LOG PROOF
# ==============================================================================

def test_val6_multiple_missing_fields_consolidated_in_single_draft() -> None:
    """Guarantees that an email missing multiple fields consolidates all omitted items into one single draft and logs audit entry."""
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=False)

    test_ts = int(datetime.now().timestamp()) % 100000
    correlation_id = f"val6_multi_{test_ts}"

    # Inbound email missing customer_name, customer_contact_email, AND ae_phone
    multi_missing_deal = {
        "message_id": f"msg_val6_{test_ts}",
        "ae_name": "Gordon Gekko",
        "ae_email": "gordon@novacrm.com",
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"
    }

    result = agent1.process_deal(multi_missing_deal, correlation_id=correlation_id)
    assert result.status == "HALTED_MISSING_DATA"
    assert result.rocketlane_project is None

    # Assert that ALL 3 missing fields are listed in the single generated draft
    missing = result.clarification_draft.missing_fields
    assert "customer_name" in missing
    assert "customer_contact_email" in missing
    assert "ae_phone" in missing

    # Verify structured audit log entry
    audit_entries = audit_logger.get_entries_for_correlation(correlation_id)
    actions = [entry.action for entry in audit_entries]
    assert "schema_validation_halt" in actions
    print(f"\n[+] VAL-6 PASSED: All 3 missing fields consolidated into single draft; Audit action 'schema_validation_halt' recorded.")
