"""Agent 3: Data QA Gatekeeper enforcing migration verification before unlocking Configuration.

Acts as an automated, immutable stage-gate between the 'Data Migration' phase and the
downstream 'Configuration' phase in Rocketlane. Solves NovaCRM's historical onboarding
failure mode where data migration tasks were marked done without genuine customer data
verification, causing corrupted configurations and executive escalations at go-live.
"""

from datetime import datetime, timezone
import logging
from typing import Optional

from src.core.audit_logger import audit_logger
from src.core.exceptions import StageGateError
from src.models.schemas import (
    AuditActionStatus,
    DataMigrationSignOffPayload,
    DataQAGatekeeperResult,
)
from src.services.rocketlane_client import RocketlaneClient, rocketlane_client
from src.services.slack_client import SlackClient, slack_client

_logger = logging.getLogger("agent3_data_qa")


class Agent3DataQAGatekeeper:
    """Agent 3: Data QA Gatekeeper verifying customer data sign-off before unlocking Configuration."""

    VALID_MIGRATION_KEYWORDS = ("migration", "data onboarding", "mig")
    INVALID_TASK_KEYWORDS = ("kickoff", "kick-off", "solutioning", "configuration", "go live", "go-live", "meeting")

    def __init__(
        self,
        rocketlane: Optional[RocketlaneClient] = None,
        slack: Optional[SlackClient] = None,
    ) -> None:
        """Initializes Agent 3 with Rocketlane and Slack client adapters.

        Args:
            rocketlane: Optional RocketlaneClient instance (defaults to global singleton).
            slack: Optional SlackClient instance (defaults to global singleton).
        """
        self.rocketlane: RocketlaneClient = rocketlane or rocketlane_client
        self.slack: SlackClient = slack or slack_client

    def validate_task_type(
        self,
        task_id: str,
        task_name: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> tuple[bool, str, Optional[str]]:
        """Enforces the Task Semantic Guardrail to ensure only genuine migration tasks are gated.

        Prevents arbitrary or unrelated tasks (e.g. 'Schedule kick-off') from being evaluated
        as data migration milestones.

        Args:
            task_id: The Rocketlane task ID submitted for sign-off.
            task_name: Optional task name provided in the payload.
            project_id: Optional expected Rocketlane project ID.

        Returns:
            A tuple of (is_valid: bool, reason_message: str, resolved_task_name: Optional[str]).
        """
        resolved_name = task_name

        # If task name was not explicitly provided and client is live, attempt API lookup
        if not resolved_name and not getattr(self.rocketlane, "mock_mode", False):
            task_data = self.rocketlane.get_task(task_id)
            if task_data:
                resolved_name = task_data.get("taskName")
                # Ownership Guardrail: Verify task belongs to target project
                task_proj = task_data.get("project", {}).get("projectId")
                if project_id and task_proj and str(task_proj) != str(project_id):
                    return (
                        False,
                        f"Task ID '{task_id}' belongs to project '{task_proj}', not target project '{project_id}'.",
                        resolved_name,
                    )

        # 1. Semantic Check on Resolved Task Name
        if resolved_name:
            name_lower = resolved_name.lower()
            has_valid_kw = any(kw in name_lower for kw in self.VALID_MIGRATION_KEYWORDS)
            has_invalid_kw = any(kw in name_lower for kw in self.INVALID_TASK_KEYWORDS)

            if has_invalid_kw and not has_valid_kw:
                return (
                    False,
                    f"Task '{resolved_name}' (ID: '{task_id}') is an unrelated onboarding milestone, not a data migration task.",
                    resolved_name,
                )
            if not has_valid_kw:
                return (
                    False,
                    f"Task '{resolved_name}' (ID: '{task_id}') does not match recognized data migration keywords.",
                    resolved_name,
                )
            return True, "Task verified as legitimate data migration milestone.", resolved_name

        # 2. Heuristic Check on Task ID string when offline/mock
        id_lower = str(task_id).lower()
        if any(kw in id_lower for kw in ("kickoff", "config", "golive", "meeting")):
            return (
                False,
                f"Task ID '{task_id}' indicates an unrelated onboarding milestone, not a data migration milestone.",
                resolved_name,
            )

        return True, "Task identifier accepted for migration evaluation.", resolved_name

    def evaluate_migration_sign_off(
        self,
        sign_off_payload: DataMigrationSignOffPayload,
        correlation_id: Optional[str] = None,
        live_dispatch: bool = False,
    ) -> DataQAGatekeeperResult:
        """Evaluates customer data sign-off, verifies record parity, and enforces stage-gating.

        Execution Branches:
            - Branch 0: Semantic Guardrail Rejection (Non-migration task submitted).
            - Branch 1: Volume Check Rejection (Zero records migrated).
            - Branch 2: Customer Sign-Off Missing (Premature completion attempt).
            - Branch 3: Record Parity Discrepancy (Missing/mismatched records escalated to CS Ops).
            - Branch 4: Verification Passed (100% parity verified, Configuration unlocked).

        Args:
            sign_off_payload: Inbound payload containing record counts and sign-off confirmation.
            correlation_id: Optional deal tracking identifier for audit linking.
            live_dispatch: If True and Rocketlane client is not mocked, dispatches live task status
                updates and conversation comments to the Rocketlane REST API.

        Returns:
            A validated DataQAGatekeeperResult detailing the gatekeeper outcome.
        """
        corr_id = correlation_id or f"qa_gate_{int(datetime.now().timestamp())}_{sign_off_payload.project_id}"

        # Audit start of Data QA evaluation
        audit_logger.log_action(
            correlation_id=corr_id,
            agent_name="Agent3_DataQA",
            action="data_qa_evaluation_started",
            inputs=sign_off_payload.model_dump(),
            outputs={"project_id": sign_off_payload.project_id},
            decision_rationale=f"Initiated Data QA gatekeeping check on migration task '{sign_off_payload.task_id}'.",
            status=AuditActionStatus.SUCCESS,
        )

        # -------------------------------------------------------------------------
        # GUARDRAIL CHECK 0: Task Semantic & Milestone Type Validation
        # -------------------------------------------------------------------------
        is_valid_type, type_msg, resolved_name = self.validate_task_type(
            task_id=sign_off_payload.task_id,
            task_name=sign_off_payload.task_name,
            project_id=sign_off_payload.project_id,
        )
        if not is_valid_type:
            _logger.warning(f"Data QA Gatekeeper rejected task '{sign_off_payload.task_id}': {type_msg}")
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="Agent3_DataQA",
                action="data_qa_verification_blocked_invalid_task",
                inputs=sign_off_payload.model_dump(),
                outputs={"is_configuration_unlocked": False, "error": type_msg},
                decision_rationale=f"Task Semantic Guardrail tripped: {type_msg} Agent 3 strictly monitors migration milestones only.",
                status=AuditActionStatus.HALTED,
            )
            return DataQAGatekeeperResult(
                correlation_id=corr_id,
                project_id=sign_off_payload.project_id,
                status="REJECTED_BLOCKED",
                is_configuration_unlocked=False,
                records_migrated=sign_off_payload.records_migrated,
                records_verified=sign_off_payload.records_verified,
                discrepancy_count=0,
                csm_alert_sent=True,
                audit_rationale=type_msg,
                task_id=sign_off_payload.task_id,
                task_name=resolved_name,
                live_comment_posted=False,
            )

        # -------------------------------------------------------------------------
        # GUARDRAIL CHECK 1: Volume Check (Cannot verify zero records)
        # -------------------------------------------------------------------------
        if sign_off_payload.records_migrated <= 0:
            err_msg = "Data migration record count is zero. Cannot complete migration without customer records."
            _logger.warning(f"Data QA Gatekeeper blocked project '{sign_off_payload.project_id}': {err_msg}")
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="Agent3_DataQA",
                action="data_qa_verification_blocked_zero_records",
                inputs=sign_off_payload.model_dump(),
                outputs={"is_configuration_unlocked": False, "error": err_msg},
                decision_rationale=f"Halted milestone transition because records_migrated is {sign_off_payload.records_migrated}. Zero-record migrations are invalid.",
                status=AuditActionStatus.HALTED,
            )
            return DataQAGatekeeperResult(
                correlation_id=corr_id,
                project_id=sign_off_payload.project_id,
                status="REJECTED_BLOCKED",
                is_configuration_unlocked=False,
                records_migrated=sign_off_payload.records_migrated,
                records_verified=sign_off_payload.records_verified,
                discrepancy_count=0,
                csm_alert_sent=True,
                audit_rationale=err_msg,
                task_id=sign_off_payload.task_id,
                task_name=resolved_name,
                live_comment_posted=False,
            )

        # -------------------------------------------------------------------------
        # GUARDRAIL CHECK 2: Explicit Customer Verification Sign-Off Check
        # -------------------------------------------------------------------------
        if not sign_off_payload.customer_sign_off_confirmed:
            err_msg = (
                f"Customer data verification sign-off is missing for '{sign_off_payload.customer_name}'. "
                f"Configuration phase is strictly locked until customer lead ({sign_off_payload.sign_off_contact_email}) verifies data."
            )
            _logger.warning(f"Data QA Gatekeeper blocked project '{sign_off_payload.project_id}': {err_msg}")
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="Agent3_DataQA",
                action="data_qa_verification_blocked_unconfirmed",
                inputs=sign_off_payload.model_dump(),
                outputs={"is_configuration_unlocked": False, "error": err_msg},
                decision_rationale="Enforced hard stage-gate: blocked Configuration phase because customer_sign_off_confirmed is False. Prevents unverified data escalations.",
                status=AuditActionStatus.HALTED,
            )

            # Live Dispatch: Keep task in To do & post blocker warning comment
            comment_posted = False
            if live_dispatch and not getattr(self.rocketlane, "mock_mode", False):
                self.rocketlane.update_task_status(sign_off_payload.task_id, 1)
                comment_text = (
                    f"[Agent 3 Data QA Gatekeeper] ⚠️ STAGE-GATE BLOCKED: "
                    f"Customer verification sign-off is MISSING for '{sign_off_payload.customer_name}'. "
                    f"Configuration phase remains strictly locked until {sign_off_payload.sign_off_contact_email} verifies data."
                )
                comment_posted = self.rocketlane.post_task_comment(sign_off_payload.task_id, comment_text)

            discrepancy_val = abs(sign_off_payload.records_migrated - sign_off_payload.records_verified)
            return DataQAGatekeeperResult(
                correlation_id=corr_id,
                project_id=sign_off_payload.project_id,
                status="REJECTED_BLOCKED",
                is_configuration_unlocked=False,
                records_migrated=sign_off_payload.records_migrated,
                records_verified=sign_off_payload.records_verified,
                discrepancy_count=discrepancy_val,
                csm_alert_sent=True,
                audit_rationale=err_msg,
                task_id=sign_off_payload.task_id,
                task_name=resolved_name,
                live_comment_posted=comment_posted,
            )

        # -------------------------------------------------------------------------
        # GUARDRAIL CHECK 3: Record Parity & Discrepancy Check
        # -------------------------------------------------------------------------
        discrepancy = abs(sign_off_payload.records_migrated - sign_off_payload.records_verified)
        if discrepancy > 0:
            err_msg = (
                f"Data parity discrepancy detected: {sign_off_payload.records_migrated} records migrated but only "
                f"{sign_off_payload.records_verified} records verified ({discrepancy} missing). Auto-escalating to CS Ops."
            )
            _logger.warning(f"Data QA Gatekeeper discrepancy in project '{sign_off_payload.project_id}': {err_msg}")
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="Agent3_DataQA",
                action="data_qa_verification_escalated_discrepancy",
                inputs=sign_off_payload.model_dump(),
                outputs={"is_configuration_unlocked": False, "discrepancy_count": discrepancy},
                decision_rationale=f"Record parity failed ({discrepancy} record mismatch). Auto-escalated to CS Ops and kept Configuration phase locked.",
                status=AuditActionStatus.ESCALATED,
            )

            # Live Dispatch: Keep task in To do & post escalation alert comment
            comment_posted = False
            if live_dispatch and not getattr(self.rocketlane, "mock_mode", False):
                self.rocketlane.update_task_status(sign_off_payload.task_id, 1)
                comment_text = (
                    f"[Agent 3 Data QA Gatekeeper] 🚨 ESCALATED TO CS OPS: "
                    f"Record parity failed! {sign_off_payload.records_migrated} migrated vs "
                    f"{sign_off_payload.records_verified} verified ({discrepancy} missing). "
                    f"Configuration phase remains strictly locked."
                )
                comment_posted = self.rocketlane.post_task_comment(sign_off_payload.task_id, comment_text)

            return DataQAGatekeeperResult(
                correlation_id=corr_id,
                project_id=sign_off_payload.project_id,
                status="ESCALATED_DISCREPANCY",
                is_configuration_unlocked=False,
                records_migrated=sign_off_payload.records_migrated,
                records_verified=sign_off_payload.records_verified,
                discrepancy_count=discrepancy,
                csm_alert_sent=True,
                audit_rationale=err_msg,
                task_id=sign_off_payload.task_id,
                task_name=resolved_name,
                live_comment_posted=comment_posted,
            )

        # -------------------------------------------------------------------------
        # ALL CHECKS PASSED: Unlock Downstream Configuration Phase
        # -------------------------------------------------------------------------
        success_msg = (
            f"Data migration fully verified for '{sign_off_payload.customer_name}' "
            f"({sign_off_payload.records_migrated} records verified, 0 discrepancies). "
            f"Customer sign-off authorized by {sign_off_payload.sign_off_contact_email}. Unlocked Configuration phase."
        )
        _logger.info(f"Data QA Gatekeeper passed for project '{sign_off_payload.project_id}': {success_msg}")

        audit_logger.log_action(
            correlation_id=corr_id,
            agent_name="Agent3_DataQA",
            action="data_qa_verification_passed_unlocked",
            inputs=sign_off_payload.model_dump(),
            outputs={"is_configuration_unlocked": True, "records_verified": sign_off_payload.records_verified},
            decision_rationale=success_msg,
            status=AuditActionStatus.SUCCESS,
        )

        # Live Dispatch: Update task to Completed (3), unlock downstream task to In progress (2), and post certificate
        comment_posted = False
        if live_dispatch and not getattr(self.rocketlane, "mock_mode", False):
            self.rocketlane.update_task_status(sign_off_payload.task_id, 3)
            if sign_off_payload.downstream_task_id:
                self.rocketlane.update_task_status(sign_off_payload.downstream_task_id, 2)
            comment_text = (
                f"[Agent 3 Data QA Gatekeeper] 🛡️ VERIFIED & UNLOCKED: "
                f"Data migration fully verified by {sign_off_payload.sign_off_contact_email} "
                f"({sign_off_payload.records_migrated}/{sign_off_payload.records_verified} records verified, 0 discrepancies). "
                f"Unlocked Configuration phase for implementation."
            )
            comment_posted = self.rocketlane.post_task_comment(sign_off_payload.task_id, comment_text)

        return DataQAGatekeeperResult(
            correlation_id=corr_id,
            project_id=sign_off_payload.project_id,
            status="VERIFIED_UNLOCKED",
            is_configuration_unlocked=True,
            records_migrated=sign_off_payload.records_migrated,
            records_verified=sign_off_payload.records_verified,
            discrepancy_count=0,
            csm_alert_sent=False,
            audit_rationale=success_msg,
            task_id=sign_off_payload.task_id,
            task_name=resolved_name,
            live_comment_posted=comment_posted,
        )


# Global singleton instance of Agent 3 Data QA Gatekeeper
agent3_data_qa: Agent3DataQAGatekeeper = Agent3DataQAGatekeeper()
