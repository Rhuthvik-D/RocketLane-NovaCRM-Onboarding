# Telephony guardrail and transcript evaluation engine enforcing zero-assumption policy on customer tiers.  # What: Module header; Why: Analyzes voice call outcomes.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps on escalation records.
import re  # What: Import regular expressions; Why: Deterministic transcript keyword matching.
from typing import Optional, Tuple  # What: Import typing utilities; Why: Type hints on return tuples and optional values.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits telephony evaluation and escalation decisions.
from src.models.schemas import (  # What: Import domain models; Why: Typed models for voice results, tiers, and escalation tickets.
    AuditActionStatus,  # What: Audit status enum; Why: Records SUCCESS or ESCALATED states.
    EscalationTicket,  # What: Escalation ticket model; Why: Creates structured tickets for human CS review.
    PlanTier,  # What: Plan tier enum; Why: Validated subscription tier.
    VoiceCallResult,  # What: Voice call result model; Why: Evaluates telephony outcome.
    VoiceCallStatus  # What: Voice call status enum; Why: Outcome status categorization.
)  # What: End of schema imports; Why: Completes domain model dependencies.


class VoiceGuardrail:  # What: Voice guardrail class; Why: Evaluates voice transcripts and blocks provisioning on ambiguity.
    """Enforces strict verbal confirmation guardrails. Auto-escalates on ambiguity, silence, or call failure."""  # What: Docstring; Why: Explains class role.

    # Ambiguity trigger keywords indicating non-committal or uncertain responses from AE
    AMBIGUOUS_KEYWORDS: list[str] = [  # What: List of ambiguity keywords; Why: Flags uncertain AE statements.
        "not sure",  # What: Keyword phrase; Why: Explicit uncertainty.
        "maybe",  # What: Keyword phrase; Why: Non-committal guess.
        "check later",  # What: Keyword phrase; Why: Postponed decision.
        "might upgrade",  # What: Keyword phrase; Why: Ambiguous future state.
        "could be",  # What: Keyword phrase; Why: Speculative answer.
        "i think",  # What: Keyword phrase; Why: Low-confidence statement.
        "don't know"  # What: Keyword phrase; Why: Complete lack of confirmation.
    ]  # What: End of ambiguity keywords list; Why: Comprehensive ambiguity filters.

    def parse_transcript_text(self, transcript: str) -> Tuple[VoiceCallStatus, PlanTier, float]:  # What: Deterministic transcript analyzer; Why: Parses raw speech-to-text.
        """Deterministically evaluates transcript text for tier keywords and ambiguity flags."""  # What: Docstring; Why: Explains analysis logic.
        lower_text = transcript.lower()  # What: Convert transcript to lowercase; Why: Case-insensitive pattern matching.

        # 1. Check for explicit ambiguity signals
        for phrase in self.AMBIGUOUS_KEYWORDS:  # What: Loop over ambiguity phrases; Why: Detects hedges and guesses.
            if phrase in lower_text:  # What: Check if ambiguity phrase is in transcript; Why: Zero-assumption guardrail trigger.
                return VoiceCallStatus.AMBIGUOUS, PlanTier.UNKNOWN, 0.4  # What: Return AMBIGUOUS with low confidence; Why: Halts pipeline.

        # 2. Check if both Enterprise and Growth are mentioned contradictory
        has_enterprise = bool(re.search(r"\benterprise\b", lower_text))  # What: Check for whole-word "enterprise"; Why: Positive enterprise mention.
        has_growth = bool(re.search(r"\bgrowth\b", lower_text))  # What: Check for whole-word "growth"; Why: Positive growth mention.

        if has_enterprise and has_growth:  # What: Check if both tiers are mentioned; Why: Contradictory answers must be escalated.
            return VoiceCallStatus.AMBIGUOUS, PlanTier.UNKNOWN, 0.5  # What: Return AMBIGUOUS; Why: Ambiguity guardrail trigger.

        if has_enterprise:  # What: Check for standalone enterprise mention; Why: Clear enterprise confirmation.
            return VoiceCallStatus.CONFIRMED, PlanTier.ENTERPRISE, 0.95  # What: Return CONFIRMED Enterprise; Why: High-confidence confirmation.

        if has_growth:  # What: Check for standalone growth mention; Why: Clear growth confirmation.
            return VoiceCallStatus.CONFIRMED, PlanTier.GROWTH, 0.95  # What: Return CONFIRMED Growth; Why: High-confidence confirmation.

        # No recognizable tier keywords found in transcript
        return VoiceCallStatus.AMBIGUOUS, PlanTier.UNKNOWN, 0.2  # What: Return AMBIGUOUS; Why: Inconclusive transcript.

    def evaluate_call_outcome(  # What: Primary guardrail evaluation method; Why: Enforces human escalation on non-confirmed calls.
        self,  # What: Self instance; Why: Accesses class methods.
        result: VoiceCallResult,  # What: Voice call outcome object; Why: Contains status, tier, transcript, and confidence.
        customer_name: str,  # What: Customer company name; Why: Included in escalation ticket.
        ae_name: str,  # What: Account Executive full name; Why: Contact referenced in escalation.
        correlation_id: str  # What: Deal tracking ID; Why: Connects evaluation to deal audit trail.
    ) -> Tuple[Optional[PlanTier], Optional[EscalationTicket]]:  # What: Return type; Why: Returns confirmed tier or escalation ticket.
        """Validates that verbal tier confirmation is unambiguous. Auto-escalates if unclear or failed."""  # What: Docstring; Why: Documents contract.

        # If incoming call has raw transcript but unconfirmed tier, evaluate transcript heuristics
        if result.confirmed_tier == PlanTier.UNKNOWN and result.transcript:  # What: Check if transcript needs evaluation; Why: Evaluates raw Vapi speech text.
            derived_status, derived_tier, derived_conf = self.parse_transcript_text(result.transcript)  # What: Parse transcript text; Why: Extracts tier and confidence.
            result = result.model_copy(update={  # What: Copy model with parsed speech attributes; Why: Normalizes raw voice result.
                "status": derived_status,  # What: Assign derived status; Why: CONFIRMED or AMBIGUOUS.
                "confirmed_tier": derived_tier,  # What: Assign derived tier; Why: ENTERPRISE, GROWTH, or UNKNOWN.
                "confidence_score": derived_conf  # What: Assign derived confidence; Why: Guardrail threshold check.
            })  # What: End of model copy; Why: Updated result object.

        # 1. Handle network failures or dropped calls
        if result.status == VoiceCallStatus.FAILED:  # What: Check if call failed; Why: Hardware/network connectivity error.
            ticket = self._generate_escalation_ticket(  # What: Generate escalation ticket; Why: Creates human review task.
                customer_name=customer_name,  # What: Customer name; Why: Deal identity.
                ae_name=ae_name,  # What: AE name; Why: Owner to reach out to.
                reason=result.escalation_reason or "Voice AI call failed to connect to AE.",  # What: Escalation reason; Why: Documents failure cause.
                call_status=VoiceCallStatus.FAILED,  # What: Status FAILED; Why: Ticket status.
                transcript=result.transcript  # What: Transcript; Why: Proof.
            )  # What: End of ticket generation; Why: Ready for escalation.
            audit_logger.log_action(  # What: Record audit log; Why: Preserves escalation record.
                correlation_id=correlation_id,  # What: Correlation ID; Why: Links audit entry.
                agent_name="VoiceGuardrail",  # What: Agent name; Why: Documents guardrail subsystem.
                action="voice_guardrail_escalated_failure",  # What: Action name; Why: Documents failure escalation.
                inputs=result.model_dump(),  # What: Result inputs; Why: Audited inputs.
                outputs=ticket.model_dump(),  # What: Ticket outputs; Why: Audited outputs.
                decision_rationale=f"Voice call failed ({ticket.reason}). Auto-escalated to human CS team without guessing.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.ESCALATED  # What: Status ESCALATED; Why: Escalated state.
            )  # What: End of audit logging; Why: Saved to trail.
            return None, ticket  # What: Return None and ticket; Why: Blocks project creation.

        # 2. Handle unanswered calls (no answer / voicemail)
        if result.status == VoiceCallStatus.UNANSWERED:  # What: Check if call was unanswered; Why: AE did not answer phone.
            ticket = self._generate_escalation_ticket(  # What: Generate escalation ticket; Why: Alerts human CS.
                customer_name=customer_name,  # What: Customer name; Why: Deal identity.
                ae_name=ae_name,  # What: AE name; Why: Owner to contact.
                reason="AE did not answer the tier confirmation call after ringing timeout.",  # What: Reason; Why: Documents no-answer.
                call_status=VoiceCallStatus.UNANSWERED,  # What: Status UNANSWERED; Why: Ticket status.
                transcript=result.transcript  # What: Transcript; Why: Proof.
            )  # What: End of ticket generation; Why: Ready for escalation.
            audit_logger.log_action(  # What: Record audit log; Why: Preserves unanswered escalation record.
                correlation_id=correlation_id,  # What: Correlation ID; Why: Links audit entry.
                agent_name="VoiceGuardrail",  # What: Agent name; Why: Documents guardrail subsystem.
                action="voice_guardrail_escalated_unanswered",  # What: Action name; Why: Documents unanswered escalation.
                inputs=result.model_dump(),  # What: Result inputs; Why: Audited inputs.
                outputs=ticket.model_dump(),  # What: Ticket outputs; Why: Audited outputs.
                decision_rationale="AE did not answer phone call. Auto-escalated to human CS team without assuming tier.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.ESCALATED  # What: Status ESCALATED; Why: Escalated state.
            )  # What: End of audit logging; Why: Saved to trail.
            return None, ticket  # What: Return None and ticket; Why: Blocks project creation.

        # 3. Handle ambiguous or non-committal responses
        if result.status == VoiceCallStatus.AMBIGUOUS or result.confidence_score < 0.8:  # What: Check for ambiguity or low confidence; Why: Ambiguous responses must halt.
            ticket = self._generate_escalation_ticket(  # What: Generate escalation ticket; Why: Prevents incorrect tier assignment.
                customer_name=customer_name,  # What: Customer name; Why: Deal identity.
                ae_name=ae_name,  # What: AE name; Why: Owner to consult.
                reason=result.escalation_reason or f"Ambiguous verbal response from AE (confidence: {result.confidence_score:.2f}).",  # What: Reason; Why: Documents ambiguity.
                call_status=VoiceCallStatus.AMBIGUOUS,  # What: Status AMBIGUOUS; Why: Ticket status.
                transcript=result.transcript  # What: Transcript text; Why: Complete proof of ambiguity.
            )  # What: End of ticket generation; Why: Ready for escalation.
            audit_logger.log_action(  # What: Record audit log; Why: Preserves ambiguity escalation record.
                correlation_id=correlation_id,  # What: Correlation ID; Why: Links audit entry.
                agent_name="VoiceGuardrail",  # What: Agent name; Why: Documents guardrail subsystem.
                action="voice_guardrail_escalated_ambiguity",  # What: Action name; Why: Documents ambiguity escalation.
                inputs=result.model_dump(),  # What: Result inputs; Why: Audited inputs.
                outputs=ticket.model_dump(),  # What: Ticket outputs; Why: Audited outputs.
                decision_rationale=(  # What: Decision rationale; Why: Documents adherence to guardrail constraint.
                    f"AE response was ambiguous. Transcript: '{result.transcript}'. "  # What: Text part 1; Why: Transcript context.
                    f"Auto-escalated to human CS team rather than guessing a tier."  # What: Text part 2; Why: Explicit guardrail compliance.
                ),  # What: End of rationale string; Why: Complete rationale.
                status=AuditActionStatus.ESCALATED  # What: Status ESCALATED; Why: Escalated state.
            )  # What: End of audit logging; Why: Saved to trail.
            return None, ticket  # What: Return None and ticket; Why: Blocks project creation.

        # 4. Verified Unambiguous Confirmation
        confirmed_tier = result.confirmed_tier  # What: Extract confirmed tier; Why: Enterprise or Growth.
        audit_logger.log_action(  # What: Record audit log; Why: Documents verified verbal confirmation.
            correlation_id=correlation_id,  # What: Correlation ID; Why: Links audit entry.
            agent_name="VoiceGuardrail",  # What: Agent name; Why: Documents guardrail subsystem.
            action="voice_guardrail_passed",  # What: Action name; Why: Documents confirmation pass.
            inputs=result.model_dump(),  # What: Result inputs; Why: Audited inputs.
            outputs={"confirmed_tier": confirmed_tier.value, "confidence_score": result.confidence_score},  # What: Outputs; Why: Audited outputs.
            decision_rationale=f"AE verbally confirmed tier '{confirmed_tier.value}' with confidence {result.confidence_score:.2f}. Proceeding to project provisioning.",  # What: Rationale; Why: Documents reason.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Normal progression.
        )  # What: End of audit logging; Why: Saved to trail.

        return confirmed_tier, None  # What: Return confirmed tier and None; Why: Unblocks project creation.

    def _generate_escalation_ticket(  # What: Helper to construct EscalationTicket; Why: Formats consistent ticket records.
        self,  # What: Self instance; Why: Accesses class helpers.
        customer_name: str,  # What: Customer company name; Why: Deal identity.
        ae_name: str,  # What: AE name; Why: Owner to reach out to.
        reason: str,  # What: Reason for escalation; Why: Documents problem.
        call_status: VoiceCallStatus,  # What: Voice call status enum; Why: Categorizes failure type.
        transcript: str  # What: Call transcript text; Why: Provides context.
    ) -> EscalationTicket:  # What: Return type; Why: Returns typed EscalationTicket model.
        """Constructs an EscalationTicket model with unique ID and timestamp."""  # What: Docstring; Why: Explains helper role.
        ticket_id = f"esc_{int(datetime.now().timestamp())}_{abs(hash(customer_name)) % 10000:04d}"  # What: Generate ticket ID; Why: Unique readable ticket identifier.
        return EscalationTicket(  # What: Instantiate EscalationTicket model; Why: Creates validated ticket model.
            ticket_id=ticket_id,  # What: Ticket ID; Why: Reference ID.
            customer_name=customer_name,  # What: Customer name; Why: Customer company.
            ae_name=ae_name,  # What: AE name; Why: AE owner.
            reason=reason,  # What: Escalation reason; Why: Explanation.
            call_status=call_status,  # What: Call status; Why: Call state.
            transcript=transcript,  # What: Transcript; Why: Transcript record.
            created_at=datetime.now(timezone.utc)  # What: Current UTC timestamp; Why: Temporal audit.
        )  # What: End of EscalationTicket instantiation; Why: Returns completed ticket.


# Global singleton guardrail instance
voice_guardrail: VoiceGuardrail = VoiceGuardrail()  # What: Instantiate global voice guardrail; Why: Shared instance across pipeline.
