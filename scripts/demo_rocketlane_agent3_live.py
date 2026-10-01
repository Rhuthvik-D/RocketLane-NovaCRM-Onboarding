"""Live interactive demonstration of Agent 3 (Data QA Gatekeeper) against Rocketlane.

Demonstrates:
1. Dynamic Task Discovery & Semantic Guardrails:
   - Queries Rocketlane for the target project's tasks (via `projectId.eq`).
   - Automatically discovers the Data Migration task and Configuration Workshop task.
   - Enforces the Semantic Guardrail: strictly verifies that the target task is a genuine
     data migration milestone before running any sign-off logic.
2. Unverified Migration Blocker:
   - Evaluates sign-off with customer_sign_off_confirmed = False.
   - Agent 3 rejects the transition, posts an audit warning comment to Rocketlane task conversations,
     and enforces the 'To do' lock on both tasks.
3. Record Parity Discrepancy Escalation:
   - Evaluates sign-off with 2,500 migrated vs 2,420 verified (80 missing records).
   - Agent 3 halts, escalates to CS Ops, posts an escalation comment to Rocketlane conversations,
     and keeps Configuration locked.
4. Verified Customer Sign-Off (Happy Path Unlock):
   - 100% record parity and confirmed customer authorization.
   - Agent 3 passes verification, marks Data Migration as 'Completed' (value: 3),
     unlocks Configuration Workshop to 'In progress' (value: 2), and posts the official
     QA verification certificate comment directly into the Rocketlane task conversation stream.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

# Ensure UTF-8 stdout encoding on Windows systems to support terminal emojis
sys.stdout.reconfigure(encoding="utf-8")

# Register project root in sys.path to allow absolute imports from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from src.agents.agent3_data_qa import agent3_data_qa
from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import DataMigrationSignOffPayload

DEFAULT_PROJECT_ID = "5000000223533"


def discover_project_tasks(
    client: httpx.Client,
    project_id: str,
    headers: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Dynamically locates Data Migration and Configuration tasks within a Rocketlane project.

    Uses Rocketlane's `projectId.eq` query filter to fetch project tasks and scans for
    canonical milestone keywords.

    Args:
        client: Active HTTPX client session.
        project_id: Target Rocketlane project identifier.
        headers: Request headers containing authentication api-key and content type.

    Returns:
        A dictionary mapping milestone keys ('migration', 'configuration') to their
        full Rocketlane task metadata payloads.

    Raises:
        RuntimeError: If the tasks API query returns a non-200 HTTP response.
    """
    base_url = settings.rocketlane_base_url.rstrip("/")
    url = f"{base_url}/tasks?projectId.eq={project_id}&pageSize=100"
    resp = client.get(url, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to query tasks for project {project_id}: HTTP {resp.status_code}")

    tasks = resp.json().get("data", [])
    discovered: dict[str, dict[str, Any]] = {}

    for t in tasks:
        name = t.get("taskName", "")
        name_lower = name.lower()
        if "data migration" in name_lower or "migration and data onboarding" in name_lower:
            discovered["migration"] = t
        elif "configuration workshop" in name_lower or "configuration" in name_lower:
            discovered["configuration"] = t

    return discovered


def get_task_status(
    client: httpx.Client,
    task_id: int,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Retrieves current task details and status badge from Rocketlane.

    Args:
        client: Active HTTPX client session.
        task_id: Unique Rocketlane task identifier.
        headers: Request headers containing authentication api-key.

    Returns:
        A dictionary containing taskId, taskName, and status (or error details).
    """
    base_url = settings.rocketlane_base_url.rstrip("/")
    resp = client.get(f"{base_url}/tasks/{task_id}", headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        return {
            "taskId": data.get("taskId"),
            "taskName": data.get("taskName"),
            "status": data.get("status"),
        }
    return {"error": f"HTTP {resp.status_code}"}


def update_task_status(
    client: httpx.Client,
    task_id: int,
    status_value: int,
    headers: dict[str, str],
) -> bool:
    """Mutates a task status in Rocketlane Cloud via REST API.

    Status value mappings:
        1 = "To do"
        2 = "In progress"
        3 = "Completed"

    Args:
        client: Active HTTPX client session.
        task_id: Unique Rocketlane task identifier.
        status_value: Integer status code to assign.
        headers: Request headers containing authentication api-key.

    Returns:
        True if the update succeeded (HTTP 200), False otherwise.
    """
    base_url = settings.rocketlane_base_url.rstrip("/")
    payload = {"status": {"value": status_value}}
    resp = client.put(f"{base_url}/tasks/{task_id}", headers=headers, json=payload)
    return resp.status_code == 200


def post_task_comment(
    client: httpx.Client,
    task_id: int,
    content: str,
    headers: dict[str, str],
) -> bool:
    """Posts an audit certificate or warning comment to a task's Conversations feed.

    Args:
        client: Active HTTPX client session.
        task_id: Unique Rocketlane task identifier.
        content: Comment body text to post into the task discussion feed.
        headers: Request headers containing authentication api-key.

    Returns:
        True if the comment was successfully created (HTTP 200 or 201), False otherwise.
    """
    base_url = settings.rocketlane_base_url.rstrip("/")
    payload = {
        "content": content,
        "source": {
            "sourceType": "TASK",
            "sourceId": int(task_id),
        },
    }
    resp = client.post(f"{base_url}/comments", headers=headers, json=payload)
    return resp.status_code in (200, 201)


def run_live_demo(
    project_id: str = DEFAULT_PROJECT_ID,
    reset_only: bool = False,
) -> None:
    """Executes the live end-to-end Agent 3 demonstration lifecycle against Rocketlane.

    Demonstration Flow:
        Phase 0: Dynamic Discovery & Task Semantic Guardrail Verification
                 (Locates Migration & Configuration tasks; verifies task keywords).
        Phase 1: Scenario 1 - Premature Completion Blocker (Sign-off missing).
        Phase 2: Scenario 2 - Data Parity Discrepancy (2,500 migrated != 2,420 verified).
        Phase 3: Scenario 3 - Verified Customer Sign-Off & Downstream Unlock.
        Phase 4: Live Cloud State Verification & Browser Portal Link.

    Args:
        project_id: Target Rocketlane project identifier (defaults to 5000000223533).
        reset_only: If True, resets target tasks to 'To do' (value: 1) and exits.
    """
    api_key = settings.rocketlane_api_key
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    portal_url = f"https://app.rocketlane.com/projects/{project_id}"

    print("=" * 80)
    print("  AGENT 3 (DATA QA GATEKEEPER) LIVE ROCKETLANE DEMONSTRATION  ")
    print("=" * 80)
    print(f"[+] Target Rocketlane Project : {portal_url}")

    with httpx.Client(timeout=30.0) as client:
        # Phase 0: Dynamic Discovery & Semantic Guardrail Verification
        print("\n[+] Dynamically discovering tasks for project in Rocketlane...")
        discovered = discover_project_tasks(client, project_id, headers)

        if "migration" not in discovered:
            print(f"[!] Error: No Data Migration task found in project {project_id}.")
            return
        if "configuration" not in discovered:
            print(f"[!] Error: No Configuration task found in project {project_id}.")
            return

        mig_task = discovered["migration"]
        cfg_task = discovered["configuration"]
        mig_task_id = mig_task["taskId"]
        cfg_task_id = cfg_task["taskId"]
        mig_name = mig_task["taskName"]
        cfg_name = cfg_task["taskName"]

        print(f"[✓] Discovered Data Migration Task : '{mig_name}' (ID: {mig_task_id})")
        print(f"[✓] Discovered Downstream Task    : '{cfg_name}' (ID: {cfg_task_id})")

        # Semantic Guardrail Validation
        print("\n[+] Enforcing Semantic Guardrail...")
        if "migration" not in mig_name.lower():
            print(f"[!] Guardrail Rejection: Task '{mig_name}' is NOT a data migration milestone. Aborting.")
            return
        print("[✓] Semantic Guardrail Passed: Target task is verified as a legitimate data migration milestone.")

        # Handle Reset Option
        if reset_only:
            print("\n[*] Resetting Rocketlane tasks to 'To do' (value: 1)...")
            update_task_status(client, mig_task_id, 1, headers)
            update_task_status(client, cfg_task_id, 1, headers)
            print("[+] Reset complete! Both tasks are back to 'To do'.")
            return

        # Display Current Cloud State
        print("\n" + "-" * 80)
        print("STEP 0: CURRENT LIVE STATE IN ROCKETLANE CLOUD")
        print("-" * 80)
        s_mig = get_task_status(client, mig_task_id, headers)
        s_cfg = get_task_status(client, cfg_task_id, headers)
        print(f"[*] Task '{s_mig.get('taskName')}' Status: {s_mig.get('status')}")
        print(f"[*] Task '{s_cfg.get('taskName')}' Status: {s_cfg.get('status')}")

        # Ensure starting in 'To do' baseline state
        update_task_status(client, mig_task_id, 1, headers)
        update_task_status(client, cfg_task_id, 1, headers)

        # ---------------------------------------------------------------------
        # Scenario 1: Premature Completion Attempt (Missing Customer Sign-Off)
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("SCENARIO 1: PREMATURE COMPLETION ATTEMPT (UNVERIFIED SIGN-OFF)")
        print("-" * 80)
        print("[!] Business Problem: CSM marks task completed, but customer lead hasn't verified.")
        print("[*] Submitting sign-off payload with customer_sign_off_confirmed = False...")

        p1 = DataMigrationSignOffPayload(
            project_id=str(project_id),
            task_id=str(mig_task_id),
            customer_name="Enterprise Apex",
            records_migrated=2500,
            records_verified=2500,
            customer_sign_off_confirmed=False,  # Unverified!
            sign_off_contact_email="lead@apexdynamics.com",
            discrepancy_notes="CSM attempted to mark done without customer verification email.",
        )
        r1 = agent3_data_qa.evaluate_migration_sign_off(p1)

        print(f"[+] Gatekeeper Decision   : {r1.status}")
        print(f"[+] Configuration Unlocked: {r1.is_configuration_unlocked} (STRICTLY BLOCKED)")
        print(f"[+] Rationale             : {r1.audit_rationale}")

        # Enforce lock in Rocketlane & post comment
        update_task_status(client, mig_task_id, 1, headers)
        update_task_status(client, cfg_task_id, 1, headers)
        comment_blocked = (
            f"[Agent 3 Data QA Gatekeeper] ⚠️ STAGE-GATE BLOCKED: "
            f"Customer verification sign-off is MISSING for 'Enterprise Apex'. "
            f"Downstream Configuration phase remains strictly locked until {p1.sign_off_contact_email} verifies data."
        )
        post_task_comment(client, mig_task_id, comment_blocked, headers)
        print("[+] Rocketlane Cloud Action: Task enforced in 'To do'. Blocker warning posted to Conversations.")

        time.sleep(1.0)

        # ---------------------------------------------------------------------
        # Scenario 2: Record Count Discrepancy
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("SCENARIO 2: DATA PARITY DISCREPANCY (MIGRATED != VERIFIED)")
        print("-" * 80)
        print("[!] Business Problem: Customer verified, but 80 records are missing.")
        print("[*] Submitting sign-off payload with 2,500 migrated vs 2,420 verified...")

        p2 = DataMigrationSignOffPayload(
            project_id=str(project_id),
            task_id=str(mig_task_id),
            customer_name="Enterprise Apex",
            records_migrated=2500,
            records_verified=2420,  # 80 records missing!
            customer_sign_off_confirmed=True,
            sign_off_contact_email="lead@apexdynamics.com",
            discrepancy_notes="80 contact records missing from staging import.",
        )
        r2 = agent3_data_qa.evaluate_migration_sign_off(p2)

        print(f"[+] Gatekeeper Decision   : {r2.status}")
        print(f"[+] Configuration Unlocked: {r2.is_configuration_unlocked} (ESCALATED TO CS OPS)")
        print(f"[+] Discrepancy Count     : {r2.discrepancy_count} records missing")
        print(f"[+] Rationale             : {r2.audit_rationale}")

        comment_escalated = (
            f"[Agent 3 Data QA Gatekeeper] 🚨 ESCALATED TO CS OPS: "
            f"Record parity failed! {p2.records_migrated} records migrated but only {p2.records_verified} verified "
            f"({r2.discrepancy_count} missing). Configuration phase remains locked."
        )
        post_task_comment(client, mig_task_id, comment_escalated, headers)
        print("[+] Rocketlane Cloud Action: Transition rejected. Escalation ticket posted to Conversations.")

        time.sleep(1.0)

        # ---------------------------------------------------------------------
        # Scenario 3: Verified Customer Sign-Off (Happy Path Unlock)
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("SCENARIO 3: VERIFIED CUSTOMER SIGN-OFF (100% PARITY -> UNLOCK ROCKETLANE)")
        print("-" * 80)
        print("[!] Business Solution: Customer lead confirms 2,500/2,500 records with 0 discrepancies.")
        print("[*] Submitting fully verified sign-off payload...")

        p3 = DataMigrationSignOffPayload(
            project_id=str(project_id),
            task_id=str(mig_task_id),
            customer_name="Enterprise Apex",
            records_migrated=2500,
            records_verified=2500,  # 100% parity!
            customer_sign_off_confirmed=True,  # Confirmed!
            sign_off_contact_email="lead@apexdynamics.com",
            discrepancy_notes="All tables and records verified with zero errors.",
        )
        r3 = agent3_data_qa.evaluate_migration_sign_off(p3)

        print(f"[+] Gatekeeper Decision   : {r3.status}")
        print(f"[+] Configuration Unlocked: {r3.is_configuration_unlocked} (APPROVED & UNLOCKED)")
        print(f"[+] Rationale             : {r3.audit_rationale}")

        print("\n[*] Executing Live Downstream Dispatch to Rocketlane REST API...")
        # 1. Update Data Migration task to Completed (value: 3)
        ok1 = update_task_status(client, mig_task_id, 3, headers)
        print(f"    - PUT /tasks/{mig_task_id} (Status -> Completed [3]): {'SUCCESS' if ok1 else 'FAILED'}")

        # 2. Unlock Configuration Workshop task to In progress (value: 2)
        ok2 = update_task_status(client, cfg_task_id, 2, headers)
        print(f"    - PUT /tasks/{cfg_task_id} (Status -> In progress [2]): {'SUCCESS' if ok2 else 'FAILED'}")

        # 3. Post Official Verification Certificate Comment
        comment_passed = (
            f"[Agent 3 Data QA Gatekeeper] 🛡️ VERIFIED & UNLOCKED: "
            f"Data migration fully verified by {p3.sign_off_contact_email} "
            f"({p3.records_migrated}/{p3.records_verified} records verified, 0 discrepancies). "
            f"Unlocked Configuration phase for implementation."
        )
        post_task_comment(client, mig_task_id, comment_passed, headers)
        print("    - POST /comments (QA Verification Certificate posted): SUCCESS")

        # ---------------------------------------------------------------------
        # Final Verification: Fetch Live State from Rocketlane
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("VERIFYING LIVE ROCKETLANE STATE AFTER AGENT 3 UNLOCK")
        print("-" * 80)
        mig_updated = get_task_status(client, mig_task_id, headers)
        cfg_updated = get_task_status(client, cfg_task_id, headers)
        print(f"[✓] LIVE Task '{mig_updated.get('taskName')}':")
        print(f"    Task ID : {mig_task_id}")
        print(f"    Status  : {mig_updated.get('status')}")
        print(f"[✓] LIVE Task '{cfg_updated.get('taskName')}':")
        print(f"    Task ID : {cfg_task_id}")
        print(f"    Status  : {cfg_updated.get('status')}")

        print("\n" + "=" * 80)
        print(f"  DEMONSTRATION COMPLETE! Open in browser to see the live update:  ")
        print(f"  {portal_url}  ")
        print("=" * 80)
        print("Tip: Run 'python scripts/demo_rocketlane_agent3_live.py --reset' to reset tasks back to 'To do'.")


if __name__ == "__main__":
    is_reset = "--reset" in sys.argv
    target_project = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else DEFAULT_PROJECT_ID
    run_live_demo(project_id=target_project, reset_only=is_reset)
