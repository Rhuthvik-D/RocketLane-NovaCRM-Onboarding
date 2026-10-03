"""Automated test suite for Gmail CS Inbox poller service and email parsing heuristics."""
from datetime import datetime, timezone
import pytest
from src.agents.agent1_intake import Agent1Intake
from src.agents.agent2_communication import Agent2Communication
from src.models.schemas import PlanTier, VoiceCallResult, VoiceCallStatus
from src.services.gmail_poller import GmailPoller
from src.services.rocketlane_client import RocketlaneClient
from src.services.slack_client import SlackClient
from src.services.voice_ai_client import VoiceAIClient


def test_gmail_poller_parse_standard_deal_email() -> None:
    """Ensures GmailPoller extracts customer name, contact email, AE name, phone, and opportunity URL accurately."""
    poller = GmailPoller(mock_mode=True)
    body = (
        "Team,\n\n"
        "Excited to share that Stark Industries just signed!\n\n"
        "Customer Name: Stark Industries\n"
        "Customer Contact Email: pepper.potts@stark.com\n"
        "AE Name: Tony Stark\n"
        "AE Phone: +1-555-0199\n"
        "Salesforce Opportunity: https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c0001/view\n\n"
        "Best,\nTony"
    )

    deal = poller.parse_deal_from_email(
        message_id="msg_test_001",
        sender="Tony Stark <tony@novacrm.com>",
        subject="[New Deal] Stark Industries Closed Won",
        body=body
    )

    assert deal["customer_name"] == "Stark Industries"
    assert deal["customer_contact_email"] == "pepper.potts@stark.com"
    assert deal["ae_name"] == "Tony Stark"
    assert deal["ae_phone"] == "+1-555-0199"
    assert "https://novacrm.lightning.force.com" in deal["opportunity_url"]
    assert deal["ae_email"] == "tony@novacrm.com"


def test_gmail_poller_subject_fallback_and_raw_links() -> None:
    """Ensures customer name is extracted from subject line and SFDC link from raw body text when labels are omitted."""
    poller = GmailPoller(mock_mode=True)
    body = (
        "Hey Priya,\n\n"
        "Just closed Wayne Enterprises! Contact is bruce@wayneenterprises.com. Call me at +1-555-0299 if needed.\n"
        "Opportunity: https://novacrm.salesforce.com/opp/0068c0002\n\n"
        "Thanks,\nLucius Fox"
    )

    deal = poller.parse_deal_from_email(
        message_id="msg_test_002",
        sender="Lucius Fox <lucius@novacrm.com>",
        subject="[New Deal] Wayne Enterprises - Onboarding",
        body=body
    )

    assert deal["customer_name"] == "Wayne Enterprises"
    assert deal["customer_contact_email"] == "bruce@wayneenterprises.com"
    assert deal["ae_phone"] == "+1-555-0299"
    assert "https://novacrm.salesforce.com/opp/0068c0002" in deal["opportunity_url"]


def test_gmail_poller_incomplete_email_halts_with_clarification() -> None:
    """Guarantees that an email missing required fields (e.g. phone or contact email) halts Agent 1 and generates a clarification draft."""
    poller = GmailPoller(mock_mode=True)
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)

    body = (
        "Hi CS,\n\n"
        "Customer Name: Cyberdyne Systems\n"
        "AE Name: Miles Dyson\n"
        "Opportunity: https://novacrm.salesforce.com/opp/003\n"
    )

    poller.inject_mock_email(
        sender="Miles Dyson <miles@novacrm.com>",
        subject="[New Deal] Cyberdyne Systems Onboarding",
        body=body
    )

    results = poller.process_incoming_deals(agent1=agent1)
    assert len(results) == 1
    assert results[0]["customer_name"] == "Cyberdyne Systems"
    assert results[0]["agent1_status"] == "HALTED_MISSING_DATA"
    assert results[0]["clarification_needed"] is True
    assert results[0]["draft_staged"] is True
    assert len(poller._staged_drafts) == 1
    assert poller._staged_drafts[0]["recipient"] == "miles@novacrm.com"
    assert results[0]["rocketlane_project_id"] is None


def test_gmail_poller_subject_filter_ignores_unrelated_traffic() -> None:
    """Guarantees that emails lacking the subject filter keyword (e.g. Rocketlane notifications) are ignored."""
    poller = GmailPoller(mock_mode=True, subject_filter="New Deal")
    agent1 = Agent1Intake()

    # Inject Rocketlane notification email (which arrives at CS inbox but is NOT a deal notification)
    poller.inject_mock_email(
        sender="Rocketlane Notifications <notifications@rocketlane.com>",
        subject="Rocketlane_assignment from NYU has invited you to project 'Apex Dynamics'",
        body="You have been assigned as the Project Owner for Apex Dynamics Onboarding."
    )

    results = poller.process_incoming_deals(agent1=agent1)
    assert len(results) == 0


def test_gmail_poller_full_happy_path_pipeline() -> None:
    """Tests complete happy path: Inbound email polled -> Enterprise verified -> Rocketlane project created -> Slack channel provisioned."""
    poller = GmailPoller(mock_mode=True)
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))

    test_ts = int(datetime.now().timestamp())

    # 1. Configure Voice AI verbal confirmation for Enterprise
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id=f"call_gmail_{test_ts}",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.ENTERPRISE,
            transcript="Yes, confirming Stark Industries signed our Enterprise plan.",
            confidence_score=0.99
        )
    )

    # 2. Inject valid AE deal notification email
    body = (
        "Customer Name: Stark Industries\n"
        "Customer Contact Email: pepper@stark.com\n"
        "AE Name: Tony Stark\n"
        "AE Phone: +1-555-0199\n"
        "Opportunity URL: https://novacrm.salesforce.com/opp/stark\n"
    )

    poller.inject_mock_email(
        sender="Tony Stark <tony@novacrm.com>",
        subject="[New Deal] Stark Industries Enterprise Onboarding",
        body=body
    )

    # 3. Process inbox through full multi-agent pipeline
    results = poller.process_incoming_deals(agent1=agent1, agent2=agent2)

    # 4. Assertions on complete workflow execution
    assert len(results) == 1
    assert results[0]["customer_name"] == "Stark Industries"
    assert results[0]["agent1_status"] == "SUCCESS"
    assert results[0]["agent2_status"] == "SUCCESS"
    assert results[0]["rocketlane_project_id"] is not None
    assert results[0]["clarification_needed"] is False


def test_gmail_poller_ae_reply_threads_missing_field_from_quotes() -> None:
    """Guarantees that an AE replying with just the missing contact email correctly combines with quoted thread details."""
    poller = GmailPoller(mock_mode=True)
    reply_body = (
        "Customer Contact Email: sarah.connor@cyberdyne.com\n\n"
        "On Sun, Sep 27, 2026, CS Team wrote:\n"
        "> Hi Miles, please provide the customer contact email.\n"
        "> \n"
        "> Customer Name: Cyberdyne Systems\n"
        "> AE Name: Miles Dyson\n"
        "> AE Phone: +1-555-0199\n"
        "> Salesforce Opportunity: https://novacrm.salesforce.com/opp/003\n"
    )

    deal = poller.parse_deal_from_email(
        message_id="msg_reply_001",
        sender="Miles Dyson <miles@novacrm.com>",
        subject="Re: [New Deal] [Action Required] Clarification Needed for Cyberdyne Systems Onboarding",
        body=reply_body
    )

    assert deal["customer_name"] == "Cyberdyne Systems"
    assert deal["customer_contact_email"] == "sarah.connor@cyberdyne.com"
    assert deal["ae_name"] == "Miles Dyson"
    assert deal["ae_phone"] == "+1-555-0199"
    assert "https://novacrm.salesforce.com/opp/003" in deal["opportunity_url"]


def test_gmail_poller_multi_missing_fields_consolidated_in_single_draft_and_cached() -> None:
    """Ensures multiple missing fields are consolidated into one clarification draft and resolved across email turns."""
    poller = GmailPoller(mock_mode=True)
    agent1 = Agent1Intake()
    agent1.rocketlane = RocketlaneClient(mock_mode=True)
    agent1.voice_client = VoiceAIClient(mock_mode=True)
    agent1.voice_client.set_simulation_outcome(
        VoiceCallResult(
            call_id="call_mock_multi",
            status=VoiceCallStatus.CONFIRMED,
            confirmed_tier=PlanTier.GROWTH,
            transcript="Yes, Cyberdrone is on Growth tier.",
            confidence_score=0.95
        )
    )

    # Turn 1: Email missing BOTH contact email and phone, containing SFDC URL
    body_turn1 = (
        "Customer Name: Cyberdrone Systems\n"
        "AE Name: Miles Dyson\n"
        "Salesforce Opportunity: https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c0000999/view\n"
    )

    poller.inject_mock_email(
        sender="Miles Dyson <miles@novacrm.com>",
        subject="[New Deal] Cyberdrone Systems Onboarding",
        body=body_turn1
    )

    results_turn1 = poller.process_incoming_deals(agent1=agent1)
    assert len(results_turn1) == 1
    assert results_turn1[0]["agent1_status"] == "HALTED_MISSING_DATA"
    assert results_turn1[0]["draft_staged"] is True

    # Assert that BOTH fields were identified and consolidated into a SINGLE draft
    assert len(poller._staged_drafts) == 1
    staged = poller._staged_drafts[0]
    assert "customer_contact_email" in staged["missing_fields"]
    assert "ae_phone" in staged["missing_fields"]
    assert "cyberdrone systems" in poller._thread_deal_cache

    # Turn 2: AE replies with the missing info, without re-sending the SFDC URL
    reply_body = (
        "Customer Contact Email: sarah.connor@cyberdrone.com\n"
        "AE Phone: +1-555-4321\n"
    )

    poller.inject_mock_email(
        sender="Miles Dyson <miles@novacrm.com>",
        subject="Re: [New Deal] [Action Required] Clarification Needed for Cyberdrone Systems Onboarding",
        body=reply_body
    )

    results_turn2 = poller.process_incoming_deals(agent1=agent1)
    assert len(results_turn2) == 1
    assert results_turn2[0]["agent1_status"] == "SUCCESS"
    assert results_turn2[0]["rocketlane_project_id"] is not None
    assert "cyberdrone systems" not in poller._thread_deal_cache


def test_gmail_poller_survives_deal_processing_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantees that an unhandled exception in deal processing is logged and does not kill the poller daemon."""
    poller = GmailPoller(mock_mode=True)
    agent1 = Agent1Intake()

    # Simulate unexpected failure during agent1.process_deal
    def crashing_process_deal(*args, **kwargs):
        raise RuntimeError("Unexpected upstream API meltdown!")

    monkeypatch.setattr(agent1, "process_deal", crashing_process_deal)

    poller.inject_mock_email(
        sender="Crash Test <crash@novacrm.com>",
        subject="[New Deal] Crash Corp Onboarding",
        body="Customer Name: Crash Corp\nCustomer Contact Email: info@crash.com\nAE Name: Tester\nAE Phone: +1-555-9999\nOpportunity: https://novacrm.salesforce.com/opp/999"
    )

    # Poller process_incoming_deals must NOT raise exception
    results = poller.process_incoming_deals(agent1=agent1)
    assert len(results) == 1
    assert results[0]["agent1_status"] == "FAILED"
    assert "Unexpected upstream API meltdown!" in results[0]["error"]
