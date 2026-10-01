"""Voice AI telephony guardrail and speech transcript evaluation engine for NovaCRM onboarding.

Analyzes outbound voice call outcomes and speech-to-text transcripts from Account Executives.
Enforces the Zero-Assumption Plan Tier Guardrail by detecting conversational ambiguity,
hedging phrases, dropped calls, or voicemail responses, automatically minting an
EscalationTicket for human CS Ops review rather than guessing between Enterprise and Growth tiers.
"""

from datetime import datetime, timezone
import re
from typing import Optional, Tuple

from src.core.audit_logger import audit_logger
from src.models.schemas import (
    AuditActionStatus,
    EscalationTicket,
    PlanTier,
    VoiceCallResult,
    VoiceCallStatus,
)


class VoiceGuardrail:
    """Enforces strict verbal confirmation guardrails. Auto-escalates on ambiguity, silence, or call failure.

    Attributes:
        AMBIGUOUS_KEYWORDS: List of hedging phrases and non-committal expressions that trigger ambiguity escalations.
    """

    AMBIGUOUS_KEYWORDS: list[str] = [
        "not sure",
        "maybe",
        "check later",
        "might upgrade",
        "could be",
        "i think",
        "don't know",
        "probably",
    ]

    def parse_transcript_text(self, transcript: str) -> Tuple[VoiceCallStatus, PlanTier, float]:
        """Deterministically evaluates transcript text for tier keywords and ambiguity flags.

        Evaluates speech-to-text transcripts for explicit tier commitments (Enterprise vs. Growth)
        while intercepting hedging phrases or contradictory tier mentions.

        Args:
            transcript: Plain-text transcript string returned by the Voice AI telephony provider.

        Returns:
            A tuple of (derived_status, derived_tier, confidence_score) where:
                - derived_status: VoiceCallStatus.CONFIRMED or VoiceCallStatus.AMBIGUOUS.
                - derived_tier: PlanTier.ENTERPRISE, PlanTier.GROWTH, or PlanTier.UNKNOWN.
                - confidence_score: Float between 0.0 and 1.0 reflecting heuristic certainty.
        """
        lower_text = transcript.lower()

        # =========================================================================
        # Stage 1: Check for Explicit Ambiguity Phrases & Hedging Signals
        # =========================================================================
        for phrase in self.AMBIGUOUS_KEYWORDS:
            if phrase in lower_text:
                return VoiceCallStatus.AMBIGUOUS, PlanTier.UNKNOWN, 0.4

        # =========================================================================
        # Stage 2: Whole-Word Regex Scanning for Plan Tier Mentions
        # =========================================================================
        has_enterprise = bool(re.search(r"\benterprise\b", lower_text))
        has_growth = bool(re.search(r"\bgrowth\b", lower_text))

        # Contradictory mention of both tiers in the same call must be escalated
        if has_enterprise and has_growth:
            return VoiceCallStatus.AMBIGUOUS, PlanTier.UNKNOWN, 0.5

        if has_enterprise:
            return VoiceCallStatus.CONFIRMED, PlanTier.ENTERPRISE, 0.95

        if has_growth:
            return VoiceCallStatus.CONFIRMED, PlanTier.GROWTH, 0.95

        # Inconclusive transcript (no recognizable tier keywords found)
        return VoiceCallStatus.AMBIGUOUS, PlanTier.UNKNOWN, 0.2

    def evaluate_call_outcome(
        self,
        result: VoiceCallResult,
        customer_name: str,
        ae_name: str,
        correlation_id: str,
    ) -> Tuple[Optional[PlanTier], Optional[EscalationTicket]]:
        """Validates that verbal tier confirmation is unambiguous. Auto-escalates if unclear or failed.

        Execution Branches:
            - Branch 1: Hardware / Network Failure -> Escalates FAILED call to CS Ops.
            - Branch 2: Unanswered / Voicemail -> Escalates UNANSWERED call to CS Ops.
            - Branch 3: Ambiguous Speech / Hedging / Low Confidence -> Escalates AMBIGUOUS call to CS Ops.
            - Branch 4: Unambiguous Confirmation -> Emits SUCCESS audit log and returns verified PlanTier.

        Args:
            result: Raw or pre-processed VoiceCallResult model from VoiceAIClient.
            customer_name: Company name of the customer being onboarded.
            ae_name: Full name of the Account Executive who closed the deal.
            correlation_id: Distributed tracing identifier linking audit trail entries.

        Returns:
            A tuple of (confirmed_tier, None) if the call outcome is verified, or
            (None, EscalationTicket) if execution requires human escalation.
        """
        # =========================================================================
        # Stage 1: Normalize Raw Speech Transcripts with Local Heuristics
        # =========================================================================
        if result.confirmed_tier == PlanTier.UNKNOWN and result.transcript:
            derived_status, derived_tier, derived_conf = self.parse_transcript_text(result.transcript)
            result = result.model_copy(
                update={
                    "status": derived_status,
                    "confirmed_tier": derived_tier,
                    "confidence_score": derived_conf,
                }
            )

        # =========================================================================
        # Branch 1: Hardware, Carrier, or Network Connection Failures
        # =========================================================================
        if result.status == VoiceCallStatus.FAILED:
            ticket = self._generate_escalation_ticket(
                customer_name=customer_name,
                ae_name=ae_name,
                reason=result.escalation_reason or "Voice AI call failed to connect to AE.",
                call_status=VoiceCallStatus.FAILED,
                transcript=result.transcript,
            )
            audit_logger.log_action(
                correlation_id=correlation_id,
                agent_name="VoiceGuardrail",
                action="voice_guardrail_escalated_failure",
                inputs=result.model_dump(),
                outputs=ticket.model_dump(),
                decision_rationale=f"Voice call failed ({ticket.reason}). Auto-escalated to human CS team without guessing.",
                status=AuditActionStatus.ESCALATED,
            )
            return None, ticket

        # =========================================================================
        # Branch 2: Unanswered Calls, Ringing Timeouts, or Voicemail Drops
        # =========================================================================
        if result.status == VoiceCallStatus.UNANSWERED:
            ticket = self._generate_escalation_ticket(
                customer_name=customer_name,
                ae_name=ae_name,
                reason="AE did not answer the tier confirmation call after ringing timeout.",
                call_status=VoiceCallStatus.UNANSWERED,
                transcript=result.transcript,
            )
            audit_logger.log_action(
                correlation_id=correlation_id,
                agent_name="VoiceGuardrail",
                action="voice_guardrail_escalated_unanswered",
                inputs=result.model_dump(),
                outputs=ticket.model_dump(),
                decision_rationale="AE did not answer phone call. Auto-escalated to human CS team without assuming tier.",
                status=AuditActionStatus.ESCALATED,
            )
            return None, ticket

        # =========================================================================
        # Branch 3: Ambiguous Speech, Hedging Phrases, or Low Confidence (< 0.80)
        # =========================================================================
        if result.status == VoiceCallStatus.AMBIGUOUS or result.confidence_score < 0.8:
            ticket = self._generate_escalation_ticket(
                customer_name=customer_name,
                ae_name=ae_name,
                reason=result.escalation_reason or f"Ambiguous verbal response from AE (confidence: {result.confidence_score:.2f}).",
                call_status=VoiceCallStatus.AMBIGUOUS,
                transcript=result.transcript,
            )
            audit_logger.log_action(
                correlation_id=correlation_id,
                agent_name="VoiceGuardrail",
                action="voice_guardrail_escalated_ambiguity",
                inputs=result.model_dump(),
                outputs=ticket.model_dump(),
                decision_rationale=(
                    f"AE response was ambiguous. Transcript: '{result.transcript}'. "
                    f"Auto-escalated to human CS team rather than guessing a tier."
                ),
                status=AuditActionStatus.ESCALATED,
            )
            return None, ticket

        # =========================================================================
        # Branch 4: Verified Unambiguous Confirmation
        # =========================================================================
        confirmed_tier = result.confirmed_tier
        audit_logger.log_action(
            correlation_id=correlation_id,
            agent_name="VoiceGuardrail",
            action="voice_guardrail_passed",
            inputs=result.model_dump(),
            outputs={"confirmed_tier": confirmed_tier.value, "confidence_score": result.confidence_score},
            decision_rationale=f"AE verbally confirmed tier '{confirmed_tier.value}' with confidence {result.confidence_score:.2f}. Proceeding to project provisioning.",
            status=AuditActionStatus.SUCCESS,
        )

        return confirmed_tier, None

    def _generate_escalation_ticket(
        self,
        customer_name: str,
        ae_name: str,
        reason: str,
        call_status: VoiceCallStatus,
        transcript: str,
    ) -> EscalationTicket:
        """Constructs an EscalationTicket model with a unique collision-free ID and UTC timestamp.

        Args:
            customer_name: Company name of the customer being onboarded.
            ae_name: Full name of the Account Executive to consult.
            reason: Explanatory diagnostic message detailing why escalation was triggered.
            call_status: Categorical status of the voice call.
            transcript: Verbatim speech-to-text transcript or empty string.

        Returns:
            A populated EscalationTicket model ready to be audited and routed to CS Ops.
        """
        ticket_id = f"esc_{int(datetime.now().timestamp())}_{abs(hash(customer_name)) % 10000:04d}"
        return EscalationTicket(
            ticket_id=ticket_id,
            customer_name=customer_name,
            ae_name=ae_name,
            reason=reason,
            call_status=call_status,
            transcript=transcript,
            created_at=datetime.now(timezone.utc),
        )


# Global singleton guardrail instance
voice_guardrail: VoiceGuardrail = VoiceGuardrail()
