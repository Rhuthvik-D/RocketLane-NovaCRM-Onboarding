# Package initializer for external integration services and API clients.  # What: Module header; Why: Marks src/services as Python package.
"""External client integrations for NovaCRM onboarding."""  # What: Docstring; Why: Describes package scope.
from src.services.rocketlane_client import RocketlaneClient, rocketlane_client  # What: Export Rocketlane client; Why: Clean package imports.
from src.services.slack_client import SlackClient, slack_client  # What: Export Slack client; Why: Clean package imports.
from src.services.voice_ai_client import VoiceAIClient, voice_ai_client  # What: Export Voice AI client; Why: Clean package imports.

__all__ = [  # What: Package exports list; Why: Restricts public API of src.services.
    "RocketlaneClient",  # What: RocketlaneClient class export; Why: Allows instantiating custom client.
    "rocketlane_client",  # What: rocketlane_client singleton export; Why: Default shared instance.
    "SlackClient",  # What: SlackClient class export; Why: Allows instantiating custom client.
    "slack_client",  # What: slack_client singleton export; Why: Default shared instance.
    "VoiceAIClient",  # What: VoiceAIClient class export; Why: Allows instantiating custom client.
    "voice_ai_client",  # What: voice_ai_client singleton export; Why: Default shared instance.
]  # What: End of exports list; Why: Completes package interface.
