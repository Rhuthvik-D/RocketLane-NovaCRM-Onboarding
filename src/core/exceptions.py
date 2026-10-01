"""Domain-specific exception hierarchy for the NovaCRM onboarding automation system.

This module defines specialized exception classes used across the pipeline to represent
distinct operational failure modes, including missing inbound data, telephony issues,
upstream API communication failures, idempotency conflicts, and stage-gate violations.
"""

from typing import Any, Optional


class NovaCRMError(Exception):
    """Base exception class for all errors originating within the NovaCRM pipeline.

    Attributes:
        message (str): Human-readable explanation of the error.
        details (dict[str, Any]): Structured contextual metadata providing debugging insight.
    """

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None) -> None:
        """Initializes a new NovaCRMError instance.

        Args:
            message: Descriptive error message.
            details: Optional dictionary containing execution context or diagnostic data.
        """
        super().__init__(message)
        self.message: str = message
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:
        """Returns the string representation of the error."""
        return self.message


class MissingFieldError(NovaCRMError):
    """Raised when an inbound deal notification email omits mandatory schema fields.

    This exception enforces the zero-guesswork guardrail when fields such as customer_name,
    customer_contact_email, ae_name, or ae_phone are missing or whitespace-only.
    """
    pass


class TelephonyError(NovaCRMError):
    """Raised when the Voice AI outbound telephony verification encounters a failure.

    Triggers include network transport errors, unanswered calls, carrier timeouts,
    or ambiguous spoken responses from the Account Executive.
    """
    pass


class RocketlaneAPIError(NovaCRMError):
    """Raised when an interaction with the Rocketlane REST API fails.

    Attributes:
        status_code (Optional[int]): HTTP response status code (e.g., 500, 503, 400).
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[dict[str, Any]] = None
    ) -> None:
        """Initializes a RocketlaneAPIError with HTTP status code support.

        Args:
            message: Descriptive error message.
            status_code: The HTTP status code returned by the Rocketlane API.
            details: Additional payload or error response details.
        """
        super().__init__(message, details)
        self.status_code: Optional[int] = status_code


class DuplicateProjectError(NovaCRMError):
    """Raised when an attempt is made to provision a project that already exists.

    Enforces idempotency constraints to guarantee that duplicate deal emails
    or concurrent submissions never spawn redundant customer workspaces.
    """
    pass


class StageGateError(NovaCRMError):
    """Raised when an onboarding milestone transition fails verification criteria.

    Used by Agent 3 (Data QA Gatekeeper) to strictly block downstream phases
    (such as System Configuration) until customer sign-off and 100% record
    parity are confirmed.
    """
    pass


class SlackAPIError(NovaCRMError):
    """Raised when an interaction with the Slack Web API fails.

    Attributes:
        error_code (Optional[str]): Slack API specific error code (e.g., 'name_taken').
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None
    ) -> None:
        """Initializes a SlackAPIError with Slack-specific error code tracking.

        Args:
            message: Descriptive error message.
            error_code: Slack API error identifier returned in response JSON.
            details: Full API response dictionary for debugging.
        """
        super().__init__(message, details)
        self.error_code: Optional[str] = error_code
