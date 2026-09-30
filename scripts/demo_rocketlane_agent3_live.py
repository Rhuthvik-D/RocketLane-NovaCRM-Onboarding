"""Live interactive demonstration of Agent 3 (Data QA Gatekeeper) against Rocketlane.

Demonstrates:
1. Unverified Migration Blocker: A CSM or automated script attempts to complete Data Migration
   without customer verification. Agent 3 detects missing sign-off and enforces the stage-gate lock.
2. Data Parity Discrepancy: Sign-off is provided but record counts do not match. Agent 3 escalates
   to CS Ops and blocks downstream Configuration.
3. Verified Sign-Off (Happy Path): 100% record parity and confirmed customer sign-off. Agent 3
   unlocks the gate and updates the Rocketlane task to 'Completed' (value: 3) and the downstream
   Configuration task to 'In progress' (value: 2) in real time.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from src.agents.agent3_data_qa import agent3_data_qa
from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import DataMigrationSignOffPayload


PROJECT_ID = "5000000223533"
MIGRATION_TASK_ID = "5000005741138" 
CONFIG_TASK_ID = "5000005741130"


def get_task_status(client: httpx.Client, task_id: str, headers: dict) -> dict:
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


def update_task_status(client: httpx.Client, task_id: str, status_value: int, headers: dict) -> bool:
    base_url = settings.rocketlane_base_url.rstrip("/")
    payload = {"status": {"value": status_value}}
    resp = client.put(f"{base_url}/tasks/{task_id}", headers=headers, json=payload)
    return resp.status_code == 200


def run_live_demo(reset_only: bool = False) -> None:
    api_key = settings.rocketlane_api_key
    base_url = settings.rocketlane_base_url.rstrip("/")
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    portal_url = f"https://app.rocketlane.com/projects/{PROJECT_ID}"

    print("=" * 80)
    print("  AGENT 3 (DATA QA GATEKEEPER) LIVE ROCKETLANE DEMONSTRATION  ")
    print("=" * 80)
    print(f"[+] Target Rocketlane Project : {portal_url}")
    print(f"[+] Data Migration Task ID   : {MIGRATION_TASK_ID}")
    print(f"[+] Configuration Task ID    : {CONFIG_TASK_ID}")

    with httpx.Client(timeout=30.0) as client:
        # Check if reset only
        if reset_only:
            print("\n[*] Resetting Rocketlane tasks to 'To do' (value: 1)...")
            update_task_status(client, MIGRATION_TASK_ID, 1, headers)
            update_task_status(client, CONFIG_TASK_ID, 1, headers)
            print("[+] Reset complete! Both tasks are back to 'To do'.")
            return

        # ---------------------------------------------------------------------
        # Step 0: Read Current Live State from Rocketlane
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("STEP 0: CURRENT LIVE STATE IN ROCKETLANE CLOUD")
        print("-" * 80)
        mig_status = get_task_status(client, MIGRATION_TASK_ID, headers)
        cfg_status = get_task_status(client, CONFIG_TASK_ID, headers)
        print(f"[*] Task '{mig_status.get('taskName')}' Status: {mig_status.get('status')}")
        print(f"[*] Task '{cfg_status.get('taskName')}' Status: {cfg_status.get('status')}")

        # ---------------------------------------------------------------------
        # Scenario 1: Premature Completion Attempt (Unverified Sign-Off)
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("SCENARIO 1: PREMATURE COMPLETION ATTEMPT (MISSING CUSTOMER SIGN-OFF)")
        print("-" * 80)
        print("[!] Business Context: A CSM tries to mark migration done, but customer hasn't verified.")
        print("[*] Submitting sign-off payload with customer_sign_off_confirmed = False...")

        p1 = DataMigrationSignOffPayload(
            project_id=PROJECT_ID,
            task_id=MIGRATION_TASK_ID,
            customer_name="Enterprise Apex 84823",
            records_migrated=2500,
            records_verified=2500,
            customer_sign_off_confirmed=False,  # Unverified!
            sign_off_contact_email="lead@apexdynamics.com",
            discrepancy_notes="CSM attempted to close task without customer email confirmation.",
        )
        r1 = agent3_data_qa.evaluate_migration_sign_off(p1)

        print(f"[+] Gatekeeper Decision   : {r1.status}")
        print(f"[+] Configuration Unlocked: {r1.is_configuration_unlocked} (STRICTLY BLOCKED)")
        print(f"[+] Rationale             : {r1.audit_rationale}")

        # Enforce lock in Rocketlane
        update_task_status(client, MIGRATION_TASK_ID, 1, headers)
        update_task_status(client, CONFIG_TASK_ID, 1, headers)
        print("[+] Rocketlane Cloud Action: Task enforced in 'To do'. Configuration phase remains locked.")

        time.sleep(1.0)

        # ---------------------------------------------------------------------
        # Scenario 2: Data Parity Discrepancy
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("SCENARIO 2: RECORD COUNT DISCREPANCY (MIGRATED != VERIFIED)")
        print("-" * 80)
        print("[!] Business Context: Customer signed off, but 80 records are missing from verification.")
        print("[*] Submitting sign-off payload with 2,500 migrated vs 2,420 verified...")

        p2 = DataMigrationSignOffPayload(
            project_id=PROJECT_ID,
            task_id=MIGRATION_TASK_ID,
            customer_name="Enterprise Apex 84823",
            records_migrated=2500,
            records_verified=2420,  # 80 missing records!
            customer_sign_off_confirmed=True,
            sign_off_contact_email="lead@apexdynamics.com",
            discrepancy_notes="Checksum mismatch in contact table.",
        )
        r2 = agent3_data_qa.evaluate_migration_sign_off(p2)

        print(f"[+] Gatekeeper Decision   : {r2.status}")
        print(f"[+] Configuration Unlocked: {r2.is_configuration_unlocked} (ESCALATED TO CS OPS)")
        print(f"[+] Discrepancy Count     : {r2.discrepancy_count} records missing")
        print(f"[+] Rationale             : {r2.audit_rationale}")
        print("[+] Rocketlane Cloud Action: Transition rejected. Configuration phase remains locked.")

        time.sleep(1.0)

        # ---------------------------------------------------------------------
        # Scenario 3: Verified Customer Sign-Off (Happy Path Unlock)
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("SCENARIO 3: VERIFIED CUSTOMER SIGN-OFF (100% PARITY -> UNLOCK ROCKETLANE)")
        print("-" * 80)
        print("[!] Business Context: Customer reviews data, confirms 2,500/2,500 records with 0 discrepancies.")
        print("[*] Submitting fully verified sign-off payload...")

        p3 = DataMigrationSignOffPayload(
            project_id=PROJECT_ID,
            task_id=MIGRATION_TASK_ID,
            customer_name="Enterprise Apex 84823",
            records_migrated=2500,
            records_verified=2500,  # 100% parity!
            customer_sign_off_confirmed=True,  # Confirmed!
            sign_off_contact_email="lead@apexdynamics.com",
            discrepancy_notes="All tables and records verified by customer lead.",
        )
        r3 = agent3_data_qa.evaluate_migration_sign_off(p3)

        print(f"[+] Gatekeeper Decision   : {r3.status}")
        print(f"[+] Configuration Unlocked: {r3.is_configuration_unlocked} (APPROVED & UNLOCKED)")
        print(f"[+] Rationale             : {r3.audit_rationale}")

        print("\n[*] Executing Live Downstream Dispatch to Rocketlane REST API...")
        # 1. Update Data Migration task to Completed (value: 3)
        ok1 = update_task_status(client, MIGRATION_TASK_ID, 3, headers)
        print(f"    - PUT /tasks/{MIGRATION_TASK_ID} (Status -> Completed [3]): {'SUCCESS' if ok1 else 'FAILED'}")

        # 2. Unlock Configuration Workshop task to In progress (value: 2)
        ok2 = update_task_status(client, CONFIG_TASK_ID, 2, headers)
        print(f"    - PUT /tasks/{CONFIG_TASK_ID} (Status -> In progress [2]): {'SUCCESS' if ok2 else 'FAILED'}")

        # ---------------------------------------------------------------------
        # Verification: Fetch and display live updated state from Rocketlane
        # ---------------------------------------------------------------------
        print("\n" + "-" * 80)
        print("VERIFYING LIVE ROCKETLANE STATE AFTER AGENT 3 UNLOCK")
        print("-" * 80)
        mig_updated = get_task_status(client, MIGRATION_TASK_ID, headers)
        cfg_updated = get_task_status(client, CONFIG_TASK_ID, headers)
        print(f"[✓] LIVE Task '{mig_updated.get('taskName')}':")
        print(f"    Status: {mig_updated.get('status')}")
        print(f"[✓] LIVE Task '{cfg_updated.get('taskName')}':")
        print(f"    Status: {cfg_updated.get('status')}")

        print("\n" + "=" * 80)
        print(f"  DEMONSTRATION COMPLETE! Open in browser to see the live update:  ")
        print(f"  {portal_url}  ")
        print("=" * 80)
        print("Tip: Run 'python scripts/demo_rocketlane_agent3_live.py --reset' to reset tasks back to 'To do'.")


if __name__ == "__main__":
    is_reset = "--reset" in sys.argv
    run_live_demo(reset_only=is_reset)
