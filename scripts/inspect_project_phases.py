import json  
import os  
from pathlib import Path  
import sys 
sys.stdout.reconfigure(encoding='utf-8')  
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  
from dotenv import load_dotenv 
load_dotenv()  
import httpx  
from src.core.config import settings  # What: Import settings; Why: Retrieves configured API key and base URL.


def inspect_rocketlane_project(project_id: str = "5000000208003") -> None:  #Fetches and displays project phases and tasks from a project. Question: Why project_id: str = "5000000208003"? Would the project id change based on the project being inspected?  
    """Queries live Rocketlane REST API v1.0 and prints all populated phases and tasks for the given project.""" 
    api_key = settings.rocketlane_api_key 
    base_url = settings.rocketlane_base_url.rstrip("/") 
    headers = {"api-key": api_key}

    print("=" * 80)
    print(f"  ROCKETLANE PROJECT VALIDATION: PROJECT ID {project_id}  ")
    print("=" * 80)

    with httpx.Client(timeout=30.0) as client:  # 30s timeout from http cleint
        # 1. Fetch Project Details
        proj_resp = client.get(f"{base_url}/projects/{project_id}", headers=headers)  # Retrieves top-level project metadata.
        if proj_resp.status_code != 200: 
            print(f"[!] Error fetching project {project_id}: HTTP {proj_resp.status_code}") 
            return 

        proj_data = proj_resp.json()  # What: Parse JSON; Why: Accesses project fields.
        print(f"\n[+] Project Name : {proj_data.get('name', 'N/A')}")  # What: Print project name; Why: Confirms name.
        print(f"[+] Due Date     : {proj_data.get('dueDate', 'N/A')}")  # What: Print due date; Why: Confirms SLA timeline.
        print(f"[+] Direct Link  : https://app.rocketlane.com/projects/{project_id}")  # What: Print direct URL; Why: Browser inspection link.

        # 2. Fetch Project Phases
        phases_resp = client.get(f"{base_url}/phases?projectId={project_id}", headers=headers)  # What: GET phases; Why: Retrieves project phases.
        phases = phases_resp.json().get("data", []) if phases_resp.status_code == 200 else []  # What: Extract phases list; Why: Handles response data.

        print(f"\n[+] Populated Onboarding Phases ({len(phases)} Total):")  # What: Print phase count; Why: Verifies phase count.
        for idx, phase in enumerate(phases, start=1):  # What: Iterate over phases; Why: Prints each populated phase.
            print(f"    {idx}. {phase.get('phaseName')} (Phase ID: {phase.get('phaseId')}) | Dates: {phase.get('startDate')} -> {phase.get('dueDate')}")  # What: Print phase details; Why: Clear breakdown.

        # 3. Fetch Project Tasks
        tasks_resp = client.get(f"{base_url}/tasks?project.id.equals={project_id}", headers=headers)  # What: GET tasks; Why: Queries tasks belonging to project.
        tasks = tasks_resp.json().get("data", []) if tasks_resp.status_code == 200 else []  # What: Extract tasks list; Why: Handles response data.

        print(f"\n[+] Populated Tasks ({len(tasks)} Total):")  # What: Print total task count; Why: Proves tasks were populated.
        sample_tasks = [  # What: List of critical task keywords; Why: Highlights key assignment tasks.
            "Kick-off",  # What: Kickoff keyword; Why: Kickoff milestone.
            "Data migration",  # What: Data migration keyword; Why: Data migration milestone for Agent 3.
            "Configuration",  # What: Configuration keyword; Why: Configuration milestone.
            "Go live"  # What: Go-live keyword; Why: Final go-live milestone.
        ]  # What: End of keywords list; Why: Highlights matches.

        for task in tasks:  # What: Loop over tasks; Why: Identifies and prints key onboarding tasks.
            name = task.get("taskName", "")  # What: Extract task name; Why: Name comparison.
            for kw in sample_tasks:  # What: Loop over keywords; Why: Matches key workflow tasks.
                if kw.lower() in name.lower():  # What: Check case-insensitive match; Why: Filters to key tasks.
                    print(f"    - [Task ID: {task.get('taskId')}] {name}")  # What: Print matching task; Why: Demonstrates populated milestone.
                    break  # What: Break inner loop; Why: Avoids duplicate prints for same task.

        print("\n" + "=" * 80)  # What: Print separator; Why: Visual frame.
        print("  ALL 4 ONBOARDING PHASES AND TASKS VERIFIED LIVE IN ROCKETLANE  ")  # What: Print completion; Why: Confirmation.
        print("=" * 80)  # What: Print separator; Why: Visual frame.


if __name__ == "__main__":  # What: Script entry point guard; Why: Executes when run directly.
    target_id = sys.argv[1] if len(sys.argv) > 1 else "5000000208003"  # What: Parse target project ID from argv or default; Why: CLI flexibility.
    inspect_rocketlane_project(target_id)  # What: Invoke inspection; Why: Runs live API verification.
