"""Resilient Slack API client for customer onboarding channel provisioning.

Integrates with the Slack Web API to automate private customer channel creation,
portal URL topic configuration, personalized kickoff welcome message posting,
and human team member workspace auto-discovery and invitation.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional

import httpx

from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.core.exceptions import SlackAPIError
from src.models.schemas import (
    AuditActionStatus,
    SlackChannelPayload,
    SlackProvisioningResult,
)

_logger = logging.getLogger("slack_client")


class SlackClient:
    """Client for provisioning customer Slack channels, setting topics, and posting welcome messages.

    Supports both live Slack Web API communication and an offline mock sandbox
    mode for automated testing.
    """

    SLACK_API_BASE_URL: str = "https://slack.com/api"

    def __init__(
        self,
        token: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ) -> None:
        """Initializes the Slack client credentials and mock settings.

        Args:
            token: Optional Slack bot token override. Defaults to settings.slack_bot_token.
            mock_mode: Optional mock mode flag override. Defaults to settings.slack_mock_mode.
        """
        self.token: str = token or settings.slack_bot_token
        self.mock_mode: bool = mock_mode if mock_mode is not None else settings.slack_mock_mode
        self._created_channels: dict[str, dict[str, Any]] = {}
        self._client: httpx.Client = httpx.Client(timeout=15.0)

    def _get_headers(self) -> dict[str, str]:
        """Builds HTTP request headers required for Slack Web API requests.

        Returns:
            A dictionary containing Bearer token authorization and JSON content-type.
        """
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def create_channel(
        self,
        channel_name: str,
        is_private: bool = True,
        correlation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Creates a Slack channel or returns mock representation if mock mode is active.

        Args:
            channel_name: Desired channel name (e.g. 'csm-ent-acme').
            is_private: Whether the channel should be private. Defaults to True.
            correlation_id: Optional deal correlation ID for audit trail linking.

        Returns:
            The raw Slack API dictionary containing channel metadata.

        Raises:
            SlackAPIError: If Slack rejects channel creation (other than name collision)
                or network fails.
        """
        clean_name = channel_name.lstrip("#").strip().lower()

        # =========================================================================
        # Branch 1: Mock Mode Simulation
        # -------------------------------------------------------------------------
        # When mock_mode is True, bypasses external Slack API calls, generates
        # a deterministic mock channel ID ('C_MOCK_<hash>'), stores the channel in
        # the local in-memory registry, and returns a simulated successful response.
        # =========================================================================
        if self.mock_mode:
            channel_id = f"C_MOCK_{abs(hash(clean_name)) % 1000000:06d}"
            channel_data = {
                "id": channel_id,
                "name": clean_name,
                "is_private": is_private,
            }
            self._created_channels[clean_name] = channel_data
            _logger.info(f"[MOCK] Provisioned Slack channel '#{clean_name}' (ID: {channel_id})")
            return {"ok": True, "channel": channel_data}

        # =========================================================================
        # Branch 2: Live Slack Web API (conversations.create)
        # -------------------------------------------------------------------------
        # Dispatches POST request to https://slack.com/api/conversations.create.
        # Implements automatic self-healing collision recovery: if Slack returns
        # error 'name_taken', it appends a unique 3-digit timestamp suffix and
        # recursively retries channel creation to ensure the pipeline never halts.
        # =========================================================================
        url = f"{self.SLACK_API_BASE_URL}/conversations.create"
        payload = {"name": clean_name, "is_private": is_private}

        try:
            response = self._client.post(url, headers=self._get_headers(), json=payload)
            data = response.json()
        except Exception as exc:
            raise SlackAPIError(f"Network error communicating with Slack API: {exc}") from exc

        if not data.get("ok"):
            error_code = data.get("error", "unknown_error")
            # Sub-branch: Collision Detection & Recursive Suffix Recovery
            if error_code == "name_taken":
                _logger.warning(f"Slack channel name '{clean_name}' is taken. Appending timestamp suffix.")
                suffix = f"-{int(datetime.now().timestamp()) % 1000:03d}"
                fallback_name = f"{clean_name[:80 - len(suffix)]}{suffix}"
                return self.create_channel(fallback_name, is_private=is_private, correlation_id=correlation_id)
            # Sub-branch: Non-recoverable API rejection
            raise SlackAPIError(
                f"Slack API rejected channel creation: {error_code}",
                error_code=error_code,
                details=data,
            )

        return data

    def set_channel_topic(
        self,
        channel_id: str,
        topic: str,
        correlation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Sets the topic of a Slack channel with the Rocketlane project URL.

        Args:
            channel_id: Target Slack channel ID.
            topic: Topic text string containing project URL and tier.
            correlation_id: Optional deal correlation ID for audit trail linking.

        Returns:
            The Slack API response dictionary.

        Raises:
            SlackAPIError: If Slack API rejects setting the channel topic.
        """
        # =========================================================================
        # Branch 1: Mock Mode Simulation
        # -------------------------------------------------------------------------
        # Bypasses network I/O and returns a synthetic OK response for testing.
        # =========================================================================
        if self.mock_mode:
            _logger.info(f"[MOCK] Set topic on channel '{channel_id}': {topic}")
            return {"ok": True, "topic": topic}

        # =========================================================================
        # Branch 2: Live Slack Web API (conversations.setTopic)
        # -------------------------------------------------------------------------
        # Dispatches POST request to https://slack.com/api/conversations.setTopic.
        # =========================================================================
        url = f"{self.SLACK_API_BASE_URL}/conversations.setTopic"
        payload = {"channel": channel_id, "topic": topic}

        try:
            response = self._client.post(url, headers=self._get_headers(), json=payload)
            data = response.json()
        except Exception as exc:
            raise SlackAPIError(f"Network error setting Slack channel topic: {exc}") from exc

        if not data.get("ok"):
            error_code = data.get("error", "unknown_error")
            raise SlackAPIError(
                f"Slack API rejected setTopic: {error_code}",
                error_code=error_code,
                details=data,
            )

        return data

    def post_welcome_message(
        self,
        channel_id: str,
        message_text: str,
        correlation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Posts a personalized onboarding welcome message into the customer Slack channel.

        Args:
            channel_id: Target Slack channel ID.
            message_text: Markdown formatted onboarding message text.
            correlation_id: Optional deal correlation ID for audit trail linking.

        Returns:
            The Slack API response dictionary containing message timestamp ts.

        Raises:
            SlackAPIError: If Slack API rejects posting the message.
        """
        # =========================================================================
        # Branch 1: Mock Mode Simulation
        # -------------------------------------------------------------------------
        # Synthesizes a mock message timestamp ID and returns success.
        # =========================================================================
        if self.mock_mode:
            mock_ts = f"{int(datetime.now().timestamp())}.{abs(hash(message_text)) % 10000:04d}"
            _logger.info(f"[MOCK] Posted welcome message to channel '{channel_id}' (ts: {mock_ts})")
            return {"ok": True, "ts": mock_ts, "message": {"text": message_text}}

        # =========================================================================
        # Branch 2: Live Slack Web API (chat.postMessage)
        # -------------------------------------------------------------------------
        # Dispatches POST request to https://slack.com/api/chat.postMessage with
        # mrkdwn=True to render milestone checklists and formatting properly.
        # =========================================================================
        url = f"{self.SLACK_API_BASE_URL}/chat.postMessage"
        payload = {"channel": channel_id, "text": message_text, "mrkdwn": True}

        try:
            response = self._client.post(url, headers=self._get_headers(), json=payload)
            data = response.json()
        except Exception as exc:
            raise SlackAPIError(f"Network error posting Slack welcome message: {exc}") from exc

        if not data.get("ok"):
            error_code = data.get("error", "unknown_error")
            raise SlackAPIError(
                f"Slack API rejected postMessage: {error_code}",
                error_code=error_code,
                details=data,
            )

        return data

    def invite_workspace_members(
        self,
        channel_id: str,
        correlation_id: Optional[str] = None,
    ) -> list[str]:
        """Discovers human workspace members from the primary public channel and invites them.

        Args:
            channel_id: Target Slack channel ID.
            correlation_id: Optional deal correlation ID for audit trail linking.

        Returns:
            List of successfully invited Slack member user IDs.
        """
        # =========================================================================
        # Branch 1: Mock Mode Simulation
        # -------------------------------------------------------------------------
        # Returns a mock user ID list without making API requests.
        # =========================================================================
        if self.mock_mode:
            _logger.info(f"[MOCK] Invited default workspace members to channel '{channel_id}'.")
            return ["U_MOCK_HUMAN"]

        # =========================================================================
        # Branch 2: Live Member Auto-Discovery & Invitation
        # -------------------------------------------------------------------------
        # 1. Calls auth.test to find the bot user ID.
        # 2. Calls conversations.list to discover the general public channel.
        # 3. Calls conversations.members to extract candidate user IDs.
        # 4. Filters out the bot itself to only invite real human team members.
        # 5. Calls conversations.invite to add humans to the new onboarding channel
        #    so it pops up directly in their left sidebar navigation.
        # Wrapped in a non-fatal try-except block so invite warnings never halt flow.
        # =========================================================================
        try:
            auth_resp = self._client.post(f"{self.SLACK_API_BASE_URL}/auth.test", headers=self._get_headers())
            bot_user_id = auth_resp.json().get("user_id", "")
            conv_resp = self._client.get(
                f"{self.SLACK_API_BASE_URL}/conversations.list",
                headers=self._get_headers(),
                params={"types": "public_channel"},
            )
            channels = conv_resp.json().get("channels", [])
            if not channels:
                return []

            gen_chan = next(
                (
                    c["id"]
                    for c in channels
                    if c.get("is_general") or "general" in c.get("name", "") or "all-" in c.get("name", "")
                ),
                channels[0]["id"],
            )
            mem_resp = self._client.get(
                f"{self.SLACK_API_BASE_URL}/conversations.members",
                headers=self._get_headers(),
                params={"channel": gen_chan},
            )
            members = mem_resp.json().get("members", [])

            human_members = [m for m in members if m and m != bot_user_id]
            if not human_members:
                return []

            invite_resp = self._client.post(
                f"{self.SLACK_API_BASE_URL}/conversations.invite",
                headers=self._get_headers(),
                json={"channel": channel_id, "users": ",".join(human_members)},
            )
            invite_data = invite_resp.json()
            if invite_data.get("ok"):
                _logger.info(f"Successfully invited workspace members {human_members} to Slack channel '{channel_id}'.")
            else:
                _logger.info(f"Notice on member invite for '{channel_id}': {invite_data.get('error', 'ok')}")

            return human_members
        except Exception as exc:
            _logger.warning(f"Could not auto-invite workspace members to channel '{channel_id}': {exc}")
            return []

    def provision_customer_channel(
        self,
        payload: SlackChannelPayload,
        correlation_id: str,
    ) -> SlackProvisioningResult:
        """Coordinates full Slack provisioning: channel creation, topic embedding, and kickoff message dispatch.

        Args:
            payload: Validated SlackChannelPayload model containing channel specifications.
            correlation_id: Unique correlation identifier linking this provisioning to the deal trail.

        Returns:
            A validated SlackProvisioningResult model.
        """
        # =========================================================================
        # Orchestration Workflow: 4 Sequential Steps
        # =========================================================================

        # Step 1: Create the Slack channel
        audit_logger.log_action(
            correlation_id=correlation_id,
            agent_name="SlackClient",
            action="slack_channel_creation_started",
            inputs={"channel_name": payload.channel_name, "is_private": payload.is_private},
            outputs={"mock_mode": self.mock_mode},
            decision_rationale=f"Initiating Slack channel provisioning for handle '{payload.channel_name}'.",
            status=AuditActionStatus.SUCCESS,
        )

        create_resp = self.create_channel(
            payload.channel_name,
            is_private=payload.is_private,
            correlation_id=correlation_id,
        )
        channel_id = str(create_resp["channel"]["id"])
        actual_name = str(create_resp["channel"].get("name", payload.channel_name))

        # Step 2: Set the channel topic with the Rocketlane project URL
        self.set_channel_topic(channel_id, payload.topic, correlation_id=correlation_id)
        audit_logger.log_action(
            correlation_id=correlation_id,
            agent_name="SlackClient",
            action="slack_topic_set",
            inputs={"channel_id": channel_id, "topic": payload.topic},
            outputs={"channel_id": channel_id, "topic_set": True},
            decision_rationale="Embedded Rocketlane project URL into Slack channel topic for immediate customer access.",
            status=AuditActionStatus.SUCCESS,
        )

        # Step 3: Post the personalized onboarding welcome message
        msg_resp = self.post_welcome_message(
            channel_id,
            payload.welcome_message,
            correlation_id=correlation_id,
        )
        msg_ts = str(msg_resp.get("ts", ""))
        audit_logger.log_action(
            correlation_id=correlation_id,
            agent_name="SlackClient",
            action="slack_welcome_message_posted",
            inputs={"channel_id": channel_id, "message_preview": payload.welcome_message[:120]},
            outputs={"channel_id": channel_id, "message_ts": msg_ts},
            decision_rationale="Dispatched personalized onboarding welcome message tailored to customer plan tier.",
            status=AuditActionStatus.SUCCESS,
        )

        # Step 4: Auto-invite workspace members so channel pops up directly in left sidebar
        self.invite_workspace_members(channel_id, correlation_id=correlation_id)

        return SlackProvisioningResult(
            channel_id=channel_id,
            channel_name=actual_name,
            topic_set=True,
            welcome_message_ts=msg_ts,
            is_mock=self.mock_mode,
        )


# Global singleton Slack client instance
slack_client: SlackClient = SlackClient()
