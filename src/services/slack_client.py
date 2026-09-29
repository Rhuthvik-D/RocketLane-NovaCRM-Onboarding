# Resilient Slack API client for automated customer onboarding channel provisioning and messaging.  # What: Module header; Why: Integrates with Slack Web API with mock mode support.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps and mock message IDs.
import logging  # What: Import standard logging; Why: Emits debug and warning messages for Slack operations.
import re  # What: Import regular expressions; Why: Sanitizes channel names and handles error responses.
from typing import Any, Optional  # What: Import typing utilities; Why: Type annotations for payloads and headers.
import httpx  # What: Import httpx; Why: Modern HTTP client for synchronous Slack Web API requests.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits every Slack API call and state transition.
from src.core.config import settings  # What: Import settings; Why: Retrieves Slack bot token and mock mode flag.
from src.core.exceptions import SlackAPIError  # What: Import SlackAPIError; Why: Domain exception for Slack API rejections.
from src.models.schemas import (  # What: Import domain models; Why: Type safety on Slack payloads and results.
    AuditActionStatus,  # What: Audit status enum; Why: Records audit action outcomes.
    SlackChannelPayload,  # What: Slack channel configuration model; Why: Encapsulates channel provisioning parameters.
    SlackProvisioningResult  # What: Slack provisioning result model; Why: Standardizes Slack provisioning response.
)  # What: End of schema imports; Why: Completes domain model dependencies.


_logger = logging.getLogger("slack_client")  # What: Instantiate module logger; Why: Logs Slack events to console.


class SlackClient:  # What: Slack client class; Why: Encapsulates all Slack Web API communication and simulation.
    """Client for provisioning customer Slack channels, setting topics, and posting welcome messages."""  # What: Docstring; Why: Explains Slack client role.

    SLACK_API_BASE_URL: str = "https://slack.com/api"  # What: Slack API base endpoint; Why: Standard endpoint prefix for all Slack Web API methods.

    def __init__(  # What: Constructor method; Why: Initializes Slack bot token, mock mode flag, and HTTP client.
        self,  # What: Self instance; Why: Accesses class members.
        token: Optional[str] = None,  # What: Optional token argument; Why: Overrides settings if provided.
        mock_mode: Optional[bool] = None  # What: Optional mock mode flag; Why: Toggles simulation mode for tests.
    ) -> None:  # What: Return type; Why: Constructor returns None.
        self.token: str = token or settings.slack_bot_token  # What: Store Slack bot token; Why: Authenticates requests via Bearer token.
        self.mock_mode: bool = mock_mode if mock_mode is not None else settings.slack_mock_mode  # What: Store mock flag; Why: Controls simulation behavior.
        self._created_channels: dict[str, dict[str, Any]] = {}  # What: In-memory channel registry; Why: Stores created channels during mock execution.
        self._client: httpx.Client = httpx.Client(timeout=15.0)  # What: Initialize httpx client; Why: Reusable HTTP client with 15s timeout.

    def _get_headers(self) -> dict[str, str]:  # What: Private helper method; Why: Formats standard authorization and content-type headers.
        """Builds HTTP request headers required for Slack Web API requests."""  # What: Docstring; Why: Explains header construction.
        return {  # What: Return headers dictionary; Why: Supplies bearer authentication and json content type.
            "Authorization": f"Bearer {self.token}",  # What: Bearer authorization header; Why: Authenticates bot user with Slack workspace.
            "Content-Type": "application/json; charset=utf-8"  # What: JSON content type header; Why: Specifies JSON payload encoding.
        }  # What: End of headers dictionary; Why: Complete headers.

    def create_channel(  # What: Channel creation method; Why: Provisions new private or public Slack channel for customer onboarding.
        self,  # What: Self instance; Why: Accesses token and mock mode.
        channel_name: str,  # What: Desired channel name string; Why: Human-readable handle e.g. csm-ent-acme.
        is_private: bool = True,  # What: Channel privacy boolean; Why: Onboarding channels default to private for customer confidentiality.
        correlation_id: Optional[str] = None  # What: Optional deal correlation ID; Why: Connects creation to deal audit trail.
    ) -> dict[str, Any]:  # What: Return type; Why: Returns Slack API channel dictionary.
        """Creates a Slack channel or returns mock representation if mock mode is active."""  # What: Docstring; Why: Explains method contract.
        clean_name = channel_name.lstrip("#").strip().lower()  # What: Strip leading hash and whitespace; Why: Slack API rejects leading hash in channel names.

        # Simulated test mode branch
        if self.mock_mode:  # What: Check if mock mode is active; Why: Bypasses live Slack API calls during automated tests.
            channel_id = f"C_MOCK_{abs(hash(clean_name)) % 1000000:06d}"  # What: Generate deterministic mock channel ID; Why: Stable ID for testing.
            channel_data = {  # What: Construct mock channel dictionary; Why: Matches Slack conversations.create response schema.
                "id": channel_id,  # What: Mock channel ID; Why: Unique identifier.
                "name": clean_name,  # What: Clean channel name; Why: Name handle.
                "is_private": is_private  # What: Privacy flag; Why: Preserves privacy setting.
            }  # What: End of mock channel dictionary; Why: Complete mock response.
            self._created_channels[clean_name] = channel_data  # What: Store in registry; Why: Allows subsequent mock lookups.
            _logger.info(f"[MOCK] Provisioned Slack channel '#{clean_name}' (ID: {channel_id})")  # What: Log mock event; Why: Terminal visibility.
            return {"ok": True, "channel": channel_data}  # What: Return success response; Why: Fulfills Slack response contract.

        # Live Slack Web API branch
        url = f"{self.SLACK_API_BASE_URL}/conversations.create"  # What: Slack channel creation endpoint; Why: Official API endpoint.
        payload = {"name": clean_name, "is_private": is_private}  # What: Request payload; Why: Parameters for channel creation.

        try:  # What: Try block; Why: Catches network transport errors.
            response = self._client.post(url, headers=self._get_headers(), json=payload)  # What: Dispatch POST request; Why: Creates channel on Slack workspace.
            data = response.json()  # What: Parse JSON response; Why: Inspects Slack API success flag.
        except Exception as exc:  # What: Catch HTTP or network exceptions; Why: Normalizes transport failures to domain error.
            raise SlackAPIError(f"Network error communicating with Slack API: {exc}") from exc  # What: Raise domain exception; Why: Consistent error handling.

        if not data.get("ok"):  # What: Check if Slack returned ok=False; Why: Inspects Slack API rejection codes.
            error_code = data.get("error", "unknown_error")  # What: Extract Slack error string; Why: Identifies failure reason.
            if error_code == "name_taken":  # What: Check if error is name collision; Why: Channel name already exists in workspace.
                _logger.warning(f"Slack channel name '{clean_name}' is taken. Appending timestamp suffix.")  # What: Log collision warning; Why: Debugging visibility.
                suffix = f"-{int(datetime.now().timestamp()) % 1000:03d}"  # What: Generate 4-char unique suffix; Why: Resolves name collision.
                fallback_name = f"{clean_name[:80 - len(suffix)]}{suffix}"  # What: Construct truncated fallback name; Why: Adheres to 80-char limit.
                return self.create_channel(fallback_name, is_private=is_private, correlation_id=correlation_id)  # What: Recursive call with fallback; Why: Recovers from name collision.
            raise SlackAPIError(f"Slack API rejected channel creation: {error_code}", error_code=error_code, details=data)  # What: Raise SlackAPIError; Why: Non-recoverable Slack error.

        return data  # What: Return Slack response dictionary; Why: Contains live channel ID and metadata.

    def set_channel_topic(  # What: Topic setting method; Why: Embeds Rocketlane project workspace link into Slack channel header.
        self,  # What: Self instance; Why: Accesses token and mock mode.
        channel_id: str,  # What: Target Slack channel ID; Why: Identifies channel to update.
        topic: str,  # What: Topic text string; Why: Embedded Rocketlane URL and plan tier.
        correlation_id: Optional[str] = None  # What: Optional correlation ID; Why: Connects action to deal audit trail.
    ) -> dict[str, Any]:  # What: Return type; Why: Returns Slack API topic response.
        """Sets the topic of a Slack channel with the Rocketlane project URL."""  # What: Docstring; Why: Explains method purpose.
        if self.mock_mode:  # What: Check if mock mode is active; Why: Bypasses live Slack API calls during automated tests.
            _logger.info(f"[MOCK] Set topic on channel '{channel_id}': {topic}")  # What: Log mock topic event; Why: Terminal visibility.
            return {"ok": True, "topic": topic}  # What: Return mock success; Why: Fulfills Slack response contract.

        url = f"{self.SLACK_API_BASE_URL}/conversations.setTopic"  # What: Slack setTopic endpoint URL; Why: Updates channel topic.
        payload = {"channel": channel_id, "topic": topic}  # What: Request payload; Why: Target channel and new topic string.

        try:  # What: Try block; Why: Catches transport errors.
            response = self._client.post(url, headers=self._get_headers(), json=payload)  # What: Dispatch POST request; Why: Sets topic on Slack channel.
            data = response.json()  # What: Parse JSON response; Why: Checks success status.
        except Exception as exc:  # What: Catch network exceptions; Why: Normalizes transport failures.
            raise SlackAPIError(f"Network error setting Slack channel topic: {exc}") from exc  # What: Raise domain error; Why: Consistent error reporting.

        if not data.get("ok"):  # What: Check if Slack returned ok=False; Why: Inspects rejection.
            error_code = data.get("error", "unknown_error")  # What: Extract Slack error string; Why: Identifies failure reason.
            raise SlackAPIError(f"Slack API rejected setTopic: {error_code}", error_code=error_code, details=data)  # What: Raise domain error; Why: Escalates API rejection.

        return data  # What: Return Slack response dictionary; Why: Contains updated topic metadata.

    def post_welcome_message(  # What: Message posting method; Why: Dispatches personalized kickoff welcome message to customer channel.
        self,  # What: Self instance; Why: Accesses token and mock mode.
        channel_id: str,  # What: Target Slack channel ID; Why: Destination for message.
        message_text: str,  # What: Personalized markdown message; Why: Content tailored to customer tier and onboarding model.
        correlation_id: Optional[str] = None  # What: Optional correlation ID; Why: Connects action to deal audit trail.
    ) -> dict[str, Any]:  # What: Return type; Why: Returns Slack API postMessage response.
        """Posts a personalized onboarding welcome message into the customer Slack channel."""  # What: Docstring; Why: Explains method purpose.
        if self.mock_mode:  # What: Check if mock mode is active; Why: Bypasses live Slack API calls during automated tests.
            mock_ts = f"{int(datetime.now().timestamp())}.{abs(hash(message_text)) % 10000:04d}"  # What: Generate mock timestamp; Why: Simulates Slack message ts.
            _logger.info(f"[MOCK] Posted welcome message to channel '{channel_id}' (ts: {mock_ts})")  # What: Log mock message event; Why: Terminal visibility.
            return {"ok": True, "ts": mock_ts, "message": {"text": message_text}}  # What: Return mock success; Why: Matches Slack chat.postMessage response.

        url = f"{self.SLACK_API_BASE_URL}/chat.postMessage"  # What: Slack postMessage endpoint URL; Why: Posts chat messages.
        payload = {"channel": channel_id, "text": message_text, "mrkdwn": True}  # What: Request payload; Why: Channel, text, and markdown formatting flag.

        try:  # What: Try block; Why: Catches transport errors.
            response = self._client.post(url, headers=self._get_headers(), json=payload)  # What: Dispatch POST request; Why: Posts message to live Slack workspace.
            data = response.json()  # What: Parse JSON response; Why: Checks success status.
        except Exception as exc:  # What: Catch network exceptions; Why: Normalizes transport failures.
            raise SlackAPIError(f"Network error posting Slack welcome message: {exc}") from exc  # What: Raise domain error; Why: Consistent error reporting.

        if not data.get("ok"):  # What: Check if Slack returned ok=False; Why: Inspects rejection.
            error_code = data.get("error", "unknown_error")  # What: Extract Slack error string; Why: Identifies failure reason.
            raise SlackAPIError(f"Slack API rejected postMessage: {error_code}", error_code=error_code, details=data)  # What: Raise domain error; Why: Escalates API rejection.

        return data  # What: Return Slack response dictionary; Why: Contains message ts and delivery status.

    def invite_workspace_members(  # What: Workspace member invitation helper; Why: Adds human team members to the new channel so it appears in their sidebar.
        self,  # What: Self instance; Why: Accesses Slack client and token.
        channel_id: str,  # What: Target channel ID; Why: Channel destination for invite.
        correlation_id: Optional[str] = None  # What: Optional correlation ID; Why: Connects action to audit log.
    ) -> list[str]:  # What: Return type; Why: Returns list of successfully invited user IDs.
        """Discovers human workspace members from the primary public channel and invites them to the onboarding channel."""  # What: Docstring; Why: Explains auto-invitation logic.
        if self.mock_mode:  # What: Check mock mode; Why: Skips live Slack API in tests.
            _logger.info(f"[MOCK] Invited default workspace members to channel '{channel_id}'.")  # What: Log mock event; Why: Terminal visibility.
            return ["U_MOCK_HUMAN"]  # What: Return mock user ID; Why: Verified simulation.

        try:  # What: Try block; Why: Catches Slack API exceptions during member discovery and invite.
            auth_resp = self._client.post(f"{self.SLACK_API_BASE_URL}/auth.test", headers=self._get_headers())  # What: Dispatch auth.test; Why: Finds bot user ID.
            bot_user_id = auth_resp.json().get("user_id", "")  # What: Extract bot ID; Why: Filter out bot itself.
            conv_resp = self._client.get(f"{self.SLACK_API_BASE_URL}/conversations.list", headers=self._get_headers(), params={"types": "public_channel"})  # What: Query public channels; Why: Finds general workspace channel.
            channels = conv_resp.json().get("channels", [])  # What: Extract channel list; Why: Channel candidates.
            if not channels:  # What: Check if no public channels found; Why: Safety check.
                return []  # What: Return empty list; Why: Cannot discover members.

            gen_chan = next((c["id"] for c in channels if c.get("is_general") or "general" in c.get("name", "") or "all-" in c.get("name", "")), channels[0]["id"])  # What: Select primary channel; Why: Contains workspace members.
            mem_resp = self._client.get(f"{self.SLACK_API_BASE_URL}/conversations.members", headers=self._get_headers(), params={"channel": gen_chan})  # What: Query members; Why: Retrieves member IDs.
            members = mem_resp.json().get("members", [])  # What: Extract member IDs; Why: Candidate users to invite.

            human_members = [m for m in members if m and m != bot_user_id]  # What: Filter out bot ID; Why: Invites humans only.
            if not human_members:  # What: Check if no human members; Why: Safety check.
                return []  # What: Return empty list; Why: Nothing to invite.

            invite_resp = self._client.post(  # What: Dispatch conversations.invite; Why: Adds humans to the newly provisioned channel.
                f"{self.SLACK_API_BASE_URL}/conversations.invite",  # What: Invite endpoint; Why: Adds members to channel.
                headers=self._get_headers(),  # What: Auth headers; Why: Authenticates bot.
                json={"channel": channel_id, "users": ",".join(human_members)}  # What: JSON payload; Why: Target channel and user IDs.
            )  # What: End of invite POST; Why: Dispatches invite.
            invite_data = invite_resp.json()  # What: Parse JSON; Why: Inspects response.
            if invite_data.get("ok"):  # What: Check if invite succeeded; Why: Confirms addition.
                _logger.info(f"Successfully invited workspace members {human_members} to Slack channel '{channel_id}'.")  # What: Log success; Why: Terminal view.
            else:  # What: Else branch; Why: Handles already_in_channel or other warnings gracefully.
                _logger.info(f"Notice on member invite for '{channel_id}': {invite_data.get('error', 'ok')}")  # What: Log notice; Why: Visibility.

            return human_members  # What: Return invited members; Why: Confirms invited IDs.
        except Exception as exc:  # What: Catch exceptions; Why: Ensures invite failure does not crash channel provisioning.
            _logger.warning(f"Could not auto-invite workspace members to channel '{channel_id}': {exc}")  # What: Log warning; Why: Debugging info.
            return []  # What: Return empty list; Why: Safe recovery.

    def provision_customer_channel(  # What: High-level orchestrator method; Why: Coordinates channel creation, topic setting, and welcome message dispatch.
        self,  # What: Self instance; Why: Accesses client methods.
        payload: SlackChannelPayload,  # What: Typed configuration payload; Why: Provides channel name, topic, and welcome message.
        correlation_id: str  # What: Deal tracking correlation ID; Why: Connects all Slack provisioning actions to deal audit trail.
    ) -> SlackProvisioningResult:  # What: Return type; Why: Returns strongly-typed SlackProvisioningResult.
        """Coordinates full Slack provisioning: channel creation, topic embedding, and kickoff message dispatch."""  # What: Docstring; Why: Explains method contract.

        # Step 1: Create the Slack channel
        audit_logger.log_action(  # What: Record audit log; Why: Marks start of Slack channel provisioning.
            correlation_id=correlation_id,  # What: Deal tracking ID; Why: Connects log to deal.
            agent_name="SlackClient",  # What: Acting agent name; Why: Identifies Slack client subsystem.
            action="slack_channel_creation_started",  # What: Action name; Why: Documents creation start.
            inputs={"channel_name": payload.channel_name, "is_private": payload.is_private},  # What: Inputs; Why: Audited inputs.
            outputs={"mock_mode": self.mock_mode},  # What: Outputs; Why: Audited mode.
            decision_rationale=f"Initiating Slack channel provisioning for handle '{payload.channel_name}'.",  # What: Rationale; Why: Documents reason.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Step initiated.
        )  # What: End of audit logging; Why: Saved to trail.

        create_resp = self.create_channel(payload.channel_name, is_private=payload.is_private, correlation_id=correlation_id)  # What: Create channel; Why: Obtains channel ID.
        channel_id = str(create_resp["channel"]["id"])  # What: Extract channel ID; Why: Identifier for subsequent calls.
        actual_name = str(create_resp["channel"].get("name", payload.channel_name))  # What: Extract actual channel name; Why: Captures fallback name if suffixed.

        # Step 2: Set the channel topic with the Rocketlane project URL
        self.set_channel_topic(channel_id, payload.topic, correlation_id=correlation_id)  # What: Set channel topic; Why: Embeds Rocketlane link.
        audit_logger.log_action(  # What: Record audit log; Why: Documents topic setting.
            correlation_id=correlation_id,  # What: Correlation ID; Why: Connects log to deal.
            agent_name="SlackClient",  # What: Acting agent name; Why: Identifies Slack client.
            action="slack_topic_set",  # What: Action name; Why: Documents topic set.
            inputs={"channel_id": channel_id, "topic": payload.topic},  # What: Inputs; Why: Audited inputs.
            outputs={"channel_id": channel_id, "topic_set": True},  # What: Outputs; Why: Audited outputs.
            decision_rationale=f"Embedded Rocketlane project URL into Slack channel topic for immediate customer access.",  # What: Rationale; Why: Documents reason.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Step succeeded.
        )  # What: End of audit logging; Why: Saved to trail.

        # Step 3: Post the personalized onboarding welcome message
        msg_resp = self.post_welcome_message(channel_id, payload.welcome_message, correlation_id=correlation_id)  # What: Post welcome message; Why: Delivers kickoff instructions.
        msg_ts = str(msg_resp.get("ts", ""))  # What: Extract message timestamp ID; Why: Proof of message delivery.
        audit_logger.log_action(  # What: Record audit log; Why: Documents welcome message posting.
            correlation_id=correlation_id,  # What: Correlation ID; Why: Connects log to deal.
            agent_name="SlackClient",  # What: Acting agent name; Why: Identifies Slack client.
            action="slack_welcome_message_posted",  # What: Action name; Why: Documents message posted.
            inputs={"channel_id": channel_id, "message_preview": payload.welcome_message[:120]},  # What: Inputs preview; Why: Audited inputs.
            outputs={"channel_id": channel_id, "message_ts": msg_ts},  # What: Outputs; Why: Audited outputs.
            decision_rationale="Dispatched personalized onboarding welcome message tailored to customer plan tier.",  # What: Rationale; Why: Documents reason.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Step succeeded.
        )  # What: End of audit logging; Why: Saved to trail.

        # Step 4: Auto-invite workspace members so channel pops up directly in left sidebar
        self.invite_workspace_members(channel_id, correlation_id=correlation_id)  # What: Invite team members; Why: Ensures channel appears immediately in human team sidebar.

        return SlackProvisioningResult(  # What: Instantiate result model; Why: Returns typed provisioning outcome.
            channel_id=channel_id,  # What: Assigned channel ID; Why: Reference ID.
            channel_name=actual_name,  # What: Final channel name; Why: Handle.
            topic_set=True,  # What: Topic set flag; Why: Verified topic.
            welcome_message_ts=msg_ts,  # What: Welcome message ts; Why: Verified message.
            is_mock=self.mock_mode  # What: Mock mode flag; Why: Indicates whether action was simulated.
        )  # What: End of result instantiation; Why: Returns complete result.


# Global singleton Slack client instance
slack_client: SlackClient = SlackClient()  # What: Instantiate global Slack client; Why: Shared instance across pipeline.
