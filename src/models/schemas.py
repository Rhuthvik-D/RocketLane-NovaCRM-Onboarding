"""Canonical domain models and data contracts for NovaCRM onboarding multi-agent system.

Defines Pydantic v2 schemas, enumerations, API request/response contracts,
and inter-agent handoff models that enforce type safety, input validation,
deterministic idempotency hashing, and stage-gated progression across all services.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Literal, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


class PlanTier(str, Enum):
    """Supported NovaCRM customer subscription tiers."""

    ENTERPRISE = "ENTERPRISE"
    GROWTH = "GROWTH"
    UNKNOWN = "UNKNOWN"


class VoiceCallStatus(str, Enum):
    """Outcome states for the outbound voice call to the Account Executive."""

    CONFIRMED = "CONFIRMED"
    AMBIGUOUS = "AMBIGUOUS"
    UNANSWERED = "UNANSWERED"
    FAILED = "FAILED"


class AuditActionStatus(str, Enum):
    """Outcome states for recorded agent actions in the audit trail."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    HALTED = "HALTED"


class InboundEmailPayload(BaseModel):
    """Validated payload extracted from new deal notification email sent by AE."""

    message_id: str = Field(description="Unique email identifier from Gmail API or test harness")
    customer_name: str = Field(min_length=1, description="Customer company name")
    customer_contact_email: EmailStr = Field(description="Primary customer contact email address")
    ae_name: str = Field(min_length=1, description="Account Executive full name")
    ae_phone: str = Field(min_length=7, description="AE phone number in E.164 or formatted string")
    opportunity_url: Optional[str] = Field(default=None, description="Salesforce opportunity URL")
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of deal receipt",
    )

    @field_validator("customer_name", "ae_name", "ae_phone")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        """Rejects empty strings or strings composed solely of whitespace.

        Args:
            value: The raw string value to validate.

        Returns:
            The stripped, non-empty string.

        Raises:
            ValueError: If the string is empty after stripping whitespace.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or solely whitespace.")
        return stripped

    def generate_idempotency_key(self) -> str:
        """Generates a deterministic SHA-256 hash based on customer name and AE contact.

        Returns:
            A 64-character hexadecimal SHA-256 string unique to this deal.
        """
        fingerprint_raw = f"{self.customer_name.strip().lower()}:{self.customer_contact_email.strip().lower()}"
        return hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()


class VoiceCallResult(BaseModel):
    """Result payload from the outbound AE tier confirmation call."""

    call_id: str = Field(description="Unique telephony call identifier from Voice AI provider")
    status: VoiceCallStatus = Field(description="Outcome of the call")
    confirmed_tier: PlanTier = Field(
        default=PlanTier.UNKNOWN,
        description="Verified tier if confirmed by AE",
    )
    transcript: str = Field(default="", description="Full or summarized call audio transcript")
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Model confidence score in detected tier",
    )
    escalation_reason: Optional[str] = Field(
        default=None,
        description="Reason if call was escalated or failed",
    )


class RocketlaneProjectCreateRequest(BaseModel):
    """Data payload submitted to the Rocketlane Projects API."""

    project_name: str = Field(description="Name of the onboarding project")
    template_id: str = Field(description="Template ID (30-day Enterprise vs 14-day Growth)")
    tier: PlanTier = Field(description="Customer subscription tier")
    duration_days: int = Field(description="Onboarding timeline in days (30 vs 14)")
    csm_type: str = Field(description="CSM staffing model (Dedicated vs Pooled)")
    csm_assigned: str = Field(description="Assigned CSM name or team inbox")
    customer_email: EmailStr = Field(description="Customer primary contact email")
    idempotency_key: str = Field(description="Deterministic hash to prevent duplicate project creation")


class RocketlaneProjectResponse(BaseModel):
    """Standardized representation of a Rocketlane onboarding project."""

    project_id: str = Field(description="Unique Rocketlane project ID")
    project_name: str = Field(description="Title of the project")
    tier: PlanTier = Field(description="Subscription tier")
    template_id: str = Field(description="Template identifier used during creation")
    portal_url: str = Field(description="Direct URL to the Rocketlane project workspace")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp in UTC",
    )
    is_duplicate: bool = Field(
        default=False,
        description="Flag indicating if project was returned from idempotency cache",
    )


class SlackChannelPayload(BaseModel):
    """Configuration payload for creating the customer onboarding Slack channel."""

    channel_name: str = Field(description="Sanitized Slack channel name e.g. csm-ent-acme")
    topic: str = Field(description="Channel topic including Rocketlane project URL")
    welcome_message: str = Field(description="Personalized kickoff message tailored to plan tier")
    is_private: bool = Field(default=True, description="Channel privacy setting")


class AuditLogEntry(BaseModel):
    """Structured audit log record capturing every agent action, input, output, and rationale."""

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO-8601 UTC timestamp",
    )
    correlation_id: str = Field(description="Unique identifier tracking a deal across all agents")
    agent_name: str = Field(description="Name of the agent executing the action")
    action: str = Field(description="Specific operation performed e.g. validate_email, call_ae")
    inputs: dict[str, Any] = Field(description="Input parameters or raw payload received")
    outputs: dict[str, Any] = Field(description="Output data or state produced")
    decision_rationale: str = Field(description="Explicit explanation of why this decision was made")
    status: AuditActionStatus = Field(description="Outcome status of the action")


class ClarificationDraft(BaseModel):
    """Draft email sent to Account Executive requesting missing required deal information."""

    recipient_email: str = Field(description="AE email address where clarification is sent")
    subject: str = Field(description="Email subject line for clarification")
    missing_fields: list[str] = Field(description="List of fields omitted from original email")
    body: str = Field(description="Full text of draft email requesting missing details")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Draft generation timestamp in UTC",
    )


class EscalationTicket(BaseModel):
    """Human escalation ticket generated when telephony confirmation is ambiguous or unsuccessful."""

    ticket_id: str = Field(description="Unique escalation ticket identifier")
    customer_name: str = Field(description="Customer company name")
    ae_name: str = Field(description="Account Executive name")
    reason: str = Field(description="Explanation of why call was escalated")
    call_status: VoiceCallStatus = Field(description="Voice call status enum")
    transcript: str = Field(default="", description="Call transcript snippet or failure message")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Escalation creation timestamp in UTC",
    )


class Agent1Result(BaseModel):
    """Complete execution outcome of Agent 1 Intake & Routing Agent."""

    correlation_id: str = Field(description="Deal correlation ID")
    status: Literal["SUCCESS", "HALTED_MISSING_DATA", "ESCALATED_VOICE_ISSUE", "IDEMPOTENT_DUPLICATE"] = Field(
        description="Agent 1 final state"
    )
    email_payload: Optional[InboundEmailPayload] = Field(
        default=None,
        description="Validated inbound email if parsing succeeded",
    )
    clarification_draft: Optional[ClarificationDraft] = Field(
        default=None,
        description="Draft if missing fields halted workflow",
    )
    voice_result: Optional[VoiceCallResult] = Field(
        default=None,
        description="Voice AI call result if telephony was executed",
    )
    escalation_ticket: Optional[EscalationTicket] = Field(
        default=None,
        description="Escalation ticket if voice was ambiguous or failed",
    )
    rocketlane_project: Optional[RocketlaneProjectResponse] = Field(
        default=None,
        description="Provisioned Rocketlane project if confirmed",
    )


class SlackProvisioningResult(BaseModel):
    """Standardized representation of a provisioned customer onboarding Slack channel."""

    channel_id: str = Field(description="Unique Slack channel ID e.g. C01234567")
    channel_name: str = Field(description="Sanitized channel name e.g. csm-ent-acme")
    topic_set: bool = Field(default=False, description="Flag indicating if channel topic was set")
    welcome_message_ts: Optional[str] = Field(
        default=None,
        description="Timestamp ID of posted welcome message",
    )
    is_mock: bool = Field(default=False, description="Flag indicating if mock mode was used")


class Agent2Result(BaseModel):
    """Complete execution outcome of Agent 2 Communication Agent."""

    correlation_id: str = Field(description="Deal correlation ID linking all agent actions")
    status: Literal["SUCCESS", "SKIPPED_UNCONFIRMED", "FAILED"] = Field(description="Agent 2 final state")
    channel_payload: Optional[SlackChannelPayload] = Field(
        default=None,
        description="Generated Slack channel configuration",
    )
    provisioning_result: Optional[SlackProvisioningResult] = Field(
        default=None,
        description="Slack provisioning details",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if provisioning failed",
    )


class OverdueEscalationTarget(str, Enum):
    """Escalation recipient tiers for overdue Rocketlane onboarding tasks."""

    PROJECT_MANAGER = "PROJECT_MANAGER"
    PROJECT_OWNER = "PROJECT_OWNER"


class OverdueAlertResult(BaseModel):
    """Standardized representation of a Rocketlane overdue task escalation alert."""

    task_id: str = Field(description="Unique Rocketlane task ID")
    task_name: str = Field(description="Name or title of the task")
    project_id: str = Field(description="Rocketlane project ID")
    days_overdue: int = Field(ge=0, description="Number of days elapsed past due date")
    target: Optional[OverdueEscalationTarget] = Field(default=None, description="Escalation recipient")
    alert_triggered: bool = Field(default=False, description="Flag indicating if SLA rule fired")
    recipient_label: str = Field(default="", description="Recipient display name or email")
    alert_message: str = Field(default="", description="Escalation notification message")


class DataMigrationSignOffPayload(BaseModel):
    """Input payload representing customer data verification sign-off submitted for milestone gating."""

    project_id: str = Field(description="Unique Rocketlane project ID")
    task_id: str = Field(description="Unique Data Migration task ID")
    task_name: Optional[str] = Field(default=None, description="Optional name or title of the onboarding task")
    customer_name: str = Field(min_length=1, description="Customer company name")
    records_migrated: int = Field(ge=0, description="Total number of records imported into NovaCRM")
    records_verified: int = Field(ge=0, description="Total number of records verified by customer")
    customer_sign_off_confirmed: bool = Field(description="Flag confirming customer reviewed and signed off")
    sign_off_contact_email: EmailStr = Field(description="Email of customer lead who authorized sign-off")
    discrepancy_notes: Optional[str] = Field(default=None, description="Notes on any discrepancies or errors")
    downstream_task_id: Optional[str] = Field(default=None, description="Optional downstream Configuration task ID to unlock")


class DataQAGatekeeperResult(BaseModel):
    """Complete execution outcome of Agent 3 Data QA Gatekeeper enforcing migration verification."""

    correlation_id: str = Field(description="Deal correlation ID linking all agent actions")
    project_id: str = Field(description="Rocketlane project ID")
    status: Literal["VERIFIED_UNLOCKED", "REJECTED_BLOCKED", "ESCALATED_DISCREPANCY"] = Field(
        description="Gatekeeper outcome state"
    )
    is_configuration_unlocked: bool = Field(description="Flag indicating if Configuration phase is unlocked")
    records_migrated: int = Field(description="Migrated records count")
    records_verified: int = Field(description="Verified records count")
    discrepancy_count: int = Field(default=0, description="Count of mismatched or unverified records")
    csm_alert_sent: bool = Field(default=False, description="Flag indicating if CSM was notified of blocker")
    audit_rationale: str = Field(description="Explicit explanation of gatekeeper decision")
    task_id: Optional[str] = Field(default=None, description="Target task ID evaluated")
    task_name: Optional[str] = Field(default=None, description="Target task name evaluated")
    live_comment_posted: bool = Field(default=False, description="Flag indicating if comment was posted to Rocketlane")
