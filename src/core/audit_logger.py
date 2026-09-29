# Structured audit logging system recording every agent decision in append-only JSONL format.  # What: Module header; Why: Enforces auditable traceability.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Ensures UTC timestamps for all audit logs.
import json  # What: Import json library; Why: Serializes audit entries into JSON strings.
import logging  # What: Import standard logging module; Why: Provides terminal output logging alongside file persistence.
from pathlib import Path  # What: Import Path class; Why: Safely creates log directories and handles cross-platform file paths.
import threading  # What: Import threading module; Why: Guarantees thread safety when writing concurrent audit logs.
from typing import Any, Optional  # What: Import typing utilities; Why: Type annotations for inputs, outputs, and optional parameters.
from src.core.config import settings  # What: Import application settings; Why: Reads configured audit log file path and log level.
from src.models.schemas import AuditActionStatus, AuditLogEntry  # What: Import audit schemas; Why: Enforces strict data structure on every log entry.


# Configure basic console logger for readable live terminal output
_console_handler = logging.StreamHandler()  # What: Instantiate stream handler; Why: Directs logs to standard output.
_console_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")  # What: Define log format; Why: Clean visual terminal format.
_console_handler.setFormatter(_console_formatter)  # What: Attach formatter to handler; Why: Applies format to terminal output.
_root_logger = logging.getLogger("novacrm_audit")  # What: Create or retrieve logger instance; Why: Dedicated logger namespace.
_root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))  # What: Set logging level from config; Why: Dynamic verbosity.
_root_logger.addHandler(_console_handler)  # What: Add stream handler to logger; Why: Enables terminal logging.


class AuditLogger:  # What: AuditLogger service class; Why: Centralizes logging operations across all agents and services.
    """Thread-safe structured audit logger emitting standardized JSON Lines records."""  # What: Docstring; Why: Explains logger capabilities.

    def __init__(  # What: Constructor method; Why: Initializes file targets and synchronization lock.
        self,  # What: Self reference; Why: Accesses class instance attributes.
        log_path: Optional[Path] = None,  # What: Optional audit log file path; Why: Overrides default audit log target.
        escalation_path: Optional[Path] = None  # What: Optional escalation log file path; Why: Overrides default escalation log target.
    ) -> None:  # What: Return type annotation; Why: Constructor returns None.
        self.log_path: Path = log_path or settings.audit_log_file_path  # What: Set target audit log path; Why: Uses configured or overridden log path.
        self.escalation_path: Path = escalation_path or (  # What: Set target escalation log path; Why: Dedicated file for escalations.
            (self.log_path.parent / "escalation_tickets.jsonl") if log_path else settings.escalation_log_file_path  # What: Compute escalation path; Why: Co-locates with test log if overridden.
        )  # What: End of escalation path assignment; Why: Safely resolves escalation file destination.
        self._lock: threading.Lock = threading.Lock()  # What: Instantiate mutex lock; Why: Prevents race conditions during concurrent writes.
        self._ensure_log_dir()  # What: Ensure directory exists; Why: Prevents FileNotFoundError when writing log file.

    def _ensure_log_dir(self) -> None:  # What: Directory creation helper; Why: Creates parent directories if they do not yet exist.
        """Ensures that directories enclosing the audit and escalation log files exist."""  # What: Docstring; Why: Explains purpose of helper.
        if self.log_path.parent:  # What: Check if audit parent folder path is present; Why: Handles relative and absolute paths safely.
            self.log_path.parent.mkdir(parents=True, exist_ok=True)  # What: Create directory tree if missing; Why: Safe folder initialization.
        if self.escalation_path.parent:  # What: Check if escalation parent folder path is present; Why: Handles escalation directory path.
            self.escalation_path.parent.mkdir(parents=True, exist_ok=True)  # What: Create escalation folder if missing; Why: Safe folder initialization.

    def log_action(  # What: Primary logging method; Why: Creates and writes a structured audit log entry.
        self,  # What: Self reference; Why: Accesses class instance attributes.
        correlation_id: str,  # What: Deal tracking ID; Why: Correlates actions across multiple agents.
        agent_name: str,  # What: Name of acting agent; Why: Identifies who performed the operation.
        action: str,  # What: Name of specific operation; Why: Identifies what action was taken.
        inputs: dict[str, Any],  # What: Action inputs dictionary; Why: Captures raw incoming data for audit proof.
        outputs: dict[str, Any],  # What: Action outputs dictionary; Why: Captures resulting data or state for audit proof.
        decision_rationale: str,  # What: Reasoning string; Why: Explains why the agent made this choice.
        status: AuditActionStatus = AuditActionStatus.SUCCESS  # What: Outcome status enum; Why: Categorizes success, halt, or escalation.
    ) -> AuditLogEntry:  # What: Return type annotation; Why: Returns validated AuditLogEntry model.
        """Constructs an AuditLogEntry, persists it to the JSONL file, and logs to console."""  # What: Docstring; Why: Documents method flow.
        entry = AuditLogEntry(  # What: Instantiate AuditLogEntry model; Why: Validates fields against schema.
            timestamp=datetime.now(timezone.utc),  # What: Capture current UTC timestamp; Why: Precise temporal record.
            correlation_id=correlation_id,  # What: Assign correlation ID; Why: Connects deal events.
            agent_name=agent_name,  # What: Assign agent name; Why: Clarifies acting agent.
            action=action,  # What: Assign action name; Why: Clarifies action taken.
            inputs=inputs,  # What: Assign inputs dict; Why: Audits input parameters.
            outputs=outputs,  # What: Assign outputs dict; Why: Audits outputs generated.
            decision_rationale=decision_rationale,  # What: Assign rationale string; Why: Explains rationale behind decision.
            status=status  # What: Assign status; Why: Reflects outcome.
        )  # What: End of entry instantiation; Why: Validated entry object ready for serialization.

        # Serialize entry to JSON string for file storage
        json_line = entry.model_dump_json()  # What: Convert Pydantic model to JSON string; Why: Standardized JSON format.

        # Acquire lock to ensure atomic file writing across concurrent threads
        with self._lock:  # What: Context manager acquiring thread lock; Why: Prevents interleaved file writes.
            with open(self.log_path, mode="a", encoding="utf-8") as f:  # What: Open file in append mode; Why: Appends line atomically.
                f.write(json_line + "\n")  # What: Write JSON line and newline; Why: Adheres to JSON Lines standard.
            if status == AuditActionStatus.ESCALATED or "ticket_id" in outputs:  # What: Check if action is an escalation or contains ticket; Why: Mirrors to dedicated file.
                with open(self.escalation_path, mode="a", encoding="utf-8") as f_esc:  # What: Open escalation file in append mode; Why: Dedicated escalation stream.
                    f_esc.write(json_line + "\n")  # What: Write escalation JSON line; Why: Persists to separate escalation file without removing from audit log.

        # Also emit clean summary to console logger for real-time developer visibility
        log_msg = f"[{agent_name}] {action} -> {status.value}: {decision_rationale}"  # What: Format human-readable message; Why: Terminal view.
        if status in (AuditActionStatus.FAILED, AuditActionStatus.HALTED, AuditActionStatus.ESCALATED):  # What: Check for warning/error status; Why: Uses higher severity.
            _root_logger.warning(log_msg)  # What: Log at warning level; Why: Highlights non-success events.
        else:  # What: Else branch for successful events; Why: Standard informational logging.
            _root_logger.info(log_msg)  # What: Log at info level; Why: Standard operations logging.

        return entry  # What: Return created entry; Why: Allows caller to inspect or assert on logged data.

    def get_entries_for_correlation(self, correlation_id: str) -> list[AuditLogEntry]:  # What: Query method; Why: Retrieves audit trail for a deal.
        """Retrieves all audit entries matching a specific correlation ID."""  # What: Docstring; Why: Explains retrieval method.
        if not self.log_path.exists():  # What: Check if file exists; Why: Returns empty list if no logs exist yet.
            return []  # What: Return empty list; Why: Graceful handling of empty log state.

        matching_entries: list[AuditLogEntry] = []  # What: Initialize results list; Why: Collects matching entries.
        with self._lock:  # What: Acquire lock for safe read; Why: Avoids reading while a write is occurring.
            with open(self.log_path, mode="r", encoding="utf-8") as f:  # What: Open log file in read mode; Why: Iterates over stored records.
                for line in f:  # What: Loop over each line in file; Why: Inspects each JSONL record.
                    line = line.strip()  # What: Strip whitespace; Why: Handles empty lines cleanly.
                    if line:  # What: Check if line is not empty; Why: Skips blank rows.
                        data = json.loads(line)  # What: Parse JSON string into dict; Why: Converts raw string to data structure.
                        if data.get("correlation_id") == correlation_id:  # What: Filter by correlation ID; Why: Isolates target deal events.
                            matching_entries.append(AuditLogEntry.model_validate(data))  # What: Reconstruct model; Why: Strongly-typed return objects.

        return matching_entries  # What: Return filtered list; Why: Complete chronological audit trail for the deal.

    def get_escalation_entries(self) -> list[AuditLogEntry]:  # What: Query method for escalations; Why: Retrieves all records from dedicated escalation file.
        """Retrieves all escalation records from the dedicated escalation log file."""  # What: Docstring; Why: Explains method purpose.
        if not self.escalation_path.exists():  # What: Check if file exists; Why: Returns empty list if no escalations recorded yet.
            return []  # What: Return empty list; Why: Graceful handling of empty state.
        matching: list[AuditLogEntry] = []  # What: Initialize list; Why: Collects parsed records.
        with self._lock:  # What: Acquire thread lock; Why: Safe concurrent read.
            with open(self.escalation_path, mode="r", encoding="utf-8") as f:  # What: Open escalation file; Why: Reads lines.
                for line in f:  # What: Loop lines; Why: Processes each JSONL record.
                    line = line.strip()  # What: Strip whitespace; Why: Handles empty rows.
                    if line:  # What: Check non-empty; Why: Filters blank lines.
                        matching.append(AuditLogEntry.model_validate(json.loads(line)))  # What: Validate JSON model; Why: Strongly-typed return objects.
        return matching  # What: Return list; Why: Returns all escalation tickets.


# Global singleton audit logger instance
audit_logger: AuditLogger = AuditLogger()  # What: Instantiate global audit logger; Why: Shared instance across entire application.
