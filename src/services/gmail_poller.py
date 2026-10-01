"""Resilient Gmail IMAP listener service for automated CS inbox deal monitoring and extraction."""

from datetime import datetime, timezone
import email
from email.header import decode_header
from email.message import EmailMessage, Message
import email.utils
import imaplib
import logging
import re
import time
from typing import Any, Optional

from src.agents.agent1_intake import Agent1Intake, agent1_intake
from src.agents.agent2_communication import Agent2Communication, agent2_communication
from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.models.schemas import AuditActionStatus, ClarificationDraft

_logger = logging.getLogger("gmail_poller")


class GmailPoller:
    """Monitors a Customer Success Gmail inbox via IMAP for incoming deal notifications from AEs.

    Handles secure SSL IMAP connections, multi-part MIME parsing, resilient regex and heuristic
    parameter extraction, multi-turn reply thread caching, human-in-the-loop clarification draft
    staging in Gmail's Drafts folder, and pipeline coordination across Agent 1 and Agent 2.
    """

    def __init__(
        self,
        user: Optional[str] = None,
        password: Optional[str] = None,
        poll_interval: Optional[int] = None,
        subject_filter: Optional[str] = None,
        mock_mode: bool = False
    ) -> None:
        """Initializes the Gmail poller with server credentials, filtering parameters, and state stores.

        Args:
            user: Gmail address to monitor. Defaults to settings.gmail_user.
            password: App Password for IMAP SSL authentication. Defaults to settings.gmail_app_password.
            poll_interval: Delay in seconds between polling cycles. Defaults to settings.gmail_poll_interval.
            subject_filter: Case-insensitive search string to filter deal emails. Defaults to settings.gmail_subject_filter.
            mock_mode: If True, uses simulated in-memory email queues instead of live IMAP connections.
        """
        self.user: str = user or settings.gmail_user
        self.password: str = password or settings.gmail_app_password
        self.poll_interval: int = poll_interval or settings.gmail_poll_interval
        self.subject_filter: str = subject_filter or settings.gmail_subject_filter
        self.mock_mode: bool = mock_mode
        self._mock_inbox: list[dict[str, Any]] = []
        self._staged_drafts: list[dict[str, Any]] = []
        self._thread_deal_cache: dict[str, dict[str, Any]] = {}
        self._imap_client: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> bool:
        """Connects and logs into the Gmail IMAP server using SSL and configured App Password.

        Execution Branches:
            - Branch 1 (Mock Mode): Bypasses network calls and immediately returns True.
            - Branch 2 (Missing Credentials): Returns False if GMAIL_APP_PASSWORD is not configured.
            - Branch 3 (Live IMAP SSL): Establishes encrypted socket to imap.gmail.com:993 and authenticates.

        Returns:
            bool: True if connected and authenticated successfully, False otherwise.
        """
        # Branch 1: Mock Mode Simulation Bypass
        if self.mock_mode:
            _logger.info("[MOCK] Connected to simulated Gmail inbox.")
            return True

        # Branch 2: Missing Credentials Guard
        if not self.password:
            _logger.warning("GMAIL_APP_PASSWORD not set in .env. Gmail polling cannot authenticate.")
            return False

        # Branch 3: Live IMAP SSL Socket Connection & Authentication
        try:
            self._imap_client = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            self._imap_client.login(self.user, self.password)
            _logger.info(f"Successfully authenticated to Gmail inbox: {self.user}")
            return True
        except Exception as exc:
            _logger.error(f"Failed to connect to Gmail ({self.user}): {exc}")
            return False

    def disconnect(self) -> None:
        """Closes the mailbox and logs out of the IMAP session, releasing socket resources."""
        if self._imap_client is not None:
            try:
                self._imap_client.close()
                self._imap_client.logout()
            except Exception:
                pass
            self._imap_client = None

    def _decode_header_str(self, header_raw: Optional[str]) -> str:
        """Safely decodes an RFC 2047 encoded email header value into a normalized UTF-8 string.

        Args:
            header_raw: Raw header string from MIME message (e.g. '=?UTF-8?B?...?=').

        Returns:
            str: Decoded and stripped header text, or empty string if input was None/empty.
        """
        if not header_raw:
            return ""
        decoded_parts = decode_header(header_raw)
        result_str = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result_str += part.decode(encoding or "utf-8", errors="replace")
            else:
                result_str += str(part)
        return result_str.strip()

    def _extract_body_text(self, msg: Message) -> str:
        """Walks MIME message parts and extracts the primary plain-text email body.

        Navigates multipart message structures (such as multipart/alternative and multipart/mixed),
        ignoring attachments to extract decoded UTF-8 plain text.

        Args:
            msg: Parsed email.message.Message instance.

        Returns:
            str: Clean, stripped plain-text email body.
        """
        body_content = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_content += payload.decode("utf-8", errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body_content = payload.decode("utf-8", errors="replace")
        return body_content.strip()

    def parse_deal_from_email(
        self,
        message_id: str,
        sender: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None
    ) -> dict[str, Any]:
        """Parses email subject, sender, and body into a structured deal dictionary.

        Employs a resilient 3-stage extraction pipeline:
            - Stage 1 (Sender Decomposition): Extracts AE name and AE email from From header.
            - Stage 2 (Line-by-Line Regex Key-Value Parser): Strips email reply quote marks ('>', '|')
              and matches standard labels for customer name, contact email, AE name, phone, and SFDC URL.
            - Stage 3 (Contextual Fallback Heuristics): Extracts customer name from cleaned subject line,
              Salesforce link from raw body text, customer contact email via domain/sender exclusion,
              and AE telephone digits from URL-stripped body text.

        Args:
            message_id: Unique RFC 2822 Message-ID or IMAP sequence identifier.
            sender: Raw 'From' header string.
            subject: Email subject line.
            body: Plain-text email body content.
            in_reply_to: Optional Message-ID of the parent email in reply threads.

        Returns:
            dict[str, Any]: Extracted deal payload ready for ingestion by Agent 1 Intake.
        """
        extracted: dict[str, Any] = {
            "message_id": message_id,
            "subject": subject,
            "in_reply_to": in_reply_to,
            "customer_name": "",
            "customer_contact_email": "",
            "ae_name": "",
            "ae_phone": "",
            "opportunity_url": None,
            "ae_email": ""
        }

        # -------------------------------------------------------------------------
        # Stage 1: Parse sender email and name from "From" header
        # -------------------------------------------------------------------------
        if "<" in sender and ">" in sender:
            name_part = sender.split("<")[0].strip().strip("\"'")
            email_part = sender.split("<")[1].split(">")[0].strip()
            extracted["ae_name"] = name_part
            extracted["ae_email"] = email_part
        else:
            extracted["ae_email"] = sender.strip()

        # -------------------------------------------------------------------------
        # Stage 2: Key-value line parser inspecting body text (including quoted email history)
        # -------------------------------------------------------------------------
        for line in body.splitlines():
            line_clean = re.sub(r"^[>\s|]+", "", line).strip()
            if not line_clean:
                continue

            # Customer Name pattern
            cust_match = re.match(r"^(?:customer|company|client|account)(?:\s*name)?\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)
            if cust_match and not extracted["customer_name"]:
                extracted["customer_name"] = cust_match.group(1).strip()
                continue

            # Customer Contact Email pattern
            email_match = re.match(r"^(?:customer\s*contact\s*email|contact\s*email|customer\s*email|client\s*email)\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)
            if email_match and not extracted["customer_contact_email"]:
                extracted["customer_contact_email"] = email_match.group(1).strip()
                continue

            # AE Name pattern
            ae_match = re.match(r"^(?:ae\s*name|account\s*executive|sales\s*rep|ae)\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)
            if ae_match and not extracted["ae_name"]:
                extracted["ae_name"] = ae_match.group(1).strip()
                continue

            # AE Phone pattern
            phone_match = re.match(r"^(?:ae\s*phone|ae\s*mobile|phone|mobile|cell)\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)
            if phone_match and not extracted["ae_phone"]:
                extracted["ae_phone"] = phone_match.group(1).strip()
                continue

            # Opportunity URL pattern
            opp_match = re.match(r"^(?:opportunity(?:\s*url)?|salesforce(?:\s*url)?|sfdc(?:\s*link)?)\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)
            if opp_match and not extracted["opportunity_url"]:
                extracted["opportunity_url"] = opp_match.group(1).strip()
                continue

        # -------------------------------------------------------------------------
        # Stage 3: Contextual fallback heuristics if key-value labels were omitted
        # -------------------------------------------------------------------------
        # Fallback 3A: Customer name from subject line
        if not extracted["customer_name"]:
            subj_clean = re.sub(r"^(?:re|fwd|fw)\s*:\s*", "", subject, flags=re.IGNORECASE)
            subj_clean = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", subj_clean)
            subj_clean = re.sub(r"^(?:clarification\s*(?:needed|requested)?\s*(?:for)?|new\s*deal|deal\s*closed|onboarding)\s*[:\-]?\s*", "", subj_clean, flags=re.IGNORECASE)
            subj_clean = re.sub(r"\s*(?:-|–)?\s*onboarding.*$", "", subj_clean, flags=re.IGNORECASE).strip()
            if subj_clean and len(subj_clean) > 1:
                extracted["customer_name"] = subj_clean

        # Fallback 3B: Salesforce / Force.com Opportunity URL in body
        if not extracted["opportunity_url"]:
            url_match = re.search(r"https://[a-zA-Z0-9.\-_]+(?:\.salesforce\.com|\.force\.com)/[^\s]+", body)
            if url_match:
                extracted["opportunity_url"] = url_match.group(0).rstrip(". ,;:)").strip()

        # Fallback 3C: External contact email scan (excluding sender and CS inbox)
        if not extracted["customer_contact_email"]:
            emails_found = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-]+", body)
            for e in emails_found:
                clean_email = e.rstrip(". ,;:)").strip()
                if clean_email.lower() != extracted["ae_email"].lower() and clean_email.lower() != self.user.lower():
                    extracted["customer_contact_email"] = clean_email
                    break

        # Fallback 3D: AE phone number heuristic from URL-stripped body text
        if not extracted["ae_phone"]:
            body_no_urls = re.sub(r"https?://\S+", "", body)
            phone_matches = re.findall(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{4}", body_no_urls)
            for pm in phone_matches:
                clean_phone = pm.rstrip(". ,;:)").strip()
                digits_only = re.sub(r"\D", "", clean_phone)
                if len(digits_only) >= 7 and not digits_only.startswith("0000") and digits_only != "0" * len(digits_only):
                    extracted["ae_phone"] = clean_phone
                    break

        return extracted

    def inject_mock_email(self, sender: str, subject: str, body: str, in_reply_to: Optional[str] = None) -> str:
        """Injects a simulated email into the mock queue for testing and validation.

        Args:
            sender: Sender email or 'Name <email>' string.
            subject: Subject line string.
            body: Plain-text email body.
            in_reply_to: Optional parent Message-ID to simulate an in-thread reply.

        Returns:
            str: Generated unique mock message ID.
        """
        mock_id = f"mock_msg_{int(datetime.now().timestamp())}_{len(self._mock_inbox) + 1}"
        self._mock_inbox.append({
            "id": mock_id,
            "sender": sender,
            "subject": subject,
            "body": body,
            "in_reply_to": in_reply_to
        })
        return mock_id

    def fetch_unread_deal_emails(self) -> list[dict[str, Any]]:
        """Fetches unread emails matching the subject filter from the Gmail inbox.

        Execution Branches:
            - Branch 1 (Mock Mode): Drains and parses queued emails from self._mock_inbox.
            - Branch 2 (Live IMAP Search & Ingestion):
                1. Connects to Gmail IMAP if not already active.
                2. Selects 'INBOX' and issues search query:
                   (OR (SUBJECT "<filter>") (SUBJECT "Clarification")) UNSEEN
                3. Fetches RFC 822 raw message bytes and parses MIME structure.
                4. Invokes parse_deal_from_email.
                5. Marks email as \\Seen in Gmail to prevent duplicate polling.
                6. Catches socket/IMAP exceptions gracefully, disconnecting to reset state.

        Returns:
            list[dict[str, Any]]: List of parsed deal dictionaries ready for processing.
        """
        # Branch 1: Mock Mode Ingestion
        if self.mock_mode:
            unread = list(self._mock_inbox)
            self._mock_inbox.clear()
            return [
                self.parse_deal_from_email(m["id"], m["sender"], m["subject"], m["body"], in_reply_to=m.get("in_reply_to"))
                for m in unread if self.subject_filter.lower() in m["subject"].lower() or "clarification" in m["subject"].lower()
            ]

        # Branch 2: Live IMAP Search & Ingestion
        if not self._imap_client:
            if not self.connect():
                return []

        deal_payloads: list[dict[str, Any]] = []
        try:
            self._imap_client.select("INBOX")
            search_query = f'(OR (SUBJECT "{self.subject_filter}") (SUBJECT "Clarification")) UNSEEN'
            status, message_numbers = self._imap_client.search(None, search_query)
            if status != "OK" or not message_numbers[0]:
                return []

            for num in message_numbers[0].split():
                status, data = self._imap_client.fetch(num, "(RFC822)")
                if status != "OK" or not data:
                    continue

                raw_bytes = data[0][1]
                msg = email.message_from_bytes(raw_bytes)

                msg_id = self._decode_header_str(msg.get("Message-ID")) or f"gmail_{num.decode('utf-8')}"
                sender = self._decode_header_str(msg.get("From"))
                subject = self._decode_header_str(msg.get("Subject"))
                body = self._extract_body_text(msg)
                in_reply_to = self._decode_header_str(msg.get("In-Reply-To")) or self._decode_header_str(msg.get("References")) or None

                deal_dict = self.parse_deal_from_email(msg_id, sender, subject, body, in_reply_to=in_reply_to)
                deal_payloads.append(deal_dict)

                # Mutate flags to mark message as read
                self._imap_client.store(num, "+FLAGS", "\\Seen")
                _logger.info(f"Fetched and marked as read deal email for '{deal_dict.get('customer_name')}' from {sender}")

        except Exception as exc:
            _logger.error(f"Error fetching emails from Gmail inbox: {exc}")
            self.disconnect()

        return deal_payloads

    def stage_clarification_draft(
        self,
        draft: ClarificationDraft,
        correlation_id: str,
        in_reply_to: Optional[str] = None,
        original_subject: Optional[str] = None
    ) -> bool:
        """Inserts a clarification email into Gmail's Drafts folder for human review before sending.

        Ensures human-in-the-loop oversight by staging drafts rather than auto-dispatching.
        Formats RFC 5322 threading headers (In-Reply-To, References, and Re: subject) so the draft
        renders inside the existing email conversation thread in Gmail.

        Execution Branches:
            - Branch 1 (Mock Mode): Records draft in self._staged_drafts and logs audit success.
            - Branch 2 (Live IMAP Append): Constructs RFC 5322 EmailMessage, sets headers and
              plain-text content, and executes IMAP APPEND to '[Gmail]/Drafts' (falling back to 'Drafts').

        Args:
            draft: Validated ClarificationDraft schema containing recipient, subject, and body.
            correlation_id: Pipeline tracking identifier for the deal audit trail.
            in_reply_to: Optional parent Message-ID to thread the draft in Gmail.
            original_subject: Optional original deal subject line to ensure proper 'Re:' formatting.

        Returns:
            bool: True if the draft was successfully staged, False otherwise.
        """
        reply_subject = (
            original_subject if (original_subject and original_subject.lower().startswith("re:"))
            else f"Re: {original_subject}" if original_subject
            else draft.subject
        )

        # Branch 1: Mock Mode Draft Staging
        if self.mock_mode:
            self._staged_drafts.append({
                "recipient": draft.recipient_email,
                "subject": reply_subject,
                "body": draft.body,
                "missing_fields": draft.missing_fields,
                "in_reply_to": in_reply_to,
                "created_at": draft.created_at
            })
            _logger.info(f"[MOCK] Staged clarification draft in simulated Drafts folder for AE '{draft.recipient_email}'.")
            audit_logger.log_action(
                correlation_id=correlation_id,
                agent_name="GmailPoller",
                action="clarification_draft_staged",
                inputs=draft.model_dump(),
                outputs={"folder": "[MOCK]/Drafts", "recipient": draft.recipient_email, "subject": reply_subject, "staged": True},
                decision_rationale=f"Staged clarification email in simulated Drafts folder for human CS Ops review before dispatching to AE '{draft.recipient_email}'.",
                status=AuditActionStatus.SUCCESS
            )
            return True

        # Branch 2: Live IMAP Draft Appending
        if not self._imap_client:
            if not self.connect():
                _logger.warning("Cannot stage draft: Gmail IMAP not connected.")
                return False

        try:
            msg = EmailMessage()
            msg["To"] = draft.recipient_email
            msg["From"] = self.user
            msg["Subject"] = reply_subject
            msg["Date"] = email.utils.formatdate(localtime=True)
            if in_reply_to:
                msg["In-Reply-To"] = in_reply_to
                msg["References"] = in_reply_to
            msg.set_content(draft.body)
            msg_bytes = msg.as_bytes()

            draft_folder = "[Gmail]/Drafts"
            status, _ = self._imap_client.append(draft_folder, "(\\Draft)", imaplib.Time2Internaldate(time.time()), msg_bytes)
            if status != "OK":
                draft_folder = "Drafts"
                self._imap_client.append(draft_folder, "(\\Draft)", imaplib.Time2Internaldate(time.time()), msg_bytes)

            _logger.info(f"Successfully staged clarification draft in Gmail '{draft_folder}' for AE '{draft.recipient_email}'.")
            audit_logger.log_action(
                correlation_id=correlation_id,
                agent_name="GmailPoller",
                action="clarification_draft_staged",
                inputs=draft.model_dump(),
                outputs={"folder": draft_folder, "recipient": draft.recipient_email, "staged": True},
                decision_rationale=f"Staged clarification email in Gmail '{draft_folder}' folder for human CS Ops review before dispatching to AE '{draft.recipient_email}'.",
                status=AuditActionStatus.SUCCESS
            )
            return True
        except Exception as exc:
            _logger.error(f"Failed to stage clarification draft into Gmail: {exc}")
            self.disconnect()
            return False

    def process_incoming_deals(
        self,
        agent1: Optional[Agent1Intake] = None,
        agent2: Optional[Agent2Communication] = None
    ) -> list[dict[str, Any]]:
        """Fetches pending deal emails and executes the full Agent 1 and Agent 2 onboarding pipeline.

        Execution Stages:
            - Step 1 (Multi-Turn Thread Discovery & Field Merging): Computes candidate lookup keys
              (customer_name, in_reply_to, message_id, clean_subject) and checks _thread_deal_cache.
              Merges previously verified valid fields into the deal payload.
            - Step 2 (Agent 1 Execution & Clarification Staging): Invokes Agent 1 Intake:
                * If HALTED_MISSING_DATA: Indexes partial deal state across candidate keys in
                  _thread_deal_cache and stages clarification draft in Gmail Drafts folder.
                * If SUCCESS or IDEMPOTENT_DUPLICATE: Cleans up and evicts keys from _thread_deal_cache.
            - Step 3 (Agent 2 Handoff): If Agent 1 succeeded with a valid Rocketlane project, triggers
              Agent 2 Communication for Slack customer channel provisioning.
            - Fault Isolation Boundary: Wraps per-deal execution in a try...except block to record audit
              failures without crashing the daemon loop for remaining deals.

        Args:
            agent1: Optional Agent1Intake override for testing/dependency injection.
            agent2: Optional Agent2Communication override for testing/dependency injection.

        Returns:
            list[dict[str, Any]]: List of per-deal execution summaries.
        """
        a1 = agent1 or agent1_intake
        a2 = agent2 or agent2_communication

        deals = self.fetch_unread_deal_emails()
        if not deals:
            return []

        results: list[dict[str, Any]] = []
        for deal in deals:
            ts = int(datetime.now().timestamp())
            corr_id = f"gmail_deal_{ts}_{abs(hash(deal.get('customer_name', 'deal'))) % 10000:04d}"

            # ---------------------------------------------------------------------
            # Step 1: Multi-Turn Conversational Cache Key Discovery & Field Merging
            # ---------------------------------------------------------------------
            subj_raw = str(deal.get("subject", ""))
            subj_clean = re.sub(r"^(?:re|fwd|fw)\s*:\s*", "", subj_raw, flags=re.IGNORECASE)
            subj_clean = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", subj_clean).strip().lower()

            cache_keys_to_check: list[str] = []
            if deal.get("customer_name"):
                cache_keys_to_check.append(str(deal["customer_name"]).lower().strip())
            if deal.get("in_reply_to"):
                cache_keys_to_check.append(f"msg:{str(deal['in_reply_to']).strip()}")
            if deal.get("message_id"):
                cache_keys_to_check.append(f"msg:{str(deal['message_id']).strip()}")
            if subj_clean:
                cache_keys_to_check.append(f"subj:{subj_clean}")

            prior = None
            matched_key = None
            for ck in cache_keys_to_check:
                if ck in self._thread_deal_cache:
                    prior = self._thread_deal_cache[ck]
                    matched_key = ck
                    break

            if prior:
                for k in ("customer_name", "customer_contact_email", "ae_name", "ae_phone", "opportunity_url"):
                    if not deal.get(k) and prior.get(k):
                        deal[k] = prior[k]

            audit_logger.log_action(
                correlation_id=corr_id,
                agent_name="GmailPoller",
                action="inbound_email_polled",
                inputs=deal,
                outputs={"inbox": self.user, "subject_filter": self.subject_filter},
                decision_rationale=f"Polled new deal email for customer '{deal.get('customer_name')}' from CS inbox '{self.user}'.",
                status=AuditActionStatus.SUCCESS
            )

            _logger.info(f"Processing polled deal for '{deal.get('customer_name')}' (Correlation ID: {corr_id})...")

            try:
                # -----------------------------------------------------------------
                # Step 2: Agent 1 processes deal
                # -----------------------------------------------------------------
                a1_result = a1.process_deal(deal, correlation_id=corr_id)

                # Branch 2A: Validation Halted on Missing Data -> Update cache and stage draft
                draft_staged = False
                if a1_result.status == "HALTED_MISSING_DATA":
                    keys_to_store: list[str] = list(cache_keys_to_check)
                    if deal.get("customer_name"):
                        keys_to_store.append(str(deal["customer_name"]).lower().strip())
                    if deal.get("message_id"):
                        keys_to_store.append(f"msg:{str(deal['message_id']).strip()}")
                    if subj_clean:
                        keys_to_store.append(f"subj:{subj_clean}")
                    for k_store in set(keys_to_store):
                        self._thread_deal_cache[k_store] = deal
                    if a1_result.clarification_draft:
                        draft_staged = self.stage_clarification_draft(
                            draft=a1_result.clarification_draft,
                            correlation_id=corr_id,
                            in_reply_to=deal.get("message_id"),
                            original_subject=deal.get("subject")
                        )
                # Branch 2B: Success or Idempotent Duplicate -> Evict completed deal from cache
                elif a1_result.status in ("SUCCESS", "IDEMPOTENT_DUPLICATE"):
                    keys_to_evict: list[str] = list(cache_keys_to_check)
                    if matched_key:
                        keys_to_evict.append(matched_key)
                    for k_evict in set(keys_to_evict):
                        self._thread_deal_cache.pop(k_evict, None)

                # -----------------------------------------------------------------
                # Step 3: Agent 2 runs if Agent 1 confirmed and project was created
                # -----------------------------------------------------------------
                a2_result = None
                if a1_result.status in ("SUCCESS", "IDEMPOTENT_DUPLICATE") and a1_result.rocketlane_project:
                    a2_result = a2.process_project_handoff(a1_result)

                results.append({
                    "correlation_id": corr_id,
                    "customer_name": deal.get("customer_name"),
                    "agent1_status": a1_result.status,
                    "agent2_status": a2_result.status if a2_result else "SKIPPED",
                    "rocketlane_project_id": a1_result.rocketlane_project.project_id if a1_result.rocketlane_project else None,
                    "clarification_needed": a1_result.clarification_draft is not None,
                    "draft_staged": draft_staged
                })
            except Exception as deal_err:
                _logger.error(f"Error processing deal '{deal.get('customer_name')}' ({corr_id}): {deal_err}", exc_info=True)
                audit_logger.log_action(
                    correlation_id=corr_id,
                    agent_name="GmailPoller",
                    action="deal_processing_failed",
                    inputs=deal,
                    outputs={"error": str(deal_err)},
                    decision_rationale=f"Daemon caught unhandled exception during deal processing: {deal_err}. Preserving poller loop.",
                    status=AuditActionStatus.FAILED
                )
                results.append({
                    "correlation_id": corr_id,
                    "customer_name": deal.get("customer_name"),
                    "agent1_status": "FAILED",
                    "agent2_status": "SKIPPED",
                    "rocketlane_project_id": None,
                    "clarification_needed": False,
                    "draft_staged": False,
                    "error": str(deal_err)
                })

        return results

    def start_polling(self, max_polls: Optional[int] = None) -> None:
        """Starts continuous polling loop checking for unread deal emails every poll_interval seconds.

        Args:
            max_polls: Optional maximum number of poll iterations before exiting (primarily for testing).
        """
        _logger.info(f"Starting Gmail Poller for CS Inbox '{self.user}' (Subject filter: '{self.subject_filter}', Interval: {self.poll_interval}s)...")
        poll_count = 0
        try:
            while True:
                poll_count += 1
                try:
                    self.process_incoming_deals()
                except Exception as poll_err:
                    _logger.error(f"Error during poll iteration {poll_count}: {poll_err}", exc_info=True)

                if max_polls is not None and poll_count >= max_polls:
                    break

                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            _logger.info("Gmail Poller stopped by user.")
        finally:
            self.disconnect()


# Global singleton instance of Gmail poller
gmail_poller: GmailPoller = GmailPoller()
