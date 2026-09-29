# Configuration loader module using Pydantic Settings for runtime environment variable management.  # What: Module header; Why: Centralizes configuration.
from pathlib import Path  # What: Import Path class; Why: Resolves cross-platform file system paths safely.
from pydantic import Field  # What: Import Field helper; Why: Configures default values and descriptions on settings fields.
from pydantic_settings import BaseSettings, SettingsConfigDict  # What: Import BaseSettings and config dict; Why: Parses .env files into typed variables.


class Settings(BaseSettings):  # What: Settings model inheriting from BaseSettings; Why: Enforces typed environment variable parsing.
    """Application settings and API credentials for NovaCRM onboarding automation."""  # What: Docstring; Why: Describes settings model purpose.

    # Model configuration specifying the .env file path and encoding rules
    model_config = SettingsConfigDict(  # What: Configure Pydantic settings behavior; Why: Points to the local environment file.
        env_file=".env",  # What: Point to .env file in workspace root; Why: Automatically loads secrets without manual parsing.
        env_file_encoding="utf-8",  # What: Set UTF-8 encoding; Why: Ensures special characters in keys or tokens load cleanly.
        extra="ignore"  # What: Ignore unexpected variables; Why: Prevents crashes if unrelated environment variables are present.
    )  # What: End of model_config definition; Why: Finalizes settings configuration dictionary.

    # Rocketlane API credentials and runtime flags (loaded from .env)
    rocketlane_api_key: str = Field(default="", description="Rocketlane REST API key")  # What: Empty default; Why: Must be supplied via .env.
    rocketlane_base_url: str = Field(default="https://api.rocketlane.com/api/1.0", description="Base URL for Rocketlane")  # What: Default URL; Why: Upstream endpoint.
    rocketlane_mock_mode: bool = Field(default=False, description="When true, uses simulated Rocketlane responses")  # What: Mock flag; Why: Toggles sandbox mode.
    rocketlane_owner_email: str = Field(default="", description="Default Rocketlane project owner email")  # What: Empty default; Why: Must be supplied via .env.
    rocketlane_enterprise_template_id: str = Field(default="5000000095997", description="Template ID for Enterprise onboarding")  # What: Enterprise template ID; Why: Loaded from .env.
    rocketlane_growth_template_id: str = Field(default="5000000096288", description="Template ID for Growth onboarding")  # What: Growth template ID; Why: Loaded from .env.

    # Voice AI Telephony configuration for live AE verification call (loaded from .env)
    voice_ai_api_key: str = Field(default="", description="Voice AI platform API token")  # What: Empty default; Why: Must be supplied via .env.
    voice_ai_provider: str = Field(default="vapi", description="Provider identifier (vapi, bland, or retell)")  # What: Provider name; Why: Selects voice adapter.
    voice_ai_agent_id: str = Field(default="", description="Assistant ID for AE call")  # What: Empty default; Why: Must be supplied via .env.
    voice_ai_phone_number_id: str = Field(default="", description="Vapi outbound phone number ID")  # What: Empty default; Why: Must be supplied via .env.
    voice_ai_assume_enterprise: bool = Field(default=True, description="When true, assumes AE confirmed Enterprise plan")  # What: Enterprise assumption flag; Why: Automates voice verification while provider is finalized.
    voice_ai_simulated_tier: str = Field(default="ENTERPRISE", description="Simulated plan tier for automated testing (ENTERPRISE or GROWTH)")  # What: Configurable simulated tier; Why: Single-point switch between Enterprise and Growth in .env.

    # Slack configuration for customer onboarding channel provisioning (loaded from .env)
    slack_bot_token: str = Field(default="", description="Slack bot token for workspace actions")  # What: Empty default; Why: Must be supplied via .env.
    slack_mock_mode: bool = Field(default=False, description="When true, simulates Slack channel creation")  # What: Slack mock flag; Why: Toggles Slack sandbox.

    # Gmail CS Inbox configuration for inbound deal notifications (loaded from .env)
    gmail_user: str = Field(default="rhuthvik8@gmail.com", description="Gmail address for CS inbox")  # What: CS inbox email; Why: Inbound destination for AE deal emails.
    gmail_app_password: str = Field(default="", description="Google App Password for IMAP access")  # What: Empty default; Why: Authenticates IMAP connection to Gmail.
    gmail_poll_interval: int = Field(default=15, description="Polling interval in seconds")  # What: Poll interval; Why: Controls loop cadence for checking new emails.
    gmail_subject_filter: str = Field(default="New Deal", description="Subject filter keyword")  # What: Subject keyword; Why: Filters deal notifications from other inbox traffic.

    # Observability and audit logging settings
    audit_log_file_path: Path = Field(default=Path("logs/audit_trail.jsonl"), description="Path for audit log JSONL file")  # What: Log path; Why: Audit storage.
    escalation_log_file_path: Path = Field(default=Path("logs/escalation_tickets.jsonl"), description="Path for dedicated escalation tickets JSONL file")  # What: Escalation log path; Why: Dedicated store for human review tickets.
    log_level: str = Field(default="INFO", description="Console logging verbosity level")  # What: Log level string; Why: Controls terminal verbosity.


# Singleton instance of settings for application-wide access
settings: Settings = Settings()  # What: Instantiate settings object; Why: Provides global access to validated settings.
