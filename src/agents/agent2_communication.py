"""Agent 2: Communication & Collaboration Agent for NovaCRM customer onboarding.

Automates the provisioning and orchestration of dedicated customer Slack channels:
1. Ingests verified handoff payload from Agent 1 (Inbound deal, PlanTier, Rocketlane Project).
2. Enforces precondition stage-gates (ensures upstream project creation succeeded).
3. Sanitizes customer company names into compliant Slack channel handles with tier prefixes (#csm-ent-* / #csm-grw-*).
4. Embeds the live Rocketlane customer portal URL into the private Slack channel topic.
5. Posts tier-tailored kickoff welcome messages (Dedicated CSM 30d vs. Pooled CSM 14d).
6. Auto-invites workspace team members to the newly provisioned channel.
7. Emits structured immutable audit entries across every transition to logs/audit_trail.jsonl.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Optional

from src.core.audit_logger import audit_logger
from src.models.schemas import (
    Agent1Result,
    Agent2Result,
    AuditActionStatus,
    PlanTier,
    SlackChannelPayload,
    SlackProvisioningResult,
)
from src.services.slack_client import SlackClient, slack_client

_logger = logging.getLogger("agent2_communication")


class Agent2Communication:
    """Agent 2: Communication Agent automating customer onboarding Slack channel setup and kickoff communication."""

    def __init__(self, client: Optional[SlackClient] = None) -> None:
        """Initializes Agent 2 with a Slack Web API client instance.

        Args:
            client: Optional pre-configured SlackClient instance. Defaults to global singleton.
        """
        self.slack_client: SlackClient = client or slack_client

    def sanitize_channel_name(self, customer_name: str, tier: PlanTier) -> str:
        """Sanitizes customer company name into a valid Slack channel handle with tier prefix.

        Enforces Slack's 80-character maximum length, lowercasing, and alphanumeric hyphenation
        constraints while applying explicit tier prefixing (#csm-ent-* vs. #csm-grw-*).

        Args:
            customer_name: Inbound company name string (e.g. 'Acme Corporation').
            tier: Verified subscription plan tier determining channel prefix.

        Returns:
            A sanitized channel handle string prefixed with '#' (e.g. '#csm-ent-acme-corporation').
        """
        prefix = "csm-ent-" if tier == PlanTier.ENTERPRISE else "csm-grw-"
        slug = customer_name.strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        if not slug:
            slug = "customer"

        max_slug_len = 80 - len(prefix)
        truncated_slug = slug[:max_slug_len].rstrip("-")
        return f"#{prefix}{truncated_slug}"

    def format_channel_topic(self, portal_url: str, tier: PlanTier) -> str:
        """Builds standard Slack channel topic embedding the Rocketlane project URL and plan tier.

        Args:
            portal_url: Authenticated browser URL to the customer's Rocketlane project portal.
            tier: Verified subscription plan tier.

        Returns:
            A formatted single-line topic string for Slack channel header display.
        """
        return f"Rocketlane Workspace: {portal_url} | Plan: {tier.value} | NovaCRM Customer Onboarding"

    def format_welcome_message(
        self,
        customer_name: str,
        tier: PlanTier,
        portal_url: str,
        csm_name: str,
    ) -> str:
        """Generates a personalized onboarding kickoff message tailored to Enterprise (30d) vs Growth (14d).

        Args:
            customer_name: Company name of the customer being onboarded.
            tier: Verified subscription plan tier.
            portal_url: Link to the Rocketlane project onboarding hub.
            csm_name: Display name of the assigned Dedicated CSM or Pooled CSM team.

        Returns:
            A rich markdown-formatted onboarding welcome message string.
        """
        # Enterprise Tier Template: High-touch 30-day timeline with dedicated CSM and Calendly link
        if tier == PlanTier.ENTERPRISE:
            return (
                f"🎉 *Welcome to NovaCRM, {customer_name}!* 🎉\n\n"
                f"We are thrilled to partner with your team. You are enrolled in our *Enterprise Onboarding Program* "
                f"(30-day timeline) with a Dedicated Customer Success Manager to guide your implementation.\n\n"
                f"👤 *Your Dedicated CSM:* {csm_name}\n"
                f"🚀 *Rocketlane Onboarding Hub:* {portal_url}\n\n"
                f"📋 *30-Day Onboarding Roadmap & Milestones:*\n"
                f"  • *Phase 1: Kickoff & Architecture Discovery* (Days 1–5): Scope business workflows and security requirements.\n"
                f"  • *Phase 2: Data Migration & Verification* (Days 6–15): Complete data parity checks and customer verification sign-off.\n"
                f"  • *Phase 3: System Configuration & Integrations* (Days 16–25): Configure custom pipelines and user permissions.\n"
                f"  • *Phase 4: User Enablement & Go-Live* (Days 26–30): End-user training and formal handoff to ongoing support.\n\n"
                f"📅 *Next Step:* Please book your executive kickoff call with your CSM using the link below:\n"
                f"👉 https://calendly.com/novacrm-enterprise/kickoff\n\n"
                f"Feel free to ask any questions directly in this channel. Let's build something great together!"
            )

        # Growth Tier Template: Fast-track 14-day timeline with pooled CSM team and live office hours
        return (
            f"🎉 *Welcome to NovaCRM, {customer_name}!* 🎉\n\n"
            f"We are excited to help you launch quickly! You are enrolled in our *Growth Fast-Track Onboarding* "
            f"(14-day timeline) supported by our Pooled Customer Success Team.\n\n"
            f"👥 *Your Onboarding Support:* {csm_name}\n"
            f"🚀 *Rocketlane Onboarding Hub:* {portal_url}\n\n"
            f"📋 *14-Day Fast-Track Roadmap & Milestones:*\n"
            f"  • *Phase 1: Kickoff & Team Setup* (Days 1–3): Review onboarding checklist and invite workspace users.\n"
            f"  • *Phase 2: Data Import & QA* (Days 4–7): Import core CRM records using standard CSV migration templates.\n"
            f"  • *Phase 3: Core Configuration* (Days 8–11): Set up standard sales pipelines and notification rules.\n"
            f"  • *Phase 4: Go-Live & Validation* (Days 12–14): Final launch sign-off and access to standard knowledge base.\n\n"
            f"💡 *Resources & Office Hours:*\n"
            f"  • *Weekly Live Office Hours:* Tuesdays & Thursdays at 2:00 PM EST (Meeting link available in Rocketlane hub).\n"
            f"  • *NovaCRM Getting Started Guide:* https://docs.novacrm.com/getting-started\n\n"
            f"Our team is monitoring this channel to answer your questions as you progress through each milestone!"
        )

    def process_project_handoff(
        self,
        agent1_result: Agent1Result,
    ) -> Agent2Result:
        """Processes handoff from Agent 1: validates precondition, formats channel and message, and provisions Slack.

        Execution Branches:
            - Branch 1: Precondition Failure -> Skips Slack provisioning if upstream Rocketlane project was not created.
            - Branch 2: Slack Provisioning Failure -> Catches network/API exceptions and records FAILED status.
            - Branch 3: Success -> Provisions private channel, sets topic, posts welcome message, invites team.

        Args:
            agent1_result: Complete Agent 1 outcome containing project response and email metadata.

        Returns:
            An Agent2Result model containing configuration payloads and provisioning details.
        """
        corr_id = agent1_result.correlation_id

        audit_logger.log_action(
            correlation_id=corr_id,
            agent_name="Agent2_Communication",
            action="process_handoff_started",
            inputs={"agent1_status": agent1_result.status},
            outputs={"correlation_id": corr_id},
            decision_rationale="Initiated Agent 2 Communication Agent processing for project handoff.",
            status=AuditActionStatus.SUCCESS,
        )

        # =========================================================================
        # Branch 1: Upstream Precondition Guardrail
        # =========================================================================
        if (
            agent1_result.status not in ("SUCCESS", "IDEMPOTENT_DUPLICATE")
            or agent1_result.rocketlane_project is None
        ):
            err_msg = (
                f"Agent 1 did not produce a confirmed project (status: {agent1_result.status}). "
                f"Slack provisioning skipped."
            )
            _logger.warning(f"Agent 2 skipped for correlation '{corr_id}': {err_msg}")
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="Agent2_Communication",
                action="slack_provisioning_skipped",
                inputs={"agent1_status": agent1_result.status},
                outputs={"skipped": True, "reason": err_msg},
                decision_rationale=f"Halted Slack channel creation because upstream Agent 1 was not confirmed ({agent1_result.status}).",
                status=AuditActionStatus.HALTED,
            )
            return Agent2Result(
                correlation_id=corr_id,
                status="SKIPPED_UNCONFIRMED",
                error_message=err_msg,
            )

        # =========================================================================
        # Step 2: Parameter Resolution & Message Formatting
        # =========================================================================
        project = agent1_result.rocketlane_project
        customer_name = (
            agent1_result.email_payload.customer_name
            if agent1_result.email_payload
            else project.project_name.split(" - ")[0]
        ).strip()
        tier = project.tier
        portal_url = project.portal_url
        csm_name = "Sarah Connor (Enterprise Lead)" if tier == PlanTier.ENTERPRISE else "Pooled CSM Team"

        channel_name = self.sanitize_channel_name(customer_name, tier)
        topic = self.format_channel_topic(portal_url, tier)
        welcome_message = self.format_welcome_message(customer_name, tier, portal_url, csm_name)

        channel_payload = SlackChannelPayload(
            channel_name=channel_name,
            topic=topic,
            welcome_message=welcome_message,
            is_private=True,
        )

        # =========================================================================
        # Step 3: Dispatch Channel Provisioning via SlackClient
        # =========================================================================
        try:
            provisioning_result = self.slack_client.provision_customer_channel(
                channel_payload,
                correlation_id=corr_id,
            )
        except Exception as exc:
            # =====================================================================
            # Branch 2: Slack Web API Provisioning Failure
            # =====================================================================
            _logger.error(f"Slack provisioning failed for correlation '{corr_id}': {exc}")
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="Agent2_Communication",
                action="slack_provisioning_failed",
                inputs=channel_payload.model_dump(),
                outputs={"error": str(exc)},
                decision_rationale=f"Slack channel provisioning failed due to error: {exc}.",
                status=AuditActionStatus.FAILED,
            )
            return Agent2Result(
                correlation_id=corr_id,
                status="FAILED",
                channel_payload=channel_payload,
                error_message=str(exc),
            )

        # =========================================================================
        # Branch 3: Successful Lifecycle Completion
        # =========================================================================
        audit_logger.log_action(
            correlation_id=corr_id,
            agent_name="Agent2_Communication",
            action="agent2_workflow_completed",
            inputs=channel_payload.model_dump(),
            outputs=provisioning_result.model_dump(),
            decision_rationale=(
                f"Agent 2 successfully provisioned Slack channel '{provisioning_result.channel_name}' "
                f"(ID: '{provisioning_result.channel_id}'), embedded Rocketlane project topic, and "
                f"dispatched tier-personalized welcome message."
            ),
            status=AuditActionStatus.SUCCESS,
        )

        return Agent2Result(
            correlation_id=corr_id,
            status="SUCCESS",
            channel_payload=channel_payload,
            provisioning_result=provisioning_result,
        )


# Global singleton Agent 2 communication instance
agent2_communication: Agent2Communication = Agent2Communication()
