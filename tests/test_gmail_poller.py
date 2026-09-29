# Automated test suite for Gmail CS Inbox poller service and email parsing heuristics.  # What: Module header; Why: Validates Gmail ingestion component.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps in test payloads.
import pytest  # What: Import pytest; Why: Test assertion and execution framework.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent 1; Why: Ingests parsed deal payloads.
from src.agents.agent2_communication import Agent2Communication  # What: Import Agent 2; Why: Provisions customer Slack channel.
from src.models.schemas import PlanTier, VoiceCallResult, VoiceCallStatus  # What: Import schemas; Why: Configures mock voice call outcomes.
from src.services.gmail_poller import GmailPoller  # What: Import GmailPoller; Why: Tests poller methods and parsing logic.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Uses mock Rocketlane for fast unit test.
from src.services.slack_client import SlackClient  # What: Import SlackClient; Why: Uses mock Slack client.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Uses mock Voice AI for verbal confirmation.


def test_gmail_poller_parse_standard_deal_email() -> None:  # What: Parsing unit test; Why: Verifies extraction from standard AE notification format.
    """Ensures GmailPoller extracts customer name, contact email, AE name, phone, and opportunity URL accurately."""  # What: Docstring; Why: Documents test intent.
    poller = GmailPoller(mock_mode=True)  # What: Instantiate poller in mock mode; Why: Isolated unit test without network calls.
    body = (  # What: Sample well-formatted AE email body; Why: Standard deal notification format.
        "Team,\n\n"  # What: Salutation; Why: Context.
        "Excited to share that Stark Industries just signed!\n\n"  # What: Announcement; Why: Context.
        "Customer Name: Stark Industries\n"  # What: Customer name; Why: Name field.
        "Customer Contact Email: pepper.potts@stark.com\n"  # What: Contact email; Why: Email field.
        "AE Name: Tony Stark\n"  # What: AE name; Why: Deal owner field.
        "AE Phone: +1-555-0199\n"  # What: AE phone; Why: Destination number field.
        "Salesforce Opportunity: https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c0001/view\n\n"  # What: SFDC link; Why: Context URL field.
        "Best,\nTony"  # What: Closing; Why: Sign-off.
    )  # What: End of body string; Why: Complete email body.

    deal = poller.parse_deal_from_email(  # What: Parse email into deal dict; Why: Executes parsing heuristics.
        message_id="msg_test_001",  # What: Message ID; Why: Identifier.
        sender="Tony Stark <tony@novacrm.com>",  # What: Sender header; Why: AE sender.
        subject="[New Deal] Stark Industries Closed Won",  # What: Subject line; Why: Subject context.
        body=body  # What: Email body; Why: Text content.
    )  # What: End of parse call; Why: Returns deal dictionary.

    assert deal["customer_name"] == "Stark Industries"  # What: Assert customer name; Why: Extracted accurately.
    assert deal["customer_contact_email"] == "pepper.potts@stark.com"  # What: Assert contact email; Why: Extracted accurately.
    assert deal["ae_name"] == "Tony Stark"  # What: Assert AE name; Why: Extracted accurately.
    assert deal["ae_phone"] == "+1-555-0199"  # What: Assert AE phone; Why: Extracted accurately.
    assert "https://novacrm.lightning.force.com" in deal["opportunity_url"]  # What: Assert SFDC link; Why: Extracted accurately.
    assert deal["ae_email"] == "tony@novacrm.com"  # What: Assert AE email; Why: Parsed from From header.


def test_gmail_poller_subject_fallback_and_raw_links() -> None:  # What: Fallback heuristic test; Why: Verifies subject name and link extraction when labels missing.
    """Ensures customer name is extracted from subject line and SFDC link from raw body text when labels are omitted."""  # What: Docstring; Why: Documents test intent.
    poller = GmailPoller(mock_mode=True)  # What: Instantiate poller in mock mode; Why: Offline testing.
    body = (  # What: Informally formatted email body; Why: Simulates unstructured AE email.
        "Hey Priya,\n\n"  # What: Salutation; Why: Context.
        "Just closed Wayne Enterprises! Contact is bruce@wayneenterprises.com. Call me at +1-555-0299 if needed.\n"  # What: Inline text; Why: Unlabeled fields.
        "Opportunity: https://novacrm.salesforce.com/opp/0068c0002\n\n"  # What: Opp link; Why: Salesforce link.
        "Thanks,\nLucius Fox"  # What: Closing; Why: Sign-off.
    )  # What: End of body string; Why: Complete informal email.

    deal = poller.parse_deal_from_email(  # What: Parse informal email; Why: Tests regex and subject fallback heuristics.
        message_id="msg_test_002",  # What: Message ID; Why: Identifier.
        sender="Lucius Fox <lucius@novacrm.com>",  # What: Sender header; Why: AE sender.
        subject="[New Deal] Wayne Enterprises - Onboarding",  # What: Subject containing customer name; Why: Subject fallback source.
        body=body  # What: Email body; Why: Text content.
    )  # What: End of parse call; Why: Returns deal dictionary.

    assert deal["customer_name"] == "Wayne Enterprises"  # What: Assert customer name; Why: Extracted from subject line.
    assert deal["customer_contact_email"] == "bruce@wayneenterprises.com"  # What: Assert contact email; Why: Extracted via regex.
    assert deal["ae_phone"] == "+1-555-0299"  # What: Assert AE phone; Why: Extracted via regex.
    assert "https://novacrm.salesforce.com/opp/0068c0002" in deal["opportunity_url"]  # What: Assert SFDC link; Why: Extracted via regex.


def test_gmail_poller_incomplete_email_halts_with_clarification() -> None:  # What: Validation guardrail test; Why: Proves incomplete email halts Agent 1.
    """Guarantees that an email missing required fields (e.g. phone or contact email) halts Agent 1 and generates a clarification draft."""  # What: Docstring; Why: Documents test intent.
    poller = GmailPoller(mock_mode=True)  # What: Instantiate poller; Why: Offline test.
    agent1 = Agent1Intake()  # What: Fresh Agent 1 instance; Why: Ingestion orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock Rocketlane; Why: Ensures no project created.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Ensures no call dispatched.

    body = (  # What: Incomplete email body missing AE phone and contact email; Why: Violates zero-assumption guardrail.
        "Hi CS,\n\n"  # What: Salutation; Why: Context.
        "Customer Name: Cyberdyne Systems\n"  # What: Customer name; Why: Present.
        "AE Name: Miles Dyson\n"  # What: AE name; Why: Present.
        "Opportunity: https://novacrm.salesforce.com/opp/003\n"  # What: SFDC link; Why: Present.
    )  # What: End of incomplete body; Why: Missing contact email and AE phone.

    poller.inject_mock_email(  # What: Inject incomplete email into mock inbox; Why: Queues email for poller.
        sender="Miles Dyson <miles@novacrm.com>",  # What: Sender header; Why: AE sender.
        subject="[New Deal] Cyberdyne Systems Onboarding",  # What: Subject matching filter; Why: Passes filter.
        body=body  # What: Incomplete body; Why: Missing mandatory data.
    )  # What: End of mock injection; Why: Ready for polling.

    results = poller.process_incoming_deals(agent1=agent1)  # What: Run process_incoming_deals; Why: Executes polling and pipeline.
    assert len(results) == 1  # What: Assert one deal processed; Why: Polled single queued email.
    assert results[0]["customer_name"] == "Cyberdyne Systems"  # What: Assert customer name; Why: Correctly extracted.
    assert results[0]["agent1_status"] == "HALTED_MISSING_DATA"  # What: Assert status HALTED_MISSING_DATA; Why: Pipeline halted without guessing.
    assert results[0]["clarification_needed"] is True  # What: Assert clarification flag; Why: Clarification draft created.
    assert results[0]["draft_staged"] is True  # What: Assert draft staged; Why: Proves human-in-the-loop staging in Drafts folder.
    assert len(poller._staged_drafts) == 1  # What: Assert one draft queued; Why: Draft stored in simulated Drafts mailbox.
    assert poller._staged_drafts[0]["recipient"] == "miles@novacrm.com"  # What: Assert recipient; Why: Directed to AE.
    assert results[0]["rocketlane_project_id"] is None  # What: Assert no project ID; Why: Rocketlane creation blocked.


def test_gmail_poller_subject_filter_ignores_unrelated_traffic() -> None:  # What: Filter unit test; Why: Verifies poller ignores non-deal emails.
    """Guarantees that emails lacking the subject filter keyword (e.g. Rocketlane notifications) are ignored."""  # What: Docstring; Why: Documents test intent.
    poller = GmailPoller(mock_mode=True, subject_filter="New Deal")  # What: Instantiate poller with filter; Why: Isolates deal emails.
    agent1 = Agent1Intake()  # What: Fresh Agent 1; Why: Clean instance.

    # Inject Rocketlane notification email (which arrives at CS inbox but is NOT a deal notification)
    poller.inject_mock_email(  # What: Inject unrelated email; Why: Simulates incoming Rocketlane notification.
        sender="Rocketlane Notifications <notifications@rocketlane.com>",  # What: Rocketlane sender; Why: System email.
        subject="Rocketlane_assignment from NYU has invited you to project 'Apex Dynamics'",  # What: Subject lacking 'New Deal'; Why: Does not match filter.
        body="You have been assigned as the Project Owner for Apex Dynamics Onboarding."  # What: Body text; Why: Internal notification.
    )  # What: End of mock injection; Why: Ready.

    results = poller.process_incoming_deals(agent1=agent1)  # What: Run process_incoming_deals; Why: Poller checks inbox.
    assert len(results) == 0  # What: Assert zero deals processed; Why: Non-deal email was correctly filtered out.


def test_gmail_poller_full_happy_path_pipeline() -> None:  # What: End-to-end integration test; Why: Verifies email -> voice confirmation -> Rocketlane -> Slack.
    """Tests complete happy path: Inbound email polled -> Enterprise verified -> Rocketlane project created -> Slack channel provisioned."""  # What: Docstring; Why: Documents test intent.
    poller = GmailPoller(mock_mode=True)  # What: Instantiate poller; Why: Simulated inbox.
    agent1 = Agent1Intake()  # What: Fresh Agent 1; Why: Deal intake.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock Rocketlane; Why: Fast deterministic test.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Telephony confirmation.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Agent 2 with mock Slack; Why: Slack channel provisioning.

    test_ts = int(datetime.now().timestamp())  # What: Timestamp integer; Why: Unique test run.

    # 1. Configure Voice AI verbal confirmation for Enterprise
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Unambiguous Enterprise confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Enterprise result.
            call_id=f"call_gmail_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful voice confirmation.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Yes, confirming Stark Industries signed our Enterprise plan.",  # What: Verbal confirmation transcript; Why: Speech proof.
            confidence_score=0.99  # What: High confidence; Why: Passes voice guardrail.
        )  # What: End of VoiceCallResult instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # 2. Inject valid AE deal notification email
    body = (  # What: Complete valid email body; Why: Standard deal notification format.
        "Customer Name: Stark Industries\n"  # What: Customer name; Why: Name field.
        "Customer Contact Email: pepper@stark.com\n"  # What: Contact email; Why: Email field.
        "AE Name: Tony Stark\n"  # What: AE name; Why: Deal owner field.
        "AE Phone: +1-555-0199\n"  # What: AE phone; Why: Destination number field.
        "Opportunity URL: https://novacrm.salesforce.com/opp/stark\n"  # What: SFDC link; Why: Context link.
    )  # What: End of body string; Why: Complete payload.

    poller.inject_mock_email(  # What: Inject deal email into mock inbox; Why: Queues email for poller.
        sender="Tony Stark <tony@novacrm.com>",  # What: Sender header; Why: AE sender.
        subject="[New Deal] Stark Industries Enterprise Onboarding",  # What: Subject matching filter; Why: Passes filter.
        body=body  # What: Email body; Why: Text content.
    )  # What: End of mock injection; Why: Ready for polling.

    # 3. Process inbox through full multi-agent pipeline
    results = poller.process_incoming_deals(agent1=agent1, agent2=agent2)  # What: Run process_incoming_deals; Why: Executes Agent 1 and Agent 2.

    # 4. Assertions on complete workflow execution
    assert len(results) == 1  # What: Assert one deal processed; Why: Polled single email.
    assert results[0]["customer_name"] == "Stark Industries"  # What: Assert customer name; Why: Deal identity preserved.
    assert results[0]["agent1_status"] == "SUCCESS"  # What: Assert Agent 1 status; Why: Agent 1 completed successfully.
    assert results[0]["agent2_status"] == "SUCCESS"  # What: Assert Agent 2 status; Why: Agent 2 completed successfully.
    assert results[0]["rocketlane_project_id"] is not None  # What: Assert project ID exists; Why: Rocketlane project provisioned.
    assert results[0]["clarification_needed"] is False  # What: Assert no clarification needed; Why: All fields present.


def test_gmail_poller_ae_reply_threads_missing_field_from_quotes() -> None:  # What: Reply parser test; Why: Verifies AE reply combined with quoted email history.
    """Guarantees that an AE replying with just the missing contact email correctly combines with quoted thread details."""  # What: Docstring; Why: Explains test intent.
    poller = GmailPoller(mock_mode=True)  # What: Instantiate poller in mock mode; Why: Offline testing.
    reply_body = (  # What: Sample AE reply body with missing field at top and quoted history below; Why: Standard email client reply format.
        "Customer Contact Email: sarah.connor@cyberdyne.com\n\n"  # What: Provided missing field; Why: AE reply content.
        "On Sun, Sep 27, 2026, CS Team wrote:\n"  # What: Thread header; Why: Quoted boundary.
        "> Hi Miles, please provide the customer contact email.\n"  # What: Quoted draft text; Why: Clarification text.
        "> \n"  # What: Quoted blank; Why: Formatting.
        "> Customer Name: Cyberdyne Systems\n"  # What: Quoted customer name; Why: Extracted from history.
        "> AE Name: Miles Dyson\n"  # What: Quoted AE name; Why: Extracted from history.
        "> AE Phone: +1-555-0199\n"  # What: Quoted AE phone; Why: Extracted from history.
        "> Salesforce Opportunity: https://novacrm.salesforce.com/opp/003\n"  # What: Quoted SFDC link; Why: Extracted from history.
    )  # What: End of reply body; Why: Complete email body.

    deal = poller.parse_deal_from_email(  # What: Parse reply email; Why: Tests quote handling.
        message_id="msg_reply_001",  # What: Message ID; Why: Identifier.
        sender="Miles Dyson <miles@novacrm.com>",  # What: Sender header; Why: AE sender.
        subject="Re: [New Deal] [Action Required] Clarification Needed for Cyberdyne Systems Onboarding",  # What: Reply subject line; Why: Standard reply format.
        body=reply_body  # What: Reply body; Why: Content.
    )  # What: End of parse call; Why: Returns deal dictionary.

    assert deal["customer_name"] == "Cyberdyne Systems"  # What: Assert customer name; Why: Extracted from quoted line.
    assert deal["customer_contact_email"] == "sarah.connor@cyberdyne.com"  # What: Assert contact email; Why: Extracted from top reply.
    assert deal["ae_name"] == "Miles Dyson"  # What: Assert AE name; Why: Extracted from quoted line.
    assert deal["ae_phone"] == "+1-555-0199"  # What: Assert AE phone; Why: Extracted from quoted line.
    assert "https://novacrm.salesforce.com/opp/003" in deal["opportunity_url"]  # What: Assert SFDC link; Why: Extracted from quoted line.


def test_gmail_poller_multi_missing_fields_consolidated_in_single_draft_and_cached() -> None:  # What: Multi-missing fields and cache test; Why: Verifies all missing fields consolidated into one email and resolved via thread memory.
    """Ensures multiple missing fields are consolidated into one clarification draft and resolved across email turns."""  # What: Docstring; Why: Documents test intent.
    poller = GmailPoller(mock_mode=True)  # What: Instantiate poller; Why: Offline testing.
    agent1 = Agent1Intake()  # What: Instantiate Agent 1; Why: Intake pipeline orchestrator.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock Rocketlane; Why: Fast unit execution.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Verbal confirmation simulation.
    agent1.voice_client.set_simulation_outcome(  # What: Set voice outcome; Why: Injects confirmed call.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: High confidence confirmation.
            call_id="call_mock_multi",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.GROWTH,  # What: Growth tier; Why: Selected plan.
            transcript="Yes, Cyberdrone is on Growth tier.",  # What: Transcript; Why: Verbal proof.
            confidence_score=0.95  # What: High confidence; Why: Meets SLA.
        )  # What: End of VoiceCallResult; Why: Ready.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # Turn 1: Email missing BOTH contact email and phone, containing SFDC URL
    body_turn1 = (  # What: Incomplete email body; Why: Missing contact email and phone.
        "Customer Name: Cyberdrone Systems\n"  # What: Customer name; Why: Present.
        "AE Name: Miles Dyson\n"  # What: AE name; Why: Present.
        "Salesforce Opportunity: https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c0000999/view\n"  # What: SFDC URL with digits; Why: Tests regex immunity to URL digits.
    )  # What: End of body turn 1; Why: Missing 2 fields.

    poller.inject_mock_email(  # What: Inject email into mock inbox; Why: Simulates Turn 1.
        sender="Miles Dyson <miles@novacrm.com>",  # What: Sender header; Why: AE sender.
        subject="[New Deal] Cyberdrone Systems Onboarding",  # What: Deal subject; Why: Passes filter.
        body=body_turn1  # What: Incomplete body; Why: Missing fields.
    )  # What: End of mock injection; Why: Ready for polling.

    results_turn1 = poller.process_incoming_deals(agent1=agent1)  # What: Process Turn 1; Why: Triggers validation.
    assert len(results_turn1) == 1  # What: Assert one deal; Why: Processed Turn 1.
    assert results_turn1[0]["agent1_status"] == "HALTED_MISSING_DATA"  # What: Assert status HALTED; Why: Incomplete data.
    assert results_turn1[0]["draft_staged"] is True  # What: Assert draft staged; Why: Draft created.

    # Assert that BOTH fields were identified and consolidated into a SINGLE draft
    assert len(poller._staged_drafts) == 1  # What: Assert exactly one draft staged; Why: Avoids multiple drafts.
    staged = poller._staged_drafts[0]  # What: Retrieve staged draft dict; Why: Inspects content.
    assert "customer_contact_email" in staged["missing_fields"]  # What: Assert email missing; Why: Consolidated in list.
    assert "ae_phone" in staged["missing_fields"]  # What: Assert phone missing; Why: Consolidated in list.
    assert "cyberdrone systems" in poller._thread_deal_cache  # What: Assert deal cached; Why: Preserves Turn 1 fields.

    # Turn 2: AE replies with the missing info, without re-sending the SFDC URL
    reply_body = (  # What: AE reply body; Why: Provides missing fields.
        "Customer Contact Email: sarah.connor@cyberdrone.com\n"  # What: Provided email; Why: Resolves email.
        "AE Phone: +1-555-4321\n"  # What: Provided phone; Why: Resolves phone.
    )  # What: End of reply body; Why: Turn 2 payload.

    poller.inject_mock_email(  # What: Inject reply email; Why: Simulates Turn 2.
        sender="Miles Dyson <miles@novacrm.com>",  # What: Sender header; Why: AE sender.
        subject="Re: [New Deal] [Action Required] Clarification Needed for Cyberdrone Systems Onboarding",  # What: Reply subject; Why: Connects to deal.
        body=reply_body  # What: Reply body; Why: Content.
    )  # What: End of mock injection; Why: Ready for polling.

    results_turn2 = poller.process_incoming_deals(agent1=agent1)  # What: Process Turn 2; Why: Resolves deal.
    assert len(results_turn2) == 1  # What: Assert one deal; Why: Processed Turn 2.
    assert results_turn2[0]["agent1_status"] == "SUCCESS"  # What: Assert status SUCCESS; Why: Validated using cached SFDC URL and new fields.
    assert results_turn2[0]["rocketlane_project_id"] is not None  # What: Assert project ID; Why: Project created.
    assert "cyberdrone systems" not in poller._thread_deal_cache  # What: Assert evicted from cache; Why: Cache cleanup.


def test_gmail_poller_survives_deal_processing_exception(monkeypatch: pytest.MonkeyPatch) -> None:  # What: Daemon resilience test; Why: Verifies poller survives unhandled exceptions.
    """Guarantees that an unhandled exception in deal processing is logged and does not kill the poller daemon."""  # What: Docstring; Why: Documents test intent.
    poller = GmailPoller(mock_mode=True)  # What: Instantiate poller in mock mode; Why: Isolated unit test.
    agent1 = Agent1Intake()  # What: Fresh Agent 1; Why: Ingestion processor.

    # Simulate unexpected failure during agent1.process_deal
    def crashing_process_deal(*args, **kwargs):  # What: Mock crashing handler; Why: Simulates unhandled bug or network crash.
        raise RuntimeError("Unexpected upstream API meltdown!")  # What: Raise RuntimeError; Why: Simulates severe crash.

    monkeypatch.setattr(agent1, "process_deal", crashing_process_deal)  # What: Patch process_deal; Why: Injects crash behavior.

    poller.inject_mock_email(  # What: Inject valid email; Why: Triggers deal processing.
        sender="Crash Test <crash@novacrm.com>",  # What: Sender; Why: AE sender.
        subject="[New Deal] Crash Corp Onboarding",  # What: Subject; Why: Deal email subject.
        body="Customer Name: Crash Corp\nCustomer Contact Email: info@crash.com\nAE Name: Tester\nAE Phone: +1-555-9999\nOpportunity: https://novacrm.salesforce.com/opp/999"  # What: Body; Why: Complete deal fields.
    )  # What: End of mock injection; Why: Ready for polling.

    # Poller process_incoming_deals must NOT raise exception
    results = poller.process_incoming_deals(agent1=agent1)  # What: Execute polling; Why: Must catch error and return summary.
    assert len(results) == 1  # What: Assert one deal recorded; Why: Summary generated.
    assert results[0]["agent1_status"] == "FAILED"  # What: Assert status FAILED; Why: Error captured.
    assert "Unexpected upstream API meltdown!" in results[0]["error"]  # What: Assert error message; Why: Reason recorded.



