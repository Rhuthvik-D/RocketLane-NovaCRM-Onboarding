# Agent 2 Communication Agent orchestrating Slack channel provisioning, topic embedding, and welcome messaging.  # What: Module header; Why: Master orchestrator for Agent 2.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps and log records.
import logging  # What: Import standard logging; Why: Emits progress and warning logs for Agent 2.
import re  # What: Import regular expressions; Why: Deterministic slugification and handle sanitization.
from typing import Optional  # What: Import Optional; Why: Type annotations for optional parameters.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits full end-to-end Agent 2 actions.
from src.models.schemas import (  # What: Import domain models; Why: Type safety across inputs and outputs.
    Agent1Result,  # What: Agent 1 outcome model; Why: Ingests handoff payload from Agent 1.
    Agent2Result,  # What: Agent 2 outcome model; Why: Returns complete Agent 2 execution state.
    AuditActionStatus,  # What: Audit status enum; Why: Records execution outcomes.
    PlanTier,  # What: Plan tier enum; Why: Determines channel prefix and messaging template.
    SlackChannelPayload,  # What: Slack configuration model; Why: Packages channel name, topic, and message.
    SlackProvisioningResult  # What: Slack provisioning result model; Why: Captures Slack API results.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.slack_client import SlackClient, slack_client  # What: Import Slack client; Why: Interacts with Slack Web API.


_logger = logging.getLogger("agent2_communication")  # What: Instantiate module logger; Why: Terminal logging for Agent 2.


class Agent2Communication:  # What: Agent 2 orchestrator class; Why: Coordinates customer Slack setup and personalized onboarding messaging.
    """Agent 2: Communication Agent automating customer onboarding Slack channel setup and kickoff communication."""  # What: Docstring; Why: Explains agent role.

    def __init__(self, client: Optional[SlackClient] = None) -> None:  # What: Constructor method; Why: Initializes Slack client dependency.
        self.slack_client: SlackClient = client or slack_client  # What: Store Slack client reference; Why: Supports dependency injection for testing.

    def sanitize_channel_name(self, customer_name: str, tier: PlanTier) -> str:  # What: Handle sanitization helper; Why: Formats RFC/Slack compliant channel handles.
        """Sanitizes customer company name into a valid Slack channel handle with tier prefix (#csm-ent-* / #csm-grw-*)."""  # What: Docstring; Why: Documents sanitization logic.
        prefix = "csm-ent-" if tier == PlanTier.ENTERPRISE else "csm-grw-"  # What: Determine tier prefix; Why: Separates Enterprise from Growth channels.
        slug = customer_name.strip().lower()  # What: Trim whitespace and lowercase; Why: Slack requires all-lowercase channel handles.
        slug = re.sub(r"[^a-z0-9]+", "-", slug)  # What: Replace non-alphanumeric chars with hyphens; Why: Slack forbids spaces, dots, and symbols.
        slug = re.sub(r"-+", "-", slug).strip("-")  # What: Collapse consecutive hyphens and trim edges; Why: Clean handle formatting.
        if not slug:  # What: Check if slug is empty after trimming; Why: Fallback for names composed purely of special characters.
            slug = "customer"  # What: Assign default slug fallback; Why: Guarantees non-empty handle.

        max_slug_len = 80 - len(prefix)  # What: Calculate remaining character budget; Why: Slack limits channel names to 80 characters total.
        truncated_slug = slug[:max_slug_len].rstrip("-")  # What: Truncate slug and trim trailing hyphen; Why: Strictly enforces 80-character maximum.
        return f"#{prefix}{truncated_slug}"  # What: Return prefixed channel handle; Why: Human-readable Slack channel handle with hash.

    def format_channel_topic(self, portal_url: str, tier: PlanTier) -> str:  # What: Topic formatting helper; Why: Embeds Rocketlane project workspace into channel topic.
        """Builds standard Slack channel topic embedding the Rocketlane project URL and customer plan tier."""  # What: Docstring; Why: Documents topic structure.
        return f"Rocketlane Workspace: {portal_url} | Plan: {tier.value} | NovaCRM Customer Onboarding"  # What: Return formatted topic; Why: Immediate project portal access.

    def format_welcome_message(  # What: Welcome message templating helper; Why: Generates personalized onboarding kickoff instructions.
        self,  # What: Self instance; Why: Accesses class methods.
        customer_name: str,  # What: Customer company name; Why: Personalizes message header.
        tier: PlanTier,  # What: Verified plan tier; Why: Selects Enterprise vs Growth messaging template.
        portal_url: str,  # What: Rocketlane project link; Why: Direct link for customer to view onboarding tasks.
        csm_name: str  # What: Assigned CSM name or team; Why: Introduces onboarding point of contact.
    ) -> str:  # What: Return type; Why: Returns formatted markdown string.
        """Generates a personalized onboarding kickoff message tailored to Enterprise (30d) vs Growth (14d)."""  # What: Docstring; Why: Explains message differences.
        if tier == PlanTier.ENTERPRISE:  # What: Check if Enterprise tier; Why: Selects high-touch 30-day dedicated CSM template.
            return (  # What: Return Enterprise welcome message string; Why: Outlines 30-day onboarding milestones and dedicated CSM model.
                f"🎉 *Welcome to NovaCRM, {customer_name}!* 🎉\n\n"  # What: Greeting line; Why: Welcomes customer.
                f"We are thrilled to partner with your team. You are enrolled in our *Enterprise Onboarding Program* "  # What: Program intro; Why: Reassures customer of enterprise status.
                f"(30-day timeline) with a Dedicated Customer Success Manager to guide your implementation.\n\n"  # What: Dedicated CSM model; Why: High-touch SLA statement.
                f"👤 *Your Dedicated CSM:* {csm_name}\n"  # What: Assigned CSM; Why: Identifies primary point of contact.
                f"🚀 *Rocketlane Onboarding Hub:* {portal_url}\n\n"  # What: Rocketlane URL; Why: Direct workspace access.
                f"📋 *30-Day Onboarding Roadmap & Milestones:*\n"  # What: Roadmap header; Why: Sets clear expectations.
                f"  • *Phase 1: Kickoff & Architecture Discovery* (Days 1–5): Scope business workflows and security requirements.\n"  # What: Kickoff milestone; Why: Alignment.
                f"  • *Phase 2: Data Migration & Verification* (Days 6–15): Complete data parity checks and customer verification sign-off.\n"  # What: Data migration milestone; Why: Verified migration.
                f"  • *Phase 3: System Configuration & Integrations* (Days 16–25): Configure custom pipelines and user permissions.\n"  # What: Configuration milestone; Why: Platform readiness.
                f"  • *Phase 4: User Enablement & Go-Live* (Days 26–30): End-user training and formal handoff to ongoing support.\n\n"  # What: Go-live milestone; Why: Handoff completion.
                f"📅 *Next Step:* Please book your executive kickoff call with your CSM using the link below:\n"  # What: Call to action; Why: Immediate next step.
                f"👉 https://calendly.com/novacrm-enterprise/kickoff\n\n"  # What: Kickoff link; Why: Scheduling.
                f"Feel free to ask any questions directly in this channel. Let's build something great together!"  # What: Closing line; Why: Welcoming sign-off.
            )  # What: End of Enterprise template; Why: Complete message.

        # Growth Tier Template (14-day timeline, pooled CSM model, self-serve office hours)
        return (  # What: Return Growth welcome message string; Why: Outlines 14-day fast-track milestones and pooled CSM resources.
            f"🎉 *Welcome to NovaCRM, {customer_name}!* 🎉\n\n"  # What: Greeting line; Why: Welcomes customer.
            f"We are excited to help you launch quickly! You are enrolled in our *Growth Fast-Track Onboarding* "  # What: Program intro; Why: Clarifies fast-track model.
            f"(14-day timeline) supported by our Pooled Customer Success Team.\n\n"  # What: Pooled CSM model; Why: Clarifies staffing structure.
            f"👥 *Your Onboarding Support:* {csm_name}\n"  # What: Pooled team name; Why: Identifies team alias.
            f"🚀 *Rocketlane Onboarding Hub:* {portal_url}\n\n"  # What: Rocketlane URL; Why: Direct workspace access.
            f"📋 *14-Day Fast-Track Roadmap & Milestones:*\n"  # What: Roadmap header; Why: Sets fast-track timeline.
            f"  • *Phase 1: Kickoff & Team Setup* (Days 1–3): Review onboarding checklist and invite workspace users.\n"  # What: Kickoff milestone; Why: Quick start.
            f"  • *Phase 2: Data Import & QA* (Days 4–7): Import core CRM records using standard CSV migration templates.\n"  # What: Data import milestone; Why: Data setup.
            f"  • *Phase 3: Core Configuration* (Days 8–11): Set up standard sales pipelines and notification rules.\n"  # What: Configuration milestone; Why: Core setup.
            f"  • *Phase 4: Go-Live & Validation* (Days 12–14): Final launch sign-off and access to standard knowledge base.\n\n"  # What: Go-live milestone; Why: Rapid launch.
            f"💡 *Resources & Office Hours:*\n"  # What: Resources header; Why: Self-serve enablement.
            f"  • *Weekly Live Office Hours:* Tuesdays & Thursdays at 2:00 PM EST (Meeting link available in Rocketlane hub).\n"  # What: Office hours; Why: Live group support.
            f"  • *NovaCRM Getting Started Guide:* https://docs.novacrm.com/getting-started\n\n"  # What: Documentation link; Why: Self-serve docs.
            f"Our team is monitoring this channel to answer your questions as you progress through each milestone!"  # What: Closing line; Why: Supportive sign-off.
        )  # What: End of Growth template; Why: Complete message.

    def process_project_handoff(  # What: Primary handoff processing method; Why: Coordinates full Agent 2 lifecycle from Agent 1 result.
        self,  # What: Self instance; Why: Accesses class helpers and Slack client.
        agent1_result: Agent1Result  # What: Complete Agent 1 outcome; Why: Ingests validated customer data, tier, and project response.
    ) -> Agent2Result:  # What: Return type; Why: Returns typed Agent2Result with channel and provisioning details.
        """Processes handoff from Agent 1: validates precondition, formats channel and message, and provisions Slack."""  # What: Docstring; Why: Explains method contract.
        corr_id = agent1_result.correlation_id  # What: Extract correlation ID; Why: Connects Agent 2 actions to overarching deal audit trail.

        audit_logger.log_action(  # What: Record audit log; Why: Marks start of Agent 2 execution.
            correlation_id=corr_id,  # What: Deal tracking ID; Why: Connects log to deal.
            agent_name="Agent2_Communication",  # What: Agent identifier; Why: Identifies Agent 2 as acting entity.
            action="process_handoff_started",  # What: Action name; Why: Documents start.
            inputs={"agent1_status": agent1_result.status},  # What: Inputs; Why: Audited inputs.
            outputs={"correlation_id": corr_id},  # What: Outputs; Why: Audited outputs.
            decision_rationale="Initiated Agent 2 Communication Agent processing for project handoff.",  # What: Rationale; Why: Documents reason.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Step initiated.
        )  # What: End of audit logging; Why: Saved to trail.

        # Precondition check: Verify that Agent 1 successfully created a Rocketlane project
        if agent1_result.status not in ("SUCCESS", "IDEMPOTENT_DUPLICATE") or agent1_result.rocketlane_project is None:  # What: Precondition guardrail check; Why: Cannot create channel without confirmed project.
            err_msg = f"Agent 1 did not produce a confirmed project (status: {agent1_result.status}). Slack provisioning skipped."  # What: Reason string; Why: Explains skip.
            _logger.warning(f"Agent 2 skipped for correlation '{corr_id}': {err_msg}")  # What: Log warning; Why: Console visibility.
            audit_logger.log_action(  # What: Record audit log; Why: Documents skip event.
                correlation_id=corr_id,  # What: Correlation ID; Why: Connects to deal.
                agent_name="Agent2_Communication",  # What: Agent identifier; Why: Identifies Agent 2.
                action="slack_provisioning_skipped",  # What: Action name; Why: Documents skipped state.
                inputs={"agent1_status": agent1_result.status},  # What: Inputs; Why: Audited inputs.
                outputs={"skipped": True, "reason": err_msg},  # What: Outputs; Why: Audited outputs.
                decision_rationale=f"Halted Slack channel creation because upstream Agent 1 was not confirmed ({agent1_result.status}).",  # What: Rationale; Why: Explains reason.
                status=AuditActionStatus.HALTED  # What: Status HALTED; Why: Precondition not met.
            )  # What: End of audit logging; Why: Saved to trail.
            return Agent2Result(  # What: Return skipped result; Why: Communicates skipped state to caller.
                correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
                status="SKIPPED_UNCONFIRMED",  # What: Skipped status; Why: Precondition failure.
                error_message=err_msg  # What: Error message; Why: Explains skip.
            )  # What: End of skipped result; Why: Halts cleanly.

        # Extract parameters from confirmed project and inbound email payload
        project = agent1_result.rocketlane_project  # What: Reference Rocketlane project response; Why: Accesses tier, portal_url, and name.
        customer_name = (agent1_result.email_payload.customer_name if agent1_result.email_payload else project.project_name.split(" - ")[0]).strip()  # What: Resolve clean customer name; Why: Used for handle and greeting.
        tier = project.tier  # What: Extract confirmed tier; Why: Enterprise vs Growth.
        portal_url = project.portal_url  # What: Extract Rocketlane workspace URL; Why: Embedded in topic and welcome message.
        csm_name = "Sarah Connor (Enterprise Lead)" if tier == PlanTier.ENTERPRISE else "Pooled CSM Team"  # What: Assign CSM string; Why: Matches staffing model.

        # Format channel name, topic, and personalized welcome message
        channel_name = self.sanitize_channel_name(customer_name, tier)  # What: Generate sanitized channel handle; Why: Compliant Slack handle.
        topic = self.format_channel_topic(portal_url, tier)  # What: Format channel topic; Why: Embeds portal link.
        welcome_message = self.format_welcome_message(customer_name, tier, portal_url, csm_name)  # What: Generate welcome text; Why: Tier-tailored kickoff instructions.

        channel_payload = SlackChannelPayload(  # What: Instantiate channel payload model; Why: Validates Slack parameters.
            channel_name=channel_name,  # What: Sanitized channel name; Why: Name parameter.
            topic=topic,  # What: Formatted topic; Why: Topic parameter.
            welcome_message=welcome_message,  # What: Welcome message text; Why: Chat message parameter.
            is_private=True  # What: Private boolean; Why: Enforces customer confidentiality.
        )  # What: End of channel payload creation; Why: Ready for provisioning.

        # Dispatch channel provisioning via SlackClient
        try:  # What: Try block; Why: Catches Slack provisioning errors.
            provisioning_result = self.slack_client.provision_customer_channel(channel_payload, correlation_id=corr_id)  # What: Call provisioning coordinator; Why: Creates channel, sets topic, posts message.
        except Exception as exc:  # What: Catch exceptions during Slack execution; Why: Prevents unhandled crash and logs failure.
            _logger.error(f"Slack provisioning failed for correlation '{corr_id}': {exc}")  # What: Log error; Why: Console visibility.
            audit_logger.log_action(  # What: Record audit log; Why: Captures failure in audit trail.
                correlation_id=corr_id,  # What: Correlation ID; Why: Connects to deal.
                agent_name="Agent2_Communication",  # What: Agent identifier; Why: Identifies Agent 2.
                action="slack_provisioning_failed",  # What: Action name; Why: Documents failure.
                inputs=channel_payload.model_dump(),  # What: Dispatched payload; Why: Audited inputs.
                outputs={"error": str(exc)},  # What: Error message; Why: Audited outputs.
                decision_rationale=f"Slack channel provisioning failed due to error: {exc}.",  # What: Rationale; Why: Explains failure.
                status=AuditActionStatus.FAILED  # What: Status FAILED; Why: Error state.
            )  # What: End of audit logging; Why: Saved to trail.
            return Agent2Result(  # What: Return failed result; Why: Signals failure to caller.
                correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
                status="FAILED",  # What: Status FAILED; Why: Provisioning failed.
                channel_payload=channel_payload,  # What: Attempted payload; Why: Preserves attempted configuration.
                error_message=str(exc)  # What: Error message; Why: Detailed failure description.
            )  # What: End of failed result; Why: Error return.

        # Record successful completion of Agent 2 workflow
        audit_logger.log_action(  # What: Record audit log; Why: Documents successful Agent 2 execution.
            correlation_id=corr_id,  # What: Correlation ID; Why: Connects to deal.
            agent_name="Agent2_Communication",  # What: Agent identifier; Why: Identifies Agent 2.
            action="agent2_workflow_completed",  # What: Action name; Why: Documents workflow completion.
            inputs=channel_payload.model_dump(),  # What: Channel payload; Why: Audited inputs.
            outputs=provisioning_result.model_dump(),  # What: Provisioning result; Why: Audited outputs.
            decision_rationale=(  # What: Decision rationale; Why: Documents why and what was executed.
                f"Agent 2 successfully provisioned Slack channel '{provisioning_result.channel_name}' "  # What: Rationale part 1; Why: Channel handle proof.
                f"(ID: '{provisioning_result.channel_id}'), embedded Rocketlane project topic, and "  # What: Rationale part 2; Why: Topic proof.
                f"dispatched tier-personalized welcome message."  # What: Rationale part 3; Why: Message proof.
            ),  # What: End of rationale string; Why: Complete rationale.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Normal completion.
        )  # What: End of audit logging; Why: Saved to trail.

        return Agent2Result(  # What: Return successful result; Why: Returns complete Agent 2 outcome.
            correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
            status="SUCCESS",  # What: Status SUCCESS; Why: Succeeded.
            channel_payload=channel_payload,  # What: Channel payload; Why: Configured parameters.
            provisioning_result=provisioning_result  # What: Provisioning result; Why: Channel ID, ts, and mock status.
        )  # What: End of result instantiation; Why: Done.


# Global singleton Agent 2 communication instance
agent2_communication: Agent2Communication = Agent2Communication()  # What: Instantiate global Agent 2; Why: Shared instance across pipeline.
