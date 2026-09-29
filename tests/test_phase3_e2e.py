# End-to-end integration test validating Phase 3 Agent 1 -> Agent 2 complete handoff lifecycle.  # What: Module header; Why: Verifies Phase 3 multi-agent integration.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps and correlation IDs.
import pytest  # What: Import pytest; Why: Test assertion and execution framework.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent 1; Why: Runs upstream deal intake.
from src.agents.agent2_communication import Agent2Communication  # What: Import Agent 2; Why: Runs downstream communications.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Verifies cross-agent audit continuity.
from src.models.schemas import (  # What: Import domain models; Why: Type safety across test models.
    PlanTier,  # What: Plan tier enum; Why: Enterprise and Growth plan tiers.
    VoiceCallResult,  # What: Voice call result model; Why: Telephony results.
    VoiceCallStatus  # What: Voice call status enum; Why: Confirmed status.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Configures mock or live Rocketlane.
from src.services.slack_client import SlackClient  # What: Import SlackClient; Why: Configures mock or live Slack client.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Configures mock or live Voice AI client.


def test_e2e_phase3_enterprise_intake_to_slack_provisioning() -> None:  # What: E2E Enterprise test; Why: Verifies complete deal-to-Slack flow for Enterprise.
    """Tests complete lifecycle: Enterprise deal email -> Voice AI confirmation -> Rocketlane project -> Slack channel & kickoff message."""  # What: Docstring; Why: Explains test intent.
    agent1 = Agent1Intake()  # What: Instantiate fresh Agent 1; Why: Clean instance for test.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Use mock Rocketlane; Why: Fast deterministic test without cloud latency.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Use mock voice client; Why: Deterministic verbal confirmation.

    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Instantiate Agent 2 with mock Slack; Why: Deterministic Slack test.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique deal ID.
    corr_id = f"e2e_phase3_ent_{test_ts}"  # What: Unique correlation ID; Why: Tracks deal across both agents.

    # 1. Configure Voice AI to simulate clear Enterprise verbal confirmation
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Injects unambiguous verbal confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Enterprise result.
            call_id=f"call_ent_{test_ts}",  # What: Call ID; Why: Telephony session ID.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Yes, confirming Wayne Enterprises is on the Enterprise tier with 30-day onboarding.",  # What: Verbal confirmation transcript; Why: Proof.
            confidence_score=0.99  # What: High confidence; Why: Passes voice guardrail.
        )  # What: End of VoiceCallResult instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email = {  # What: Raw inbound email dictionary; Why: Healthy AE notification.
        "message_id": f"msg_ent_{test_ts}",  # What: Message ID; Why: Unique email ID.
        "customer_name": f"Wayne Enterprises {test_ts}",  # What: Customer name; Why: Name to sanitize.
        "customer_contact_email": f"bruce_{test_ts}@wayneenterprises.com",  # What: Customer contact email; Why: Primary collaborator.
        "ae_name": "Lucius Fox",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0199"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Valid payload.

    # 2. Execute Agent 1 (Intake & Routing)
    a1_result = agent1.process_deal(raw_email, correlation_id=corr_id)  # What: Run Agent 1; Why: Ingestion, voice confirmation, and project creation.
    assert a1_result.status == "SUCCESS"  # What: Assert Agent 1 status; Why: Agent 1 must succeed.
    assert a1_result.rocketlane_project is not None  # What: Assert project exists; Why: Rocketlane project provisioned.
    assert a1_result.rocketlane_project.tier == PlanTier.ENTERPRISE  # What: Assert Enterprise tier; Why: Correct template applied.

    # 3. Execute Agent 2 (Communication Agent)
    a2_result = agent2.process_project_handoff(a1_result)  # What: Run Agent 2; Why: Slack channel provisioning and messaging.
    assert a2_result.status == "SUCCESS"  # What: Assert Agent 2 status; Why: Agent 2 must succeed.
    assert a2_result.provisioning_result is not None  # What: Assert Slack result exists; Why: Channel was created.
    assert a2_result.provisioning_result.channel_name.startswith("csm-ent-wayne-enterprises")  # What: Assert channel prefix; Why: Enterprise naming convention.
    assert a2_result.provisioning_result.topic_set is True  # What: Assert topic set; Why: Rocketlane link embedded.
    assert a2_result.provisioning_result.welcome_message_ts is not None  # What: Assert message ts; Why: Welcome message delivered.

    # 4. Verify continuous audit trail across both agents
    entries = audit_logger.get_entries_for_correlation(corr_id)  # What: Retrieve audit entries; Why: Verifies cross-agent logging continuity.
    actions = [e.action for e in entries]  # What: Extract action names list; Why: Inspects executed lifecycle events.

    # Agent 1 actions
    assert "process_deal_started" in actions  # What: Assert deal start; Why: Agent 1 initiated.
    assert "schema_validation_passed" in actions  # What: Assert validation; Why: Deterministic schema passed.
    assert "voice_guardrail_passed" in actions  # What: Assert voice guardrail; Why: Telephony confirmed.
    assert "agent1_workflow_completed" in actions  # What: Assert Agent 1 done; Why: Rocketlane project provisioned.

    # Agent 2 actions
    assert "process_handoff_started" in actions  # What: Assert handoff start; Why: Agent 2 initiated.
    assert "slack_channel_creation_started" in actions  # What: Assert channel creation; Why: Channel creation initiated.
    assert "slack_topic_set" in actions  # What: Assert topic set; Why: Rocketlane workspace URL embedded.
    assert "slack_welcome_message_posted" in actions  # What: Assert message posted; Why: Kickoff message posted.
    assert "agent2_workflow_completed" in actions  # What: Assert Agent 2 done; Why: Communication completed.


def test_e2e_phase3_growth_intake_to_slack_provisioning() -> None:  # What: E2E Growth test; Why: Verifies complete deal-to-Slack flow for Growth.
    """Tests complete lifecycle: Growth deal email -> Voice AI confirmation -> Rocketlane project -> Slack channel & kickoff message."""  # What: Docstring; Why: Explains test intent.
    agent1 = Agent1Intake()  # What: Instantiate fresh Agent 1; Why: Clean instance.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock Rocketlane; Why: Fast execution.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Controlled confirmation.

    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Instantiate Agent 2; Why: Clean instance.

    test_ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique deal ID.
    corr_id = f"e2e_phase3_grw_{test_ts}"  # What: Unique correlation ID; Why: Tracks deal.

    # 1. Configure Voice AI to simulate clear Growth verbal confirmation
    agent1.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Injects Growth confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Growth result.
            call_id=f"call_grw_{test_ts}",  # What: Call ID; Why: Telephony session ID.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.GROWTH,  # What: Growth tier; Why: Selected plan.
            transcript="Acme is definitely on the Growth plan with 14-day onboarding.",  # What: Verbal confirmation transcript; Why: Proof.
            confidence_score=0.97  # What: High confidence; Why: Passes voice guardrail.
        )  # What: End of VoiceCallResult instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email = {  # What: Raw inbound email dictionary; Why: Healthy AE notification.
        "message_id": f"msg_grw_{test_ts}",  # What: Message ID; Why: Unique email ID.
        "customer_name": f"Pied Piper {test_ts}",  # What: Customer name; Why: Name to sanitize.
        "customer_contact_email": f"richard_{test_ts}@piedpiper.com",  # What: Customer contact email; Why: Primary collaborator.
        "ae_name": "Jared Dunn",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0200"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Valid payload.

    # 2. Execute Agent 1
    a1_result = agent1.process_deal(raw_email, correlation_id=corr_id)  # What: Run Agent 1; Why: Ingestion and project creation.
    assert a1_result.status == "SUCCESS"  # What: Assert status; Why: Succeeded.
    assert a1_result.rocketlane_project is not None  # What: Assert project; Why: Provisioned.
    assert a1_result.rocketlane_project.tier == PlanTier.GROWTH  # What: Assert Growth; Why: Growth template.

    # 3. Execute Agent 2
    a2_result = agent2.process_project_handoff(a1_result)  # What: Run Agent 2; Why: Slack setup.
    assert a2_result.status == "SUCCESS"  # What: Assert status; Why: Succeeded.
    assert a2_result.provisioning_result is not None  # What: Assert Slack result; Why: Provisioned.
    assert a2_result.provisioning_result.channel_name.startswith("csm-grw-pied-piper")  # What: Assert channel prefix; Why: Growth naming convention.
    assert "Pooled CSM Team" in a2_result.channel_payload.welcome_message  # What: Assert pooled CSM template; Why: Correct personalization.


def test_e2e_phase3_guardrail_prevents_slack_on_missing_email_data() -> None:  # What: E2E negative test for missing data; Why: Proves guardrail blocks Slack setup.
    """Verifies that missing inbound email fields prevent both project provisioning and Slack channel creation."""  # What: Docstring; Why: Explains test intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1; Why: Clean instance.
    agent2 = Agent2Communication(client=SlackClient(mock_mode=True))  # What: Fresh Agent 2; Why: Clean instance.

    test_ts = int(datetime.now().timestamp())  # What: Timestamp; Why: Unique ID.
    corr_id = f"e2e_phase3_missing_{test_ts}"  # What: Correlation ID; Why: Deal trace.

    # Incomplete email missing customer_name
    bad_email = {  # What: Incomplete raw email; Why: Missing mandatory field.
        "message_id": f"msg_bad_{test_ts}",  # What: Message ID; Why: Email ID.
        "customer_contact_email": "ceo@unknown.com",  # What: Contact email; Why: Provided.
        "ae_name": "Tom Davis",  # What: AE name; Why: Provided.
        "ae_phone": "+1-555-0300"  # What: AE phone; Why: Provided.
    }  # What: End of bad email dictionary; Why: customer_name omitted.

    # Agent 1 halts
    a1_result = agent1.process_deal(bad_email, correlation_id=corr_id)  # What: Run Agent 1; Why: Triggers schema guardrail halt.
    assert a1_result.status == "HALTED_MISSING_DATA"  # What: Assert halted status; Why: Missing field caught.
    assert a1_result.rocketlane_project is None  # What: Assert no project; Why: Never guess missing data.

    # Agent 2 skips
    a2_result = agent2.process_project_handoff(a1_result)  # What: Run Agent 2; Why: Triggers precondition guardrail skip.
    assert a2_result.status == "SKIPPED_UNCONFIRMED"  # What: Assert skipped status; Why: Precondition enforced.
    assert a2_result.provisioning_result is None  # What: Assert no channel; Why: Slack channel not created.


def test_e2e_phase3_live_slack_channel_creation() -> None:  # What: Live Slack E2E test; Why: Verifies actual channel creation in the real Slack workspace.
    """Provisions a live, real Slack channel in the configured Slack workspace and posts the kickoff welcome message."""  # What: Docstring; Why: Documents live test intent.
    agent1 = Agent1Intake()  # What: Fresh Agent 1; Why: Clean instance.
    agent1.rocketlane = RocketlaneClient(mock_mode=True)  # What: Mock Rocketlane; Why: Avoids 35s cloud delay while testing live Slack.
    agent1.voice_client = VoiceAIClient(mock_mode=True)  # What: Mock Voice AI; Why: Injects verified Enterprise tier.

    # Initialize Agent 2 with mock_mode=False to hit the live Slack Web API
    agent2 = Agent2Communication(client=SlackClient(mock_mode=False))  # What: Agent 2 with live SlackClient; Why: Creates real channel on Slack.

    test_ts = int(datetime.now().timestamp()) % 10000  # What: Short timestamp; Why: Keeps channel slug concise.
    corr_id = f"e2e_live_slack_{test_ts}"  # What: Correlation ID; Why: Deal trace.

    agent1.voice_client.set_simulation_outcome(  # What: Simulate verified Enterprise; Why: Supplies confirmed tier.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Verified Enterprise result.
            call_id=f"call_live_{test_ts}",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Passes voice guardrail.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Enterprise plan.
            transcript="Confirmed Enterprise tier for Acme.",  # What: Transcript; Why: Speech proof.
            confidence_score=0.99  # What: High confidence; Why: Verified.
        )  # What: End of VoiceCallResult instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email = {  # What: Inbound raw email; Why: Enterprise deal payload.
        "message_id": f"msg_live_{test_ts}",  # What: Message ID; Why: Unique ID.
        "customer_name": f"Nova Customer {test_ts}",  # What: Customer name; Why: Name for Slack channel.
        "customer_contact_email": f"csm_{test_ts}@novacustomer.com",  # What: Contact email; Why: Primary collaborator.
        "ae_name": "Sarah Jenkins",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0155"  # What: AE phone; Why: Destination phone.
    }  # What: End of raw email dictionary; Why: Ready.

    a1_result = agent1.process_deal(raw_email, correlation_id=corr_id)  # What: Process deal with Agent 1; Why: Provisions deal.
    assert a1_result.status == "SUCCESS"  # What: Assert success; Why: Upstream completed.

    a2_result = agent2.process_project_handoff(a1_result)  # What: Process handoff with Agent 2; Why: Creates live Slack channel.
    assert a2_result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Slack channel created.
    assert a2_result.provisioning_result is not None  # What: Assert result exists; Why: Slack channel created.
    assert a2_result.provisioning_result.is_mock is False  # What: Assert is_mock is False; Why: Real live channel provisioned.
    assert a2_result.provisioning_result.channel_id.startswith("C")  # What: Assert Slack channel ID format; Why: Real Slack channel ID starts with 'C'.
    assert a2_result.provisioning_result.welcome_message_ts is not None  # What: Assert message ts; Why: Welcome message delivered.

