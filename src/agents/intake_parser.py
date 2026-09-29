# Email intake parser and deterministic validation guardrail for NovaCRM deal notifications.  # What: Module header; Why: Parses inbound emails and enforces zero-assumption validation.
import re  # What: Import regular expressions; Why: Validates phone digit counts and email syntax patterns.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps on drafted clarification records.
from typing import Any, Optional, Tuple  # What: Import typing utilities; Why: Type hints for raw dictionaries, tuples, and optional returns.
from pydantic import ValidationError  # What: Import ValidationError; Why: Catches schema validation failures.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits parsing and validation decisions.
from src.models.schemas import (  # What: Import domain models; Why: Uses typed schemas for payload and clarification drafts.
    AuditActionStatus,  # What: Audit status enum; Why: Records HALTED or SUCCESS states.
    ClarificationDraft,  # What: Clarification draft model; Why: Creates structured clarification drafts.
    InboundEmailPayload  # What: Inbound email model; Why: Validates inbound email fields.
)  # What: End of schema imports; Why: Completes domain model dependencies.


class IntakeParser:  # What: Intake parser class; Why: Encapsulates email parsing, field validation, and draft generation.
    """Parses incoming AE deal notification emails and enforces zero-assumption validation guardrails."""  # What: Docstring; Why: Documents class role.

    MANDATORY_FIELDS: list[str] = [  # What: List of required field names; Why: Defines strict schema requirements for incoming deals.
        "customer_name",  # What: Customer company name; Why: Required for Rocketlane project and Slack channel.
        "customer_contact_email",  # What: Customer contact email; Why: Required for customer invitation and collaboration.
        "ae_name",  # What: Account Executive name; Why: Required to identify deal owner and recipient of voice call.
        "ae_phone"  # What: Account Executive phone number; Why: Required destination for Voice AI tier confirmation call.
    ]  # What: End of mandatory fields list; Why: Non-negotiable deal parameters.

    def parse_and_validate(  # What: Main validation method; Why: Enforces schema guardrail and generates clarification draft on failure.
        self,  # What: Self instance; Why: Accesses class methods.
        raw_email: dict[str, Any],  # What: Raw email dictionary; Why: Inbound payload from Gmail trigger or webhook.
        correlation_id: str  # What: Deal tracking ID; Why: Connects parsing step to the deal's audit trail.
    ) -> Tuple[Optional[InboundEmailPayload], Optional[ClarificationDraft]]:  # What: Tuple return type; Why: Returns payload if valid, or draft if halted.
        """Validates that all mandatory fields are present. Halts and drafts clarification if any field is missing."""  # What: Docstring; Why: Explains method contract.

        # 1. Deterministic check: Inspect raw dictionary for missing, blank, or invalid fields
        missing_fields: list[str] = []  # What: Initialize missing fields list; Why: Collects all omitted or invalid attributes for AE report.
        for field in self.MANDATORY_FIELDS:  # What: Loop over mandatory fields; Why: Deterministic field-by-field verification.
            val = raw_email.get(field)  # What: Retrieve value from dictionary; Why: Checks for existence and content.
            if val is None or (isinstance(val, str) and not val.strip()):  # What: Check if value is None or whitespace; Why: Zero-assumption check.
                missing_fields.append(field)  # What: Append field to missing list; Why: Flags omitted field for clarification.
            elif field == "customer_contact_email" and isinstance(val, str):  # What: Check contact email string; Why: Validates email syntax.
                clean_email = val.strip()  # What: Clean email string; Why: Normalizes email.
                if "@" not in clean_email or "." not in clean_email.split("@")[-1] or len(clean_email.split("@")[-1]) < 2:  # What: Basic email structure check; Why: Rejects incomplete email fragments.
                    missing_fields.append(field)  # What: Append to missing; Why: Flags invalid email for clarification.
            elif field == "ae_phone" and isinstance(val, str):  # What: Check AE phone string; Why: Validates phone for Voice AI call.
                digits = re.sub(r"\D", "", val.strip())  # What: Extract digits only; Why: Measures valid phone length.
                if len(digits) < 7 or digits.startswith("0000") or digits == "0" * len(digits):  # What: Require at least 7 digits, non-zero, and not starting with 0000; Why: Rejects dummy strings like 0000999.
                    missing_fields.append(field)  # What: Append to missing; Why: Flags invalid phone for clarification.

        # 2. If any field is missing, HALT execution immediately and draft clarification request
        if missing_fields:  # What: Check if any fields were missing; Why: Guardrail triggers when data is incomplete.
            draft = self.draft_clarification_email(raw_email, missing_fields)  # What: Call drafting helper; Why: Prepares clarification email for AE.
            audit_logger.log_action(  # What: Record audit log; Why: Documents guardrail halt and reasoning.
                correlation_id=correlation_id,  # What: Deal tracking ID; Why: Connects log to deal.
                agent_name="Agent1_Intake",  # What: Agent identifier; Why: Identifies Agent 1 as acting entity.
                action="schema_validation_halt",  # What: Action name; Why: Identifies validation halt event.
                inputs=raw_email,  # What: Inbound raw email; Why: Full proof of incomplete incoming data.
                outputs=draft.model_dump(),  # What: Serialized draft; Why: Full proof of generated clarification draft.
                decision_rationale=(  # What: Decision rationale; Why: Fulfills prompt requirement to never guess missing data.
                    f"Inbound email omitted mandatory fields: {missing_fields}. Halted pipeline "  # What: Rationale text part 1; Why: Explains failure.
                    f"and drafted clarification request to AE without guessing missing data."  # What: Rationale text part 2; Why: Reaffirms guardrail.
                ),  # What: End of rationale string; Why: Complete rationale.
                status=AuditActionStatus.HALTED  # What: Status HALTED; Why: Pipeline stopped awaiting human input.
            )  # What: End of audit logging; Why: Saved to audit trail.
            return None, draft  # What: Return None and draft; Why: Informs orchestrator that pipeline is halted.

        # 3. Parse with Pydantic model for type checking and email format validation
        try:  # What: Try block; Why: Catches Pydantic validation errors (e.g. malformed email address).
            payload = InboundEmailPayload(  # What: Instantiate validated model; Why: Normalizes types and generates idempotency key.
                message_id=str(raw_email.get("message_id", f"msg_{int(datetime.now().timestamp())}")),  # What: Message ID; Why: Email ID.
                customer_name=str(raw_email["customer_name"]).strip(),  # What: Sanitized customer name; Why: Customer company name.
                customer_contact_email=raw_email["customer_contact_email"],  # What: Validated email address; Why: Primary collaborator.
                ae_name=str(raw_email["ae_name"]).strip(),  # What: Sanitized AE name; Why: Account executive full name.
                ae_phone=str(raw_email["ae_phone"]).strip(),  # What: Sanitized phone; Why: Destination for Voice AI call.
                opportunity_url=raw_email.get("opportunity_url")  # What: Optional opportunity URL; Why: Context link.
            )  # What: End of model instantiation; Why: Validated payload object ready.
        except ValidationError as exc:  # What: Catch schema validation error; Why: Handles invalid formatting (e.g. bad email syntax).
            err_fields = [err["loc"][0] for err in exc.errors() if "loc" in err]  # What: Extract failing fields; Why: Identifies malformed fields.
            err_field_names = [str(f) for f in err_fields] or ["malformed_input"]  # What: Format field names list; Why: For clarification draft.
            draft = self.draft_clarification_email(raw_email, err_field_names)  # What: Draft clarification for format error; Why: Notifies AE.
            audit_logger.log_action(  # What: Record audit log; Why: Documents formatting validation halt.
                correlation_id=correlation_id,  # What: Correlation ID; Why: Links audit entry.
                agent_name="Agent1_Intake",  # What: Agent identifier; Why: Documents acting agent.
                action="schema_validation_halt",  # What: Action name; Why: Documents halt.
                inputs=raw_email,  # What: Raw email input; Why: Captures failing input.
                outputs=draft.model_dump(),  # What: Serialized draft; Why: Captures generated draft.
                decision_rationale=f"Email payload failed validation rules on fields: {err_field_names}. Details: {exc}",  # What: Rationale; Why: Explains format error.
                status=AuditActionStatus.HALTED  # What: Status HALTED; Why: Halts pipeline.
            )  # What: End of audit logging; Why: Saved to trail.
            return None, draft  # What: Return None and draft; Why: Pipeline halted.

        # 4. Valid payload passes schema guardrail
        audit_logger.log_action(  # What: Record audit log; Why: Documents successful validation.
            correlation_id=correlation_id,  # What: Correlation ID; Why: Connects to deal flow.
            agent_name="Agent1_Intake",  # What: Agent identifier; Why: Documents acting agent.
            action="schema_validation_passed",  # What: Action name; Why: Documents success.
            inputs=raw_email,  # What: Inbound raw email; Why: Inputs audited.
            outputs=payload.model_dump(),  # What: Serialized validated payload; Why: Outputs audited.
            decision_rationale="All mandatory email fields validated successfully. Proceeding to tier confirmation.",  # What: Rationale; Why: Documents reasoning.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Normal progression.
        )  # What: End of audit logging; Why: Saved to trail.

        return payload, None  # What: Return payload and None; Why: Pipeline advances to voice confirmation.

    def draft_clarification_email(  # What: Helper method to draft AE clarification email; Why: Standardizes human-in-the-loop communication.
        self,  # What: Self instance; Why: Accesses class helpers.
        raw_email: dict[str, Any],  # What: Incomplete raw email; Why: Pulls available context to populate draft.
        missing_fields: list[str]  # What: List of missing field names; Why: Explicitly enumerated in email body.
    ) -> ClarificationDraft:  # What: Return type; Why: Returns typed ClarificationDraft model.
        """Generates a professional, structured clarification draft email to the Account Executive."""  # What: Docstring; Why: Explains draft contents.
        customer_display = raw_email.get("customer_name") or "New Customer (Name Missing)"  # What: Fallback customer label; Why: Clear email subject.
        ae_email_dest = raw_email.get("ae_email") or f"{str(raw_email.get('ae_name', 'ae')).lower().replace(' ', '.')}@novacrm.com"  # What: Target AE address; Why: Destination for clarification.
        formatted_missing = "\n".join([f"  - {f}" for f in missing_fields])  # What: Format bulleted list; Why: Clean visual readability for AE.

        subject = f"[New Deal] [Action Required] Clarification Needed for {customer_display} Onboarding"  # What: Format subject line; Why: Includes filter keyword and priority notification.
        body = (  # What: Compose email body string; Why: Complete draft ready for dispatch.
            f"Hi {raw_email.get('ae_name', 'Account Executive')},\n\n"  # What: Salutation; Why: Greets AE.
            f"The NovaCRM automated onboarding system received your deal notification for '{customer_display}', "  # What: Context line; Why: Explains notification.
            f"but the following required onboarding fields are missing or invalid:\n\n"  # What: Explanation; Why: Details problem.
            f"{formatted_missing}\n\n"  # What: Enumerate missing fields; Why: Clear list of missing parameters.
            f"In accordance with our zero-assumption data policy, the onboarding pipeline has been paused "  # What: Guardrail reminder; Why: Explains why project wasn't created.
            f"and will not create a project until these details are provided.\n\n"  # What: Policy statement; Why: Reaffirms no guessing.
            f"Please reply with the missing information or update the Salesforce opportunity record so we can proceed.\n\n"  # What: Action instruction; Why: Guides AE on next steps.
            f"Best regards,\nNovaCRM Onboarding AI Engine"  # What: Sign-off; Why: Professional closing.
        )  # What: End of body string composition; Why: Ready for draft instantiation.

        return ClarificationDraft(  # What: Instantiate ClarificationDraft model; Why: Strongly-typed draft object.
            recipient_email=ae_email_dest,  # What: AE recipient email; Why: Destination address.
            subject=subject,  # What: Subject line; Why: Clear notification header.
            missing_fields=missing_fields,  # What: Missing fields list; Why: Metadata for tracking.
            body=body,  # What: Complete body text; Why: Message content.
            created_at=datetime.now(timezone.utc)  # What: Current UTC timestamp; Why: Temporal audit.
        )  # What: End of ClarificationDraft instantiation; Why: Returns typed draft.


# Global singleton parser instance
intake_parser: IntakeParser = IntakeParser()  # What: Instantiate global parser; Why: Shared instance across Agent 1.
