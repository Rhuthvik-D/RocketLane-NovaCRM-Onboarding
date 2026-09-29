# Agent 1 Intake & Routing Agent orchestrating email ingestion, telephony verification, and Rocketlane provisioning.  # What: Module header; Why: Master orchestrator for Agent 1.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps and correlation IDs.
import logging  # What: Import standard logging; Why: Emits execution progress logs to terminal.
from typing import Any, Optional  # What: Import typing utilities; Why: Type annotations for payloads and optional parameters.
from src.agents.intake_parser import intake_parser  # What: Import intake parser; Why: Validates inbound email and drafts clarifications.
from src.agents.voice_guardrail import voice_guardrail  # What: Import voice guardrail; Why: Evaluates telephony outcomes and enforces zero-guessing.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits full end-to-end agent decisions.
from src.models.schemas import (  # What: Import domain models; Why: Typed models for outputs and status codes.
    Agent1Result,  # What: Agent 1 outcome model; Why: Structured handoff payload for Agent 2.
    AuditActionStatus,  # What: Audit status enum; Why: Records execution outcomes.
    InboundEmailPayload,  # What: Inbound email model; Why: Validated email data.
    PlanTier,  # What: Plan tier enum; Why: Subscription tiers.
    RocketlaneProjectResponse  # What: Project response model; Why: Created project data.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import rocketlane_client  # What: Import Rocketlane client; Why: Provisions projects and handles idempotency.
from src.services.voice_ai_client import voice_ai_client  # What: Import Voice AI client; Why: Places outbound call to AE.


_logger = logging.getLogger("agent1_intake")  # What: Instantiate module logger; Why: Terminal logging for Agent 1.


class Agent1Intake:  # What: Agent 1 orchestrator class; Why: Coordinates ingestion, telephony, and provisioning in a single pipeline.
    """Agent 1: Intake & Routing Agent automating deal intake, AE voice confirmation, and project provisioning."""  # What: Docstring; Why: Explains agent role.

    def __init__(self) -> None:  # What: Constructor method; Why: Initializes orchestrator instance.
        self.parser = intake_parser  # What: Store parser reference; Why: Email validation.
        self.voice_client = voice_ai_client  # What: Store voice client reference; Why: Telephony calls.
        self.guardrail = voice_guardrail  # What: Store guardrail reference; Why: Ambiguity checks.
        self.rocketlane = rocketlane_client  # What: Store Rocketlane client reference; Why: Project creation.

    def process_deal(  # What: Primary deal processing method; Why: Runs complete Agent 1 lifecycle for an inbound deal.
        self,  # What: Self instance; Why: Accesses class components.
        raw_email: dict[str, Any],  # What: Inbound deal dictionary; Why: Raw notification from AE.
        correlation_id: Optional[str] = None  # What: Optional correlation ID; Why: Can be supplied by caller or generated.
    ) -> Agent1Result:  # What: Return type; Why: Returns typed Agent1Result with full lifecycle state.
        """Processes an incoming deal notification email through validation, telephony confirmation, and provisioning."""  # What: Docstring; Why: Explains method contract.
        corr_id = correlation_id or f"deal_{int(datetime.now().timestamp())}_{abs(hash(str(raw_email))) % 10000:04d}"  # What: Resolve correlation ID; Why: Unique trace ID.

        audit_logger.log_action(  # What: Record audit log; Why: Marks start of deal processing.
            correlation_id=corr_id,  # What: Correlation ID; Why: Connects all events for this deal.
            agent_name="Agent1_Intake",  # What: Agent name; Why: Identifies acting agent.
            action="process_deal_started",  # What: Action name; Why: Start event.
            inputs=raw_email,  # What: Raw email input; Why: Full input audited.
            outputs={"correlation_id": corr_id},  # What: Output trace ID; Why: Trace audit.
            decision_rationale="Initiated Agent 1 deal processing pipeline for new incoming deal email.",  # What: Rationale; Why: Documents reason.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Pipeline initiated.
        )  # What: End of audit logging; Why: Saved to trail.

        # -------------------------------------------------------------------------
        # STEP 1: Deterministic Schema Validation & Zero-Assumption Guardrail
        # -------------------------------------------------------------------------
        payload, clarification_draft = self.parser.parse_and_validate(raw_email, correlation_id=corr_id)  # What: Validate schema; Why: Rejects incomplete emails.
        if clarification_draft is not None or payload is None:  # What: Check if validation failed; Why: Missing fields halt pipeline immediately.
            _logger.warning(f"Deal halted due to missing data. Clarification drafted for AE: {clarification_draft.recipient_email if clarification_draft else 'N/A'}")  # What: Log warning; Why: Terminal view.
            return Agent1Result(  # What: Return halted result; Why: Stops pipeline and returns clarification draft.
                correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
                status="HALTED_MISSING_DATA",  # What: Halted status; Why: Missing data state.
                clarification_draft=clarification_draft  # What: Clarification draft; Why: Draft email to AE.
            )  # What: End of halted result; Why: Halts execution.

        # -------------------------------------------------------------------------
        # STEP 2: Strict Idempotency Check
        # -------------------------------------------------------------------------
        idempotency_key = payload.generate_idempotency_key()  # What: Generate SHA-256 key; Why: Unique deal fingerprint.
        if idempotency_key in self.rocketlane._idempotency_cache:  # What: Check idempotency cache; Why: Prevents duplicate voice calls and projects.
            cached_project = self.rocketlane._idempotency_cache[idempotency_key]  # What: Retrieve cached project; Why: Reuses provisioned project.
            _logger.info(f"Duplicate deal detected for key '{idempotency_key}'. Returning existing Rocketlane project '{cached_project.project_id}'.")  # What: Log info; Why: Terminal view.
            audit_logger.log_action(  # What: Record audit log; Why: Documents duplicate detection.
                correlation_id=corr_id,  # What: Correlation ID; Why: Links audit record.
                agent_name="Agent1_Intake",  # What: Agent name; Why: Identifies agent.
                action="idempotent_duplicate_prevented",  # What: Action name; Why: Duplicate event.
                inputs={"idempotency_key": idempotency_key, "customer_name": payload.customer_name},  # What: Inputs; Why: Audited inputs.
                outputs=cached_project.model_dump(),  # What: Cached project; Why: Audited outputs.
                decision_rationale=f"Duplicate email detected for customer '{payload.customer_name}'. Returned existing project '{cached_project.project_id}' without re-dialing AE.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Successfully prevented duplicate.
            )  # What: End of audit logging; Why: Saved to trail.
            return Agent1Result(  # What: Return duplicate result; Why: Safe idempotent response.
                correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
                status="IDEMPOTENT_DUPLICATE",  # What: Duplicate status; Why: Duplicate outcome.
                email_payload=payload,  # What: Parsed payload; Why: Preserves parsed data.
                rocketlane_project=cached_project  # What: Cached project; Why: Existing project reference.
            )  # What: End of duplicate result; Why: Done.

        # -------------------------------------------------------------------------
        # STEP 3: Outbound Voice AI Call to Account Executive
        # -------------------------------------------------------------------------
        voice_result = self.voice_client.dispatch_tier_confirmation_call(  # What: Dispatch Voice AI call; Why: Verbally confirms omitted plan tier.
            customer_name=payload.customer_name,  # What: Customer name; Why: Injected into voice assistant prompt.
            ae_name=payload.ae_name,  # What: AE name; Why: Injected into voice greeting.
            ae_phone=payload.ae_phone,  # What: AE phone; Why: Destination number for outbound call.
            correlation_id=corr_id  # What: Correlation ID; Why: Connects call to deal audit trail.
        )  # What: End of voice call dispatch; Why: Telephony completed.

        # -------------------------------------------------------------------------
        # STEP 4: Telephony Guardrail (Ambiguity / Failure / Silence Check)
        # -------------------------------------------------------------------------
        confirmed_tier, escalation_ticket = self.guardrail.evaluate_call_outcome(  # What: Evaluate call outcome; Why: Blocks provisioning on ambiguity.
            result=voice_result,  # What: Voice result; Why: Evaluates status and transcript.
            customer_name=payload.customer_name,  # What: Customer name; Why: Passed to escalation ticket.
            ae_name=payload.ae_name,  # What: AE name; Why: Passed to escalation ticket.
            correlation_id=corr_id  # What: Correlation ID; Why: Audit linkage.
        )  # What: End of guardrail evaluation; Why: Decision made.

        if escalation_ticket is not None or confirmed_tier is None:  # What: Check if call was escalated; Why: Non-confirmed calls cannot provision.
            _logger.warning(f"Voice confirmation failed or ambiguous ({escalation_ticket.reason if escalation_ticket else 'Unconfirmed'}). Escalation ticket: {escalation_ticket.ticket_id if escalation_ticket else 'N/A'}")  # What: Log warning; Why: Terminal view.
            return Agent1Result(  # What: Return escalated result; Why: Halts pipeline and returns escalation ticket.
                correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
                status="ESCALATED_VOICE_ISSUE",  # What: Escalated status; Why: Escalation state.
                email_payload=payload,  # What: Parsed payload; Why: Preserves parsed data.
                voice_result=voice_result,  # What: Voice result; Why: Full transcript proof.
                escalation_ticket=escalation_ticket  # What: Escalation ticket; Why: Human review ticket.
            )  # What: End of escalated result; Why: Halts execution.

        # -------------------------------------------------------------------------
        # STEP 5: Rocketlane Project Provisioning
        # -------------------------------------------------------------------------
        project_request = self.rocketlane.resolve_tier_payload(  # What: Resolve tier configuration; Why: Maps confirmed tier to 30d vs 14d template.
            customer_name=payload.customer_name,  # What: Customer name; Why: Project title.
            customer_email=payload.customer_contact_email,  # What: Customer contact email; Why: Primary collaborator.
            tier=confirmed_tier,  # What: Verified tier enum; Why: Enterprise or Growth.
            idempotency_key=idempotency_key  # What: SHA-256 fingerprint; Why: Enforces deduplication.
        )  # What: End of payload resolution; Why: Ready to provision.

        project_response = self.rocketlane.create_project(project_request, correlation_id=corr_id)  # What: Call create_project; Why: Provisions project in Rocketlane.

        # -------------------------------------------------------------------------
        # STEP 6: Lifecycle Completion Audit
        # -------------------------------------------------------------------------
        audit_logger.log_action(  # What: Record final audit log; Why: Documents successful end-to-end completion of Agent 1.
            correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
            agent_name="Agent1_Intake",  # What: Agent name; Why: Identifies agent.
            action="agent1_workflow_completed",  # What: Action name; Why: Completion event.
            inputs=raw_email,  # What: Original raw email; Why: Audited inputs.
            outputs={  # What: Outputs dictionary; Why: Summary of completed actions.
                "customer_name": payload.customer_name,  # What: Customer name; Why: Customer identity.
                "confirmed_tier": confirmed_tier.value,  # What: Verified tier; Why: Confirmed subscription.
                "project_id": project_response.project_id,  # What: Rocketlane project ID; Why: Provisioned workspace.
                "portal_url": project_response.portal_url  # What: Rocketlane portal link; Why: Link for Agent 2.
            },  # What: End of outputs dictionary; Why: Complete summary.
            decision_rationale=(  # What: Rationale string; Why: Explains full decision chain.
                f"Agent 1 successfully validated inbound email, confirmed '{confirmed_tier.value}' tier via voice call, "  # What: Text part 1; Why: Context.
                f"and provisioned Rocketlane project '{project_response.project_id}' ({project_request.duration_days}-day SLA). Ready for Agent 2."  # What: Text part 2; Why: SLA info.
            ),  # What: End of rationale string; Why: Complete rationale.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Normal completion.
        )  # What: End of audit logging; Why: Saved to trail.

        return Agent1Result(  # What: Return successful result model; Why: Handoff payload for Agent 2.
            correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
            status="SUCCESS",  # What: Success status; Why: Successful completion.
            email_payload=payload,  # What: Validated email payload; Why: Parsed data.
            voice_result=voice_result,  # What: Voice result; Why: Telephony proof.
            rocketlane_project=project_response  # What: Rocketlane project response; Why: Created project data.
        )  # What: End of successful result; Why: Ready for handoff.


# Global singleton Agent 1 instance
agent1_intake: Agent1Intake = Agent1Intake()  # What: Instantiate global Agent 1; Why: Shared instance across application.
