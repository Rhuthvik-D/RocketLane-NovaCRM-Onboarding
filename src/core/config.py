"""Configuration management module for NovaCRM onboarding automation.

Utilizes Pydantic Settings to validate and expose strongly-typed runtime
environment variables, API credentials, service toggles, and file paths
from local `.env` files or runtime process environments.
"""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and API credentials for NovaCRM onboarding automation.

    Reads configuration from the project `.env` file (UTF-8 encoded) with
    strict fallback defaults. Ignores unrelated extra environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Rocketlane API credentials and runtime flags
    rocketlane_api_key: str = Field(default="", description="Rocketlane REST API key")
    rocketlane_base_url: str = Field(default="https://api.rocketlane.com/api/1.0", description="Base URL for Rocketlane")
    rocketlane_mock_mode: bool = Field(default=False, description="When true, uses simulated Rocketlane responses")
    rocketlane_owner_email: str = Field(default="", description="Default Rocketlane project owner email")
    rocketlane_enterprise_template_id: str = Field(default="5000000095997", description="Template ID for Enterprise onboarding")
    rocketlane_growth_template_id: str = Field(default="5000000096288", description="Template ID for Growth onboarding")

    # Voice AI Telephony configuration for live AE verification call
    voice_ai_api_key: str = Field(default="", description="Voice AI platform API token")
    voice_ai_provider: str = Field(default="vapi", description="Provider identifier (vapi, bland, or retell)")
    voice_ai_agent_id: str = Field(default="", description="Assistant ID for AE call")
    voice_ai_phone_number_id: str = Field(default="", description="Vapi outbound phone number ID")
    voice_ai_assume_enterprise: bool = Field(default=True, description="When true, assumes AE confirmed Enterprise plan")
    voice_ai_simulated_tier: str = Field(default="ENTERPRISE", description="Simulated plan tier for automated testing (ENTERPRISE or GROWTH)")

    # Slack configuration for customer onboarding channel provisioning
    slack_bot_token: str = Field(default="", description="Slack bot token for workspace actions")
    slack_mock_mode: bool = Field(default=False, description="When true, simulates Slack channel creation")

    # Gmail CS Inbox configuration for inbound deal notifications
    gmail_user: str = Field(default="rhuthvik8@gmail.com", description="Gmail address for CS inbox")
    gmail_app_password: str = Field(default="", description="Google App Password for IMAP access")
    gmail_poll_interval: int = Field(default=15, description="Polling interval in seconds")
    gmail_subject_filter: str = Field(default="New Deal", description="Subject filter keyword")

    # Observability and audit logging settings
    audit_log_file_path: Path = Field(default=Path("logs/audit_trail.jsonl"), description="Path for audit log JSONL file")
    escalation_log_file_path: Path = Field(default=Path("logs/escalation_tickets.jsonl"), description="Path for dedicated escalation tickets JSONL file")
    log_level: str = Field(default="INFO", description="Console logging verbosity level")


# Singleton instance of settings for application-wide access
settings: Settings = Settings()
