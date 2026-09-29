# Automated test suite for Agent 1 Intake & Routing Agent covering happy paths, guardrails, and escalations.  # What: Module header; Why: Verifies Agent 1 requirements.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps.
from typing import Any  # What: Import Any; Why: Type annotations for dictionary fixtures.
import pytest  # What: Import pytest; Why: Test execution and assertions.
from src.agents.agent1_intake import Agent1Intake  # What: Import Agent1Intake; Why: Tests master orchestrator.
from src.agents.intake_parser import IntakeParser  # What: Import IntakeParser; Why: Tests parser directly.
from src.agents.voice_guardrail import VoiceGuardrail  # What: Import VoiceGuardrail; Why: Tests guardrail directly.
from src.models.schemas import (  # What: Import domain models; Why: Verifies typed schemas in test assertions.
    InboundEmailPayload,  # What: Inbound email model; Why: Inbound fixture.
    PlanTier,  # What: Plan tier enum; Why: Verified tiers.
    VoiceCallResult,  # What: Voice call result model; Why: Simulated telephony inputs.
    VoiceCallStatus  # What: Voice call status enum; Why: Status assertions.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient  # What: Import RocketlaneClient; Why: Clean mock instance.
from src.services.voice_ai_client import VoiceAIClient  # What: Import VoiceAIClient; Why: Clean simulated voice instance.


@pytest.fixture  # What: Pytest fixture decorator; Why: Provides isolated Agent 1 instance per test.
def agent1_fixture() -> Agent1Intake:  # What: Fixture factory function; Why: Builds isolated Agent 1 with mock clients.
    """Builds a hermetic Agent 1 instance with isolated mock clients for testing."""  # What: Docstring; Why: Explains fixture role.
    agent = Agent1Intake()  # What: Instantiate fresh Agent1Intake; Why: Clean test harness.
    agent.rocketlane = RocketlaneClient(mock_mode=True)  # What: Set mock Rocketlane client; Why: Offline deterministic execution.
    agent.voice_client = VoiceAIClient(mock_mode=True)  # What: Set mock Voice AI client; Why: Controlled telephony simulation.
    return agent  # What: Return isolated agent; Why: Ready for test execution.


def test_agent1_happy_path_enterprise(agent1_fixture: Agent1Intake) -> None:  # What: Happy path test for Enterprise; Why: Verifies 30-day template flow.
    """Verifies that an Enterprise deal email is validated, confirmed via voice, and provisioned with 30-day SLA."""  # What: Docstring; Why: Documents test intent.
    # 1. Configure voice simulation to return confirmed Enterprise tier
    agent1_fixture.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Simulates successful AE verbal confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: High-confidence Enterprise outcome.
            call_id="call_sim_ent_01",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Yes, this is an Enterprise deal with 30 days onboarding.",  # What: Transcript text; Why: Verbal confirmation proof.
            confidence_score=0.98  # What: High confidence; Why: Passes guardrail.
        )  # What: End of result instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email: dict[str, Any] = {  # What: Raw deal email dictionary; Why: Healthy AE notification.
        "message_id": "msg_ent_101",  # What: Message ID; Why: Email ID.
        "customer_name": "Wayne Enterprises",  # What: Customer name; Why: Project title base.
        "customer_contact_email": "bruce@wayne.com",  # What: Customer contact email; Why: Primary collaborator.
        "ae_name": "Lucius Fox",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0100",  # What: AE phone; Why: Destination for call.
        "opportunity_url": "https://novacrm.salesforce.com/opp/wayne01"  # What: SFDC link; Why: Context link.
    }  # What: End of raw email dictionary; Why: Valid payload.

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_ent_test_01")  # What: Execute process_deal; Why: Runs complete Agent 1 flow.

    assert result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Verifies normal completion.
    assert result.rocketlane_project is not None  # What: Assert project exists; Why: Confirms project creation.
    assert result.rocketlane_project.tier == PlanTier.ENTERPRISE  # What: Assert Enterprise tier; Why: Correct tier assigned.
    assert "https://app.rocketlane.com/projects/" in result.rocketlane_project.portal_url  # What: Assert portal URL; Why: Ready for Slack topic.


def test_agent1_happy_path_growth(agent1_fixture: Agent1Intake) -> None:  # What: Happy path test for Growth; Why: Verifies 14-day template flow.
    """Verifies that a Growth deal email is validated, confirmed via voice, and provisioned with 14-day SLA."""  # What: Docstring; Why: Documents test intent.
    agent1_fixture.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Simulates successful AE verbal confirmation.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: High-confidence Growth outcome.
            call_id="call_sim_grw_01",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.GROWTH,  # What: Growth tier; Why: Selected plan.
            transcript="The customer signed for the standard Growth plan, 14 days.",  # What: Transcript text; Why: Verbal confirmation proof.
            confidence_score=0.95  # What: High confidence; Why: Passes guardrail.
        )  # What: End of result instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email: dict[str, Any] = {  # What: Raw deal email dictionary; Why: Healthy AE notification.
        "message_id": "msg_grw_102",  # What: Message ID; Why: Email ID.
        "customer_name": "Pied Piper",  # What: Customer name; Why: Project title base.
        "customer_contact_email": "richard@piedpiper.com",  # What: Customer contact email; Why: Primary collaborator.
        "ae_name": "Jared Dunn",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0200",  # What: AE phone; Why: Destination for call.
        "opportunity_url": "https://novacrm.salesforce.com/opp/pied02"  # What: SFDC link; Why: Context link.
    }  # What: End of raw email dictionary; Why: Valid payload.

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_grw_test_01")  # What: Execute process_deal; Why: Runs complete Agent 1 flow.

    assert result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Verifies normal completion.
    assert result.rocketlane_project is not None  # What: Assert project exists; Why: Confirms project creation.
    assert result.rocketlane_project.tier == PlanTier.GROWTH  # What: Assert Growth tier; Why: Correct tier assigned.


def test_agent1_missing_fields_validation_halt(agent1_fixture: Agent1Intake) -> None:  # What: Validation halt test; Why: Verifies zero-assumption policy.
    """Guarantees that missing mandatory fields immediately halt execution and draft a clarification email."""  # What: Docstring; Why: Documents test intent.
    incomplete_email: dict[str, Any] = {  # What: Incomplete raw email dictionary; Why: Simulates AE omitting contact email and AE phone.
        "message_id": "msg_inc_103",  # What: Message ID; Why: Present.
        "customer_name": "Cyberdyne Systems",  # What: Customer name; Why: Present.
        "customer_contact_email": "",  # What: Blank contact email; Why: Violates mandatory requirement.
        "ae_name": "Miles Dyson",  # What: AE name; Why: Present.
        "ae_phone": "   "  # What: Whitespace phone; Why: Violates mandatory requirement.
    }  # What: End of incomplete dictionary; Why: Invalid payload.

    result = agent1_fixture.process_deal(incomplete_email, correlation_id="corr_inc_test_01")  # What: Execute process_deal; Why: Runs validation.

    assert result.status == "HALTED_MISSING_DATA"  # What: Assert status HALTED_MISSING_DATA; Why: Confirms pipeline stopped.
    assert result.clarification_draft is not None  # What: Assert clarification draft generated; Why: Verifies draft created.
    assert "customer_contact_email" in result.clarification_draft.missing_fields  # What: Assert missing email identified; Why: Specific omitted field.
    assert "ae_phone" in result.clarification_draft.missing_fields  # What: Assert missing phone identified; Why: Specific omitted field.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Zero-assumption guardrail maintained.
    assert result.voice_result is None  # What: Assert no voice call placed; Why: Did not waste phone call on invalid data.


def test_agent1_ambiguous_voice_escalation(agent1_fixture: Agent1Intake) -> None:  # What: Ambiguity escalation test; Why: Enforces voice guardrail.
    """Guarantees that an ambiguous verbal tier response halts project creation and generates an escalation ticket."""  # What: Docstring; Why: Documents test intent.
    agent1_fixture.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Simulates ambiguous AE statement.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Low-confidence ambiguous outcome.
            call_id="call_sim_amb_01",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.AMBIGUOUS,  # What: Status AMBIGUOUS; Why: Uncertain response.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN; Why: No tier confirmed.
            transcript="I think they might be Enterprise, but maybe start with Growth and upgrade later.",  # What: Ambiguous transcript; Why: Contradictory.
            confidence_score=0.45,  # What: Low confidence; Why: Below 0.8 threshold.
            escalation_reason="AE mentioned both Enterprise and Growth and could not provide a firm tier."  # What: Reason; Why: Detailed rationale.
        )  # What: End of result instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email: dict[str, Any] = {  # What: Valid email dictionary; Why: Healthy inbound notification.
        "message_id": "msg_amb_104",  # What: Message ID; Why: Email ID.
        "customer_name": "Stark Industries",  # What: Customer name; Why: Company title.
        "customer_contact_email": "tony@stark.com",  # What: Customer contact email; Why: Primary collaborator.
        "ae_name": "Pepper Potts",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0300"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Valid payload.

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_amb_test_01")  # What: Execute process_deal; Why: Evaluates voice guardrail.

    assert result.status == "ESCALATED_VOICE_ISSUE"  # What: Assert status ESCALATED_VOICE_ISSUE; Why: Pipeline halted for human review.
    assert result.escalation_ticket is not None  # What: Assert escalation ticket exists; Why: Ticket generated.
    assert result.escalation_ticket.call_status == VoiceCallStatus.AMBIGUOUS  # What: Assert call status AMBIGUOUS; Why: Ticket categorized accurately.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Enforces zero-guessing guardrail.


def test_agent1_unanswered_voice_escalation(agent1_fixture: Agent1Intake) -> None:  # What: Unanswered escalation test; Why: Enforces silence guardrail.
    """Guarantees that an unanswered voice call halts project creation and generates an escalation ticket."""  # What: Docstring; Why: Documents test intent.
    agent1_fixture.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Simulates unanswered call.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Unanswered outcome.
            call_id="call_sim_unans_01",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.UNANSWERED,  # What: Status UNANSWERED; Why: No answer.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN; Why: No tier confirmed.
            transcript="",  # What: Empty transcript; Why: Nobody answered.
            confidence_score=0.0,  # What: Zero confidence; Why: No response.
            escalation_reason="AE did not answer after 4 rings."  # What: Reason; Why: Detailed rationale.
        )  # What: End of result instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email: dict[str, Any] = {  # What: Valid email dictionary; Why: Healthy inbound notification.
        "message_id": "msg_unans_105",  # What: Message ID; Why: Email ID.
        "customer_name": "Oscorp Industries",  # What: Customer name; Why: Company title.
        "customer_contact_email": "norman@oscorp.com",  # What: Customer contact email; Why: Primary collaborator.
        "ae_name": "Harry Osborn",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0400"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Valid payload.

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_unans_test_01")  # What: Execute process_deal; Why: Evaluates silence guardrail.

    assert result.status == "ESCALATED_VOICE_ISSUE"  # What: Assert status ESCALATED_VOICE_ISSUE; Why: Pipeline halted for human review.
    assert result.escalation_ticket is not None  # What: Assert escalation ticket exists; Why: Ticket generated.
    assert result.escalation_ticket.call_status == VoiceCallStatus.UNANSWERED  # What: Assert call status UNANSWERED; Why: Ticket categorized accurately.
    assert result.rocketlane_project is None  # What: Assert no project created; Why: Never assume tier on silence.


def test_agent1_idempotency_prevents_duplicate_call_and_project(agent1_fixture: Agent1Intake) -> None:  # What: Idempotency deduplication test; Why: Prevents double provisioning.
    """Guarantees that reprocessing the same deal returns existing project without placing second call or creating duplicate."""  # What: Docstring; Why: Documents test intent.
    agent1_fixture.voice_client.set_simulation_outcome(  # What: Set simulation outcome; Why: Confirms tier on first run.
        VoiceCallResult(  # What: Instantiate VoiceCallResult; Why: Confirmed Enterprise outcome.
            call_id="call_sim_idemp_01",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.CONFIRMED,  # What: Status CONFIRMED; Why: Successful confirmation.
            confirmed_tier=PlanTier.ENTERPRISE,  # What: Enterprise tier; Why: Selected plan.
            transcript="Enterprise tier confirmed.",  # What: Transcript; Why: Verbal proof.
            confidence_score=0.99  # What: High confidence; Why: Unambiguous.
        )  # What: End of result instantiation; Why: Configured.
    )  # What: End of set_simulation_outcome; Why: Ready.

    raw_email: dict[str, Any] = {  # What: Raw deal email dictionary; Why: Duplicate test payload.
        "message_id": "msg_idemp_106",  # What: Message ID; Why: Email ID.
        "customer_name": "Massive Dynamic",  # What: Customer name; Why: Company title.
        "customer_contact_email": "william.bell@massivedynamic.com",  # What: Customer contact email; Why: Primary collaborator.
        "ae_name": "Nina Sharp",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0500"  # What: AE phone; Why: Destination number.
    }  # What: End of raw email dictionary; Why: Valid payload.

    # First run provisions project
    first_result = agent1_fixture.process_deal(raw_email, correlation_id="corr_idemp_01")  # What: First run; Why: Provisions new project.
    assert first_result.status == "SUCCESS"  # What: Assert SUCCESS; Why: First run completes.
    assert first_result.rocketlane_project is not None  # What: Assert project exists; Why: Initial project created.
    first_proj_id = first_result.rocketlane_project.project_id  # What: Save project ID; Why: For comparison with second run.

    # Change simulation to AMBIGUOUS to prove that second run never even calls voice client
    agent1_fixture.voice_client.set_simulation_outcome(  # What: Overwrite simulation with failure; Why: Proves second run skips telephony.
        VoiceCallResult(  # What: Dummy ambiguous result; Why: Would fail if called.
            call_id="call_should_never_be_reached",  # What: Call ID; Why: Identifier.
            status=VoiceCallStatus.AMBIGUOUS,  # What: Status AMBIGUOUS; Why: Would trigger escalation if called.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN; Why: No tier.
            transcript="Ambiguous response",  # What: Transcript; Why: Text.
            confidence_score=0.2  # What: Low confidence; Why: Guardrail trigger.
        )  # What: End of result instantiation; Why: Set.
    )  # What: End of set_simulation_outcome; Why: Ready.

    # Second run with same email payload
    second_result = agent1_fixture.process_deal(raw_email, correlation_id="corr_idemp_02")  # What: Second run with same email; Why: Simulates duplicate email webhook.
    assert second_result.status == "IDEMPOTENT_DUPLICATE"  # What: Assert status IDEMPOTENT_DUPLICATE; Why: Proves idempotency caught it early.
    assert second_result.rocketlane_project is not None  # What: Assert project exists; Why: Returns existing project.
    assert second_result.rocketlane_project.project_id == first_proj_id  # What: Assert same project ID; Why: No duplicate project created.


def test_transcript_analyzer_heuristics() -> None:  # What: Unit test for transcript analysis logic; Why: Verifies speech-to-text keyword evaluation.
    """Verifies that transcript text is evaluated accurately for Enterprise, Growth, and ambiguity patterns."""  # What: Docstring; Why: Documents test intent.
    guardrail = VoiceGuardrail()  # What: Instantiate fresh VoiceGuardrail; Why: Evaluates transcripts.

    # Positive Enterprise
    status, tier, conf = guardrail.parse_transcript_text("We closed the deal on the Enterprise plan with dedicated support.")  # What: Parse enterprise; Why: Clear enterprise phrase.
    assert status == VoiceCallStatus.CONFIRMED  # What: Assert CONFIRMED; Why: Clear confirmation.
    assert tier == PlanTier.ENTERPRISE  # What: Assert ENTERPRISE; Why: Correct tier.
    assert conf >= 0.9  # What: Assert high confidence; Why: Unambiguous.

    # Positive Growth
    status, tier, conf = guardrail.parse_transcript_text("The customer chose Growth, 14 days.")  # What: Parse growth; Why: Clear growth phrase.
    assert status == VoiceCallStatus.CONFIRMED  # What: Assert CONFIRMED; Why: Clear confirmation.
    assert tier == PlanTier.GROWTH  # What: Assert GROWTH; Why: Correct tier.
    assert conf >= 0.9  # What: Assert high confidence; Why: Unambiguous.

    # Ambiguous phrase "not sure"
    status, tier, conf = guardrail.parse_transcript_text("I'm not sure, maybe Enterprise?")  # What: Parse ambiguous phrase; Why: Uncertain hedge phrase.
    assert status == VoiceCallStatus.AMBIGUOUS  # What: Assert AMBIGUOUS; Why: Uncertainty detected.
    assert tier == PlanTier.UNKNOWN  # What: Assert UNKNOWN; Why: Never guess.

    # Contradictory mention of both tiers
    status, tier, conf = guardrail.parse_transcript_text("Start them on Growth but sell them Enterprise next quarter.")  # What: Parse dual tiers; Why: Contradictory mentions.
    assert status == VoiceCallStatus.AMBIGUOUS  # What: Assert AMBIGUOUS; Why: Contradictory mentions.
    assert tier == PlanTier.UNKNOWN  # What: Assert UNKNOWN; Why: Never guess.


def test_agent1_automated_voice_enterprise_assumption(agent1_fixture: Agent1Intake) -> None:  # What: Automated voice assumption test; Why: Verifies pipeline completes with Enterprise tier when assumption is active.
    """Verifies that Agent 1 assumes Enterprise tier when voice_ai_assume_enterprise is active and simulation is not set."""  # What: Docstring; Why: Documents test intent.
    agent1_fixture.voice_client.set_simulation_outcome(None)  # What: Clear explicit simulation outcome; Why: Tests automated assumption fallback.
    agent1_fixture.voice_client.assume_enterprise = True  # What: Activate enterprise assumption; Why: Tests automated voice flow.

    raw_email: dict[str, Any] = {  # What: Inbound raw email; Why: Valid deal email.
        "message_id": "msg_auto_ent_01",  # What: Message ID; Why: Email ID.
        "customer_name": "Initech Systems",  # What: Customer name; Why: Project title base.
        "customer_contact_email": "peter@initech.com",  # What: Contact email; Why: Collaborator.
        "ae_name": "Bill Lumbergh",  # What: AE name; Why: Deal owner.
        "ae_phone": "+1-555-0300",  # What: AE phone; Why: Destination number.
        "opportunity_url": "https://novacrm.salesforce.com/opp/initech"  # What: SFDC link; Why: Context link.
    }  # What: End of raw email dictionary; Why: Complete payload.

    result = agent1_fixture.process_deal(raw_email, correlation_id="corr_auto_ent_01")  # What: Execute process_deal; Why: Runs Agent 1 with automated voice assumption.

    assert result.status == "SUCCESS"  # What: Assert status SUCCESS; Why: Verifies automated assumption succeeds.
    assert result.rocketlane_project is not None  # What: Assert project created; Why: Project provisioned.
    assert result.rocketlane_project.tier == PlanTier.ENTERPRISE  # What: Assert Enterprise tier; Why: Correctly mapped to Enterprise.
    assert result.voice_result is not None  # What: Assert voice result present; Why: Telephony record preserved.
    assert result.voice_result.status == VoiceCallStatus.CONFIRMED  # What: Assert CONFIRMED status; Why: Confirmed by assumption.
    assert result.voice_result.confidence_score == 0.99  # What: Assert 0.99 confidence; Why: High confidence.

