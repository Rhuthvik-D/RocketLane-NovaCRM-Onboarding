# Resilient Gmail IMAP listener service for automated CS inbox deal monitoring and extraction.  # What: Module header; Why: Integrates Gmail with Agent 1.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps and message generation.
import email  # What: Import standard email package; Why: Parses raw MIME messages into email objects.
from email.header import decode_header  # What: Import decode_header helper; Why: Decodes encoded subject lines and sender names.
from email.message import EmailMessage, Message  # What: Import EmailMessage and Message; Why: Composes draft emails and parses inbound MIME messages.
import email.utils  # What: Import email.utils; Why: Formats RFC 2822 date strings for draft headers.
import imaplib  # What: Import standard imaplib; Why: Connects securely to Gmail IMAP servers via SSL.
import logging  # What: Import standard logging; Why: Emits debug, warning, and progress logs for poller.
import re  # What: Import regular expressions; Why: Extracts emails, phone numbers, and keys from email text.
import time  # What: Import time module; Why: Manages sleep intervals during continuous polling.
from typing import Any, Optional  # What: Import typing utilities; Why: Type annotations across methods.
from src.agents.agent1_intake import Agent1Intake, agent1_intake  # What: Import Agent 1; Why: Ingests parsed deal payloads.
from src.agents.agent2_communication import Agent2Communication, agent2_communication  # What: Import Agent 2; Why: Runs downstream Slack provisioning.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits every inbound email ingestion event.
from src.core.config import settings  # What: Import settings; Why: Retrieves Gmail credentials, intervals, and filters.
from src.models.schemas import AuditActionStatus, ClarificationDraft  # What: Import schemas; Why: Types for audit status and clarification drafts.


_logger = logging.getLogger("gmail_poller")  # What: Instantiate module logger; Why: Logs polling lifecycle to console.


class GmailPoller:  # What: Gmail poller class; Why: Connects to Gmail IMAP, monitors for AE emails, and triggers agents.
    """Monitors a Gmail inbox (CS team inbox) via IMAP for incoming deal notifications from AEs."""  # What: Docstring; Why: Documents class purpose.

    def __init__(  # What: Constructor method; Why: Initializes credentials, server settings, and agent references.
        self,  # What: Self instance; Why: Accesses class members.
        user: Optional[str] = None,  # What: Optional Gmail user argument; Why: Overrides settings if provided.
        password: Optional[str] = None,  # What: Optional App Password argument; Why: Overrides settings if provided.
        poll_interval: Optional[int] = None,  # What: Optional interval integer; Why: Overrides settings if provided.
        subject_filter: Optional[str] = None,  # What: Optional filter string; Why: Overrides settings if provided.
        mock_mode: bool = False  # What: Mock mode boolean; Why: Enables offline testing without real IMAP credentials.
    ) -> None:  # What: Return type; Why: Constructor returns None.
        self.user: str = user or settings.gmail_user  # What: Store Gmail address; Why: Authenticates IMAP connection.
        self.password: str = password or settings.gmail_app_password  # What: Store App Password; Why: Authenticates IMAP connection.
        self.poll_interval: int = poll_interval or settings.gmail_poll_interval  # What: Store poll interval; Why: Loop delay.
        self.subject_filter: str = subject_filter or settings.gmail_subject_filter  # What: Store subject filter; Why: Selects deal emails.
        self.mock_mode: bool = mock_mode  # What: Store mock flag; Why: Toggles offline simulation.
        self._mock_inbox: list[dict[str, Any]] = []  # What: In-memory mock queue; Why: Stores injected emails for testing.
        self._staged_drafts: list[dict[str, Any]] = []  # What: In-memory staged drafts list; Why: Stores staged clarification drafts for testing/inspection.
        self._thread_deal_cache: dict[str, dict[str, Any]] = {}  # What: Deal thread cache; Why: Retains valid fields across clarification turns for a customer deal.
        self._imap_client: Optional[imaplib.IMAP4_SSL] = None  # What: IMAP client instance; Why: Reusable connection handle.

    def connect(self) -> bool:  # What: Connection helper method; Why: Establishes secure IMAP connection to imap.gmail.com.
        """Connects and logs into the Gmail IMAP server using SSL and configured App Password."""  # What: Docstring; Why: Explains connection logic.
        if self.mock_mode:  # What: Check mock mode; Why: Skips live network connection during tests.
            _logger.info("[MOCK] Connected to simulated Gmail inbox.")  # What: Log mock info; Why: Terminal visibility.
            return True  # What: Return True; Why: Mock connection always succeeds.

        if not self.password:  # What: Check if App Password is missing; Why: Prevents connection attempts without password.
            _logger.warning("GMAIL_APP_PASSWORD not set in .env. Gmail polling cannot authenticate.")  # What: Log warning; Why: Informs user how to configure.
            return False  # What: Return False; Why: Signals connection failure.

        try:  # What: Try block; Why: Catches IMAP connection and authentication errors.
            self._imap_client = imaplib.IMAP4_SSL("imap.gmail.com", 993)  # What: Open SSL socket to Gmail; Why: Standard secure IMAP port.
            self._imap_client.login(self.user, self.password)  # What: Authenticate with user and password; Why: Logs into Gmail account.
            _logger.info(f"Successfully authenticated to Gmail inbox: {self.user}")  # What: Log success; Why: Confirms login.
            return True  # What: Return True; Why: Connection established.
        except Exception as exc:  # What: Catch exceptions; Why: Handles bad credentials, timeouts, or network failures.
            _logger.error(f"Failed to connect to Gmail ({self.user}): {exc}")  # What: Log error; Why: Debugging information.
            return False  # What: Return False; Why: Connection failed.

    def disconnect(self) -> None:  # What: Disconnect helper method; Why: Closes IMAP connection cleanly.
        """Closes the mailbox and logs out of the IMAP session."""  # What: Docstring; Why: Explains disconnection.
        if self._imap_client is not None:  # What: Check if client exists; Why: Only disconnect active connections.
            try:  # What: Try block; Why: Catches errors during logout.
                self._imap_client.close()  # What: Close selected mailbox; Why: Releases mailbox lock.
                self._imap_client.logout()  # What: Send LOGOUT command; Why: Closes connection to server.
            except Exception:  # What: Catch any exception; Why: Suppress errors during cleanup.
                pass  # What: Pass silently; Why: Cleanup best-effort.
            self._imap_client = None  # What: Reset client to None; Why: Marks disconnected state.

    def _decode_header_str(self, header_raw: Optional[str]) -> str:  # What: Header decoding helper; Why: Decodes RFC 2047 encoded email headers.
        """Safely decodes an email header value into a standard UTF-8 string."""  # What: Docstring; Why: Explains decoding logic.
        if not header_raw:  # What: Check if raw header is empty; Why: Returns empty string for absent headers.
            return ""  # What: Return empty string; Why: Default value.
        decoded_parts = decode_header(header_raw)  # What: Decode header bytes; Why: Splits into (bytes, encoding) tuples.
        result_str = ""  # What: Initialize result string; Why: Accumulates decoded parts.
        for part, encoding in decoded_parts:  # What: Loop over decoded parts; Why: Decodes each fragment.
            if isinstance(part, bytes):  # What: Check if part is bytes; Why: Needs decoding to string.
                result_str += part.decode(encoding or "utf-8", errors="replace")  # What: Decode bytes; Why: Converts to string safely.
            else:  # What: Else branch; Why: Part is already a string.
                result_str += str(part)  # What: Append string part; Why: Preserves decoded text.
        return result_str.strip()  # What: Return stripped string; Why: Normalized clean header.

    def _extract_body_text(self, msg: Message) -> str:  # What: Body extraction helper; Why: Extracts plain text content from MIME structure.
        """Walks MIME message parts and extracts the primary plain-text email body."""  # What: Docstring; Why: Explains body extraction.
        body_content = ""  # What: Initialize body content string; Why: Accumulates plain text.
        if msg.is_multipart():  # What: Check if message has multiple parts; Why: Handles multipart/alternative and multipart/mixed.
            for part in msg.walk():  # What: Walk through all MIME parts; Why: Finds text/plain payload.
                content_type = part.get_content_type()  # What: Get content type; Why: Identifies MIME type.
                disposition = str(part.get("Content-Disposition", ""))  # What: Get disposition; Why: Filters out attachments.
                if content_type == "text/plain" and "attachment" not in disposition:  # What: Check if plain text non-attachment; Why: Target body part.
                    payload = part.get_payload(decode=True)  # What: Decode payload bytes; Why: Extracts raw content.
                    if payload:  # What: Check if payload is non-empty; Why: Avoids decoding None.
                        body_content += payload.decode("utf-8", errors="replace")  # What: Decode UTF-8; Why: Converts to string.
        else:  # What: Single part message branch; Why: Directly extracts payload.
            payload = msg.get_payload(decode=True)  # What: Decode payload bytes; Why: Extracts raw content.
            if payload:  # What: Check if payload exists; Why: Avoids decoding None.
                body_content = payload.decode("utf-8", errors="replace")  # What: Decode UTF-8; Why: Converts to string.
        return body_content.strip()  # What: Return trimmed body string; Why: Clean body text for parsing.

    def parse_deal_from_email(  # What: Deal extraction method; Why: Converts raw email headers and body into structured deal dictionary.
        self,  # What: Self instance; Why: Accesses class helpers.
        message_id: str,  # What: Email message ID; Why: Unique deal message tracking.
        sender: str,  # What: From header string; Why: Identifies AE sender.
        subject: str,  # What: Subject line string; Why: Context and customer name fallback.
        body: str,  # What: Body text string; Why: Source of deal parameters.
        in_reply_to: Optional[str] = None  # What: Optional reply parent ID; Why: Connects clarification replies to parent thread.
    ) -> dict[str, Any]:  # What: Return type; Why: Returns deal dictionary ready for Agent 1.
        """Parses email subject, sender, and body using key-value heuristics and regex into a deal dictionary."""  # What: Docstring; Why: Explains parsing rules.
        extracted: dict[str, Any] = {  # What: Initialize extracted fields dictionary; Why: Default baseline payload.
            "message_id": message_id,  # What: Assign message ID; Why: Deduplication identifier.
            "subject": subject,  # What: Store original subject line; Why: Used for in-thread draft reply threading.
            "in_reply_to": in_reply_to,  # What: Store reply parent ID; Why: Multi-turn reply thread reference.
            "customer_name": "",  # What: Empty default; Why: Must be found or flagged missing.
            "customer_contact_email": "",  # What: Empty default; Why: Must be found or flagged missing.
            "ae_name": "",  # What: Empty default; Why: Must be found or flagged missing.
            "ae_phone": "",  # What: Empty default; Why: Must be found or flagged missing.
            "opportunity_url": None,  # What: None default; Why: Optional SFDC context link.
            "ae_email": ""  # What: Empty default; Why: For clarification routing.
        }  # What: End of dictionary initialization; Why: Baseline schema ready.

        # 1. Parse sender email and name from "From" header
        if "<" in sender and ">" in sender:  # What: Check standard RFC 5322 format "Name <email>"; Why: Separates display name and address.
            name_part = sender.split("<")[0].strip().strip("\"'")  # What: Extract name fragment; Why: AE name candidate.
            email_part = sender.split("<")[1].split(">")[0].strip()  # What: Extract email fragment; Why: AE email address.
            extracted["ae_name"] = name_part  # What: Assign candidate AE name; Why: Fallback if not specified in body.
            extracted["ae_email"] = email_part  # What: Assign AE email; Why: Target for clarification drafts.
        else:  # What: Plain email address without display name; Why: Raw email fallback.
            extracted["ae_email"] = sender.strip()  # What: Store raw sender; Why: AE email.

        # 2. Key-value line parser inspecting body text (including quoted email history)
        for line in body.splitlines():  # What: Split body into lines; Why: Iterates over text line-by-line.
            line_clean = re.sub(r"^[>\s|]+", "", line).strip()  # What: Strip quote markers and whitespace; Why: Normalizes reply and quoted thread lines.
            if not line_clean:  # What: Check if line is empty; Why: Skips blank lines.
                continue  # What: Continue to next line; Why: Efficiency.

            # Customer Name pattern
            cust_match = re.match(r"^(?:customer|company|client|account)(?:\s*name)?\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)  # What: Regex match customer name; Why: Extracts customer name.
            if cust_match and not extracted["customer_name"]:  # What: Check match and unpopulated; Why: Topmost non-quoted value takes precedence.
                extracted["customer_name"] = cust_match.group(1).strip()  # What: Store matched customer name; Why: Captures name.
                continue  # What: Continue to next line; Why: Line consumed.

            # Customer Contact Email pattern
            email_match = re.match(r"^(?:customer\s*contact\s*email|contact\s*email|customer\s*email|client\s*email)\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)  # What: Regex match email; Why: Extracts customer email.
            if email_match and not extracted["customer_contact_email"]:  # What: Check match and unpopulated; Why: Topmost non-quoted value takes precedence.
                extracted["customer_contact_email"] = email_match.group(1).strip()  # What: Store matched email; Why: Captures contact email.
                continue  # What: Continue to next line; Why: Line consumed.

            # AE Name pattern
            ae_match = re.match(r"^(?:ae\s*name|account\s*executive|sales\s*rep|ae)\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)  # What: Regex match AE name; Why: Extracts AE name.
            if ae_match and not extracted["ae_name"]:  # What: Check match and unpopulated; Why: Topmost non-quoted value takes precedence.
                extracted["ae_name"] = ae_match.group(1).strip()  # What: Store matched AE name; Why: Captures AE name.
                continue  # What: Continue to next line; Why: Line consumed.

            # AE Phone pattern
            phone_match = re.match(r"^(?:ae\s*phone|ae\s*mobile|phone|mobile|cell)\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)  # What: Regex match AE phone; Why: Extracts AE phone.
            if phone_match and not extracted["ae_phone"]:  # What: Check match and unpopulated; Why: Topmost non-quoted value takes precedence.
                extracted["ae_phone"] = phone_match.group(1).strip()  # What: Store matched AE phone; Why: Captures phone destination.
                continue  # What: Continue to next line; Why: Line consumed.

            # Opportunity URL pattern
            opp_match = re.match(r"^(?:opportunity(?:\s*url)?|salesforce(?:\s*url)?|sfdc(?:\s*link)?)\s*[:=\-]\s*(.+)$", line_clean, re.IGNORECASE)  # What: Regex match opportunity; Why: Extracts SFDC link.
            if opp_match and not extracted["opportunity_url"]:  # What: Check match and unpopulated; Why: Topmost non-quoted value takes precedence.
                extracted["opportunity_url"] = opp_match.group(1).strip()  # What: Store matched URL; Why: Captures opportunity URL.
                continue  # What: Continue to next line; Why: Line consumed.

        # 3. Fallback heuristics if key-value labels were omitted
        # Fallback for customer name from subject line e.g. "[New Deal] Stark Industries Onboarding" or "Re: [New Deal] Clarification Needed for Cyberdyne Systems Onboarding"
        if not extracted["customer_name"]:  # What: Check if customer name still empty; Why: Attempts subject extraction.
            subj_clean = re.sub(r"^(?:re|fwd|fw)\s*:\s*", "", subject, flags=re.IGNORECASE)  # What: Strip reply or forward prefix; Why: Cleans subject.
            subj_clean = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", subj_clean)  # What: Strip leading bracket tags like [New Deal] [Action Required]; Why: Isolates subject content.
            subj_clean = re.sub(r"^(?:clarification\s*(?:needed|requested)?\s*(?:for)?|new\s*deal|deal\s*closed|onboarding)\s*[:\-]?\s*", "", subj_clean, flags=re.IGNORECASE)  # What: Strip clarification or deal prefix; Why: Leaves customer name.
            subj_clean = re.sub(r"\s*(?:-|–)?\s*onboarding.*$", "", subj_clean, flags=re.IGNORECASE).strip()  # What: Strip trailing onboarding suffix; Why: Leaves clean company name.
            if subj_clean and len(subj_clean) > 1:  # What: Check if clean subject has content; Why: Valid name candidate.
                extracted["customer_name"] = subj_clean  # What: Assign extracted subject name; Why: Customer name fallback.

        # Fallback for Salesforce Opportunity URL in body
        if not extracted["opportunity_url"]:  # What: Check if opportunity URL still None; Why: Searches body for Salesforce URL.
            url_match = re.search(r"https://[a-zA-Z0-9.\-_]+(?:\.salesforce\.com|\.force\.com)/[^\s]+", body)  # What: Regex search for SFDC URL; Why: Matches Salesforce links.
            if url_match:  # What: Check if URL found; Why: Extracts link.
                extracted["opportunity_url"] = url_match.group(0).rstrip(". ,;:)").strip()  # What: Store found URL; Why: Captures clean link without trailing punctuation.

        # Fallback for contact email if still missing
        if not extracted["customer_contact_email"]:  # What: Check if customer email still empty; Why: Scans body for customer email address.
            emails_found = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-]+", body)  # What: Find all emails in body; Why: Identifies customer email without trailing period.
            for e in emails_found:  # What: Loop over found emails; Why: Filters out sender email.
                clean_email = e.rstrip(". ,;:)").strip()  # What: Strip trailing punctuation; Why: Removes sentence-ending periods.
                if clean_email.lower() != extracted["ae_email"].lower() and clean_email.lower() != self.user.lower():  # What: Check if email is not AE or CS inbox; Why: Must be customer email.
                    extracted["customer_contact_email"] = clean_email  # What: Assign first external email; Why: Customer email fallback.
                    break  # What: Break loop; Why: First match accepted.

        # Fallback for phone number if still missing
        if not extracted["ae_phone"]:  # What: Check if phone still empty; Why: Scans body for phone number pattern.
            body_no_urls = re.sub(r"https?://\S+", "", body)  # What: Strip all URLs from body text; Why: Prevents numbers in Salesforce URLs from falsely matching as phones.
            phone_matches = re.findall(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{4}", body_no_urls)  # What: Find phone candidates in URL-stripped text; Why: Extracts valid phone representations including leading plus sign.
            for pm in phone_matches:  # What: Loop over candidate phone matches; Why: Validates digits.
                clean_phone = pm.rstrip(". ,;:)").strip()  # What: Clean trailing punctuation; Why: Normalizes phone.
                digits_only = re.sub(r"\D", "", clean_phone)  # What: Extract digits; Why: Validates digit count.
                if len(digits_only) >= 7 and not digits_only.startswith("0000") and digits_only != "0" * len(digits_only):  # What: Verify phone criteria; Why: Rejects dummy numbers.
                    extracted["ae_phone"] = clean_phone  # What: Store clean phone; Why: AE phone fallback.
                    break  # What: Break loop; Why: First valid phone match accepted.

        return extracted  # What: Return extracted dictionary; Why: Ready for Agent 1 consumption.

    def inject_mock_email(self, sender: str, subject: str, body: str, in_reply_to: Optional[str] = None) -> str:  # What: Mock email injector; Why: Supports testing without real IMAP access.
        """Injects a simulated email into the mock queue for testing and validation."""  # What: Docstring; Why: Explains mock injection.
        mock_id = f"mock_msg_{int(datetime.now().timestamp())}_{len(self._mock_inbox) + 1}"  # What: Generate unique mock ID; Why: Identifies test email.
        self._mock_inbox.append({  # What: Append email dict; Why: Queues email for poller.
            "id": mock_id,  # What: Mock ID; Why: Identifier.
            "sender": sender,  # What: Sender string; Why: AE sender.
            "subject": subject,  # What: Subject string; Why: Email subject.
            "body": body,  # What: Body string; Why: Email content.
            "in_reply_to": in_reply_to  # What: In-reply-to string; Why: Preserves thread reference.
        })  # What: End of append; Why: Email queued.
        return mock_id  # What: Return mock ID; Why: For test assertions.

    def fetch_unread_deal_emails(self) -> list[dict[str, Any]]:  # What: Fetch unread emails method; Why: Retrieves unread deal emails from inbox.
        """Fetches unread emails matching the subject filter from the Gmail inbox."""  # What: Docstring; Why: Explains retrieval method.
        # Mock mode branch
        if self.mock_mode:  # What: Check mock mode; Why: Returns queued mock emails.
            unread = list(self._mock_inbox)  # What: Copy mock inbox; Why: Fetches queued emails.
            self._mock_inbox.clear()  # What: Clear mock inbox; Why: Simulates marking as read.
            return [  # What: Return parsed list; Why: Converts mock emails to deal payloads.
                self.parse_deal_from_email(m["id"], m["sender"], m["subject"], m["body"], in_reply_to=m.get("in_reply_to"))  # What: Call parser; Why: Extracts deal parameters.
                for m in unread if self.subject_filter.lower() in m["subject"].lower() or "clarification" in m["subject"].lower()  # What: Filter by subject or clarification; Why: Matches deal notifications and clarification replies.
            ]  # What: End of mock return list; Why: Complete.

        if not self._imap_client:  # What: Check if client is connected; Why: Connects if disconnected.
            if not self.connect():  # What: Call connect; Why: Establishes connection.
                return []  # What: Return empty list; Why: Cannot fetch if not connected.

        deal_payloads: list[dict[str, Any]] = []  # What: Initialize deal payloads list; Why: Accumulates parsed deals.
        try:  # What: Try block; Why: Catches IMAP search and fetch exceptions.
            self._imap_client.select("INBOX")  # What: Select INBOX folder; Why: Required before searching.
            search_query = f'(OR (SUBJECT "{self.subject_filter}") (SUBJECT "Clarification")) UNSEEN'  # What: Compose search query string; Why: Finds unread deal emails or clarification replies.
            status, message_numbers = self._imap_client.search(None, search_query)  # What: Execute IMAP SEARCH; Why: Retrieves matching email sequence IDs.
            if status != "OK" or not message_numbers[0]:  # What: Check if search returned OK and non-empty; Why: Skips if no emails found.
                return []  # What: Return empty list; Why: No new emails.

            for num in message_numbers[0].split():  # What: Loop over email IDs; Why: Fetches each email.
                status, data = self._imap_client.fetch(num, "(RFC822)")  # What: Fetch full RFC822 message; Why: Retrieves raw email bytes.
                if status != "OK" or not data:  # What: Check fetch status; Why: Skips failed fetches.
                    continue  # What: Continue to next message; Why: Error recovery.

                raw_bytes = data[0][1]  # What: Extract message bytes; Why: Input for email parser.
                msg = email.message_from_bytes(raw_bytes)  # What: Parse into Message object; Why: Structured access to headers and body.

                msg_id = self._decode_header_str(msg.get("Message-ID")) or f"gmail_{num.decode('utf-8')}"  # What: Extract Message-ID; Why: Deduplication identifier.
                sender = self._decode_header_str(msg.get("From"))  # What: Extract From header; Why: Identifies AE sender.
                subject = self._decode_header_str(msg.get("Subject"))  # What: Extract Subject header; Why: Email subject line.
                body = self._extract_body_text(msg)  # What: Extract body text; Why: Email message content.
                in_reply_to = self._decode_header_str(msg.get("In-Reply-To")) or self._decode_header_str(msg.get("References")) or None  # What: Extract thread references; Why: Associates reply with parent thread.

                deal_dict = self.parse_deal_from_email(msg_id, sender, subject, body, in_reply_to=in_reply_to)  # What: Parse deal dictionary; Why: Converts to standardized deal format.
                deal_payloads.append(deal_dict)  # What: Append to payloads list; Why: Queued for processing.

                # Mark email as read so it isn't fetched repeatedly
                self._imap_client.store(num, "+FLAGS", "\\Seen")  # What: Set \\Seen flag on message; Why: Marks email as read in Gmail.
                _logger.info(f"Fetched and marked as read deal email for '{deal_dict.get('customer_name')}' from {sender}")  # What: Log info; Why: Terminal visibility.

        except Exception as exc:  # What: Catch unexpected IMAP errors; Why: Prevents poller crash.
            _logger.error(f"Error fetching emails from Gmail inbox: {exc}")  # What: Log error; Why: Debugging information.
            self.disconnect()  # What: Reset client handle on exception; Why: Prevents reusing dead socket on next poll attempt.

        return deal_payloads  # What: Return parsed deal payloads; Why: Ready for agent pipeline.

    def stage_clarification_draft(  # What: Draft staging method; Why: Inserts clarification email into Gmail Drafts folder for human review.
        self,  # What: Self instance; Why: Accesses IMAP client and user settings.
        draft: ClarificationDraft,  # What: Clarification draft model; Why: Ingests recipient, subject, and body.
        correlation_id: str,  # What: Deal tracking correlation ID; Why: Connects draft action to deal audit trail.
        in_reply_to: Optional[str] = None,  # What: Optional parent message ID; Why: Threads draft directly with AE deal email in Gmail.
        original_subject: Optional[str] = None  # What: Optional original email subject; Why: Sets Re: subject to keep draft in the exact same email thread.
    ) -> bool:  # What: Return type; Why: Returns True if draft was staged successfully.
        """Inserts the clarification email into the Gmail 'Drafts' folder so human CS Ops can review before sending."""  # What: Docstring; Why: Explains human-in-the-loop design.
        reply_subject = (  # What: Compute reply subject line; Why: Prefixes Re: if original subject present.
            original_subject if (original_subject and original_subject.lower().startswith("re:"))  # What: Keep existing Re:; Why: Prevents double Re: prefix.
            else f"Re: {original_subject}" if original_subject  # What: Prepend Re: prefix; Why: Conforms to RFC 5322 threading.
            else draft.subject  # What: Fallback to standalone subject; Why: When original subject absent.
        )  # What: End of subject computation; Why: Unified thread subject ready.

        if self.mock_mode:  # What: Check mock mode; Why: Stores draft in memory for testing.
            self._staged_drafts.append({  # What: Append to staged drafts queue; Why: Simulates Drafts folder storage.
                "recipient": draft.recipient_email,  # What: AE recipient email; Why: Target address.
                "subject": reply_subject,  # What: In-thread reply subject line; Why: Keeps thread unified.
                "body": draft.body,  # What: Clarification body text; Why: Email content.
                "missing_fields": draft.missing_fields,  # What: Missing fields list; Why: Missing attributes.
                "in_reply_to": in_reply_to,  # What: Parent message ID; Why: References deal email thread.
                "created_at": draft.created_at  # What: Timestamp; Why: Time record.
            })  # What: End of mock draft dictionary; Why: Ready.
            _logger.info(f"[MOCK] Staged clarification draft in simulated Drafts folder for AE '{draft.recipient_email}'.")  # What: Log mock event; Why: Terminal view.
            audit_logger.log_action(  # What: Record audit log; Why: Captures staged draft.
                correlation_id=correlation_id,  # What: Correlation ID; Why: Links audit entry.
                agent_name="GmailPoller",  # What: Acting agent name; Why: Identifies Gmail poller.
                action="clarification_draft_staged",  # What: Action name; Why: Documents draft staging.
                inputs=draft.model_dump(),  # What: Serialized draft inputs; Why: Full draft recorded.
                outputs={"folder": "[MOCK]/Drafts", "recipient": draft.recipient_email, "subject": reply_subject, "staged": True},  # What: Outputs; Why: Staging record.
                decision_rationale=f"Staged clarification email in simulated Drafts folder for human CS Ops review before dispatching to AE '{draft.recipient_email}'.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Successfully staged.
            )  # What: End of audit logging; Why: Saved to trail.
            return True  # What: Return True; Why: Mock draft staged.

        if not self._imap_client:  # What: Check if client is connected; Why: Connects if disconnected.
            if not self.connect():  # What: Call connect; Why: Establishes connection.
                _logger.warning("Cannot stage draft: Gmail IMAP not connected.")  # What: Log warning; Why: Informs caller.
                return False  # What: Return False; Why: Connection failed.

        try:  # What: Try block; Why: Catches MIME formatting and IMAP append exceptions.
            msg = EmailMessage()  # What: Instantiate EmailMessage object; Why: RFC 5322 MIME message container.
            msg["To"] = draft.recipient_email  # What: Set To header; Why: Directs draft to AE.
            msg["From"] = self.user  # What: Set From header; Why: Originates from CS team inbox.
            msg["Subject"] = reply_subject  # What: Set reply subject; Why: Ensures draft is rendered inside original deal thread.
            msg["Date"] = email.utils.formatdate(localtime=True)  # What: Set RFC 2822 date header; Why: Standard email timestamp.
            if in_reply_to:  # What: Check if parent message ID provided; Why: Threads draft into deal conversation.
                msg["In-Reply-To"] = in_reply_to  # What: Set In-Reply-To header; Why: RFC 2822 email threading.
                msg["References"] = in_reply_to  # What: Set References header; Why: Message reference chain.
            msg.set_content(draft.body)  # What: Set plain text content; Why: Body of clarification email.
            msg_bytes = msg.as_bytes()  # What: Convert message to bytes; Why: Required for IMAP APPEND command.

            # Attempt standard Gmail Drafts folder name first, fallback to generic Drafts
            draft_folder = "[Gmail]/Drafts"  # What: Standard Gmail Drafts mailbox name; Why: Gmail folder path.
            status, _ = self._imap_client.append(draft_folder, "(\\Draft)", imaplib.Time2Internaldate(time.time()), msg_bytes)  # What: Execute IMAP APPEND with (\\Draft) flag; Why: Inserts into Drafts.
            if status != "OK":  # What: Check if primary folder returned non-OK; Why: Fallback for localized accounts.
                draft_folder = "Drafts"  # What: Generic mailbox name; Why: Fallback path.
                self._imap_client.append(draft_folder, "(\\Draft)", imaplib.Time2Internaldate(time.time()), msg_bytes)  # What: Retry append on generic folder; Why: Fallback insert.

            _logger.info(f"Successfully staged clarification draft in Gmail '{draft_folder}' for AE '{draft.recipient_email}'.")  # What: Log success; Why: Terminal confirmation.
            audit_logger.log_action(  # What: Record audit log; Why: Captures staged draft.
                correlation_id=correlation_id,  # What: Correlation ID; Why: Links audit entry.
                agent_name="GmailPoller",  # What: Acting agent name; Why: Identifies Gmail poller.
                action="clarification_draft_staged",  # What: Action name; Why: Documents draft staging.
                inputs=draft.model_dump(),  # What: Serialized draft inputs; Why: Full draft recorded.
                outputs={"folder": draft_folder, "recipient": draft.recipient_email, "staged": True},  # What: Outputs; Why: Staging record.
                decision_rationale=f"Staged clarification email in Gmail '{draft_folder}' folder for human CS Ops review before dispatching to AE '{draft.recipient_email}'.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Successfully staged.
            )  # What: End of audit logging; Why: Saved to trail.
            return True  # What: Return True; Why: Successfully staged.
        except Exception as exc:  # What: Catch exceptions during draft staging; Why: Prevents crashing poller on draft insert error.
            _logger.error(f"Failed to stage clarification draft into Gmail: {exc}")  # What: Log error; Why: Debugging information.
            self.disconnect()  # What: Reset client handle on exception; Why: Prevents reusing dead socket on next attempt.
            return False  # What: Return False; Why: Staging failed.

    def process_incoming_deals(  # What: Inbound processing coordinator; Why: Feeds polled emails into Agent 1 and Agent 2.
        self,  # What: Self instance; Why: Accesses class methods.
        agent1: Optional[Agent1Intake] = None,  # What: Optional Agent 1 override; Why: Supports dependency injection in tests.
        agent2: Optional[Agent2Communication] = None  # What: Optional Agent 2 override; Why: Supports dependency injection in tests.
    ) -> list[dict[str, Any]]:  # What: Return type; Why: Returns list of processing execution summaries.
        """Fetches pending deal emails and executes the full Agent 1 and Agent 2 onboarding pipeline."""  # What: Docstring; Why: Explains method contract.
        a1 = agent1 or agent1_intake  # What: Resolve Agent 1 instance; Why: Deals intake orchestrator.
        a2 = agent2 or agent2_communication  # What: Resolve Agent 2 instance; Why: Communication orchestrator.

        deals = self.fetch_unread_deal_emails()  # What: Fetch unread deals; Why: Retrieves new emails.
        if not deals:  # What: Check if deals list is empty; Why: Exits early if no new deals.
            return []  # What: Return empty list; Why: No processing required.

        results: list[dict[str, Any]] = []  # What: Initialize results list; Why: Tracks outcomes for each deal.
        for deal in deals:  # What: Loop over parsed deals; Why: Executes pipeline for each inbound deal.
            ts = int(datetime.now().timestamp())  # What: Capture timestamp; Why: Unique deal run identifier.
            corr_id = f"gmail_deal_{ts}_{abs(hash(deal.get('customer_name', 'deal'))) % 10000:04d}"  # What: Build correlation ID; Why: Connects all events to this deal.

            # Resilient multi-turn cache key discovery supporting missing customer names
            subj_raw = str(deal.get("subject", ""))  # What: Extract subject string; Why: Thread subject line.
            subj_clean = re.sub(r"^(?:re|fwd|fw)\s*:\s*", "", subj_raw, flags=re.IGNORECASE)  # What: Strip reply prefix; Why: Cleans subject.
            subj_clean = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", subj_clean).strip().lower()  # What: Strip tag brackets; Why: Normalized clean subject.

            cache_keys_to_check: list[str] = []  # What: Candidate lookup keys list; Why: Matches multi-turn thread even if customer name was missing.
            if deal.get("customer_name"):  # What: Check customer name; Why: Primary deal identifier.
                cache_keys_to_check.append(str(deal["customer_name"]).lower().strip())  # What: Add customer name key; Why: Canonical deal key.
            if deal.get("in_reply_to"):  # What: Check In-Reply-To header; Why: Direct link to parent message ID.
                cache_keys_to_check.append(f"msg:{str(deal['in_reply_to']).strip()}")  # What: Add reply message key; Why: Thread reference key.
            if deal.get("message_id"):  # What: Check message ID; Why: Current email identifier.
                cache_keys_to_check.append(f"msg:{str(deal['message_id']).strip()}")  # What: Add message ID key; Why: Message identifier key.
            if subj_clean:  # What: Check clean subject; Why: Thread subject key.
                cache_keys_to_check.append(f"subj:{subj_clean}")  # What: Add clean subject key; Why: Links by subject.

            prior = None  # What: Prior deal dictionary; Why: Holds previous turn data.
            matched_key = None  # What: Matched cache key; Why: Tracks which key succeeded for cleanup.
            for ck in cache_keys_to_check:  # What: Loop over candidate keys; Why: Searches cache.
                if ck in self._thread_deal_cache:  # What: Check cache membership; Why: Matches prior state.
                    prior = self._thread_deal_cache[ck]  # What: Fetch prior state; Why: Retrieves cached turn.
                    matched_key = ck  # What: Store matched key; Why: Used for eviction.
                    break  # What: Break search loop; Why: First match accepted.

            if prior:  # What: Check if prior turn was found; Why: Merges earlier valid data.
                for k in ("customer_name", "customer_contact_email", "ae_name", "ae_phone", "opportunity_url"):  # What: Loop over core fields; Why: Preserves valid fields.
                    if not deal.get(k) and prior.get(k):  # What: Check if field missing now but present in prior; Why: Merges missing field.
                        deal[k] = prior[k]  # What: Merge field value; Why: Reconstitutes complete deal.

            audit_logger.log_action(  # What: Record audit log; Why: Documents email ingestion.
                correlation_id=corr_id,  # What: Correlation ID; Why: Links audit entry.
                agent_name="GmailPoller",  # What: Acting agent name; Why: Identifies Gmail poller.
                action="inbound_email_polled",  # What: Action name; Why: Ingestion event.
                inputs=deal,  # What: Deal dictionary; Why: Audited inputs.
                outputs={"inbox": self.user, "subject_filter": self.subject_filter},  # What: Outputs; Why: Audited outputs.
                decision_rationale=f"Polled new deal email for customer '{deal.get('customer_name')}' from CS inbox '{self.user}'.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Successfully polled.
            )  # What: End of audit logging; Why: Saved to trail.

            _logger.info(f"Processing polled deal for '{deal.get('customer_name')}' (Correlation ID: {corr_id})...")  # What: Log info; Why: Terminal view.

            try:  # What: Try block around per-deal execution; Why: Prevents individual deal processing errors from crashing the daemon loop.
                # Step 1: Agent 1 processes deal
                a1_result = a1.process_deal(deal, correlation_id=corr_id)  # What: Run Agent 1; Why: Validation -> Voice -> Rocketlane.

                # Step 2: Human-in-the-loop: Stage clarification draft into Drafts folder if halted on missing data
                draft_staged = False  # What: Initialize draft staged flag; Why: Default state.
                if a1_result.status == "HALTED_MISSING_DATA":  # What: Check if validation halted; Why: Updates cache and stages clarification.
                    keys_to_store: list[str] = list(cache_keys_to_check)  # What: Gather all store keys; Why: Indexes deal by all available identifiers.
                    if deal.get("customer_name"):  # What: Check customer name; Why: Name present.
                        keys_to_store.append(str(deal["customer_name"]).lower().strip())  # What: Add customer key; Why: Canonical key.
                    if deal.get("message_id"):  # What: Check message ID; Why: Inbound message identifier.
                        keys_to_store.append(f"msg:{str(deal['message_id']).strip()}")  # What: Add message key; Why: Thread message key.
                    if subj_clean:  # What: Check clean subject; Why: Clean subject identifier.
                        keys_to_store.append(f"subj:{subj_clean}")  # What: Add subject key; Why: Clean subject key.
                    for k_store in set(keys_to_store):  # What: Loop unique store keys; Why: Populates cache under each identifier.
                        self._thread_deal_cache[k_store] = deal  # What: Store partial deal state; Why: Available when AE replies.
                    if a1_result.clarification_draft:  # What: Check if draft present; Why: Stages draft.
                        draft_staged = self.stage_clarification_draft(  # What: Call stage_clarification_draft; Why: Inserts into Drafts folder.
                            draft=a1_result.clarification_draft,  # What: Pass draft; Why: Draft content.
                            correlation_id=corr_id,  # What: Pass correlation ID; Why: Audit reference.
                            in_reply_to=deal.get("message_id"),  # What: Pass deal email Message-ID; Why: Threads draft directly with AE email.
                            original_subject=deal.get("subject")  # What: Pass original deal subject; Why: Ensures in-thread reply formatting with Re: prefix.
                        )  # What: End of draft staging call; Why: Ready.
                elif a1_result.status in ("SUCCESS", "IDEMPOTENT_DUPLICATE"):  # What: Check if deal completed successfully; Why: Cleans up cache.
                    keys_to_evict: list[str] = list(cache_keys_to_check)  # What: Gather eviction candidate keys; Why: Evicts all related keys.
                    if matched_key:  # What: Check matched key; Why: Ensures matched key is evicted.
                        keys_to_evict.append(matched_key)  # What: Add matched key; Why: Complete eviction.
                    for k_evict in set(keys_to_evict):  # What: Loop unique eviction keys; Why: Cleans up thread cache.
                        self._thread_deal_cache.pop(k_evict, None)  # What: Evict from cache; Why: Frees memory and completes deal lifecycle.

                # Step 3: Agent 2 runs if Agent 1 was confirmed
                a2_result = None  # What: Initialize Agent 2 result as None; Why: May be skipped if Agent 1 halted.
                if a1_result.status in ("SUCCESS", "IDEMPOTENT_DUPLICATE") and a1_result.rocketlane_project:  # What: Check if project exists; Why: Triggers Slack setup.
                    a2_result = a2.process_project_handoff(a1_result)  # What: Run Agent 2; Why: Slack channel provisioning.

                results.append({  # What: Append execution summary dict; Why: Summarizes deal run.
                    "correlation_id": corr_id,  # What: Correlation ID; Why: Reference.
                    "customer_name": deal.get("customer_name"),  # What: Customer name; Why: Deal identity.
                    "agent1_status": a1_result.status,  # What: Agent 1 status; Why: Outcome status.
                    "agent2_status": a2_result.status if a2_result else "SKIPPED",  # What: Agent 2 status; Why: Outcome status.
                    "rocketlane_project_id": a1_result.rocketlane_project.project_id if a1_result.rocketlane_project else None,  # What: Project ID; Why: Provisioned workspace.
                    "clarification_needed": a1_result.clarification_draft is not None,  # What: Clarification flag; Why: Indicates missing fields.
                    "draft_staged": draft_staged  # What: Draft staged flag; Why: Confirms human-in-the-loop staging.
                })  # What: End of summary dict; Why: Complete.
            except Exception as deal_err:  # What: Catch deal execution error; Why: Keeps daemon alive on unexpected errors.
                _logger.error(f"Error processing deal '{deal.get('customer_name')}' ({corr_id}): {deal_err}", exc_info=True)  # What: Log error with traceback; Why: Aids debugging and root-cause analysis.
                audit_logger.log_action(  # What: Record audit log for deal failure; Why: Documents failure in audit trail.
                    correlation_id=corr_id,  # What: Deal tracking ID; Why: Associates failure with deal.
                    agent_name="GmailPoller",  # What: Agent/component name; Why: Gmail poller component.
                    action="deal_processing_failed",  # What: Action identifier; Why: Distinguishes failure events.
                    inputs=deal,  # What: Input deal payload; Why: Records inputs at time of failure.
                    outputs={"error": str(deal_err)},  # What: Error message; Why: Documents error reason.
                    decision_rationale=f"Daemon caught unhandled exception during deal processing: {deal_err}. Preserving poller loop.",  # What: Rationale string; Why: Explains fault tolerance boundary.
                    status=AuditActionStatus.FAILED  # What: Audit failure status; Why: Marks action as failed.
                )  # What: End of audit log call; Why: Record written to audit log.
                results.append({  # What: Append failure summary dict; Why: Records failed deal in poller return.
                    "correlation_id": corr_id,  # What: Correlation ID; Why: Reference.
                    "customer_name": deal.get("customer_name"),  # What: Customer name; Why: Deal identity.
                    "agent1_status": "FAILED",  # What: Agent 1 status; Why: Indicates failure.
                    "agent2_status": "SKIPPED",  # What: Agent 2 status; Why: Skipped due to error.
                    "rocketlane_project_id": None,  # What: Project ID None; Why: Creation failed.
                    "clarification_needed": False,  # What: Clarification flag False; Why: Failed before clarification check.
                    "draft_staged": False,  # What: Draft staged flag False; Why: No draft created.
                    "error": str(deal_err)  # What: Error string; Why: Explains failure reason.
                })  # What: End of failure summary dict; Why: Complete.

        return results  # What: Return execution results list; Why: Complete summary of polled deals.

    def start_polling(self, max_polls: Optional[int] = None) -> None:  # What: Main polling loop method; Why: Continuously polls Gmail inbox in background.
        """Starts continuous polling loop checking for unread deal emails every poll_interval seconds."""  # What: Docstring; Why: Explains loop behavior.
        _logger.info(f"Starting Gmail Poller for CS Inbox '{self.user}' (Subject filter: '{self.subject_filter}', Interval: {self.poll_interval}s)...")  # What: Log start; Why: Terminal visibility.
        poll_count = 0  # What: Counter integer; Why: Tracks number of iterations.
        try:  # What: Try block; Why: Catches KeyboardInterrupt cleanly.
            while True:  # What: Infinite polling loop; Why: Continuously monitors inbox.
                poll_count += 1  # What: Increment poll count; Why: Iteration tracking.
                try:  # What: Try block around polling iteration; Why: Prevents loop termination on transient errors.
                    self.process_incoming_deals()  # What: Process pending deals; Why: Runs pipeline if emails found.
                except Exception as poll_err:  # What: Catch loop iteration errors; Why: Survives transient IMAP disconnects or unexpected errors.
                    _logger.error(f"Error during poll iteration {poll_count}: {poll_err}", exc_info=True)  # What: Log iteration error; Why: Observability.

                if max_polls is not None and poll_count >= max_polls:  # What: Check max polls bound; Why: Exits if limit reached (for testing).
                    break  # What: Break loop; Why: Bounded execution.

                time.sleep(self.poll_interval)  # What: Sleep for poll interval seconds; Why: Waits before next poll.
        except KeyboardInterrupt:  # What: Catch user Ctrl+C; Why: Clean shutdown.
            _logger.info("Gmail Poller stopped by user.")  # What: Log shutdown; Why: Terminal confirmation.
        finally:  # What: Finally block; Why: Ensures disconnect on exit.
            self.disconnect()  # What: Call disconnect; Why: Closes IMAP session.


# Global singleton instance of Gmail poller
gmail_poller: GmailPoller = GmailPoller()  # What: Instantiate global Gmail poller; Why: Shared instance across application.
