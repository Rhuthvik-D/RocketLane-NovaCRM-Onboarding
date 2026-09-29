# Canonical domain models and data contracts for NovaCRM onboarding multi-agent system.  # What: Module header; Why: Enforces typed data contracts.
from datetime import datetime, timezone  
from enum import Enum  
import hashlib  
from typing import Any, Literal, Optional  
from pydantic import BaseModel, EmailStr, Field, field_validator  

class PlanTier(str, Enum):  # What: Enumeration for customer subscription plans; Why: Restricts plan types to NovaCRM offerings.
    """Supported NovaCRM customer subscription tiers."""  
    ENTERPRISE = "ENTERPRISE"  # What: 30-day onboarding with dedicated CSM; 
    GROWTH = "GROWTH"  # What: 14-day onboarding with pooled CSM;
    UNKNOWN = "UNKNOWN"  # What: Unconfirmed tier requiring clarification; Represents state before voice verification.


class VoiceCallStatus(str, Enum):  # What: Enumeration for Voice AI call outcomes; Why: Codifies telephony results deterministically.
    """Outcome states for the outbound voice call to the Account Executive."""  
    CONFIRMED = "CONFIRMED"  # What: AE explicitly stated Enterprise or Growth; Why: Allows pipeline to advance to provisioning.
    AMBIGUOUS = "AMBIGUOUS"  # What: AE gave an unclear response or contradicted themselves; Why: Triggers human escalation guardrail.
    UNANSWERED = "UNANSWERED"  # What: AE did not pick up the phone; Why: Triggers retry or human notification guardrail.
    FAILED = "FAILED"  # What: Telephony network error or connection dropped; Why: Escalates to human without guessing.


class AuditActionStatus(str, Enum):  # What: Enumeration for audit log outcome states; Why: Categorizes agent execution status.
    """Outcome states for recorded agent actions."""  
    SUCCESS = "SUCCESS"  # What: Action completed without errors; Why: Normal operational state.
    FAILED = "FAILED"  # What: Action failed due to technical error or exception; Why: Marks runtime exceptions.
    ESCALATED = "ESCALATED"  # What: Action routed to human review due to ambiguity; Why: Tracks guardrail trigger events.
    HALTED = "HALTED"  # What: Action halted due to missing mandatory data; Why: Enforces zero-assumption policy.


class InboundEmailPayload(BaseModel):  # What: Schema representing AE deal notification email; Why: Ingests and validates inbound data.
    """Validated payload extracted from new deal notification email sent by AE."""  # What: Docstring; Why: Details payload structure.
    message_id: str = Field(description="Unique email identifier from Gmail API or test harness")  # What: Email ID; Why: Deduplication identifier.
    customer_name: str = Field(min_length=1, description="Customer company name")  # What: Customer name string; Why: Rocketlane project title.
    customer_contact_email: EmailStr = Field(description="Primary customer contact email address")  # What: Customer email; Why: Rocketlane invite & Slack.
    ae_name: str = Field(min_length=1, description="Account Executive full name")  # What: AE name string; Why: Tracks deal owner.
    ae_phone: str = Field(min_length=7, description="AE phone number in E.164 or formatted string")  # What: AE phone string; Why: Destination for Voice AI call.
    opportunity_url: Optional[str] = Field(default=None, description="Salesforce opportunity URL")  # What: Optional SFDC link; Why: Contextual link for CSM.
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of receipt")  # What: Receipt time; Why: SLA tracking.

    @field_validator("customer_name", "ae_name", "ae_phone")  # What: Validator decorator; Why: Prevents empty or whitespace-only values.
    @classmethod  # What: Classmethod decorator; Why: Standard Pydantic validator signature.
    def reject_blank_strings(cls, value: str) -> str:  # What: Validation function; Why: Rejects whitespace strings that pass min_length.
        stripped = value.strip()  # What: Strip leading/trailing whitespace; Why: Normalizes raw input strings.
        if not stripped:  # What: Check if string is empty after trimming; Why: Enforces strict guardrail against missing data.
            raise ValueError("Field cannot be empty or solely whitespace.")  # What: Raise ValueError; Why: Fulfills zero-assumption rule.
        return stripped  # What: Return trimmed valid string; Why: Provides clean sanitized value.

    def generate_idempotency_key(self) -> str:  # What: Idempotency helper method; Why: Creates unique SHA-256 fingerprint for this deal.
        """Generates a deterministic SHA-256 hash based on customer name and AE contact."""  # What: Docstring; Why: Explains key generation.
        fingerprint_raw = f"{self.customer_name.strip().lower()}:{self.customer_contact_email.strip().lower()}"  # What: Format string; Why: Unique deal key.
        return hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()  # What: Return hex digest; Why: Reliable collision-resistant identifier.


class VoiceCallResult(BaseModel):  # What: Schema for telephony call outcome; Why: Captures structured output of Voice AI interaction.
    """Result payload from the outbound AE tier confirmation call."""  # What: Docstring; Why: Describes voice call data contract.
    call_id: str = Field(description="Unique telephony call identifier from Voice AI provider")  # What: Provider call ID; Why: Call trace link.
    status: VoiceCallStatus = Field(description="Outcome of the call")  # What: Call status enum; Why: Determines if pipeline proceeds.
    confirmed_tier: PlanTier = Field(default=PlanTier.UNKNOWN, description="Verified tier if confirmed")  # What: Confirmed tier; Why: Configures project.
    transcript: str = Field(default="", description="Full or summarized call audio transcript")  # What: Call transcript text; Why: Complete audit proof.
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Model confidence in detected tier")  # What: Confidence; Why: Ambiguity check.
    escalation_reason: Optional[str] = Field(default=None, description="Reason if call was escalated or failed")  # What: Escalation text; Why: Alert notes.


class RocketlaneProjectCreateRequest(BaseModel):  # What: Request payload for Rocketlane project creation; Why: Enforces API input structure.
    """Data payload submitted to the Rocketlane Projects API."""  # What: Docstring; Why: Explains Rocketlane payload contract.
    project_name: str = Field(description="Name of the onboarding project")  # What: Project name string; Why: Displayed on Rocketlane dashboard.
    template_id: str = Field(description="Template ID (30-day Enterprise vs 14-day Growth)")  # What: Template ID; Why: Sets correct milestone checklist.
    tier: PlanTier = Field(description="Customer subscription tier")  # What: Tier enum; Why: Determines project governance and rules.
    duration_days: int = Field(description="Onboarding timeline in days (30 vs 14)")  # What: Timeline integer; Why: Enforces SLA end dates.
    csm_type: str = Field(description="CSM staffing model (Dedicated vs Pooled)")  # What: CSM model string; Why: Assigns appropriate resource pool.
    csm_assigned: str = Field(description="Assigned CSM name or team inbox")  # What: Assigned resource string; Why: Assigns project manager.
    customer_email: EmailStr = Field(description="Customer primary contact email")  # What: Customer email; Why: Primary external collaborator.
    idempotency_key: str = Field(description="Deterministic hash to prevent duplicate project creation")  # What: Idempotency key; Why: Deduplication guard.


class RocketlaneProjectResponse(BaseModel):  # What: Response model for created Rocketlane project; Why: Standardizes API response data.
    """Standardized representation of a Rocketlane onboarding project."""  # What: Docstring; Why: Documents response attributes.
    project_id: str = Field(description="Unique Rocketlane project ID")  # What: Project ID; Why: Reference for tasks and Slack channel.
    project_name: str = Field(description="Title of the project")  # What: Project title; Why: Verification and UI display.
    tier: PlanTier = Field(description="Subscription tier")  # What: Subscription tier; Why: Confirms applied template.
    template_id: str = Field(description="Template identifier used during creation")  # What: Template ID; Why: Audit verification.
    portal_url: str = Field(description="Direct URL to the Rocketlane project workspace")  # What: Project link; Why: Embedded in Slack channel topic.
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")  # What: Timestamp; Why: Audit trails.
    is_duplicate: bool = Field(default=False, description="Flag indicating if project was returned from idempotency cache")  # What: Duplicate flag; Why: Idempotency audit.


class SlackChannelPayload(BaseModel):  # What: Model for Slack channel provisioning; Why: Ensures correct parameters for Agent 2.
    """Configuration payload for creating the customer onboarding Slack channel."""  # What: Docstring; Why: Explains Slack channel attributes.
    channel_name: str = Field(description="Sanitized Slack channel name e.g. #csm-ent-acme")  # What: Channel handle; Why: Must adhere to Slack naming rules.
    topic: str = Field(description="Channel topic including Rocketlane project URL")  # What: Topic text; Why: Gives customer and CSM immediate project access.
    welcome_message: str = Field(description="Personalized kickoff message tailored to plan tier")  # What: Welcome text; Why: Kickoff communication.
    is_private: bool = Field(default=True, description="Channel privacy setting")  # What: Private boolean; Why: Protects confidential customer data.


class AuditLogEntry(BaseModel):  # What: Mandatory audit trail record schema; Why: Satisfies prompt requirement for structured logging.
    """Structured audit log record capturing every agent action, input, output, and rationale."""  # What: Docstring; Why: Outlines audit fields.
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="ISO-8601 UTC timestamp")  # What: Timestamp; Why: Time proof.
    correlation_id: str = Field(description="Unique identifier tracking a deal across all agents")  # What: Correlation ID; Why: Cross-agent traceability.
    agent_name: str = Field(description="Name of the agent executing the action")  # What: Agent name; Why: Identifies actor (Agent 1, Agent 2, Agent 3).
    action: str = Field(description="Specific operation performed e.g., 'validate_email', 'call_ae'")  # What: Action name; Why: Clarifies step taken.
    inputs: dict[str, Any] = Field(description="Input parameters or raw payload received")  # What: Inputs dict; Why: Complete input audit.
    outputs: dict[str, Any] = Field(description="Output data or state produced")  # What: Outputs dict; Why: Complete outcome audit.
    decision_rationale: str = Field(description="Explicit explanation of why this decision was made")  # What: Rationale text; Why: Explains agent reasoning.
    status: AuditActionStatus = Field(description="Outcome status of the action")  # What: Status enum; Why: Quick filtering for failures/halts.


class ClarificationDraft(BaseModel):  # What: Model for clarification request draft; Why: Generated when inbound email lacks mandatory info.
    """Draft email sent to Account Executive requesting missing required deal information."""  # What: Docstring; Why: Explains clarification purpose.
    recipient_email: str = Field(description="AE email address where clarification is sent")  # What: AE email; Why: Clarification recipient.
    subject: str = Field(description="Email subject line for clarification")  # What: Subject; Why: Contextual email header.
    missing_fields: list[str] = Field(description="List of fields omitted from original email")  # What: Field names; Why: Specific missing data.
    body: str = Field(description="Full text of draft email requesting missing details")  # What: Body text; Why: Clarification draft message.
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp")  # What: Timestamp; Why: Audit temporal record.


class EscalationTicket(BaseModel):  # What: Model for human escalation record; Why: Generated when Voice AI is ambiguous or fails.
    """Human escalation ticket generated when telephony confirmation is ambiguous or unsuccessful."""  # What: Docstring; Why: Explains escalation purpose.
    ticket_id: str = Field(description="Unique escalation ticket identifier")  # What: Ticket ID; Why: Tracks escalation in queue.
    customer_name: str = Field(description="Customer company name")  # What: Customer name; Why: Deal identity.
    ae_name: str = Field(description="Account Executive name")  # What: AE name; Why: Owner to consult.
    reason: str = Field(description="Explanation of why call was escalated")  # What: Escalation reason; Why: Tells human CS what went wrong.
    call_status: VoiceCallStatus = Field(description="Voice call status enum")  # What: Call status; Why: AMBIGUOUS, UNANSWERED, or FAILED.
    transcript: str = Field(default="", description="Call transcript snippet or failure message")  # What: Transcript; Why: Proof of ambiguity.
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp")  # What: Timestamp; Why: Time record.


class Agent1Result(BaseModel):  # What: Comprehensive output model for Agent 1; Why: Provides structured handoff to Agent 2 and audit log.
    """Complete execution outcome of Agent 1 Intake & Routing Agent."""  # What: Docstring; Why: Explains Agent 1 output container.
    correlation_id: str = Field(description="Deal correlation ID")  # What: Correlation ID; Why: Connects to downstream agents.
    status: Literal["SUCCESS", "HALTED_MISSING_DATA", "ESCALATED_VOICE_ISSUE", "IDEMPOTENT_DUPLICATE"] = Field(description="Agent 1 final state")  # What: Status; Why: Outcome state.
    email_payload: Optional[InboundEmailPayload] = Field(default=None, description="Validated inbound email if parsing succeeded")  # What: Email payload; Why: Parsed data.
    clarification_draft: Optional[ClarificationDraft] = Field(default=None, description="Draft if missing fields halted workflow")  # What: Clarification draft; Why: Generated when halted.
    voice_result: Optional[VoiceCallResult] = Field(default=None, description="Voice AI call result if telephony was executed")  # What: Voice result; Why: Telephony record.
    escalation_ticket: Optional[EscalationTicket] = Field(default=None, description="Escalation ticket if voice was ambiguous/failed")  # What: Escalation ticket; Why: Escalation record.
    rocketlane_project: Optional[RocketlaneProjectResponse] = Field(default=None, description="Provisioned Rocketlane project if confirmed")  # What: Project response; Why: Created project data.


class SlackProvisioningResult(BaseModel):  # What: Model for Slack provisioning outcome; Why: Captures Slack API response attributes.
    """Standardized representation of a provisioned customer onboarding Slack channel."""  # What: Docstring; Why: Explains Slack result schema.
    channel_id: str = Field(description="Unique Slack channel ID e.g. C01234567")  # What: Channel ID; Why: Identifier for messages and invites.
    channel_name: str = Field(description="Sanitized channel name e.g. csm-ent-acme")  # What: Channel handle; Why: Human-readable channel name.
    topic_set: bool = Field(default=False, description="Flag indicating if channel topic was set")  # What: Topic flag; Why: Verifies topic embedding.
    welcome_message_ts: Optional[str] = Field(default=None, description="Timestamp ID of posted welcome message")  # What: Message ts; Why: Proves welcome message delivery.
    is_mock: bool = Field(default=False, description="Flag indicating if mock mode was used")  # What: Mock flag; Why: Distinguishes simulated vs live Slack actions.


class Agent2Result(BaseModel):  # What: Comprehensive output model for Agent 2; Why: Standardizes communication agent handoff and audit output.
    """Complete execution outcome of Agent 2 Communication Agent."""  # What: Docstring; Why: Explains Agent 2 output container.
    correlation_id: str = Field(description="Deal correlation ID linking all agent actions")  # What: Correlation ID; Why: Cross-agent traceability.
    status: Literal["SUCCESS", "SKIPPED_UNCONFIRMED", "FAILED"] = Field(description="Agent 2 final state")  # What: Status string; Why: Encapsulates outcome state.
    channel_payload: Optional[SlackChannelPayload] = Field(default=None, description="Generated Slack channel configuration")  # What: Payload; Why: Records channel configuration.
    provisioning_result: Optional[SlackProvisioningResult] = Field(default=None, description="Slack provisioning details")  # What: Provisioning result; Why: Records provisioned channel details.
    error_message: Optional[str] = Field(default=None, description="Error details if provisioning failed")  # What: Error message; Why: Explains failures.


class OverdueEscalationTarget(str, Enum):  # What: Enumeration for Rocketlane overdue escalation targets; Why: Codifies SLA routing rules.
    """Escalation recipient tiers for overdue Rocketlane onboarding tasks."""  # What: Docstring; Why: Explains escalation target enum.
    PROJECT_MANAGER = "PROJECT_MANAGER"  # What: Project Manager role; Why: 1-day overdue escalation contact.
    PROJECT_OWNER = "PROJECT_OWNER"  # What: Project Owner role; Why: 4-day overdue critical escalation contact.


class OverdueAlertResult(BaseModel):  # What: Schema representing an evaluated Rocketlane task overdue alert; Why: Records SLA notification outcomes.
    """Standardized representation of a Rocketlane overdue task escalation alert."""  # What: Docstring; Why: Explains overdue alert result schema.
    task_id: str = Field(description="Unique Rocketlane task ID")  # What: Task ID; Why: Identifies overdue task.
    task_name: str = Field(description="Name or title of the task")  # What: Task name; Why: Human-readable task label.
    project_id: str = Field(description="Rocketlane project ID")  # What: Project ID; Why: Connects task to project.
    days_overdue: int = Field(ge=0, description="Number of days elapsed past due date")  # What: Days overdue; Why: Determines escalation tier.
    target: Optional[OverdueEscalationTarget] = Field(default=None, description="Escalation recipient")  # What: Target enum; Why: PM vs Owner.
    alert_triggered: bool = Field(default=False, description="Flag indicating if SLA rule fired")  # What: Trigger flag; Why: Indicates notification state.
    recipient_label: str = Field(default="", description="Recipient display name or email")  # What: Recipient label; Why: Identifies notified party.
    alert_message: str = Field(default="", description="Escalation notification message")  # What: Alert text; Why: Notification content.


class DataMigrationSignOffPayload(BaseModel):  # What: Schema for Data Migration verification handoff; Why: Enforces complete sign-off proof.
    """Input payload representing customer data verification sign-off submitted for milestone gating."""  # What: Docstring; Why: Explains sign-off schema.
    project_id: str = Field(description="Unique Rocketlane project ID")  # What: Project ID; Why: Identifies project workspace.
    task_id: str = Field(description="Unique Data Migration task ID")  # What: Task ID; Why: Identifies migration task.
    customer_name: str = Field(min_length=1, description="Customer company name")  # What: Customer name; Why: Deal identity.
    records_migrated: int = Field(ge=0, description="Total number of records imported into NovaCRM")  # What: Migrated count; Why: Parity check.
    records_verified: int = Field(ge=0, description="Total number of records verified by customer")  # What: Verified count; Why: Parity check.
    customer_sign_off_confirmed: bool = Field(description="Flag confirming customer reviewed and signed off")  # What: Sign-off flag; Why: Prevents unverified sign-offs.
    sign_off_contact_email: EmailStr = Field(description="Email of customer lead who authorized sign-off")  # What: Sign-off email; Why: Proof of customer sign-off.
    discrepancy_notes: Optional[str] = Field(default=None, description="Notes on any discrepancies or errors")  # What: Discrepancy text; Why: QA record.


class DataQAGatekeeperResult(BaseModel):  # What: Schema representing Agent 3 Data QA Gatekeeper outcome; Why: Determines downstream phase unlock.
    """Complete execution outcome of Agent 3 Data QA Gatekeeper enforcing migration verification."""  # What: Docstring; Why: Explains Gatekeeper result schema.
    correlation_id: str = Field(description="Deal correlation ID linking all agent actions")  # What: Correlation ID; Why: Cross-agent traceability.
    project_id: str = Field(description="Rocketlane project ID")  # What: Project ID; Why: Project reference.
    status: Literal["VERIFIED_UNLOCKED", "REJECTED_BLOCKED", "ESCALATED_DISCREPANCY"] = Field(description="Gatekeeper outcome state")  # What: Status string; Why: Gate state.
    is_configuration_unlocked: bool = Field(description="Flag indicating if Configuration phase is unlocked")  # What: Unlock flag; Why: Controls stage-gate.
    records_migrated: int = Field(description="Migrated records count")  # What: Migrated integer; Why: Parity audit.
    records_verified: int = Field(description="Verified records count")  # What: Verified integer; Why: Parity audit.
    discrepancy_count: int = Field(default=0, description="Count of mismatched or unverified records")  # What: Discrepancy count; Why: Error tracking.
    csm_alert_sent: bool = Field(default=False, description="Flag indicating if CSM was notified of blocker")  # What: Alert flag; Why: Human-in-the-loop tracking.
    audit_rationale: str = Field(description="Explicit explanation of gatekeeper decision")  # What: Rationale text; Why: Complete audit proof.


