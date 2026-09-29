# Dedicated Live Proof-of-Functionality test suite for email schema validation and clarification guardrails.  # What: Module header; Why: Proves zero-guessing validation and live draft staging against real APIs.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps and unique test identifiers.
from email.message import EmailMessage  # What: Import EmailMessage; Why: Validates MIME formatting.
import pytest  # What: Import pytest; Why: Test assertion and execution framework.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent 1; Why: Runs deterministic schema validation and draft generation.
from src.agents.agent2_communication import Agent2Communication  # What: Import Agent 2; Why: Verifies Slack provisioning is skipped on upstream halts.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Verifies structured audit trail entries for validation halts.
from src.core.config import settings  # What: Import application settings; Why: Retrieves configured credentials and endpoints.
from src.models.schemas import InboundEmailPayload, PlanTier  # What: Import domain models; Why: Type contracts for email payloads.
from src.services.gmail_poller import GmailPoller  # What: Import GmailPoller; Why: Connects to live Gmail IMAP for draft staging.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Uses live Rocketlane client to prove no projects created.
from src.services.slack_client import SlackClient  # What: Import SlackClient; Why: Uses live Slack client to prove no channels created.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Telephony client.


# ==============================================================================
# VAL-1: MISSING CUSTOMER NAME GUARDRAIL & LIVE GMAIL DRAFT STAGING
# ==============================================================================

def test_val1_missing_customer_name_halts_and_stages_draft() -> None:  # What: Test VAL-1; Why: Proves missing customer_name halts pipeline and stages draft in Gmail.
    """Guarantees that an email missing customer_name halts execution, creates no Rocketlane project, and stages draft in [Gmail]/Drafts."""  # What: Docstring; Why: Documents VAL-1 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion and validation orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Proves no project created in real workspace.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Proves telephony is not dialed on invalid data.
    poller = GmailPoller(mock_mode=False)  # What: LIVE Gmail poller; Why: Stages draft to real [Gmail]/Drafts over TLS.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate 5-digit unique timestamp; Why: Prevents collision.
    correlation_id = f"val1_noname_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.

    # Inbound email completely omitting customer_name
    missing_name_email = {  # What: Incomplete raw email dictionary; Why: Simulates missing customer_name.
        "message_id": f"msg_val1_{test_ts}",  # What: Unique message ID; Why: Email identifier.
        "customer_contact_email": f"ceo_{test_ts}@acmecorp.com",  # What: Contact email; Why: Present.
        "ae_name": "Jordan Bell",  # What: Account Executive name; Why: Present.
        "ae_email": "jordan@novacrm.com",  # What: AE email; Why: Present.
        "ae_phone": "+1-555-0100",  # What: AE phone; Why: Present.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: Present.
    }  # What: End of incomplete dictionary; Why: customer_name omitted.

    # Execute Agent 1 validation
    result = agent1.process_deal(missing_name_email, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Triggers deterministic validator.

    # 1. Assert pipeline halted with zero guesswork
    assert result.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED; Why: Missing field strictly blocks pipeline.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Zero live Rocketlane project created.
    assert result.voice_result is None  # What: Assert no call made; Why: Did not dial phone on missing data.
    assert result.clarification_draft is not None  # What: Assert draft generated; Why: Clarification draft created for AE.
    assert "customer_name" in result.clarification_draft.missing_fields  # What: Assert customer_name in missing list; Why: Correct field identified.
    assert result.clarification_draft.recipient_email == "jordan@novacrm.com"  # What: Assert recipient is AE; Why: Directed to deal owner.

    # 2. Stage clarification draft directly into LIVE [Gmail]/Drafts via IMAP
    draft_staged = poller.stage_clarification_draft(  # What: Call live stage_clarification_draft; Why: Inserts draft into real [Gmail]/Drafts.
        draft=result.clarification_draft,  # What: Inbound draft model; Why: Clarification text.
        correlation_id=correlation_id,  # What: Correlation ID; Why: Connects to deal trail.
        in_reply_to=f"<msg_val1_{test_ts}@novacrm.com>",  # What: Message ID header; Why: Standard RFC 2822 threading.
        original_subject="[New Deal] Closed Won Opportunity"  # What: Original subject line; Why: Sets Re: subject in Gmail.
    )  # What: End of live stage call; Why: Appended to live Gmail folder.
    assert draft_staged is True  # What: Assert draft staged True; Why: Confirms IMAP APPEND succeeded on live Gmail.
    print(f"\n[+] VAL-1 PASSED: Halted on missing customer_name; Draft staged in [Gmail]/Drafts for {result.clarification_draft.recipient_email}")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# VAL-2: MISSING CUSTOMER CONTACT EMAIL GUARDRAIL & DOWNSTREAM SKIPPING
# ==============================================================================

def test_val2_missing_contact_email_halts_and_skips_slack() -> None:  # What: Test VAL-2; Why: Proves missing contact email halts Agent 1 and skips Agent 2 Slack channel.
    """Guarantees that an email missing customer_contact_email halts Agent 1 and causes Agent 2 to skip Slack provisioning."""  # What: Docstring; Why: Documents VAL-2 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Proves no project created.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Proves no voice call made.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))  # What: LIVE Slack client; Why: Proves no Slack channel created.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate 5-digit unique timestamp; Why: Prevents collision.
    correlation_id = f"val2_noemail_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.
    customer_name = f"Wayne Enterprises {test_ts}"  # What: Customer name; Why: Name field.

    # Inbound email completely omitting customer_contact_email
    missing_email_deal = {  # What: Incomplete raw email dictionary; Why: Simulates missing customer_contact_email.
        "message_id": f"msg_val2_{test_ts}",  # What: Unique message ID; Why: Email identifier.
        "customer_name": customer_name,  # What: Customer name; Why: Present.
        "ae_name": "Lucius Fox",  # What: AE name; Why: Present.
        "ae_email": "lucius@novacrm.com",  # What: AE email; Why: Present.
        "ae_phone": "+1-555-0299",  # What: AE phone; Why: Present.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: Present.
    }  # What: End of incomplete dictionary; Why: customer_contact_email omitted.

    # Execute Agent 1 validation
    a1_result = agent1.process_deal(missing_email_deal, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Runs deterministic validator.
    assert a1_result.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED; Why: Missing contact email halts pipeline.
    assert a1_result.rocketlane_project is None  # What: Assert no project created; Why: Zero live Rocketlane project created.
    assert "customer_contact_email" in a1_result.clarification_draft.missing_fields  # What: Assert contact email in missing list; Why: Correct field identified.

    # Execute Agent 2 handoff: Must skip cleanly without creating a live Slack channel
    a2_result = agent2.process_project_handoff(a1_result)  # What: Process handoff via Agent 2; Why: Tests precondition guardrail.
    assert a2_result.status == "SKIPPED_UNCONFIRMED"  # What: Assert status SKIPPED; Why: Precondition prevents Slack provisioning.
    assert a2_result.provisioning_result is None  # What: Assert no channel created; Why: Zero live Slack channel created.
    assert "Slack provisioning skipped" in (a2_result.error_message or "")  # What: Assert skip explanation; Why: Clear audit reason.
    print(f"\n[+] VAL-2 PASSED: Halted on missing contact email; Agent 2 cleanly skipped live Slack channel provisioning.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# VAL-3: MISSING AE PHONE NUMBER GUARDRAIL (CANNOT EXECUTE VOICE CONFIRMATION)
# ==============================================================================

def test_val3_missing_ae_phone_blocks_telephony() -> None:  # What: Test VAL-3; Why: Proves missing AE phone halts pipeline before attempting Voice AI call.
    """Guarantees that an email missing ae_phone halts pipeline and avoids attempting unroutable phone calls."""  # What: Docstring; Why: Documents VAL-3 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Proves no project created.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Proves telephony bypassed.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate 5-digit unique timestamp; Why: Prevents collision.
    correlation_id = f"val3_nophone_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.

    # Inbound email completely omitting ae_phone
    missing_phone_deal = {  # What: Incomplete raw email dictionary; Why: Simulates missing ae_phone.
        "message_id": f"msg_val3_{test_ts}",  # What: Unique message ID; Why: Email identifier.
        "customer_name": f"Stark Industries {test_ts}",  # What: Customer name; Why: Present.
        "customer_contact_email": f"pepper_{test_ts}@stark.com",  # What: Contact email; Why: Present.
        "ae_name": "Tony Stark",  # What: AE name; Why: Present.
        "ae_email": "tony@novacrm.com",  # What: AE email; Why: Present.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: Present.
    }  # What: End of incomplete dictionary; Why: ae_phone omitted.

    result = agent1.process_deal(missing_phone_deal, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Runs deterministic validator.
    assert result.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED; Why: Missing phone halts pipeline.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Zero live Rocketlane project created.
    assert result.voice_result is None  # What: Assert no voice call dispatched; Why: Cannot call without destination number.
    assert "ae_phone" in result.clarification_draft.missing_fields  # What: Assert ae_phone in missing list; Why: Correct field identified.
    print(f"\n[+] VAL-3 PASSED: Halted on missing ae_phone; Voice AI outbound telephony safely suppressed.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# VAL-4: MALFORMED EMAIL FORMAT SYNTAX REJECTION (RFC VIOLATION)
# ==============================================================================

def test_val4_malformed_email_syntax_rejected() -> None:  # What: Test VAL-4; Why: Proves invalid email formats (e.g. 'not-an-email') are rejected.
    """Guarantees that an email with invalid syntax fails Pydantic validation and triggers a clarification request."""  # What: Docstring; Why: Documents VAL-4 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Proves no project created.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate unique timestamp; Why: Prevents collision.
    correlation_id = f"val4_bademail_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.

    # Inbound email with syntactically malformed customer contact email
    malformed_email_deal = {  # What: Malformed email dictionary; Why: Simulates bad email syntax.
        "message_id": f"msg_val4_{test_ts}",  # What: Message ID; Why: Email identifier.
        "customer_name": f"Cyberdyne Systems {test_ts}",  # What: Customer name; Why: Present.
        "customer_contact_email": "invalid-email-address-without-at-or-domain",  # What: Malformed email; Why: Fails RFC format validation.
        "ae_name": "Miles Dyson",  # What: AE name; Why: Present.
        "ae_phone": "+1-555-0199",  # What: AE phone; Why: Present.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: Present.
    }  # What: End of malformed dictionary; Why: Bad email syntax.

    result = agent1.process_deal(malformed_email_deal, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Runs deterministic validator.
    assert result.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED; Why: Malformed email format halts pipeline.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Zero live Rocketlane project created.
    assert "customer_contact_email" in result.clarification_draft.missing_fields  # What: Assert contact email flagged; Why: Treated as missing/invalid.
    print(f"\n[+] VAL-4 PASSED: Malformed email syntax rejected cleanly; Pipeline halted without guessing.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# VAL-5: WHITESPACE-ONLY / EMPTY STRING REJECTION
# ==============================================================================

def test_val5_whitespace_only_fields_rejected() -> None:  # What: Test VAL-5; Why: Proves strings consisting purely of whitespace are rejected as empty.
    """Guarantees that whitespace-only strings fail non-empty validation and halt project creation."""  # What: Docstring; Why: Documents VAL-5 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Proves no project created.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate unique timestamp; Why: Prevents collision.
    correlation_id = f"val5_whitespace_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.

    # Inbound email with whitespace customer name and phone
    whitespace_deal = {  # What: Whitespace dictionary; Why: Simulates empty strings containing only spaces.
        "message_id": f"msg_val5_{test_ts}",  # What: Message ID; Why: Email identifier.
        "customer_name": "     ",  # What: Whitespace customer name; Why: Must fail non-empty validator.
        "customer_contact_email": f"ops_{test_ts}@validcorp.com",  # What: Valid contact email; Why: Present.
        "ae_name": "Jordan Bell",  # What: AE name; Why: Present.
        "ae_phone": "   \t  \n  ",  # What: Whitespace phone; Why: Must fail non-empty validator.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: Present.
    }  # What: End of whitespace dictionary; Why: Invalid whitespace payload.

    result = agent1.process_deal(whitespace_deal, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Runs deterministic validator.
    assert result.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED; Why: Whitespace fields halt pipeline.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Zero live Rocketlane project created.
    assert "customer_name" in result.clarification_draft.missing_fields  # What: Assert customer_name flagged; Why: Trimmed to empty.
    assert "ae_phone" in result.clarification_draft.missing_fields  # What: Assert ae_phone flagged; Why: Trimmed to empty.
    print(f"\n[+] VAL-5 PASSED: Whitespace-only fields rejected cleanly; System refuses to create blank entities.")  # What: Print confirmation; Why: Terminal visibility.


# ==============================================================================
# VAL-6: MULTIPLE MISSING FIELDS CONSOLIDATION & AUDIT LOG PROOF
# ==============================================================================

def test_val6_multiple_missing_fields_consolidated_in_single_draft() -> None:  # What: Test VAL-6; Why: Proves multiple missing fields are consolidated into one email draft.
    """Guarantees that an email missing multiple fields consolidates all omitted items into one single draft and logs audit entry."""  # What: Docstring; Why: Documents VAL-6 intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=False)  # What: LIVE Rocketlane client; Why: Proves no project created.

    test_ts = int(datetime.now().timestamp()) % 100000  # What: Generate unique timestamp; Why: Prevents collision.
    correlation_id = f"val6_multi_{test_ts}"  # What: Correlation ID; Why: Tracks deal in audit logs.

    # Inbound email missing customer_name, customer_contact_email, AND ae_phone
    multi_missing_deal = {  # What: Multi-missing raw email dictionary; Why: Simulates severely deficient deal email.
        "message_id": f"msg_val6_{test_ts}",  # What: Message ID; Why: Email identifier.
        "ae_name": "Gordon Gekko",  # What: AE name; Why: Only field provided.
        "ae_email": "gordon@novacrm.com",  # What: AE email; Why: Present.
        "opportunity_url": f"https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c_{test_ts}/view"  # What: SFDC link; Why: Present.
    }  # What: End of multi-missing dictionary; Why: 3 fields omitted.

    result = agent1.process_deal(multi_missing_deal, correlation_id=correlation_id)  # What: Process deal via Agent 1; Why: Runs deterministic validator.
    assert result.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED; Why: Missing fields halt pipeline.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Zero live Rocketlane project created.

    # Assert that ALL 3 missing fields are listed in the single generated draft
    missing = result.clarification_draft.missing_fields  # What: Extract missing fields list; Why: Inspects consolidated draft.
    assert "customer_name" in missing  # What: Assert customer_name missing; Why: Correctly flagged.
    assert "customer_contact_email" in missing  # What: Assert contact email missing; Why: Correctly flagged.
    assert "ae_phone" in missing  # What: Assert ae_phone missing; Why: Correctly flagged.

    # Verify structured audit log entry
    audit_entries = audit_logger.get_entries_for_correlation(correlation_id)  # What: Query audit logs; Why: Verifies audit trail.
    actions = [entry.action for entry in audit_entries]  # What: Extract action names list; Why: Checks logged actions.
    assert "schema_validation_halt" in actions  # What: Assert validation halt logged; Why: Immutable proof of zero-guessing guardrail.
    print(f"\n[+] VAL-6 PASSED: All 3 missing fields consolidated into single draft; Audit action 'schema_validation_halt' recorded.")  # What: Print confirmation; Why: Terminal visibility.
