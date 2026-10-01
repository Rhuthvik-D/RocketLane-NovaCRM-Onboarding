# NovaCRM Customer Onboarding Multi-Agent System

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests Passing](https://img.shields.io/badge/tests-84%2F84%20passing-brightgreen.svg)](tests/)
[![Rocketlane API](https://img.shields.io/badge/Rocketlane%20API-v1.0-orange.svg)](https://api.rocketlane.com/api/1.0)
[![Slack Integration](https://img.shields.io/badge/Slack%20API-Bolt%20%2F%20WebClient-4A154B.svg)](https://api.slack.com/)
[![Pydantic v2](https://img.shields.io/badge/validation-Pydantic%20v2-e92063.svg)](https://docs.pydantic.dev/)
[![Code Style](https://img.shields.io/badge/code%20style-PEP%20257%20%7C%20Type%20Annotated-informational.svg)](https://peps.python.org/pep-0257/)

> **Autonomous customer onboarding orchestrator for NovaCRM.**  
> Automates sales handoffs from inbound Closed-Won deal notifications to verified Go-Live unlock using Voice AI telephony, tier-tailored Rocketlane project templates, native SLA overdue automations, Slack private collaboration rooms, and cryptographic QA stage-gates.

---

## Table of Contents

1. [Executive Summary & Overview](#1-executive-summary--overview)
2. [Core Agents & Automations](#2-core-agents--automations)
3. [Prerequisites & Installation](#3-prerequisites--installation)
4. [Configuration & Environment Variables](#4-configuration--environment-variables)
5. [How to Run (Operational CLI Runners & Demos)](#5-how-to-run-operational-cli-runners--demos)
   - [Runner 1: Continuous Inbound Gmail Poller Daemon](#runner-1-continuous-inbound-gmail-poller-daemon)
   - [Runner 2: Full End-to-End Multi-Tier Live Validator](#runner-2-full-end-to-end-multi-tier-live-validator)
   - [Runner 3: Interactive Agent 3 Data QA Live Demo](#runner-3-interactive-agent-3-data-qa-live-demo)
   - [Runner 4: Rocketlane Project Lifecycle Inspector](#runner-4-rocketlane-project-lifecycle-inspector)
6. [How to Test (Complete Verification Suite)](#6-how-to-test-complete-verification-suite)
7. [Idempotency & Audit Logging](#7-idempotency--audit-logging)
8. [Repository Directory Structure](#8-repository-directory-structure)

---

## 1. Executive Summary & Overview

In high-growth B2B SaaS, handing off closed deals from Sales to Customer Success typically suffers from manual data re-entry, delayed project setup, unorganized Slack channels, unmonitored SLA breaches, and premature data migration sign-offs.

The **NovaCRM Multi-Agent System** automates this lifecycle end-to-end:
- Ingests AE deal notifications from Gmail and resolves missing plan tiers via automated **Voice AI phone calls** (or stages human-review drafts if ambiguous).
- Provisions tier-specific **Rocketlane onboarding projects** (30-day Enterprise vs. 14-day Growth blueprints).
- Spins up private, topic-linked **customer Slack channels** with personalized kickoff messaging.
- Enforces milestone timelines via **Rocketlane native SLA automations** (1-day warning to PM, 4-day escalation to Project Owner).
- Guards downstream configuration with an automated **QA stage-gate** requiring confirmed customer sign-off and 100% record migration parity.

---

## 2. Core Agents & Automations

- **Agent 1: Intake & Routing Agent** (`src/agents/agent1_intake.py`)  
  Parses inbound Closed-Won emails with Pydantic validation and 4-level SHA-256 deduplication. If the plan tier is missing, it initiates an outbound Voice AI call to the AE. If verbal confirmation is ambiguous, it safely stages a clarification draft in Gmail without guessing. Automatically provisions the project in Rocketlane using the Enterprise (`5000000095997`) or Growth (`5000000096288`) template.

- **Agent 2: Communication & Collaboration Agent** (`src/agents/agent2_communication.py`)  
  Creates a private Slack channel with sanitized naming (`#csm-ent-*` or `#csm-grw-*`), writes the Rocketlane Client Portal URL into the channel topic, posts a tier-customized welcome briefing, and auto-invites internal stakeholders with fail-soft error handling.

- **Rocketlane Native SLA Automations** (`src/services/rocketlane_sla_automations.py`)  
  Uses Rocketlane's native rule engine for 100% deterministic milestone tracking: triggers a warning to the assigned Project Manager when a phase is 1 day overdue, and escalates to the Project Owner / CS Director when 4 days overdue.

- **Agent 3: Data QA Gatekeeper Agent** (`src/agents/agent3_data_qa.py`)  
  Enforces a strict mathematical stage-gate on data migration: verifies genuine Data Migration tasks, confirms explicit customer sign-off, and mandates 100% record parity ($\text{recordsmigrated} == \text{recordsverified}$). Dispatches status updates (`Completed` for Migration, `In progress` for Configuration) and posts verification certificates directly to Rocketlane.

---

## 3. Prerequisites & Installation

### System Requirements
- **Python:** Version 3.12 or higher
- **Operating System:** Windows, macOS, or Linux

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd "Rocketlane - assignment"
```

### 2. Create and Activate a Virtual Environment
**On Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**On macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 4. Configuration & Environment Variables

All settings are managed via Pydantic Settings in `src/core/config.py` and loaded from `.env`.

To configure your environment, copy the example template:
```powershell
Copy-Item .env.example .env
```
*(On macOS/Linux: `cp .env.example .env`)*

| Variable Name | Default Value | Description |
| :--- | :--- | :--- |
| `ROCKETLANE_API_KEY` | *(Secret)* | API key for the Rocketlane REST API v1.0. |
| `ROCKETLANE_BASE_URL` | `https://api.rocketlane.com/api/1.0` | Base URL for Rocketlane endpoints. |
| `ROCKETLANE_MOCK_MODE` | `True` | Set `False` to run live calls against the Rocketlane cloud. |
| `ROCKETLANE_OWNER_EMAIL` | `example@gmail.com` | Email of the assigned project owner in Rocketlane. |
| `ROCKETLANE_ENTERPRISE_TEMPLATE_ID` | `5000000095997` | Rocketlane 30-day template ID for Enterprise tier. |
| `ROCKETLANE_GROWTH_TEMPLATE_ID` | `5000000096288` | Rocketlane 14-day template ID for Growth tier. |
| `VOICE_AI_API_KEY` | *(Secret)* | Telephony API token (Vapi, Bland.ai, or Retell). |
| `VOICE_AI_PROVIDER` | `vapi` | Outbound telephony provider selection. |
| `VOICE_AI_SIMULATED_TIER` | `ENTERPRISE` | Default tier returned during unattended voice simulation. |
| `SLACK_BOT_TOKEN` | `xoxb-...` | Slack Bot OAuth User Token with `channels:manage` scope. |
| `SLACK_MOCK_MODE` | `True` | Set `False` to create real private Slack channels. |
| `GMAIL_USER` | `example@gmail.com` | CS team inbox email monitored for deal notifications. |
| `GMAIL_APP_PASSWORD` | *(Secret)* | 16-character Google App Password for IMAP access. |
| `GMAIL_POLL_INTERVAL` | `15` | Polling cadence in seconds for the background daemon. |
| `GMAIL_SUBJECT_FILTER` | `New Deal` | Subject keyword filter used to detect Closed-Won deals. |
| `AUDIT_LOG_FILE_PATH` | `logs/audit_trail.jsonl` | Filepath where structured audit records are appended. |

> [!NOTE]
> `ROCKETLANE_MOCK_MODE=True` and `SLACK_MOCK_MODE=True` are enabled by default for zero-credential offline development. Switch both to `False` for live cloud execution.

---

## 5. How to Run (Operational CLI Runners & Demos)

Execution scripts are located in `scripts/`:

### Runner 1: Continuous Inbound Gmail Poller Daemon
Monitors the Customer Success inbox for inbound AE deal notifications. Supports simulated in-memory deal injection as well as live IMAP polling.

```powershell
# Single-sweep run with simulated Enterprise deal injection:
python scripts/run_gmail_poller.py --mock --tier ENTERPRISE --once

# Single-sweep run with simulated Growth deal injection:
python scripts/run_gmail_poller.py --mock --tier GROWTH --once

# Continuous background daemon (polls every 15s, Ctrl+C to terminate):
python scripts/run_gmail_poller.py --mock --interval 10

# Live IMAP poller against CS Gmail inbox (requires GMAIL_APP_PASSWORD):
python scripts/run_gmail_poller.py --filter "New Deal"
```

---

### Runner 2: Full End-to-End Multi-Tier Live Validator
Executes the full pipeline: Inbound Ingestion $\rightarrow$ Voice AI Tier Confirmation $\rightarrow$ Rocketlane Provisioning $\rightarrow$ Slack Channel & Welcome Briefing $\rightarrow$ SLA Evaluation $\rightarrow$ Agent 3 QA Stage-Gate.

```powershell
# Validate Enterprise tier onboarding:
python scripts/validate_e2e_live.py --tier enterprise

# Validate Growth tier onboarding:
python scripts/validate_e2e_live.py --tier growth

# Validate BOTH tiers sequentially (Default):
python scripts/validate_e2e_live.py --tier both
```

---

### Runner 3: Interactive Agent 3 Data QA Live Demo
Demonstrates dynamic task discovery, semantic guardrails, parity blocker escalation, and happy-path certificate unlock against Rocketlane milestones:

```powershell
python scripts/demo_rocketlane_agent3_live.py
```

---

### Runner 4: Rocketlane Project Lifecycle Inspector
Diagnostic tool to inspect live Rocketlane project metadata, populated onboarding lifecycle phases, and milestone tasks.

```powershell
# Inspect default project:
python scripts/inspect_project_phases.py

# Inspect any specific Rocketlane Project ID:
python scripts/inspect_project_phases.py --project-id 5000000223533
```

---

## 6. How to Test (Complete Verification Suite)

### Running the Complete Test Suite
Execute all 84 automated tests across all 14 test modules:

```powershell
pytest
```

To run with verbose output:
```powershell
pytest -v
```

### Targeted Test Suites

| Target Component | Test Command | Scope |
| :--- | :--- | :--- |
| **Agent 1 (Intake)** | `pytest tests/test_agent1.py -v` | Deal parsing, Voice AI, phonetic guardrail, draft staging, idempotency hashing. |
| **Agent 2 (Slack)** | `pytest tests/test_agent2.py -v` | Slack handle sanitization, portal URL topic setting, welcome messages, user invites. |
| **Agent 3 (Data QA)** | `pytest tests/test_agent3.py -v` | Parity checks ($\Delta = 0$), customer sign-off, task mutations, QA certificates. |
| **Native SLA Engine** | `pytest tests/test_assignment_part4.py -v` | Rocketlane 1-day (PM) and 4-day (Owner) native overdue rules. |
| **Edge Cases & Errors** | `pytest tests/test_edge_cases.py -v` | Corrupted emails, invalid dates, negative ARR, API rate-limits/timeouts. |
| **Gmail Poller** | `pytest tests/test_gmail_poller.py -v` | IMAP authentication, multipart extraction, subject filtering, mock injection. |
| **End-to-End Phases** | `pytest tests/test_phase1_e2e.py tests/test_phase2_e2e.py tests/test_phase3_e2e.py tests/test_phase4_e2e.py -v` | Multi-agent lifecycle verification across all 4 onboarding phases. |

---

## 7. Idempotency & Audit Logging

- **Multi-Level Idempotency:** Derives `SHA-256(customer_name + plan_tier + contract_value + start_date)` stored in `logs/idempotency_cache.json` to prevent duplicate Rocketlane projects or Slack channels on email re-deliveries.
- **Structured Dual-Ledger Audit:**
  - `logs/audit_trail.jsonl`: Captures event timestamps, correlation IDs, agent actions, and API latency.
  - `logs/escalation_tickets.jsonl`: Records QA stage-gate failures, parity discrepancies, and overdue SLA escalations for CS Ops review.
- **Resilience:** Built with `tenacity` exponential backoff for transient HTTP errors and fail-soft handling on Slack member invites.

---

## 8. Repository Directory Structure

```text
Rocketlane - assignment/
├── README.md                               # Master documentation & quickstart guide
├── requirements.txt                        # Project dependencies
├── .env.example                            # Configuration environment template
├── .gitignore                              # Git sanitization rules
│
├── src/                                    # Application source code
│   ├── agents/                             # Core autonomous agents
│   │   ├── agent1_intake.py                # Agent 1: Email parsing, Voice AI, Rocketlane setup
│   │   ├── agent2_communication.py         # Agent 2: Slack channel, portal topic, welcome messages
│   │   ├── agent3_data_qa.py               # Agent 3: Data QA Gatekeeper, parity checks, mutations
│   │   ├── intake_parser.py                # Deterministic regex email extractor
│   │   └── voice_guardrail.py              # Phonetic distance & speech transcript validator
│   ├── core/                               # Foundational modules
│   │   ├── config.py                       # Pydantic Settings & environment loader
│   │   ├── audit_logger.py                 # Structured JSONL dual-ledger audit logger
│   │   └── exceptions.py                   # Domain-specific custom exceptions
│   ├── models/                             # Pydantic schemas & data models
│   │   └── schemas.py                      # Strongly-typed schemas (Deal, QA, Slack, Rocketlane)
│   └── services/                           # Third-party integrations
│       ├── rocketlane_client.py            # Rocketlane REST API v1.0 client
│       ├── rocketlane_sla_automations.py   # Rocketlane native SLA rules (1-day PM, 4-day Owner)
│       ├── slack_client.py                 # Slack Web API client
│       ├── voice_ai_client.py              # Voice AI telephony client (Vapi / Retell / Bland)
│       └── gmail_poller.py                 # IMAP Gmail poller & draft staging service
│
├── scripts/                                # Operational execution CLI runners
│   ├── run_gmail_poller.py                 # Background poller CLI runner (mock / live)
│   ├── validate_e2e_live.py                # End-to-end live multi-tier validation script
│   ├── demo_rocketlane_agent3_live.py      # Interactive Agent 3 Data QA live demonstration
│   └── inspect_project_phases.py           # Rocketlane project metadata & phase inspector
│
└── tests/                                  # 100% Passing Pytest automated test suite (84 tests)
    ├── test_agent1.py                      # Agent 1 unit tests
    ├── test_agent2.py                      # Agent 2 unit tests
    ├── test_agent3.py                      # Agent 3 unit tests
    ├── test_assignment_part4.py            # Rocketlane SLA rules & template verification
    ├── test_edge_cases.py                  # Corrupted payloads, invalid dates, API errors
    ├── test_foundation.py                  # Audit logger, configs, and custom exceptions
    ├── test_gmail_poller.py                # IMAP poller, filter matching, mock injection
    ├── test_happy_path.py                  # Full end-to-end multi-agent happy path
    ├── test_phase1_e2e.py                  # Phase 1 integration verification
    ├── test_phase2_e2e.py                  # Phase 2 integration verification
    ├── test_phase3_e2e.py                  # Phase 3 integration verification
    ├── test_phase4_e2e.py                  # Phase 4 integration verification
    ├── test_template_accuracy.py           # Rocketlane Enterprise vs Growth template checks
    └── test_validation.py                  # Pydantic schema validation tests
```
