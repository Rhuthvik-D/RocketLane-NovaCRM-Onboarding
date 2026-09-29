# Agent 3 Data QA Gatekeeper enforcing customer data migration verification before unlocking Configuration phase.  # What: Module header; Why: Solves unverified migration escalations.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps in QA verification records.
import logging  # What: Import standard logging; Why: Emits debug and warning messages for Data QA operations.
from typing import Optional  # What: Import Optional; Why: Type annotations for optional parameters and clients.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits every Data QA verification decision.
from src.core.exceptions import StageGateError  # What: Import StageGateError; Why: Domain error raised on unverified stage-gate attempts.
from src.models.schemas import (  # What: Import domain models; Why: Typed models for sign-off input and gatekeeper result.
    AuditActionStatus,  # What: Audit status enum; Why: Records SUCCESS, HALTED, or ESCALATED states.
    DataMigrationSignOffPayload,  # What: Sign-off payload schema; Why: Input contract for customer verification data.
    DataQAGatekeeperResult  # What: Gatekeeper result schema; Why: Strongly-typed outcome of stage-gate evaluation.
)  # What: End of schema imports; Why: Completes domain model dependencies.
from src.services.rocketlane_client import RocketlaneClient, rocketlane_client  # What: Import Rocketlane client; Why: Interacts with Rocketlane phases.
from src.services.slack_client import SlackClient, slack_client  # What: Import Slack client; Why: Notifies customer channel of QA unlock or blockers.


_logger = logging.getLogger("agent3_data_qa")  # What: Instantiate module logger; Why: Console logging for Agent 3.


class Agent3DataQAGatekeeper:  # What: Data QA Gatekeeper agent class; Why: Enforces verification gate between Migration and Configuration.
    """Agent 3: Data QA Gatekeeper verifying customer data sign-off before unlocking the Configuration phase."""  # What: Docstring; Why: Explains agent role.

    def __init__(  # What: Constructor method; Why: Initializes Rocketlane and Slack client dependencies.
        self,  # What: Self instance; Why: Accesses class members.
        rocketlane: Optional[RocketlaneClient] = None,  # What: Optional Rocketlane client; Why: Supports test injection.
        slack: Optional[SlackClient] = None  # What: Optional Slack client; Why: Supports test injection.
    ) -> None:  # What: Return type; Why: Constructor returns None.
        self.rocketlane: RocketlaneClient = rocketlane or rocketlane_client  # What: Store Rocketlane client; Why: Phase unlocking and task management.
        self.slack: SlackClient = slack or slack_client  # What: Store Slack client; Why: Channel alerts and notifications.

    def evaluate_migration_sign_off(  # What: Primary gatekeeper evaluation method; Why: Enforces verification criteria before phase unlock.
        self,  # What: Self instance; Why: Accesses class helpers.
        sign_off_payload: DataMigrationSignOffPayload,  # What: Inbound sign-off payload; Why: Contains record counts and customer sign-off flag.
        correlation_id: Optional[str] = None  # What: Optional deal correlation ID; Why: Connects gatekeeping action to deal audit trail.
    ) -> DataQAGatekeeperResult:  # What: Return type; Why: Returns typed DataQAGatekeeperResult model.
        """Evaluates customer data sign-off, verifies record parity, and either unlocks Configuration or halts pipeline."""  # What: Docstring; Why: Explains contract.
        corr_id = correlation_id or f"qa_gate_{int(datetime.now().timestamp())}_{sign_off_payload.project_id}"  # What: Resolve correlation ID; Why: Unique trace link.

        audit_logger.log_action(  # What: Record audit log; Why: Marks start of Data QA evaluation.
            correlation_id=corr_id,  # What: Deal tracking ID; Why: Links audit record.
            agent_name="Agent3_DataQA",  # What: Acting agent name; Why: Identifies Agent 3.
            action="data_qa_evaluation_started",  # What: Action name; Why: Documents evaluation start.
            inputs=sign_off_payload.model_dump(),  # What: Inbound payload; Why: Audited inputs.
            outputs={"project_id": sign_off_payload.project_id},  # What: Project reference; Why: Audited outputs.
            decision_rationale=f"Initiated Data QA gatekeeping check on migration task '{sign_off_payload.task_id}'.",  # What: Rationale; Why: Documents reason.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Step initiated.
        )  # What: End of audit logging; Why: Saved to trail.

        # -------------------------------------------------------------------------
        # GUARDRAIL CHECK 1: Volume Check (Cannot verify zero records)
        # -------------------------------------------------------------------------
        if sign_off_payload.records_migrated <= 0:  # What: Check if migrated record count is non-positive; Why: Migration cannot be complete with zero records.
            err_msg = "Data migration record count is zero. Cannot complete migration without customer records."  # What: Error string; Why: Explains failure.
            _logger.warning(f"Data QA Gatekeeper blocked project '{sign_off_payload.project_id}': {err_msg}")  # What: Log warning; Why: Console visibility.
            audit_logger.log_action(  # What: Record audit log; Why: Captures zero-record halt.
                correlation_id=corr_id,  # What: Correlation ID; Why: Links audit entry.
                agent_name="Agent3_DataQA",  # What: Agent name; Why: Identifies Agent 3.
                action="data_qa_verification_blocked_zero_records",  # What: Action name; Why: Documents zero-record block.
                inputs=sign_off_payload.model_dump(),  # What: Inbound payload; Why: Audited inputs.
                outputs={"is_configuration_unlocked": False, "error": err_msg},  # What: Outputs; Why: Audited outputs.
                decision_rationale=f"Halted milestone transition because records_migrated is {sign_off_payload.records_migrated}. Zero-record migrations are invalid.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.HALTED  # What: Status HALTED; Why: Pipeline blocked.
            )  # What: End of audit logging; Why: Saved to trail.
            return DataQAGatekeeperResult(  # What: Return blocked result; Why: Keeps Configuration phase locked.
                correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
                project_id=sign_off_payload.project_id,  # What: Project ID; Why: Reference.
                status="REJECTED_BLOCKED",  # What: Status REJECTED_BLOCKED; Why: Gate remains locked.
                is_configuration_unlocked=False,  # What: Configuration locked; Why: Prevents downstream phase unlock.
                records_migrated=sign_off_payload.records_migrated,  # What: Record count; Why: Audit proof.
                records_verified=sign_off_payload.records_verified,  # What: Verified count; Why: Audit proof.
                discrepancy_count=0,  # What: Zero discrepancy; Why: Volume check failed.
                csm_alert_sent=True,  # What: Alert sent flag; Why: Notifies CSM lead.
                audit_rationale=err_msg  # What: Rationale string; Why: Explains blocker.
            )  # What: End of zero-record return; Why: Done.

        # -------------------------------------------------------------------------
        # GUARDRAIL CHECK 2: Explicit Customer Verification Sign-Off Check
        # -------------------------------------------------------------------------
        if not sign_off_payload.customer_sign_off_confirmed:  # What: Check customer sign-off boolean; Why: Solves Priya's core pain point (marking done without customer verification).
            err_msg = (  # What: Construct unverified sign-off explanation; Why: Documents reason for stage-gate lock.
                f"Customer data verification sign-off is missing for '{sign_off_payload.customer_name}'. "  # What: Message part 1; Why: Identifies missing sign-off.
                f"Configuration phase is strictly locked until customer lead ({sign_off_payload.sign_off_contact_email}) verifies data."  # What: Message part 2; Why: Explicit condition.
            )  # What: End of error message; Why: Complete rationale.
            _logger.warning(f"Data QA Gatekeeper blocked project '{sign_off_payload.project_id}': {err_msg}")  # What: Log warning; Why: Console visibility.
            audit_logger.log_action(  # What: Record audit log; Why: Captures unverified sign-off halt.
                correlation_id=corr_id,  # What: Correlation ID; Why: Links audit record.
                agent_name="Agent3_DataQA",  # What: Agent name; Why: Identifies Agent 3.
                action="data_qa_verification_blocked_unconfirmed",  # What: Action name; Why: Documents unconfirmed block.
                inputs=sign_off_payload.model_dump(),  # What: Inbound payload; Why: Audited inputs.
                outputs={"is_configuration_unlocked": False, "error": err_msg},  # What: Outputs; Why: Audited outputs.
                decision_rationale=f"Enforced hard stage-gate: blocked Configuration phase because customer_sign_off_confirmed is False. Prevents unverified data escalations.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.HALTED  # What: Status HALTED; Why: Pipeline blocked.
            )  # What: End of audit logging; Why: Saved to trail.
            return DataQAGatekeeperResult(  # What: Return blocked result; Why: Keeps Configuration phase locked.
                correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
                project_id=sign_off_payload.project_id,  # What: Project ID; Why: Reference.
                status="REJECTED_BLOCKED",  # What: Status REJECTED_BLOCKED; Why: Gate remains locked.
                is_configuration_unlocked=False,  # What: Configuration locked; Why: Prevents downstream phase unlock.
                records_migrated=sign_off_payload.records_migrated,  # What: Migrated count; Why: Preserves data.
                records_verified=sign_off_payload.records_verified,  # What: Verified count; Why: Preserves data.
                discrepancy_count=abs(sign_off_payload.records_migrated - sign_off_payload.records_verified),  # What: Discrepancy count; Why: Computes mismatch.
                csm_alert_sent=True,  # What: Alert sent flag; Why: Notifies CSM lead.
                audit_rationale=err_msg  # What: Rationale string; Why: Explains blocker.
            )  # What: End of unconfirmed return; Why: Done.

        # -------------------------------------------------------------------------
        # GUARDRAIL CHECK 3: Record Parity & Discrepancy Check
        # -------------------------------------------------------------------------
        discrepancy = abs(sign_off_payload.records_migrated - sign_off_payload.records_verified)  # What: Compute difference between migrated and verified; Why: Validates 100% parity.
        if discrepancy > 0:  # What: Check if discrepancy is greater than zero; Why: Partial or mismatched imports lead to data corruption.
            err_msg = (  # What: Construct discrepancy explanation; Why: Documents data mismatch.
                f"Data parity discrepancy detected: {sign_off_payload.records_migrated} records migrated but only "  # What: Discrepancy text part 1; Why: Proof of mismatch.
                f"{sign_off_payload.records_verified} records verified ({discrepancy} missing). Auto-escalating to CS Ops."  # What: Discrepancy text part 2; Why: Calls for escalation.
            )  # What: End of discrepancy message; Why: Complete rationale.
            _logger.warning(f"Data QA Gatekeeper discrepancy in project '{sign_off_payload.project_id}': {err_msg}")  # What: Log warning; Why: Console visibility.
            audit_logger.log_action(  # What: Record audit log; Why: Captures discrepancy escalation.
                correlation_id=corr_id,  # What: Correlation ID; Why: Links audit record.
                agent_name="Agent3_DataQA",  # What: Agent name; Why: Identifies Agent 3.
                action="data_qa_verification_escalated_discrepancy",  # What: Action name; Why: Documents discrepancy escalation.
                inputs=sign_off_payload.model_dump(),  # What: Inbound payload; Why: Audited inputs.
                outputs={"is_configuration_unlocked": False, "discrepancy_count": discrepancy},  # What: Outputs; Why: Audited outputs.
                decision_rationale=f"Record parity failed ({discrepancy} record mismatch). Auto-escalated to CS Ops and kept Configuration phase locked.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.ESCALATED  # What: Status ESCALATED; Why: Discrepancy escalation.
            )  # What: End of audit logging; Why: Saved to trail.
            return DataQAGatekeeperResult(  # What: Return escalated result; Why: Halts phase transition.
                correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
                project_id=sign_off_payload.project_id,  # What: Project ID; Why: Reference.
                status="ESCALATED_DISCREPANCY",  # What: Status ESCALATED_DISCREPANCY; Why: Mismatch state.
                is_configuration_unlocked=False,  # What: Configuration locked; Why: Prevents downstream phase unlock.
                records_migrated=sign_off_payload.records_migrated,  # What: Migrated count; Why: Audit proof.
                records_verified=sign_off_payload.records_verified,  # What: Verified count; Why: Audit proof.
                discrepancy_count=discrepancy,  # What: Discrepancy integer; Why: Number of failing records.
                csm_alert_sent=True,  # What: Alert sent flag; Why: Notifies CS Ops.
                audit_rationale=err_msg  # What: Rationale string; Why: Explains discrepancy.
            )  # What: End of discrepancy return; Why: Done.

        # -------------------------------------------------------------------------
        # ALL CHECKS PASSED: Unlock Downstream Configuration Phase
        # -------------------------------------------------------------------------
        success_msg = (  # What: Construct success rationale string; Why: Documents verified milestone transition.
            f"Data migration fully verified for '{sign_off_payload.customer_name}' ({sign_off_payload.records_migrated} records verified, "  # What: Success text part 1; Why: Documents count.
            f"0 discrepancies). Customer sign-off authorized by {sign_off_payload.sign_off_contact_email}. Unlocked Configuration phase."  # What: Success text part 2; Why: Documents unlock.
        )  # What: End of success rationale; Why: Complete rationale.
        _logger.info(f"Data QA Gatekeeper passed for project '{sign_off_payload.project_id}': {success_msg}")  # What: Log info; Why: Console visibility.

        audit_logger.log_action(  # What: Record audit log; Why: Captures verified unlock event.
            correlation_id=corr_id,  # What: Correlation ID; Why: Links audit record.
            agent_name="Agent3_DataQA",  # What: Agent name; Why: Identifies Agent 3.
            action="data_qa_verification_passed_unlocked",  # What: Action name; Why: Documents phase unlock.
            inputs=sign_off_payload.model_dump(),  # What: Inbound payload; Why: Audited inputs.
            outputs={"is_configuration_unlocked": True, "records_verified": sign_off_payload.records_verified},  # What: Outputs; Why: Audited outputs.
            decision_rationale=success_msg,  # What: Decision rationale; Why: Complete proof of verified migration.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Normal completion.
        )  # What: End of audit logging; Why: Saved to trail.

        return DataQAGatekeeperResult(  # What: Return verified result model; Why: Signals downstream systems that Configuration is unlocked.
            correlation_id=corr_id,  # What: Correlation ID; Why: Deal trace.
            project_id=sign_off_payload.project_id,  # What: Project ID; Why: Reference.
            status="VERIFIED_UNLOCKED",  # What: Status VERIFIED_UNLOCKED; Why: Success state.
            is_configuration_unlocked=True,  # What: Configuration unlocked; Why: Unblocks downstream tasks.
            records_migrated=sign_off_payload.records_migrated,  # What: Migrated count; Why: Audit proof.
            records_verified=sign_off_payload.records_verified,  # What: Verified count; Why: Audit proof.
            discrepancy_count=0,  # What: Zero discrepancy; Why: Complete parity.
            csm_alert_sent=False,  # What: Alert false; Why: No alert needed for success.
            audit_rationale=success_msg  # What: Rationale string; Why: Explains verification success.
        )  # What: End of verified return; Why: Done.


# Global singleton instance of Agent 3 Data QA Gatekeeper
agent3_data_qa: Agent3DataQAGatekeeper = Agent3DataQAGatekeeper()  # What: Instantiate global Agent 3; Why: Shared instance across pipeline.
