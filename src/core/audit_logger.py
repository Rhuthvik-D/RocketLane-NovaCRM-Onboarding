"""Structured audit logging system for NovaCRM onboarding automation.

Records every agent decision, tool execution, payload exchange, and status
transition in an append-only JSON Lines (JSONL) format for compliance,
traceability, and automated verification. Also mirrors escalation events
to a dedicated human-review ticket file.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
from typing import Any, Optional

from src.core.config import settings
from src.models.schemas import AuditActionStatus, AuditLogEntry


# Configure basic console logger for readable live terminal output
_console_handler = logging.StreamHandler()
_console_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
_console_handler.setFormatter(_console_formatter)
_root_logger = logging.getLogger("novacrm_audit")
_root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
_root_logger.addHandler(_console_handler)


class AuditLogger:
    """Thread-safe structured audit logger emitting standardized JSON Lines records.

    Provides mutex-locked atomic disk appending for general audit events and
    dedicated escalation tickets, alongside synchronous console logging for
    real-time visibility during automated agent execution.
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        escalation_path: Optional[Path] = None,
    ) -> None:
        """Initializes the audit logger targets and concurrency controls.

        Args:
            log_path: Optional custom file path for the primary audit log.
                Defaults to settings.audit_log_file_path.
            escalation_path: Optional custom file path for escalation tickets.
                Defaults to settings.escalation_log_file_path or co-located
                with custom log_path.
        """
        self.log_path: Path = log_path or settings.audit_log_file_path
        self.escalation_path: Path = escalation_path or (
            (self.log_path.parent / "escalation_tickets.jsonl")
            if log_path
            else settings.escalation_log_file_path
        )
        self._lock: threading.Lock = threading.Lock()
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Ensures that directories enclosing the audit and escalation log files exist."""
        if self.log_path.parent:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.escalation_path.parent:
            self.escalation_path.parent.mkdir(parents=True, exist_ok=True)

    def log_action(
        self,
        correlation_id: str,
        agent_name: str,
        action: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        decision_rationale: str,
        status: AuditActionStatus = AuditActionStatus.SUCCESS,
    ) -> AuditLogEntry:
        """Constructs an AuditLogEntry, persists it to the JSONL file, and logs to console.

        Args:
            correlation_id: Unique correlation identifier tracing the deal lifecycle.
            agent_name: Name of the agent or service executing the action.
            action: Specific action or lifecycle event being recorded.
            inputs: Dictionary capturing incoming arguments and context.
            outputs: Dictionary capturing return values, state changes, or errors.
            decision_rationale: Human-readable reasoning explaining why this action occurred.
            status: Outcome classification (SUCCESS, FAILED, HALTED, or ESCALATED).

        Returns:
            The validated and persisted AuditLogEntry instance.
        """
        entry = AuditLogEntry(
            timestamp=datetime.now(timezone.utc),
            correlation_id=correlation_id,
            agent_name=agent_name,
            action=action,
            inputs=inputs,
            outputs=outputs,
            decision_rationale=decision_rationale,
            status=status,
        )

        json_line = entry.model_dump_json()

        # Acquire lock to ensure atomic file writing across concurrent threads
        with self._lock:
            with open(self.log_path, mode="a", encoding="utf-8") as f:
                f.write(json_line + "\n")
            if status == AuditActionStatus.ESCALATED or "ticket_id" in outputs:
                with open(self.escalation_path, mode="a", encoding="utf-8") as f_esc:
                    f_esc.write(json_line + "\n")

        # Emit clean summary to console logger for real-time visibility
        log_msg = f"[{agent_name}] {action} -> {status.value}: {decision_rationale}"
        if status in (AuditActionStatus.FAILED, AuditActionStatus.HALTED, AuditActionStatus.ESCALATED):
            _root_logger.warning(log_msg)
        else:
            _root_logger.info(log_msg)

        return entry

    def get_entries_for_correlation(self, correlation_id: str) -> list[AuditLogEntry]:
        """Retrieves all audit entries matching a specific correlation ID.

        Args:
            correlation_id: Target correlation identifier to filter records by.

        Returns:
            A chronologically ordered list of matching AuditLogEntry models.
        """
        if not self.log_path.exists():
            return []

        matching_entries: list[AuditLogEntry] = []
        with self._lock:
            with open(self.log_path, mode="r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        if data.get("correlation_id") == correlation_id:
                            matching_entries.append(AuditLogEntry.model_validate(data))

        return matching_entries

    def get_escalation_entries(self) -> list[AuditLogEntry]:
        """Retrieves all escalation records from the dedicated escalation log file.

        Returns:
            A list of all AuditLogEntry models present in the escalation log.
        """
        if not self.escalation_path.exists():
            return []

        matching: list[AuditLogEntry] = []
        with self._lock:
            with open(self.escalation_path, mode="r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        matching.append(AuditLogEntry.model_validate(json.loads(line)))

        return matching


# Global singleton audit logger instance
audit_logger: AuditLogger = AuditLogger()
