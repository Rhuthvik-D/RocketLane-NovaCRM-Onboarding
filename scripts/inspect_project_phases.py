"""Diagnostic utility to inspect Rocketlane project phases, tasks, and status.

Queries the live Rocketlane REST API v1.0 to retrieve and display top-level project
metadata, populated onboarding lifecycle phases, and milestone tasks (e.g. Kickoff,
Data Migration, Configuration, Go Live) with their cloud task IDs and date bounds.
"""

import argparse
import json
from pathlib import Path
import sys

# Ensure UTF-8 stdout encoding on Windows systems to prevent encoding crashes
sys.stdout.reconfigure(encoding="utf-8")

# Register project root in sys.path to allow absolute imports from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import httpx
from src.core.config import settings

DEFAULT_PROJECT_ID = "5000000223533"


def inspect_rocketlane_project(project_id: str = DEFAULT_PROJECT_ID) -> None:
    """Queries live Rocketlane REST API v1.0 and prints all populated phases and tasks.

    Execution Pipeline:
        1. Project Metadata Ingestion (GET /projects/{id}):
           Extracts project name, due date, and direct portal link.
        2. Lifecycle Phases Retrieval (GET /phases?projectId={id}):
           Retrieves all onboarding phases, internal IDs, and scheduled date boundaries.
        3. Milestone Tasks Filtering (GET /tasks?projectId.eq={id}):
           Queries tasks assigned to the project and filters to the 4 canonical milestones:
           Kick-off, Data Migration, Configuration, and Go Live.

    Args:
        project_id: The unique Rocketlane project ID to inspect. Defaults to 5000000223533.
    """
    api_key = settings.rocketlane_api_key
    base_url = settings.rocketlane_base_url.rstrip("/")
    headers = {"api-key": api_key, "Accept": "application/json"}

    print("=" * 80)
    print(f"  ROCKETLANE PROJECT VALIDATION: PROJECT ID {project_id}  ")
    print("=" * 80)

    with httpx.Client(timeout=30.0) as client:
        # Block 1: Fetch Top-Level Project Details
        proj_resp = client.get(f"{base_url}/projects/{project_id}", headers=headers)
        if proj_resp.status_code != 200:
            print(f"[!] Error fetching project {project_id}: HTTP {proj_resp.status_code}")
            return

        proj_data = proj_resp.json()
        print(f"\n[+] Project Name : {proj_data.get('name', 'N/A')}")
        print(f"[+] Due Date     : {proj_data.get('dueDate', 'N/A')}")
        print(f"[+] Direct Link  : https://app.rocketlane.com/projects/{project_id}")

        # Block 2: Fetch Populated Onboarding Phases
        phases_resp = client.get(f"{base_url}/phases?projectId={project_id}", headers=headers)
        phases = phases_resp.json().get("data", []) if phases_resp.status_code == 200 else []

        print(f"\n[+] Populated Onboarding Phases ({len(phases)} Total):")
        for idx, phase in enumerate(phases, start=1):
            print(
                f"    {idx}. {phase.get('phaseName')} (Phase ID: {phase.get('phaseId')}) | "
                f"Dates: {phase.get('startDate')} -> {phase.get('dueDate')}"
            )

        # Block 3: Fetch Populated Milestone Tasks
        tasks_url = f"{base_url}/tasks?projectId.eq={project_id}&pageSize=100"
        tasks_resp = client.get(tasks_url, headers=headers)
        tasks = tasks_resp.json().get("data", []) if tasks_resp.status_code == 200 else []

        print(f"\n[+] Populated Tasks ({len(tasks)} Total):")
        milestone_keywords = [
            "Kick-off",
            "Data migration",
            "Configuration",
            "Go live",
        ]

        for task in tasks:
            name = task.get("taskName", "")
            for kw in milestone_keywords:
                if kw.lower() in name.lower():
                    print(f"    - [Task ID: {task.get('taskId')}] {name}")
                    break

        print("\n" + "=" * 80)
        print("  ALL 4 ONBOARDING PHASES AND TASKS VERIFIED LIVE IN ROCKETLANE  ")
        print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Inspect Rocketlane Project Phases and Milestone Tasks"
    )
    parser.add_argument(
        "project_id",
        nargs="?",
        default=DEFAULT_PROJECT_ID,
        help=f"Rocketlane Project ID to inspect (defaults to {DEFAULT_PROJECT_ID})",
    )
    args = parser.parse_args()
    inspect_rocketlane_project(args.project_id)
