"""Email intake parser and deterministic validation guardrail for NovaCRM deal notifications.

Extracts structured deal metadata from inbound email payloads and enforces the
strict Zero-Assumption Contract Guardrail. If mandatory parameters are absent
or malformed, the parser immediately halts execution and generates a structured
ClarificationDraft rather than guessing missing values.
"""

from datetime import datetime, timezone
import re
from typing import Any, Optional, Tuple

from pydantic import ValidationError

from src.core.audit_logger import audit_logger
from src.models.schemas import (
    AuditActionStatus,
    ClarificationDraft,
    InboundEmailPayload,
)


class IntakeParser:
    """Parses incoming AE deal notification emails and enforces zero-assumption validation guardrails.

    Attributes:
        MANDATORY_FIELDS: List of non-negotiable field names required to initiate onboarding.
    """

    MANDATORY_FIELDS: list[str] = [
        "customer_name",
        "customer_contact_email",
        "ae_name",
        "ae_phone",
    ]

    def parse_and_validate(
        self,
        raw_email: dict[str, Any],
        correlation_id: str,
    ) -> Tuple[Optional[InboundEmailPayload], Optional[ClarificationDraft]]:
        """Validates that all mandatory fields are present, populated, and structurally valid.

        Execution Branches:
            - Branch 1: Missing / Blank Fields -> Halts pipeline and returns ClarificationDraft.
            - Branch 2: Pydantic Schema Format Error -> Halts pipeline and returns ClarificationDraft.
            - Branch 3: Schema Validation Passed -> Emits audit log and returns validated InboundEmailPayload.

        Args:
            raw_email: Inbound dictionary containing extracted deal fields from email or webhook.
            correlation_id: Distributed tracing identifier linking audit trail entries.

        Returns:
            A tuple of (InboundEmailPayload, None) if validation succeeds, or
            (None, ClarificationDraft) if execution is halted due to missing or invalid data.
        """
        # =========================================================================
        # Stage 1: Deterministic Inspection of Mandatory Fields & Syntax Heuristics
        # =========================================================================
        missing_fields: list[str] = []
        for field in self.MANDATORY_FIELDS:
            val = raw_email.get(field)
            if val is None or (isinstance(val, str) and not val.strip()):
                missing_fields.append(field)
            elif field == "customer_contact_email" and isinstance(val, str):
                clean_email = val.strip()
                if (
                    "@" not in clean_email
                    or "." not in clean_email.split("@")[-1]
                    or len(clean_email.split("@")[-1]) < 2
                ):
                    missing_fields.append(field)
            elif field == "ae_phone" and isinstance(val, str):
                digits = re.sub(r"\D", "", val.strip())
                if len(digits) < 7 or digits.startswith("0000") or digits == "0" * len(digits):
                    missing_fields.append(field)

        # =========================================================================
        # Branch 1: Mandatory Field Omission Halt
        # =========================================================================
        if missing_fields:
            draft = self.draft_clarification_email(raw_email, missing_fields)
            audit_logger.log_action(
                correlation_id=correlation_id,
                agent_name="Agent1_Intake",
                action="schema_validation_halt",
                inputs=raw_email,
                outputs=draft.model_dump(),
                decision_rationale=(
                    f"Inbound email omitted mandatory fields: {missing_fields}. Halted pipeline "
                    f"and drafted clarification request to AE without guessing missing data."
                ),
                status=AuditActionStatus.HALTED,
            )
            return None, draft

        # =========================================================================
        # Stage 2: Pydantic Model Validation & Schema Normalization
        # =========================================================================
        try:
            payload = InboundEmailPayload(
                message_id=str(raw_email.get("message_id", f"msg_{int(datetime.now().timestamp())}")),
                customer_name=str(raw_email["customer_name"]).strip(),
                customer_contact_email=raw_email["customer_contact_email"],
                ae_name=str(raw_email["ae_name"]).strip(),
                ae_phone=str(raw_email["ae_phone"]).strip(),
                opportunity_url=raw_email.get("opportunity_url"),
            )
        except ValidationError as exc:
            # =====================================================================
            # Branch 2: Schema Formatting Failure Halt
            # =====================================================================
            err_fields = [err["loc"][0] for err in exc.errors() if "loc" in err]
            err_field_names = [str(f) for f in err_fields] or ["malformed_input"]
            draft = self.draft_clarification_email(raw_email, err_field_names)
            audit_logger.log_action(
                correlation_id=correlation_id,
                agent_name="Agent1_Intake",
                action="schema_validation_halt",
                inputs=raw_email,
                outputs=draft.model_dump(),
                decision_rationale=f"Email payload failed validation rules on fields: {err_field_names}. Details: {exc}",
                status=AuditActionStatus.HALTED,
            )
            return None, draft

        # =========================================================================
        # Branch 3: Schema Validation Succeeded
        # =========================================================================
        audit_logger.log_action(
            correlation_id=correlation_id,
            agent_name="Agent1_Intake",
            action="schema_validation_passed",
            inputs=raw_email,
            outputs=payload.model_dump(),
            decision_rationale="All mandatory email fields validated successfully. Proceeding to tier confirmation.",
            status=AuditActionStatus.SUCCESS,
        )

        return payload, None

    def draft_clarification_email(
        self,
        raw_email: dict[str, Any],
        missing_fields: list[str],
    ) -> ClarificationDraft:
        """Generates a professional, structured clarification draft email to the Account Executive.

        Args:
            raw_email: Incomplete raw email dictionary providing available context.
            missing_fields: List of missing or invalid field names to enumerate in the draft.

        Returns:
            A strongly-typed ClarificationDraft model ready to be staged to [Gmail]/Drafts.
        """
        customer_display = raw_email.get("customer_name") or "New Customer (Name Missing)"
        ae_email_dest = (
            raw_email.get("ae_email")
            or f"{str(raw_email.get('ae_name', 'ae')).lower().replace(' ', '.')}@novacrm.com"
        )
        formatted_missing = "\n".join([f"  - {f}" for f in missing_fields])

        subject = f"[New Deal] [Action Required] Clarification Needed for {customer_display} Onboarding"
        body = (
            f"Hi {raw_email.get('ae_name', 'Account Executive')},\n\n"
            f"The NovaCRM automated onboarding system received your deal notification for '{customer_display}', "
            f"but the following required onboarding fields are missing or invalid:\n\n"
            f"{formatted_missing}\n\n"
            f"In accordance with our zero-assumption data policy, the onboarding pipeline has been paused "
            f"and will not create a project until these details are provided.\n\n"
            f"Please reply with the missing information or update the Salesforce opportunity record so we can proceed.\n\n"
            f"Best regards,\nNovaCRM Onboarding AI Engine"
        )

        return ClarificationDraft(
            recipient_email=ae_email_dest,
            subject=subject,
            missing_fields=missing_fields,
            body=body,
            created_at=datetime.now(timezone.utc),
        )


# Global singleton parser instance
intake_parser: IntakeParser = IntakeParser()
