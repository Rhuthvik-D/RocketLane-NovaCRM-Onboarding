"""Agent 1: Intake & Routing Agent for NovaCRM customer onboarding.

Orchestrates the entire inbound deal lifecycle:
1. Ingests raw deal notification emails from Account Executives.
2. Enforces deterministic schema validation and human-in-the-loop clarification drafts via IntakeParser.
3. Evaluates 4-level SHA-256 idempotency to prevent duplicate projects and redundant calls.
4. Triggers Voice AI telephony to verbally confirm omitted plan tiers (Enterprise vs. Growth).
5. Enforces NLP speech ambiguity and failure guardrails via VoiceGuardrail.
6. Provisions Rocketlane cloud projects with tier-tailored milestone templates and CSM staffing.
7. Emits structured immutable audit entries across every transition to logs/audit_trail.jsonl.
"""

from datetime import datetime
import logging
from typing import Any, Optional

from src.agents.intake_parser import intake_parser
from src.agents.voice_guardrail import voice_guardrail
from src.core.audit_logger import audit_logger
from src.models.schemas import (
    Agent1Result,
    AuditActionStatus,
    InboundEmailPayload,
    PlanTier,
    RocketlaneProjectResponse,
)
from src.services.rocketlane_client import rocketlane_client
from src.services.voice_ai_client import voice_ai_client

_logger = logging.getLogger("agent1_intake")


class Agent1Intake:
    """Agent 1: Intake & Routing Agent automating deal intake, AE voice confirmation, and project provisioning."""

    def __init__(self) -> None:
        """Initializes Agent 1 with inbound parser, voice client, voice guardrail, and Rocketlane client."""
        self.parser = intake_parser
        self.voice_client = voice_ai_client
        self.guardrail = voice_guardrail
        self.rocketlane = rocketlane_client

    def process_deal(
        self,
        raw_email: dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> Agent1Result:
        """Processes an incoming deal notification email through validation, telephony confirmation, and provisioning.

        Execution Branches:
            - Branch 1: Missing / Malformed Data Halt -> Stages clarification draft to [Gmail]/Drafts, halts pipeline.
            - Branch 2: Idempotent Duplicate Hit -> Returns existing provisioned Rocketlane project without re-dialing AE.
            - Branch 3: Telephony Escalation -> Ambiguous, unanswered, or failed call generates EscalationTicket for CS Ops.
            - Branch 4: Verified Confirmation -> Provisions 30d Enterprise or 14d Growth template in Rocketlane.

        Args:
            raw_email: Inbound dictionary containing extracted deal fields from AE email notification.
            correlation_id: Optional deal tracking identifier for linking audit trail entries.

        Returns:
            A validated Agent1Result model containing handoff payload and status.
        """
        corr_id = correlation_id or f"deal_{int(datetime.now().timestamp())}_{abs(hash(str(raw_email))) % 10000:04d}"

        audit_logger.log_action(
            correlation_id=corr_id,
            agent_name="Agent1_Intake",
            action="process_deal_started",
            inputs=raw_email,
            outputs={"correlation_id": corr_id},
            decision_rationale="Initiated Agent 1 deal processing pipeline for new incoming deal email.",
            status=AuditActionStatus.SUCCESS,
        )

        # -------------------------------------------------------------------------
        # STEP 1: Deterministic Schema Validation & Zero-Assumption Guardrail
        # -------------------------------------------------------------------------
        payload, clarification_draft = self.parser.parse_and_validate(raw_email, correlation_id=corr_id)
        if clarification_draft is not None or payload is None:
            recipient = clarification_draft.recipient_email if clarification_draft else "N/A"
            _logger.warning(f"Deal halted due to missing data. Clarification drafted for AE: {recipient}")
            return Agent1Result(
                correlation_id=corr_id,
                status="HALTED_MISSING_DATA",
                clarification_draft=clarification_draft,
            )

        # -------------------------------------------------------------------------
        # STEP 2: Strict Idempotency Check (Level 1 In-Memory & Level 2 Disk Cache)
        # -------------------------------------------------------------------------
        idempotency_key = payload.generate_idempotency_key()
        if idempotency_key in self.rocketlane._idempotency_cache:
            cached_project = self.rocketlane._idempotency_cache[idempotency_key]
            _logger.info(
                f"Duplicate deal detected for key '{idempotency_key}'. "
                f"Returning existing Rocketlane project '{cached_project.project_id}'."
            )
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="Agent1_Intake",
                action="idempotent_duplicate_prevented",
                inputs={"idempotency_key": idempotency_key, "customer_name": payload.customer_name},
                outputs=cached_project.model_dump(),
                decision_rationale=(
                    f"Duplicate email detected for customer '{payload.customer_name}'. "
                    f"Returned existing project '{cached_project.project_id}' without re-dialing AE."
                ),
                status=AuditActionStatus.SUCCESS,
            )
            return Agent1Result(
                correlation_id=corr_id,
                status="IDEMPOTENT_DUPLICATE",
                email_payload=payload,
                rocketlane_project=cached_project,
            )

        # -------------------------------------------------------------------------
        # STEP 3: Outbound Voice AI Call to Account Executive
        # -------------------------------------------------------------------------
        voice_result = self.voice_client.dispatch_tier_confirmation_call(
            customer_name=payload.customer_name,
            ae_name=payload.ae_name,
            ae_phone=payload.ae_phone,
            correlation_id=corr_id,
        )

        # -------------------------------------------------------------------------
        # STEP 4: Telephony Guardrail (Ambiguity / Failure / Silence Check)
        # -------------------------------------------------------------------------
        confirmed_tier, escalation_ticket = self.guardrail.evaluate_call_outcome(
            result=voice_result,
            customer_name=payload.customer_name,
            ae_name=payload.ae_name,
            correlation_id=corr_id,
        )

        if escalation_ticket is not None or confirmed_tier is None:
            reason = escalation_ticket.reason if escalation_ticket else "Unconfirmed"
            ticket_id = escalation_ticket.ticket_id if escalation_ticket else "N/A"
            _logger.warning(f"Voice confirmation failed or ambiguous ({reason}). Escalation ticket: {ticket_id}")
            return Agent1Result(
                correlation_id=corr_id,
                status="ESCALATED_VOICE_ISSUE",
                email_payload=payload,
                voice_result=voice_result,
                escalation_ticket=escalation_ticket,
            )

        # -------------------------------------------------------------------------
        # STEP 5: Rocketlane Project Provisioning
        # -------------------------------------------------------------------------
        project_request = self.rocketlane.resolve_tier_payload(
            customer_name=payload.customer_name,
            customer_email=payload.customer_contact_email,
            tier=confirmed_tier,
            idempotency_key=idempotency_key,
        )

        project_response = self.rocketlane.create_project(project_request, correlation_id=corr_id)

        # -------------------------------------------------------------------------
        # STEP 6: Lifecycle Completion Audit
        # -------------------------------------------------------------------------
        audit_logger.log_action(
            correlation_id=corr_id,
            agent_name="Agent1_Intake",
            action="agent1_workflow_completed",
            inputs=raw_email,
            outputs={
                "customer_name": payload.customer_name,
                "confirmed_tier": confirmed_tier.value,
                "project_id": project_response.project_id,
                "portal_url": project_response.portal_url,
            },
            decision_rationale=(
                f"Agent 1 successfully validated inbound email, confirmed '{confirmed_tier.value}' tier via voice call, "
                f"and provisioned Rocketlane project '{project_response.project_id}' ({project_request.duration_days}-day SLA). "
                f"Ready for Agent 2."
            ),
            status=AuditActionStatus.SUCCESS,
        )

        return Agent1Result(
            correlation_id=corr_id,
            status="SUCCESS",
            email_payload=payload,
            voice_result=voice_result,
            rocketlane_project=project_response,
        )


# Global singleton Agent 1 instance
agent1_intake: Agent1Intake = Agent1Intake()
