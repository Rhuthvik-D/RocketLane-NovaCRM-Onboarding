# Define custom exceptions to handle specific error conditions across the pipeline.  # What: Module header; Why: Groups domain-specific error classes for clean handling.
from typing import Any, Optional  # What: Import typing utilities; Why: Allows type hints on optional details and flexible payloads.


class NovaCRMError(Exception):  # What: Base exception class; Why: Allows catching any custom error raised by the onboarding pipeline.
    """Base exception for all NovaCRM onboarding workflow errors."""  # What: Docstring; Why: Documents purpose of the base exception.
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None) -> None:  # What: Constructor; Why: Stores error message and context.
        super().__init__(message)  # What: Call parent Exception constructor; Why: Standard Python error propagation.
        self.message: str = message  # What: Store readable error message; Why: Enables formatted logging and assertions.
        self.details: dict[str, Any] = details or {}  # What: Store structured metadata context; Why: Aids debugging and audit logs.


class MissingFieldError(NovaCRMError):  # What: Exception for missing mandatory schema fields; Why: Fulfills guardrail to never guess missing data.
    """Raised when an inbound email omits critical fields like customer_name or ae_name."""  # What: Docstring; Why: Clarifies zero-assumption trigger.
    pass  # What: Pass statement; Why: Inherits all functionality from NovaCRMError without changes.


class TelephonyError(NovaCRMError):  # What: Exception for Voice AI failures or ambiguities; Why: Enforces human escalation when voice calls fail.
    """Raised when the Voice AI outbound call fails, is unanswered, or returns an ambiguous tier."""  # What: Docstring; Why: Explains voice guardrail failure.
    pass  # What: Pass statement; Why: Inherits error handling logic from NovaCRMError.


class RocketlaneAPIError(NovaCRMError):  # What: Exception for Rocketlane API communication failures; Why: Distinguishes upstream API errors.
    """Raised when the Rocketlane REST API returns an unexpected error (e.g., HTTP 500)."""  # What: Docstring; Why: Used to trigger retry logic.
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[dict[str, Any]] = None) -> None:  # What: Init with status code; Why: Captures HTTP status.
        super().__init__(message, details)  # What: Call super init; Why: Initializes base message and details dict.
        self.status_code: Optional[int] = status_code  # What: Assign HTTP status code; Why: Enables status-specific retry or abort decisions.


class DuplicateProjectError(NovaCRMError):  # What: Exception for duplicate project creation attempts; Why: Enforces idempotency guardrails.
    """Raised when a deal has already been provisioned in Rocketlane to prevent duplicate projects."""  # What: Docstring; Why: Explains duplicate guardrail.
    pass  # What: Pass statement; Why: Inherits standard error behaviors.


class StageGateError(NovaCRMError):  # What: Exception for unverified milestone transitions; Why: Prevents advancing past Data Migration without sign-off.
    """Raised when a task or milestone transition fails verification criteria (e.g., Data QA)."""  # What: Docstring; Why: Explains gatekeeping logic.
    pass  # What: Pass statement; Why: Inherits base class error attributes.


class SlackAPIError(NovaCRMError):  # What: Exception for Slack API errors; Why: Captures Slack Web API rejections or transport failures.
    """Raised when Slack channel provisioning, topic setting, or message dispatch fails."""  # What: Docstring; Why: Explains Slack error purpose.
    def __init__(self, message: str, error_code: Optional[str] = None, details: Optional[dict[str, Any]] = None) -> None:  # What: Init with error code; Why: Stores Slack API error string.
        super().__init__(message, details)  # What: Call parent constructor; Why: Sets base message and details.
        self.error_code: Optional[str] = error_code  # What: Store error code; Why: Allows programmatic handling of specific Slack errors like 'name_taken'.
