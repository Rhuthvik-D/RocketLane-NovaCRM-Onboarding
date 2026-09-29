# Rocketlane native automation engine codifying 1-day and 4-day overdue task escalation rules.  # What: Module header; Why: Enforces platform SLA rules without an AI agent.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for SLA due date calculations and timestamps.
import logging  # What: Import standard logging; Why: Emits debug and warning messages for SLA evaluations.
from typing import Any, Optional  # What: Import typing utilities; Why: Type annotations for payload dictionaries.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits every SLA evaluation and alert.
from src.core.config import settings  # What: Import settings; Why: Retrieves default owner email and configurations.
from src.models.schemas import (  # What: Import domain models; Why: Type safety on SLA alerts and audit entries.
    AuditActionStatus,  # What: Audit status enum; Why: Records audit action outcomes.
    OverdueAlertResult,  # What: Overdue alert result model; Why: Encapsulates evaluated alert state.
    OverdueEscalationTarget  # What: Escalation target enum; Why: Distinguishes PM vs Owner routing.
)  # What: End of schema imports; Why: Completes domain model dependencies.


_logger = logging.getLogger("rocketlane_sla_automations")  # What: Instantiate module logger; Why: Console logging for SLA engine.


class RocketlaneSLAEngine:  # What: SLA automation engine class; Why: Evaluates native Rocketlane overdue task rules.
    """Engine codifying native Rocketlane automation rules for 1-day and 4-day overdue task escalations."""  # What: Docstring; Why: Explains engine role.

    # Declarative rule definitions matching Rocketlane's native automation builder schema
    NATIVE_RULES_SPECIFICATION: list[dict[str, Any]] = [  # What: List of rule definitions; Why: Documents platform configuration.
        {  # What: Rule 1 configuration dictionary; Why: 1-day overdue escalation to Project Manager.
            "rule_id": "rule_sla_1day_pm",  # What: Rule identifier; Why: References 1-day rule.
            "name": "Overdue by 1 Day -> Notify Project Manager",  # What: Human-readable name; Why: Displayed in Rocketlane UI.
            "trigger": {  # What: Trigger configuration; Why: Defines event that fires the rule.
                "event": "TASK_OVERDUE",  # What: Event name; Why: Fires when task due date passes.
                "days_threshold": 1  # What: Days threshold; Why: Evaluated 1 day after due date.
            },  # What: End of trigger; Why: Trigger defined.
            "conditions": [  # What: Conditions array; Why: Filters tasks that must be alerted.
                {"field": "status", "operator": "NOT_EQUALS", "value": "COMPLETED"}  # What: Status condition; Why: Ignores finished tasks.
            ],  # What: End of conditions; Why: Conditions defined.
            "action": {  # What: Action configuration; Why: Defines escalation notification.
                "type": "NOTIFY_USER",  # What: Action type; Why: Sends notification.
                "target_role": "PROJECT_MANAGER",  # What: Target role; Why: Notifies Project Manager.
                "template": "⚠️ SLA Warning: Task '{task_name}' in project '{project_name}' is 1 day overdue. Please review blockers."  # What: Alert template; Why: Warning message.
            }  # What: End of action; Why: Action defined.
        },  # What: End of Rule 1; Why: Rule 1 complete.
        {  # What: Rule 2 configuration dictionary; Why: 4-day critical overdue escalation to Project Owner.
            "rule_id": "rule_sla_4day_owner",  # What: Rule identifier; Why: References 4-day rule.
            "name": "Overdue by 4 Days -> Escalate to Project Owner",  # What: Human-readable name; Why: Displayed in Rocketlane UI.
            "trigger": {  # What: Trigger configuration; Why: Defines event that fires critical escalation.
                "event": "TASK_OVERDUE",  # What: Event name; Why: Fires when task remains overdue.
                "days_threshold": 4  # What: Days threshold; Why: Evaluated 4 days after due date.
            },  # What: End of trigger; Why: Critical threshold.
            "conditions": [  # What: Conditions array; Why: Filters tasks that must be escalated.
                {"field": "status", "operator": "NOT_EQUALS", "value": "COMPLETED"}  # What: Status condition; Why: Ignores finished tasks.
            ],  # What: End of conditions; Why: Conditions defined.
            "action": {  # What: Action configuration; Why: Defines executive escalation.
                "type": "NOTIFY_USER",  # What: Action type; Why: Sends urgent notification.
                "target_role": "PROJECT_OWNER",  # What: Target role; Why: Notifies Project Owner.
                "template": "🚨 Critical SLA Breach: Task '{task_name}' in project '{project_name}' is 4 days overdue! Immediate escalation required."  # What: Alert template; Why: Critical escalation message.
            }  # What: End of action; Why: Action defined.
        }  # What: End of Rule 2; Why: Rule 2 complete.
    ]  # What: End of NATIVE_RULES_SPECIFICATION; Why: Both rules codified.

    def export_platform_rules(self) -> list[dict[str, Any]]:  # What: Rule export helper; Why: Exposes platform rule definitions for documentation.
        """Returns the declarative native automation rule configurations for Rocketlane setup."""  # What: Docstring; Why: Explains export purpose.
        return self.NATIVE_RULES_SPECIFICATION  # What: Return specification list; Why: Complete platform blueprint.

    def evaluate_task_overdue(  # What: Task evaluation method; Why: Evaluates task due date against 1-day and 4-day SLA thresholds.
        self,  # What: Self instance; Why: Accesses class members.
        task_id: str,  # What: Task identifier; Why: Identifies target task.
        task_name: str,  # What: Task title string; Why: Display name in notification.
        project_id: str,  # What: Project identifier; Why: Identifies parent project.
        days_overdue: int,  # What: Integer days overdue; Why: Determines if SLA rules trigger.
        is_completed: bool = False,  # What: Task completion status; Why: Completed tasks never trigger SLA alerts.
        pm_email: Optional[str] = None,  # What: Optional PM email; Why: Target for 1-day alert.
        owner_email: Optional[str] = None,  # What: Optional Owner email; Why: Target for 4-day alert.
        correlation_id: Optional[str] = None  # What: Optional correlation ID; Why: Connects evaluation to deal audit trail.
    ) -> OverdueAlertResult:  # What: Return type; Why: Returns typed OverdueAlertResult model.
        """Evaluates whether an overdue task triggers Rule 1 (1-day -> PM) or Rule 2 (4-day -> Owner)."""  # What: Docstring; Why: Explains evaluation logic.
        corr_id = correlation_id or f"sla_eval_{int(datetime.now().timestamp())}_{task_id}"  # What: Resolve correlation ID; Why: Audit trace link.
        resolved_owner = owner_email or settings.rocketlane_owner_email or "rd3377@nyu.edu"  # What: Resolve owner email; Why: Fallback to configured owner.
        resolved_pm = pm_email or "sarah.connor@novacrm.com"  # What: Resolve PM email; Why: Default project manager assignee.

        # Condition 1: Completed tasks never trigger overdue escalations
        if is_completed:  # What: Check if task is already completed; Why: Closed tasks satisfy SLA.
            _logger.debug(f"Task '{task_name}' is completed. No SLA alert required.")  # What: Log debug; Why: State tracking.
            return OverdueAlertResult(  # What: Return no-alert result; Why: Task is completed.
                task_id=task_id,  # What: Task ID; Why: Reference.
                task_name=task_name,  # What: Task name; Why: Reference.
                project_id=project_id,  # What: Project ID; Why: Reference.
                days_overdue=days_overdue,  # What: Days overdue; Why: Reference.
                target=None,  # What: No target; Why: No alert.
                alert_triggered=False,  # What: Not triggered; Why: Task done.
                recipient_label="",  # What: Empty recipient; Why: No notification.
                alert_message="Task is completed. No overdue escalation required."  # What: Explanation; Why: Documents reason.
            )  # What: End of completed return; Why: Exits early.

        # Rule 2: If overdue by 4 or more days -> Escalate to Project Owner (Highest Priority)
        if days_overdue >= 4:  # What: Check 4-day critical threshold; Why: Escalates to executive owner.
            target = OverdueEscalationTarget.PROJECT_OWNER  # What: Set target to Project Owner; Why: Rule 2 routing.
            msg = f"🚨 Critical SLA Breach: Task '{task_name}' in project '{project_id}' is {days_overdue} days overdue! Escalating to Project Owner ({resolved_owner})."  # What: Critical message; Why: Urgent alert text.
            _logger.warning(f"SLA Rule 2 Triggered: {msg}")  # What: Log warning; Why: Console visibility.
            audit_logger.log_action(  # What: Record audit log; Why: Documents critical SLA escalation.
                correlation_id=corr_id,  # What: Correlation ID; Why: Connects to deal.
                agent_name="RocketlaneNativeSLA",  # What: Agent identifier; Why: Identifies platform SLA rule.
                action="sla_overdue_owner_escalated",  # What: Action name; Why: Documents 4-day escalation.
                inputs={"task_id": task_id, "task_name": task_name, "days_overdue": days_overdue},  # What: Inputs; Why: Audited inputs.
                outputs={"target": target.value, "recipient": resolved_owner, "alert_message": msg},  # What: Outputs; Why: Audited outputs.
                decision_rationale=f"Task '{task_name}' is {days_overdue} days overdue (>= 4 days). Triggered native Rule 2 escalating to Project Owner.",  # What: Rationale; Why: Documents rule logic.
                status=AuditActionStatus.ESCALATED  # What: Status ESCALATED; Why: SLA breach escalation.
            )  # What: End of audit logging; Why: Saved to trail.
            return OverdueAlertResult(  # What: Return 4-day alert result; Why: Encapsulates Rule 2 outcome.
                task_id=task_id,  # What: Task ID; Why: Reference.
                task_name=task_name,  # What: Task name; Why: Reference.
                project_id=project_id,  # What: Project ID; Why: Reference.
                days_overdue=days_overdue,  # What: Days overdue; Why: Reference.
                target=target,  # What: Target enum; Why: PROJECT_OWNER.
                alert_triggered=True,  # What: Triggered true; Why: Alert fired.
                recipient_label=resolved_owner,  # What: Recipient email; Why: Owner notified.
                alert_message=msg  # What: Notification message; Why: Complete message text.
            )  # What: End of Rule 2 return; Why: Done.

        # Rule 1: If overdue by 1 or more days (but less than 4) -> Notify Project Manager
        if days_overdue >= 1:  # What: Check 1-day threshold; Why: Notifies front-line project manager.
            target = OverdueEscalationTarget.PROJECT_MANAGER  # What: Set target to Project Manager; Why: Rule 1 routing.
            msg = f"⚠️ SLA Warning: Task '{task_name}' in project '{project_id}' is {days_overdue} day(s) overdue. Notifying Project Manager ({resolved_pm})."  # What: Warning message; Why: PM alert text.
            _logger.info(f"SLA Rule 1 Triggered: {msg}")  # What: Log info; Why: Console visibility.
            audit_logger.log_action(  # What: Record audit log; Why: Documents 1-day SLA warning.
                correlation_id=corr_id,  # What: Correlation ID; Why: Connects to deal.
                agent_name="RocketlaneNativeSLA",  # What: Agent identifier; Why: Identifies platform SLA rule.
                action="sla_overdue_pm_notified",  # What: Action name; Why: Documents 1-day warning.
                inputs={"task_id": task_id, "task_name": task_name, "days_overdue": days_overdue},  # What: Inputs; Why: Audited inputs.
                outputs={"target": target.value, "recipient": resolved_pm, "alert_message": msg},  # What: Outputs; Why: Audited outputs.
                decision_rationale=f"Task '{task_name}' is {days_overdue} day(s) overdue (>= 1 day, < 4 days). Triggered native Rule 1 notifying Project Manager.",  # What: Rationale; Why: Documents rule logic.
                status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Normal operational alert.
            )  # What: End of audit logging; Why: Saved to trail.
            return OverdueAlertResult(  # What: Return 1-day alert result; Why: Encapsulates Rule 1 outcome.
                task_id=task_id,  # What: Task ID; Why: Reference.
                task_name=task_name,  # What: Task name; Why: Reference.
                project_id=project_id,  # What: Project ID; Why: Reference.
                days_overdue=days_overdue,  # What: Days overdue; Why: Reference.
                target=target,  # What: Target enum; Why: PROJECT_MANAGER.
                alert_triggered=True,  # What: Triggered true; Why: Alert fired.
                recipient_label=resolved_pm,  # What: Recipient email; Why: PM notified.
                alert_message=msg  # What: Notification message; Why: Complete message text.
            )  # What: End of Rule 1 return; Why: Done.

        # Not overdue yet (days_overdue == 0)
        return OverdueAlertResult(  # What: Return on-time result; Why: Task is within SLA window.
            task_id=task_id,  # What: Task ID; Why: Reference.
            task_name=task_name,  # What: Task name; Why: Reference.
            project_id=project_id,  # What: Project ID; Why: Reference.
            days_overdue=days_overdue,  # What: Zero days overdue; Why: On schedule.
            target=None,  # What: No target; Why: No alert.
            alert_triggered=False,  # What: Triggered false; Why: No action needed.
            recipient_label="",  # What: Empty recipient; Why: No notification.
            alert_message="Task is on schedule. No overdue escalation triggered."  # What: Explanation; Why: Documents reason.
        )  # What: End of on-time return; Why: Done.


# Global singleton instance of Rocketlane SLA engine
rocketlane_sla_engine: RocketlaneSLAEngine = RocketlaneSLAEngine()  # What: Instantiate global SLA engine; Why: Shared instance across pipeline.
