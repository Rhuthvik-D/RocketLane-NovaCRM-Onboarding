# Architectural Discussions & Engineering Decisions Log

This document serves as the single source of truth for architectural questions, trade-off evaluations, design discussions, and operational decisions across the **NovaCRM Customer Onboarding Multi-Agent System**.

---

## 📌 Discussion Index
1. [Decision 1: Rocketlane Template ID Management (Static `.env` vs. Dynamic API Discovery)](#1-rocketlane-template-id-management)
2. [Decision 2: Rocketlane Overdue Task Escalation Architecture](#2-rocketlane-overdue-task-escalation-architecture)
3. [Decision 3: Voice AI Outbound Telephony, Text Simulation, & Elimination Evaluation](#3-voice-ai-outbound-telephony--text-simulation)
4. [Decision 4: Slack Channel Privacy & Team Visibility](#4-slack-channel-privacy--team-visibility)
5. [Decision 5: Deterministic Native Agents vs. LLM Prompt Chaining](#5-deterministic-native-agents-vs-llm-prompt-chaining)
6. [Decision 6: Stage-Gating Data Migration (Agent 3 Gatekeeper) & Live Downstream Dispatch](#6-stage-gating-data-migration-agent-3-gatekeeper)
7. [Decision 7: Human-in-the-Loop Clarification via `[Gmail]/Drafts`](#7-human-in-the-loop-clarification-via-gmaildrafts)
8. [Decision 8: Local JSON File Idempotency Cache (Zero External Services)](#8-local-json-file-idempotency-cache-zero-external-services)
9. [Decision 9: Resilient Multi-Turn Email Thread Resolution & IMAP Socket Recovery](#9-resilient-multi-turn-email-thread-resolution--imap-socket-recovery)
10. [Gaps & Robustness Register (8 Code Gaps & Loose Ends Audit)](#10-gaps--robustness-register)
11. [Text Simulations Workflow (Design, Scenarios, & Runbook)](#11-text-simulations-workflow)
12. [Video Recording Talking Points: Live vs. Simulated / Mock APIs Across Primary & Secondary Integrations](#12-video-recording-talking-points-live-vs-simulated--mock-apis-across-primary--secondary-integrations)

---

## 1. Rocketlane Template ID Management

### Context & Question
Should the multi-agent system dynamically scrape / fetch onboarding template IDs from the Rocketlane REST API (`GET /templates`) using name matching at runtime, or should template IDs be fed via environment variables (`.env`)?

### Trade-off Evaluation
* **Option A: Pure Dynamic Discovery (`GET /templates` + string matching):**
  * *Pros:* Zero manual copying of IDs; system auto-detects whatever templates exist in the workspace.
  * *Risks in Production:* Fragile. If CS Operations (e.g., Priya) renames `Enterprise Tier - Onboarding` to `Enterprise Onboarding v2` or `Enterprise (Q3 Update)`, keyword matching fails or crashes. Additionally, if an admin creates a draft template like `Enterprise Tier - Onboarding (OLD)`, regex heuristics can mistakenly pick the deprecated template. Adds network latency before project creation.
* **Option B: Pure `.env` Configuration (12-Factor App):**
  * *Pros:* 100% deterministic, immutable, zero latency, and zero runtime ambiguity. Completely immune to cosmetic name edits in the Rocketlane UI. Conforms strictly to 12-Factor principles where environment settings dictate workspace resources.
  * *Risks in Production:* Requires updating `.env` if a template is deleted and recreated with a new ID.

### Final Decision
**Pure `.env` Configuration.** We enforce explicit configuration via:
* `ROCKETLANE_ENTERPRISE_TEMPLATE_ID=5000000095997`
* `ROCKETLANE_GROWTH_TEMPLATE_ID=5000000096288`
No automated scraping fallback is used at runtime to eliminate any possibility of accidental template mix-ups or naming-drift failures.

---

## 2. Rocketlane Overdue Task Escalation Architecture

### Context & Question
The assignment asks to handle overdue task escalation: 1 day overdue notifies the Project Manager; 4 days overdue notifies the Project Owner. Should this be an autonomous background AI agent or a platform-native automation?

### Assignment Constraint
The assignment prompt explicitly mandates:
> *"Rocketlane Automation - Overdue Task Escalation: Configure an automation within Rocketlane (not a separate agent) that handles overdue task escalation: when a task becomes overdue by 1 day, notify the Project Manager; when a task becomes overdue by 4 days, notify the Project Owner."*

### Final Decision
* **Live Implementation:** Configured natively directly within Rocketlane Settings ➔ Automations ➔ Rules under the active rule name: **`Task overdue escalation`**.
* **Code Implementation:** [`src/services/rocketlane_sla_automations.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/rocketlane_sla_automations.py) models and evaluates this exact declarative 2-tiered logic (`rule_sla_1day_pm` and `rule_sla_4day_owner`) so unit tests and CI pipelines can verify SLA compliance deterministically offline.
* **Validation Protocol & Status:** **`[NEEDS REVIEW]`**
  * *Live Platform Verification:* Create a test task with a due date set 1 day in the past (triggers PM notification) and another 4 days in the past (triggers Owner notification). Verify notification receipt via the Rocketlane in-app notification bell and inbox email delivery to `rd3377@nyu.edu`.
  * *Loom Recording Action:* Revisit and showcase the active rule toggle in Rocketlane Settings ➔ Automations during the walkthrough video.

---

## 3. Voice AI Outbound Telephony & Text Simulation

### Status: `[NEEDS REVIEW]`

### Context & Question
Inbound AE deal emails explicitly omit the plan tier (Enterprise vs. Growth). The Intake Agent must confirm the tier. Since outbound telephony providers lack free outbound PSTN calling tiers, how do we handle tier resolution, and what is the role of the voice agent?

### Trade-off Evaluation
* Outbound voice agents (Vapi, Retell AI, Bland AI) do not offer free outbound PSTN telephony; carrier termination requires a funded payment method, SIP trunk, or purchased DID number ($2+/mo + usage fees). Free trials restrict outbound dialing to verified phone numbers with strict zero-to-low minute limits.
* Relying on live phone dialing in automated test suites and continuous deployment is brittle, slow (30–60s per call), and fails whenever an AE is away or provider credits lapse.

### Final Decision & Implementation
* **Text Simulation Harness:** We implemented deterministic text simulation for tier choice via `VoiceAIClient.set_simulation_outcome(status, transcript)`. This provides realistic phone call transcripts (including spoken conversational filler like *"Hey, thanks for calling, this is definitely an Enterprise deal with custom SSO"*) to the downstream transcript analyzer.
* **Automated Test Coverage:** Figured out and implemented comprehensive automated test suites:
  * `test_transcript_analyzer_heuristics` in [`tests/test_agent1.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_agent1.py): Verifies NLP token matching across spoken enterprise/growth phrases.
  * `test_agent1_ambiguous_voice_escalation`: Verifies that ambiguous speech (*"maybe enterprise, check with Priya"*) generates an `EscalationTicket` for human CS review rather than guessing.
  * `test_agent1_unanswered_voice_escalation`: Verifies that unanswered calls escalate cleanly.
  * `test_agent1_automated_voice_enterprise_assumption`: Verifies the `voice_ai_assume_enterprise` fallback setting for unattended demonstrations.
* **Zero-Guessing Guardrail:** If an AE transcript contains ambiguity tokens (`"not sure"`, `"maybe"`, `"check later"`, `"i think"`), the pipeline halts and escalates rather than guessing a tier.

### 📝 Bottom Note (Architectural Direction to Revisit):
> **"Consider using the voice agent totally out of the scenario. Once the above cases are dealt with, we will visit this case. First, look into the current gaps."**

**Benefits & Drawbacks of Eliminating Voice Agent Completely:**
1. *Eliminating Voice Agent (Pros):*
   * Zero carrier telephony costs, zero PSTN latency (saves 30–60 seconds per deal).
   * Eliminates acoustic noise, speech-to-text hallucinations, and phone number provisioning overhead.
   * Plan tier can be captured deterministically either: (a) directly inside the deal email / Salesforce notification payload, or (b) via an automated interactive Slack button / email reply request to the AE.
2. *Eliminating Voice Agent (Cons):*
   * Loses the high-touch verbal confirmation mechanism described in the original assignment brief.
3. *Recommendation:* Revisit after all code gaps are verified and present to CS leadership as an operational optimization.

---

## 4. Slack Channel Privacy & Team Visibility

### Status: `[VERIFIED & RESOLVED]`

### Context & Question
When Agent 2 creates customer onboarding Slack channels (`#csm-ent-{slug}` or `#csm-grw-{slug}`), should they be public or private, and how do we ensure internal CSMs see them?

### Final Decision & Code Implementation
* **Privacy Enforcement:** Channels are created strictly as **private** (`is_private=True` in [`src/agents/agent2_communication.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/agent2_communication.py#L139)) to protect confidential customer data, contract details, and integration architecture from unauthorized eyes across the wider organization.
* **Auto-Invitation Engine:** In Slack's security model, private channels do not appear in user sidebars until an explicit invitation is received. [`SlackClient.invite_workspace_members()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/slack_client.py#L137) automatically queries the workspace team members and issues `conversations.invite` requests. This guarantees that newly provisioned customer onboarding channels immediately pop up in the human CSM's and CS Lead's active Slack sidebars with the topic and welcome message already posted.

---

## 5. Deterministic Native Agents vs. LLM Prompt Chaining

### Context & Question
Should the multi-agent system be orchestrated using frameworks like LangChain/CrewAI or implemented in native Python?

### Trade-off Evaluation
* LLM-orchestrated agent loops (CrewAI / AutoGen) introduce non-deterministic decision paths, high token cost, prompt injection risks, and 3–10 second latency overhead per step.
* Intake schema validation, idempotency hashing, and stage-gating are mathematical, deterministic business constraints that must never hallucinate.

### Final Decision
**Native Python 3.12 Architecture with Pydantic v2.**
* Pure typed data contracts.
* Microsecond latency and 100% deterministic decision repeatability.
* All state transitions and reasoning logged in append-only JSONL format via `AuditLogger`.

---

## 6. Stage-Gating Data Migration (Agent 3 Gatekeeper) & Downstream Dispatch

### Status: `[NEEDS REVIEW]` (Downstream Live Dispatch)

### Context & Question
Priya highlighted: *"We've had cases where data migration tasks were marked done but the customer's data wasn't actually verified - that caused a few ugly escalations."* How should Agent 3 enforce verification, and how should it unlock downstream phases in Rocketlane?

### Verification Checks & Gatekeeping Logic
[`Agent3DataQAGatekeeper`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/agent3_data_qa.py) enforces three non-negotiable checks before unlocking the downstream "Configuration" phase:
1. **Volume check:** `records_migrated > 0` (cannot complete an empty migration).
2. **Explicit Customer Sign-Off:** `customer_sign_off_confirmed == True` authorized by customer lead email.
3. **Record Parity:** `abs(records_migrated - records_verified) == 0` (zero discrepancy).
If any check fails, Configuration remains strictly locked and an alert is dispatched to CS Ops.

### Review Item: Live Downstream Task Status Update
* **Current State:** The verification logic is 100% verified across 12 comprehensive unit and integration tests.
* **Open Review:** In production, should Agent 3 issue a live Rocketlane REST API `PUT /tasks/{id}` call or trigger a webhook to toggle the downstream phase in Rocketlane directly, or should it post an approved verification certificate to the customer's Slack channel for human CSM sign-off? Tagged as `[NEEDS REVIEW]` for final sign-off.

---

## 7. Human-in-the-Loop Clarification via `[Gmail]/Drafts`

### Status: `[VERIFIED & RESOLVED]`

### Context & Question
When an AE sends an incomplete deal notification (e.g. missing `customer_contact_email` or `ae_phone`), how should the system request clarification without guessing?

### Final Decision
* The pipeline halts immediately (zero guesswork).
* [`IntakeParser.draft_clarification_email()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/intake_parser.py) drafts a structured, polite request to the AE enumerating the exact missing fields.
* [`GmailPoller.stage_clarification_draft()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py) inserts the draft directly into the Gmail account's **`[Gmail]/Drafts`** folder with proper `In-Reply-To` and `Re:` subject headers.
* Human CS Ops can review or customize the email in their Gmail UI before hitting send.
* When the AE replies in-thread, the poller matches the conversation via `_thread_deal_cache`, merges the newly supplied data with previously validated fields, and resumes the pipeline.

---

## 8. Local JSON File Idempotency Cache (Zero External Services)

### Status: `[VERIFIED & RESOLVED]`

### Context & Question
Rocketlane project creation must be strictly idempotent to prevent duplicate projects from being provisioned if an AE resends a deal email or network timeouts occur. Should we introduce an external database/caching service (e.g. Redis, DynamoDB), or use local storage?

### Final Decision & Code Implementation
* **Zero External Services:** In accordance with architectural simplicity and local deployment constraints, we rejected external dependencies like Redis.
* **Persistent Local File Storage:** [`RocketlaneClient`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/rocketlane_client.py#L61) maintains its idempotency cache in `logs/idempotency_cache.json`.
  * `_load_idempotency_cache()`: Restores previously provisioned project mappings on client startup.
  * `_persist_idempotency_cache()`: Atomically serializes new project records immediately upon successful creation.
* **Verification:** Verified by `test_rocketlane_client_idempotency_file_persistence` in [`tests/test_foundation.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_foundation.py#L143), confirming that duplicate deals across service restarts correctly detect existing projects and return them without re-hitting Rocketlane's API.

---

## 9. Resilient Multi-Turn Email Thread Resolution & IMAP Socket Recovery

### Status: `[VERIFIED & RESOLVED]`

### Context & Question
During multi-turn clarification with Account Executives:
1. What happens if an AE omits the `customer_name` in Turn 1, receives a clarification draft, and replies in Turn 2?
2. What happens if the Gmail IMAP connection drops during a background polling cycle?

### Final Decision & Code Implementation
1. **Multi-Key Thread Indexing:** [`GmailPoller.process_incoming_deals()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L366) builds and queries candidate cache keys across:
   * `customer_name` (canonical deal key)
   * `msg:{in_reply_to}` (RFC 5322 In-Reply-To header referencing previous draft/email)
   * `msg:{message_id}` (unique email identifier)
   * `subj:{clean_subject}` (normalized subject line stripped of `Re:`, `Fwd:`, and tags)
   This allows full thread state recovery and parameter merging even if `customer_name` was completely missing in the original inbound email.
2. **Automatic IMAP Socket Reset:**
   * In [`fetch_unread_deal_emails`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L264) and [`stage_clarification_draft`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L340), any transport exception triggers `self.disconnect()` immediately.
   * This clears the poisoned `_imap_client` socket handle, forcing a fresh SSL handshake and login on the next polling iteration rather than looping on broken pipes.

---

## 10. Gaps & Robustness Register

This section tracks the codebase robustness evaluation, code gaps, and loose ends identified during architectural auditing, along with their engineering resolutions, status tags, and open review items.

### 📋 Gaps & Resolutions Summary Table

| # | Gap / Loose End | Category | Resolution Status | Technical Resolution / Engineering Action |
|---|---|---|---|---|
| **Gap 1** | Slack Channel Privacy & Internal Visibility | Security & Visibility | `[VERIFIED & RESOLVED]` | Enforced `is_private=True` in [`Agent2Communication`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/agent2_communication.py#L139) to protect sensitive customer data. Added auto-invite mechanism via [`SlackClient.invite_workspace_members()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/slack_client.py#L137) so private channels immediately appear in internal CSMs' sidebars. |
| **Gap 2** | Agent 3 Data QA Gatekeeper Live Downstream Dispatch | Workflow & Automations | `[NEEDS REVIEW]` | Sign-off & 100% record parity logic is 100% verified across 12 tests. Tagged for review whether downstream phase unlocking should dispatch a live Rocketlane REST API `PUT /tasks/{id}` call or post an approved verification summary certificate to Slack. |
| **Gap 3** | Gmail Poller Multi-Turn Thread Caching when `customer_name` is Missing | Resilience & Ingestion | `[CODED & VERIFIED]` | Updated [`GmailPoller.process_incoming_deals()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L366) to index and query cache keys across `customer_name`, `msg:{in_reply_to}`, `msg:{message_id}`, and `subj:{subj_clean}`. Allows multi-turn state recovery on AE replies even if customer name was omitted in Turn 1. |
| **Gap 4** | Idempotency Persistence across Process Restarts (Local File Only) | Reliability & State | `[CODED & VERIFIED]` | Stored in local JSON file `logs/idempotency_cache.json` in [`RocketlaneClient`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/rocketlane_client.py#L61) with zero external service dependencies (no Redis, no external DB). Auto-loads on startup; verified by `test_rocketlane_client_idempotency_file_persistence`. |
| **Gap 5** | Automatic IMAP Socket Disconnect on Connection/Fetch Exceptions | Network Resilience | `[CODED & VERIFIED]` | Added `self.disconnect()` inside exception handlers of [`fetch_unread_deal_emails`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L264) and [`stage_clarification_draft`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L340). Prevents polling loop from reusing poisoned or broken socket handles. |
| **Gap 6** | Voice AI Outbound Telephony Replacement with Text Simulation | Testing & Telephony | `[NEEDS REVIEW]` | Outbound voice providers (Vapi, Retell AI) lack free outbound PSTN calling tiers. Implemented text simulation harness (`VoiceAIClient.set_simulation_outcome()`). Automated tests in [`tests/test_agent1.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_agent1.py) verify speech heuristic parsing, ambiguity escalation, and unanswered call handling. |
| **Gap 7** | Voice Agent Viability & Evaluation of Complete Elimination | Architecture & Scope | `[DOCUMENTED & ON HOLD]` | User bottom note recorded: evaluate eliminating the voice agent entirely from the architecture once current gaps are resolved. Tier choice can be resolved via direct email payload or interactive Slack blocks. |
| **Gap 8** | Rocketlane Cloud `externalReferenceId` Collision & Poller Exception Boundary | Reliability & Error Handling | `[CODED & VERIFIED]` | Rocketlane returns HTTP 400 (`Bad Request: Invalid External Reference Key specified`) instead of HTTP 409 when `externalReferenceId` exists. Added self-healing cloud reconciliation in [`RocketlaneClient.create_project()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/rocketlane_client.py#L309) via `GET /projects?externalReferenceId.EQUALS={key}`, local cache sync, and an exception boundary in [`GmailPoller.process_incoming_deals()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L442). |

---

### Detailed Record of Each Gap

#### Gap 1: Slack Channel Privacy & Team Member Visibility
* **Identified Loose End:** When customer onboarding channels were created, setting `is_private=True` without auto-inviting team members caused channels to remain invisible in the human CSM's Slack sidebar due to Slack's private channel security model.
* **Resolution Applied:**
  * Hardened [`Agent2Communication.process_project_handoff()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/agent2_communication.py#L139) to strictly enforce `is_private=True`.
  * Implemented [`SlackClient.invite_workspace_members()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/slack_client.py#L137) to automatically discover internal human workspace members and dispatch `conversations.invite`.
  * Verified live in Slack workspace `T0C4RF0PWHF`: private channel `#csm-ent-apex-dynamics-64950` (`C0C49FFEGH5`) was provisioned and visible in user `U0C4MJ5EU6S`'s sidebar.
* **Status:** `[VERIFIED & RESOLVED]`

#### Gap 2: Agent 3 Data QA Gatekeeper Live Downstream Dispatch
* **Identified Loose End:** While [`Agent3DataQAGatekeeper`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/agent3_data_qa.py) perfectly verifies customer sign-off and 100% record parity, the live downstream dispatch against Rocketlane's task status was not linked to a live production webhook trigger.
* **Resolution Applied:**
  * Tagged as `[NEEDS REVIEW]` in the project registry.
  * Codified the exact downstream dispatch contract ready for either: (a) automated `PUT /tasks/{id}` status update to "COMPLETED", or (b) dispatching an approved QA Certificate directly to the customer's Slack channel.
* **Status:** `[NEEDS REVIEW]`

#### Gap 3: Gmail Poller Multi-Turn Thread Deal Caching
* **Identified Loose End:** If an Account Executive sent an initial deal email lacking `customer_name`, the clarification draft was staged in `[Gmail]/Drafts`, but the thread cache was keyed purely on `customer_name`. When the AE replied in Turn 2, the poller could not look up Turn 1's partial deal state.
* **Resolution Applied:**
  * Refactored [`GmailPoller.process_incoming_deals()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L366-L388) to index and query cache keys across 4 distinct candidates: `customer_name`, `msg:{in_reply_to}`, `msg:{message_id}`, and `subj:{subj_clean}`.
  * Even with a blank customer name, the deal is cached under its RFC 5322 Message-ID and normalized subject line. When the AE replies in-thread, Turn 1 data is seamlessly recovered and merged.
  * Verified by `test_gmail_poller_ae_reply_threads_missing_field_from_quotes` and `test_gmail_poller_multi_missing_fields_consolidated_in_single_draft_and_cached` in [`tests/test_gmail_poller.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_gmail_poller.py).
* **Status:** `[CODED & VERIFIED]`

#### Gap 4: Local File Idempotency Cache (Zero External Services)
* **Identified Loose End:** In-memory idempotency caching in `RocketlaneClient` did not survive process restarts. If the background daemon restarted or crashed, duplicate deals could trigger duplicate project creations in Rocketlane.
* **Resolution Applied:**
  * Enhanced [`RocketlaneClient`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/rocketlane_client.py#L61) with persistent local file storage bound to `logs/idempotency_cache.json`.
  * Implemented `_load_idempotency_cache()` and `_persist_idempotency_cache()` with zero external service dependencies (no Redis, Memcached, or cloud databases).
  * Added persistence test `test_rocketlane_client_idempotency_file_persistence` in [`tests/test_foundation.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_foundation.py#L143) confirming duplicate detection survives across fresh client instantiations.
* **Status:** `[CODED & VERIFIED]`

#### Gap 5: Automatic IMAP Socket Reset on Network/Fetch Exceptions
* **Identified Loose End:** If an IMAP socket connection suffered a TCP timeout or SSL reset during background polling, subsequent iterations continued attempting calls against the poisoned client handle, logging cascading `imaplib.abort` errors.
* **Resolution Applied:**
  * Added `self.disconnect()` in exception blocks of [`fetch_unread_deal_emails`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L264) and [`stage_clarification_draft`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L340).
  * Cleans up the invalid connection handle so the next polling iteration initiates a fresh SSL handshake and login.
* **Status:** `[CODED & VERIFIED]`

#### Gap 6: Voice AI Outbound Telephony & Text Simulation Harness
* **Identified Loose End:** Outbound telephony vendors (Vapi, Retell AI, Bland AI) lack free outbound calling tiers; free trials enforce 0 outbound PSTN minutes unless a paid balance or SIP trunk is attached.
* **Resolution Applied:**
  * Tagged as `[NEEDS REVIEW]`.
  * Implemented deterministic text simulation via `VoiceAIClient.set_simulation_outcome(status, transcript)`.
  * Verified automated tests across all voice paths: heuristic speech parsing ([`test_transcript_analyzer_heuristics`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_agent1.py#L112)), ambiguity escalation ([`test_agent1_ambiguous_voice_escalation`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_agent1.py#L58)), and unattended enterprise assumption ([`test_agent1_automated_voice_enterprise_assumption`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_agent1.py#L131)).
* **Status:** `[NEEDS REVIEW]`

#### Gap 7: Voice Agent Viability & Elimination Bottom Note
* **Recorded Mandate:**
  > *"Consider using the voice agent totally out of the scenario. Once the above cases are dealt with, we will visit this case. First, look into the current gaps."*
* **Architectural Evaluation Logged:**
  * **Pros of Complete Removal:** Zero PSTN calling costs, zero carrier latency (saves 30–60s per deal), zero speech-to-text ambiguity/hallucination, simplified architecture. Tier choice can be deterministically captured in inbound deal email / Salesforce notification payload or via automated interactive Slack blocks.
  * **Cons of Removal:** Deviates from the verbal AE phone confirmation requirement in the original assignment brief.
  * **Current State:** Recorded and held for strategic review after all code gaps are finalized.
* **Status:** `[DOCUMENTED & ON HOLD]`

#### Gap 8: Rocketlane Cloud `externalReferenceId` Collision & Poller Exception Boundary
* **Identified Loose End / Root Cause Analysis:**
  * When an Account Executive sends an email for an existing customer (e.g., "CyberScript Systems") whose project was provisioned in a prior session or whose idempotency key was missing from the local file cache, Rocketlane cloud rejects duplicate `externalReferenceId` keys with `HTTP 400 Bad Request: {"errors":[{"code":"INVALID_INPUTS","reason":"Bad Request: Invalid External Reference Key specified"}]}` rather than standard `HTTP 409 Conflict`.
  * In [`GmailPoller.process_incoming_deals()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L402), per-deal execution was not wrapped in an exception boundary, causing unhandled client API exceptions to bubble up and crash the background email polling daemon process entirely.
* **Resolution Applied:**
  * **Self-Healing Cloud Idempotency:** Implemented `_execute_http_get()` and `_reconcile_cloud_project()` in [`RocketlaneClient`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/rocketlane_client.py#L187). When `create_project()` catches a `RocketlaneAPIError` with status 400 and reason `"Invalid External Reference Key specified"`, it queries Rocketlane's cloud endpoint (`GET /projects?externalReferenceId.EQUALS={idempotency_key}`), retrieves the pre-existing project ID (`5000000208093`), updates `self._idempotency_cache` and `logs/idempotency_cache.json`, records audit action `create_project_idempotent_cloud_reconciliation`, and returns the project marked as duplicate (`is_duplicate=True`).
  * **Daemon Fault Tolerance & Exception Isolation:** Wrapped the per-deal processing block inside [`GmailPoller.process_incoming_deals()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/gmail_poller.py#L442) in a `try...except Exception as deal_err:` block. Unhandled exceptions are logged to `logs/audit_trail.jsonl` under `deal_processing_failed` without terminating the polling daemon. In addition, the main loop in `start_polling()` was wrapped in an inner try-except block to defend against unexpected transport crashes.
  * **Historical Project Cache Synchronization:** Reconciled 45 existing Rocketlane cloud project references from historical audit records into `logs/idempotency_cache.json` (including `CyberScript Systems` key `d7fcf2a9c598d37763531f3fb12f85a7aae9f46783df76e1755d504bed430a5c`).
  * **Automated Unit & Live Verification:** Added unit tests `test_rocketlane_client_self_healing_cloud_reconciliation_on_400_duplicate` in [`tests/test_foundation.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_foundation.py#L183) and `test_gmail_poller_survives_deal_processing_exception` in [`tests/test_gmail_poller.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_gmail_poller.py#L249). Verified live against Rocketlane API for both cache-hit and self-healing cloud recovery paths.
* **Architectural Clarification on Duplicate Handling vs. Timestamp Slugs:**
  * **Zero Duplicate Project Creation in Rocketlane:** When identical customer or deal information is received for an existing customer, the system **does NOT create a second project**, nor does it append a timestamp slug to the project name in Rocketlane. Rocketlane strictly rejects duplicate `externalReferenceId` keys. The self-healing workflow catches the collision, retrieves the original pre-existing project entity (e.g., Project ID `5000000208093` for `CyberScript Systems`), flags it as `is_duplicate=True`, and skips creation. This guarantees zero duplicate workspaces, zero duplicated onboarding checklists/tasks, and zero duplicate customer billing.
  * **Distinction from Slack Channel Collision Resolution:** The timestamp suffix mechanism exists strictly in Slack channel provisioning ([`SlackClient.create_channel()`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/slack_client.py#L75-L79)). If Slack returns `error: "name_taken"` because a channel handle already exists in the workspace, a 3-digit numeric suffix (`f"-{timestamp % 1000:03d}"`) is appended to the channel handle to prevent Slack API failures. This is isolated to Slack handles and does not affect Rocketlane projects.
  * **Distinction from Automated Test Script Identifiers:** Automated test suites (e.g., [`tests/test_assignment_part4.py`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/tests/test_assignment_part4.py)) intentionally appended Unix timestamps (e.g., `Acme Global Labs 1790608119`) to company names strictly to generate fresh, distinct entities during automated CI test runs.
* **Status:** `[CODED & VERIFIED]`

---

## 11. Text Simulations Workflow

### Context & Strategic Purpose
The assignment specification asks for verbal plan tier confirmation from the Account Executive via Voice AI before provisioning Rocketlane projects. However, because outbound PSTN telephony providers lack free outbound carrier tiers (requiring funded carrier balances or SIP trunk provisioning to dial real mobile numbers), the system utilizes a **Telephony Simulation Adapter** (`VoiceAIClient.set_simulation_outcome()`).

This workflow ensures complete test coverage and verification for both positive (happy path) and negative (unanswered, ambiguous) telephony scenarios while keeping the real Vapi client integration intact for production environments.

---

### 🏛️ Simulation Architecture: Dual-Mode Operation
1. **Production Mode:** [`VoiceAIClient`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/services/voice_ai_client.py) connects directly to Vapi's REST API (`POST https://api.vapi.ai/call`) using Assistant ID `c5333979-6cce-408b-8662-69ac2a444023` and Phone Number ID `858f2f46-4a19-4eec-965d-2cfd791fb12f` (`+15312231089`). It dials the AE's mobile phone and polls `GET /call/{id}` for completion and audio transcripts.
2. **Simulation / CI Mode:** The simulation harness injects structured telephony outcomes (`VoiceCallStatus`) and realistic spoken conversational transcripts directly into [`VoiceGuardrail`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/voice_guardrail.py). This allows automated test suites and demonstration scripts to verify complex guardrail decisions deterministically, instantaneously, and with zero telecom carrier fees.

---

### 🧪 Detailed Simulation Scenarios

#### Scenario 1: AE Does Not Answer the Call (`UNANSWERED`)
* **Simulated Telephony Event:**
  * Outbound call dispatches to the AE's phone (`ae_phone`).
  * Telephony event returns after 30 seconds of ringing with no pickup, or a standard carrier voicemail greeting tone is detected.
  * **Injected Status:** `VoiceCallStatus.UNANSWERED`
  * **Simulated Transcript:** `"[NO_ANSWER: Ring timeout exceeded (30s) / Voicemail tone detected]"`
  * **Confidence Score:** `0.0`
* **Pipeline Behavior & Outcome:**
  1. **Strict Provisioning Block:** [`Agent1Intake`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/agent1_intake.py) halts immediately. Rocketlane project creation is **blocked** (preventing default tier assumptions or template mix-ups).
  2. **Escalation Ticket Generated:** An [`EscalationTicket`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/models/schemas.py#L112) is created with:
     * `ticket_id`: e.g., `ESC-VOICE-UNANSWERED-9821`
     * `customer_name`: `Acme Corp`
     * `ae_name`: `Sarah Connor`
     * `reason`: `"AE did not answer the tier confirmation call after ringing timeout."`
     * `suggested_action`: *"CS Ops to message AE on Slack or follow up via email before creating project manually."*
  3. **Downstream Skipping:** [`Agent2Communication`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/agents/agent2_communication.py) detects that Agent 1 halted and skips Slack channel provisioning.
  4. **Audit Trail:** An immutable `voice_guardrail_escalated_unanswered` record is appended to `logs/audit_trail.jsonl` with status `ESCALATED`.

#### Scenario 2: AE Gives an Ambiguous / Hedging Reply (`AMBIGUOUS`)
* **Simulated Telephony Event:**
  * Call connects, but the AE is hesitant, hedges, or mentions contradictory tiers.
  * **Injected Status:** `VoiceCallStatus.AMBIGUOUS`
  * **Simulated Spoken Transcript:**
    > *"Hey! Yeah, for Nexus Retail... I think they're probably going with Growth, but honestly they might upgrade to Enterprise next week if their VP signs off. Not totally sure yet, maybe check with Priya."*
  * **Confidence Score:** Evaluated by heuristic NLP parser at `0.40` (below the `0.80` safety threshold).
* **Guardrail Analysis:**
  * Detects hedge keywords: `"i think"`, `"might upgrade"`, and `"not totally sure"`.
  * Detects conflicting tier tokens: mentions both `"growth"` and `"enterprise"`.
  * Flags confidence score as unsafe.
* **Pipeline Behavior & Outcome:**
  1. **Zero-Guessing Guardrail:** Execution freezes immediately. System refuses to assume Growth (lower tier) or Enterprise (higher tier).
  2. **Escalation Ticket with Context:** Generates an [`EscalationTicket`](file:///D:/SEMS/temp/Rocketlane%20-%20assignment/src/models/schemas.py#L112) containing the verbatim transcript so human CS Ops can resolve the ambiguity without re-calling the AE.
  3. **Downstream Skipping:** Rocketlane project and Slack channel creation are strictly blocked.
  4. **Audit Trail:** Appends `voice_guardrail_escalated_ambiguity` to `logs/audit_trail.jsonl` with status `ESCALATED`.

#### Scenario 3: Confirmed Enterprise Tier (Happy Path)
* **Simulated Telephony Event:**
  * Call connects, AE confirms Enterprise cleanly.
  * **Injected Status:** `VoiceCallStatus.CONFIRMED`
  * **Simulated Spoken Transcript:**
    > *"Hi! Yes, Apex Dynamics signed the Enterprise plan. We agreed on a 30-day onboarding with a dedicated CSM and custom SSO setup."*
  * **Confidence Score:** `0.95`
* **Pipeline Behavior & Outcome:**
  1. **Rocketlane Project Created:** Provisions with Template `5000000095997` (*Enterprise Tier - Onboarding*), 30-day milestone duration, assigned Dedicated CSM.
  2. **Agent 2 Dispatched:** Creates private Slack channel `#csm-ent-apex-dynamics`, embeds Rocketlane portal link in topic, posts Enterprise kickoff greeting, and auto-invites team members.
  3. **Audit Trail:** Appends `voice_guardrail_passed` with status `SUCCESS`.

#### Scenario 4: Confirmed Growth Tier (Happy Path)
* **Simulated Telephony Event:**
  * Call connects, AE confirms Growth tier.
  * **Injected Status:** `VoiceCallStatus.CONFIRMED`
  * **Simulated Spoken Transcript:**
    > *"Hey, this is a standard Growth tier deal for 15 seats. Standard 14-day pooled onboarding checklist is fine."*
  * **Confidence Score:** `0.95`
* **Pipeline Behavior & Outcome:**
  1. **Rocketlane Project Created:** Provisions with Template `5000000096288` (*Growth Tier - Onboarding*), 14-day milestone duration, pooled CSM staffing.
  2. **Agent 2 Dispatched:** Creates private Slack channel `#csm-grw-apex-dynamics`, embeds Rocketlane portal link in topic, posts pooled CSM kickoff greeting, and auto-invites team members.
  3. **Audit Trail:** Appends `voice_guardrail_passed` with status `SUCCESS`.

---

### 📊 Summary Comparison Matrix

| Simulation Scenario | AE Phone Response / Transcript | Injected Status | Guardrail Decision | Rocketlane Project Created? | Slack Channel Created? | CS Ops Escalation Ticket? |
|---|---|---|---|---|---|---|
| **1. Unanswered Call** | Ring timeout / Voicemail greeting | `UNANSWERED` | **HALT** | ❌ None (Blocked) | ❌ Skipped | ✅ Yes (`ESC-VOICE-UNANSWERED`) |
| **2. Ambiguous Reply** | *"I think Growth, but maybe Enterprise..."* | `AMBIGUOUS` | **HALT** | ❌ None (Blocked) | ❌ Skipped | ✅ Yes (`ESC-VOICE-AMBIGUOUS`) |
| **3. Confirmed Enterprise** | *"Confirmed, this is an Enterprise deal with 50 seats."* | `CONFIRMED` | **PROCEED** | ✅ Enterprise Template (`5000000095997`, 30d) | ✅ `#csm-ent-*` (Dedicated CSM) | ❌ None (Clean run) |
| **4. Confirmed Growth** | *"This is standard Growth tier, 14-day onboarding."* | `CONFIRMED` | **PROCEED** | ✅ Growth Template (`5000000096288`, 14d) | ✅ `#csm-grw-*` (Pooled CSM) | ❌ None (Clean run) |

---

### 🎬 Loom Video Walkthrough Presentation Runbook
During the recorded video submission:
1. **Show Live Vapi Configuration (30 seconds):** Screen-share the active Vapi dashboard showing Assistant ID `c5333979-6cce-408b-8662-69ac2a444023`, system prompt instructions, and voice model to establish real Voice AI architecture.
2. **Explain Dual-Mode Adapter (20 seconds):** Explain that `VoiceAIClient` supports live REST dialing for production, but utilizes the deterministic text simulation adapter for testing and walkthrough demonstrations to avoid carrier limits.
3. **Run Positive Sample:** Run the pipeline demonstrating deal email ingestion, confirmed Enterprise voice outcome, live Rocketlane project creation with 30-day template, and private Slack channel creation.
4. **Run Negative Sample 1 (Unanswered Call):** Run simulation with unanswered status, demonstrating immediate pipeline halt, zero project created, and escalation ticket generated.
5. **Run Negative Sample 2 (Ambiguous Call):** Run simulation with contradictory transcript (*"maybe growth, maybe enterprise"*), showing NLP keyword detection, verbatim transcript capture, and guardrail enforcement.

---

## 12. Video Recording Talking Points: Live vs. Simulated / Mock APIs Across Primary & Secondary Integrations

### Context & Strategic Purpose for Video Presentation
During the video walkthrough submission, evaluators examine which integrations are operating against live cloud services versus mocks or simulations. The assignment prompt explicitly states:
> *(Note: A simulated/mocked Slack API is acceptable as long as the data payload is structurally sound)*

Our engineering philosophy went significantly beyond this minimum requirement: we adopted a **"Dual-Mode Adapter" architecture** that provides **100% LIVE production integrations** for Rocketlane, Slack, and Gmail, while utilizing deterministic simulations where telecom carrier barriers exist (Voice AI PSTN calling) and for isolated CI unit tests.

This section provides the exact talking points, architectural rationale, and summary cheat sheet to present during the Loom video recording.

---

### 🎙️ Video Presentation Script & Talking Points

#### 1. Rocketlane (Primary Integration) — 100% LIVE
* **What to say in the video:**
  > *"For our primary integration, Rocketlane, we are operating 100% against the live Rocketlane REST API. Every deal provisions an actual cloud project using real workspace templates—Template 5000000095997 for Enterprise with 30-day timelines and dedicated CSM staffing, and Template 5000000096288 for Growth with 14-day timelines and pooled CSM staffing. The integration features automated exponential backoff retries via Tenacity for HTTP 500 errors and self-healing SHA-256 cloud idempotency reconciliation to strictly prevent duplicate projects."*
* **What to show on screen:**
  * Screen-share the active Rocketlane project dashboard showing the provisioned project (e.g., `Apex Dynamics 64950` or `CyberScript Systems`).
  * Highlight the populated phases (`Kickoff & Readiness`, `Solutioning & Planning`, `Implementation`, `Go-live & Value Delivery`) and 100+ tasks imported from the template.

#### 2. Slack (Secondary Integration) — 100% LIVE (Mock Permitted by Brief)
* **What to say in the video:**
  > *"For our secondary integration with Slack, the assignment brief specifically stated that a simulated or mocked Slack API was acceptable as long as the payload was structurally sound. However, we went further and implemented a 100% live Slack Web API client using real Bot OAuth tokens. In live mode, Agent 2 actually creates real private Slack channels (`#csm-ent-*`), embeds the live Rocketlane project URL directly into the channel topic, auto-invites internal CSM team members so the private channel appears in their sidebar, and posts a tier-tailored kickoff welcome message. We only toggle mock mode on during automated unit testing so CI tests run offline without consuming Slack API rate limits."*
* **What to show on screen:**
  * Screen-share the Slack workspace (`novacrmonboar-lox2926.slack.com`), showing the private channel `#csm-ent-apex-dynamics-64950`, the topic containing the Rocketlane URL, and the formatted welcome message.

#### 3. Inbound Deal Intake (Gmail IMAP & Drafts) — 100% LIVE
* **What to say in the video:**
  > *"For deal ingestion, Agent 1 is triggered by a live Gmail IMAP poller connecting over TLS to our CS inbox. It parses real incoming AE deal notification emails and multi-turn reply threads. Crucially, when an email arrives with missing required fields, the agent enforces a zero-guessing human-in-the-loop guardrail: instead of hallucinating or sending premature emails, it directly stages a pre-composed clarification draft into the human CSM's live `[Gmail]/Drafts` folder ready for review."*
* **What to show on screen:**
  * Show the incoming deal email in the inbox, and show the staged clarification draft in the `Drafts` folder.

#### 4. Voice AI / Telephony (Secondary Integration) — Real Vapi Client Built, Telephony Simulation Adapter Used for Demo
* **What to say in the video:**
  > *"For the Voice AI verbal tier confirmation requirement, we built a full production integration with Vapi's REST API using an active Assistant ID and configured phone number (+15312231089). However, because outbound PSTN calling to real mobile phone numbers requires a funded carrier balance or a configured SIP trunk with 0 free outbound minutes on trial tiers, we implemented a dual-mode Telephony Simulation Adapter. In this walkthrough, I will demonstrate how the simulation adapter injects both positive outcomes (confirmed Enterprise / Growth) and negative edge cases (unanswered ring timeouts and ambiguous AE replies) into our NLP guardrail, proving that our ambiguity detection, confidence scoring, and human CS escalation ticket generation work flawlessly without incurring telecom carrier fees."*
* **What to show on screen:**
  * Screen-share the Vapi dashboard displaying the Assistant configuration (`c5333979-6cce-408b-8662-69ac2a444023`) to prove real API setup.
  * Run the simulation showing the guardrail evaluating transcript ambiguity and generating an escalation ticket.

---

### 📊 Summary Cheat Sheet for Video Walkthrough

| Integration | Tier / Category | Prompt Constraint | Live API Implemented? | Production State | Why Simulation/Mock Exists |
|---|---|---|---|---|---|
| **Rocketlane** | **Primary** | Full API integration & retries required | ✅ Yes | **100% LIVE** | Offline CI/CD unit testing (`mock_mode=True`) |
| **Slack** | **Secondary** | Mock explicitly permitted by prompt | ✅ Yes | **100% LIVE** | Offline CI/CD unit testing to avoid rate limits |
| **Gmail** | **Secondary** | Inbound deal monitoring required | ✅ Yes | **100% LIVE** | Fast unit test mock injection (`inject_mock_email`) |
| **Voice AI (Vapi)** | **Secondary** | Outbound phone confirmation required | ✅ Yes | ⚠️ **Text Simulation** | Overcomes PSTN telephony carrier restrictions & zero trial credits |



