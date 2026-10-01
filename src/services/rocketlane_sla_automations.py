"""Rocketlane native automation engine codifying 1-day and 4-day overdue task escalation rules."""

from datetime import datetime, timezone
import logging
from typing import Any, Optional

from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import (
    AuditActionStatus,
    OverdueAlertResult,
    OverdueEscalationTarget
)

_logger = logging.getLogger("rocketlane_sla_automations")


class RocketlaneSLAEngine:
    """Engine codifying native Rocketlane automation rules for 1-day and 4-day overdue task escalations.

    Formulates declarative rule definitions matching Rocketlane's native automation builder
    and provides a deterministic evaluation method for testing, simulation, and audit verification
    without non-deterministic AI agent overhead.
    """

    # Declarative rule definitions matching Rocketlane's native automation builder schema
    NATIVE_RULES_SPECIFICATION: list[dict[str, Any]] = [
        {
            "rule_id": "rule_sla_1day_pm",
            "name": "Overdue by 1 Day -> Notify Project Manager",
            "trigger": {
                "event": "TASK_OVERDUE",
                "days_threshold": 1
            },
            "conditions": [
                {"field": "status", "operator": "NOT_EQUALS", "value": "COMPLETED"}
            ],
            "action": {
                "type": "NOTIFY_USER",
                "target_role": "PROJECT_MANAGER",
                "template": "⚠️ SLA Warning: Task '{task_name}' in project '{project_name}' is 1 day overdue. Please review blockers."
            }
        },
        {
            "rule_id": "rule_sla_4day_owner",
            "name": "Overdue by 4 Days -> Escalate to Project Owner",
            "trigger": {
                "event": "TASK_OVERDUE",
                "days_threshold": 4
            },
            "conditions": [
                {"field": "status", "operator": "NOT_EQUALS", "value": "COMPLETED"}
            ],
            "action": {
                "type": "NOTIFY_USER",
                "target_role": "PROJECT_OWNER",
                "template": "🚨 Critical SLA Breach: Task '{task_name}' in project '{project_name}' is 4 days overdue! Immediate escalation required."
            }
        }
    ]

    def export_platform_rules(self) -> list[dict[str, Any]]:
        """Returns the declarative native automation rule configurations for Rocketlane setup.

        Returns:
            list[dict[str, Any]]: Blueprint list of native platform rule specifications.
        """
        return self.NATIVE_RULES_SPECIFICATION

    def evaluate_task_overdue(
        self,
        task_id: str,
        task_name: str,
        project_id: str,
        days_overdue: int,
        is_completed: bool = False,
        pm_email: Optional[str] = None,
        owner_email: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> OverdueAlertResult:
        """Evaluates whether an overdue task triggers Rule 1 (1-day -> PM) or Rule 2 (4-day -> Owner).

        Execution Branches:
            - Branch 1 (Completed Task Guard): If task is completed, no escalation occurs regardless of dates.
            - Branch 2 (Critical Escalation - Rule 2): If overdue >= 4 days, escalates to Project Owner (highest priority).
            - Branch 3 (Operational Warning - Rule 1): If overdue >= 1 day and < 4 days, notifies Project Manager.
            - Branch 4 (On-Schedule Guard): If 0 days overdue, reports on-schedule with no alert.

        Args:
            task_id: Rocketlane task identifier.
            task_name: Display title of the task.
            project_id: Associated Rocketlane project identifier.
            days_overdue: Number of elapsed days since task due date.
            is_completed: Boolean indicating whether the task is already finished. Defaults to False.
            pm_email: Optional email override for Project Manager notification recipient.
            owner_email: Optional email override for Project Owner escalation recipient.
            correlation_id: Optional tracking identifier linking evaluation to project audit trail.

        Returns:
            OverdueAlertResult: Encapsulated outcome detailing trigger status, target role, recipient, and message.
        """
        corr_id = correlation_id or f"sla_eval_{int(datetime.now().timestamp())}_{task_id}"
        resolved_owner = owner_email or settings.rocketlane_owner_email or "rd3377@nyu.edu"
        resolved_pm = pm_email or "sarah.connor@novacrm.com"

        # -------------------------------------------------------------------------
        # Branch 1: Completed Task Guard (Finished tasks never trigger escalations)
        # -------------------------------------------------------------------------
        if is_completed:
            _logger.debug(f"Task '{task_name}' is completed. No SLA alert required.")
            return OverdueAlertResult(
                task_id=task_id,
                task_name=task_name,
                project_id=project_id,
                days_overdue=days_overdue,
                target=None,
                alert_triggered=False,
                recipient_label="",
                alert_message="Task is completed. No overdue escalation required."
            )

        # -------------------------------------------------------------------------
        # Branch 2: Rule 2 Critical Escalation (>= 4 days overdue -> Project Owner)
        # -------------------------------------------------------------------------
        if days_overdue >= 4:
            target = OverdueEscalationTarget.PROJECT_OWNER
            msg = f"🚨 Critical SLA Breach: Task '{task_name}' in project '{project_id}' is {days_overdue} days overdue! Escalating to Project Owner ({resolved_owner})."
            _logger.warning(f"SLA Rule 2 Triggered: {msg}")
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="RocketlaneNativeSLA",
                action="sla_overdue_owner_escalated",
                inputs={"task_id": task_id, "task_name": task_name, "days_overdue": days_overdue},
                outputs={"target": target.value, "recipient": resolved_owner, "alert_message": msg},
                decision_rationale=f"Task '{task_name}' is {days_overdue} days overdue (>= 4 days). Triggered native Rule 2 escalating to Project Owner.",
                status=AuditActionStatus.ESCALATED
            )
            return OverdueAlertResult(
                task_id=task_id,
                task_name=task_name,
                project_id=project_id,
                days_overdue=days_overdue,
                target=target,
                alert_triggered=True,
                recipient_label=resolved_owner,
                alert_message=msg
            )

        # -------------------------------------------------------------------------
        # Branch 3: Rule 1 Operational Warning (1 to 3 days overdue -> Project Manager)
        # -------------------------------------------------------------------------
        if days_overdue >= 1:
            target = OverdueEscalationTarget.PROJECT_MANAGER
            msg = f"⚠️ SLA Warning: Task '{task_name}' in project '{project_id}' is {days_overdue} day(s) overdue. Notifying Project Manager ({resolved_pm})."
            _logger.info(f"SLA Rule 1 Triggered: {msg}")
            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="RocketlaneNativeSLA",
                action="sla_overdue_pm_notified",
                inputs={"task_id": task_id, "task_name": task_name, "days_overdue": days_overdue},
                outputs={"target": target.value, "recipient": resolved_pm, "alert_message": msg},
                decision_rationale=f"Task '{task_name}' is {days_overdue} day(s) overdue (>= 1 day, < 4 days). Triggered native Rule 1 notifying Project Manager.",
                status=AuditActionStatus.SUCCESS
            )
            return OverdueAlertResult(
                task_id=task_id,
                task_name=task_name,
                project_id=project_id,
                days_overdue=days_overdue,
                target=target,
                alert_triggered=True,
                recipient_label=resolved_pm,
                alert_message=msg
            )

        # -------------------------------------------------------------------------
        # Branch 4: On-Schedule Guard (0 days overdue)
        # -------------------------------------------------------------------------
        return OverdueAlertResult(
            task_id=task_id,
            task_name=task_name,
            project_id=project_id,
            days_overdue=days_overdue,
            target=None,
            alert_triggered=False,
            recipient_label="",
            alert_message="Task is on schedule. No overdue escalation triggered."
        )


# Global singleton instance of Rocketlane SLA engine
rocketlane_sla_engine: RocketlaneSLAEngine = RocketlaneSLAEngine()
