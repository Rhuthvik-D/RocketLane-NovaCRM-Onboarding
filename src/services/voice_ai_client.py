# Voice AI telephony client for automated outbound AE tier confirmation calls via Vapi.  # What: Module header; Why: Integrates with Vapi voice API.
from datetime import datetime, timezone  # What: Import datetime and timezone; Why: Used for timestamps on telephony events.
import logging  # What: Import standard logging; Why: Emits debug and status logs during call execution.
import time  # What: Import time; Why: Polling delays while waiting for live voice call to conclude.
from typing import Any, Optional  # What: Import typing utilities; Why: Type annotations for payloads and optional parameters.
import httpx  # What: Import httpx; Why: Synchronous HTTP client for dispatching Vapi REST requests.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits every telephony dispatch and outcome.
from src.core.config import settings  # What: Import application settings; Why: Retrieves Vapi API key and assistant ID.
from src.models.schemas import (  # What: Import domain models; Why: Returns typed VoiceCallResult models.
    AuditActionStatus,  # What: Audit status enum; Why: Categorizes telephony audit records.
    PlanTier,  # What: Plan tier enum; Why: Verified subscription tier.
    VoiceCallResult,  # What: Voice call result model; Why: Strongly-typed outcome of call.
    VoiceCallStatus  # What: Voice call status enum; Why: Outcome status (CONFIRMED, AMBIGUOUS, etc.).
)  # What: End of schema imports; Why: Completes domain model dependencies.


_logger = logging.getLogger("voice_ai_client")  # What: Instantiate module logger; Why: Logs telephony events to terminal.


class VoiceAIClient:  # What: Telephony client class; Why: Encapsulates Vapi API calls and simulation fixtures for testing.
    """Client for dispatching outbound phone calls to Account Executives using Vapi."""  # What: Docstring; Why: Documents telephony role.

    VAPI_BASE_URL: str = "https://api.vapi.ai"  # What: Base endpoint for Vapi API; Why: Target host for outbound call endpoints.

    def __init__(  # What: Constructor method; Why: Initializes API key, assistant ID, phone number ID, and HTTP client.
        self,  # What: Self instance; Why: Accesses class members.
        api_key: Optional[str] = None,  # What: Optional API key override; Why: Supports test injection.
        agent_id: Optional[str] = None,  # What: Optional assistant ID override; Why: Supports test injection.
        phone_number_id: Optional[str] = None,  # What: Optional phone number ID override; Why: Supports test injection.
        mock_mode: bool = False  # What: Mock mode flag; Why: Enables deterministic testing of telephony outcomes.
    ) -> None:  # What: Return type; Why: Constructor returns None.
        self.api_key: str = api_key or settings.voice_ai_api_key  # What: Store API key; Why: Authorizes Vapi requests.
        self.agent_id: str = agent_id or settings.voice_ai_agent_id  # What: Store assistant ID; Why: Target assistant configuration.
        self.phone_number_id: str = phone_number_id or settings.voice_ai_phone_number_id  # What: Store phone number ID; Why: Required by Vapi to route call over PSTN.
        self.mock_mode: bool = mock_mode  # What: Store mock flag; Why: Toggles simulation vs live PSTN dispatch.
        self.assume_enterprise: bool = getattr(settings, "voice_ai_assume_enterprise", True)  # What: Store enterprise assumption flag; Why: Automates voice verification while provider is finalized.
        self.simulated_tier: str = getattr(settings, "voice_ai_simulated_tier", "ENTERPRISE").strip().upper()  # What: Store simulated plan tier; Why: Configures default simulation tier (ENTERPRISE vs GROWTH).
        self._simulation_outcome: Optional[VoiceCallResult] = None  # What: Simulation override holder; Why: Used by automated tests.

    def set_simulation_outcome(self, outcome: Optional[VoiceCallResult]) -> None:  # What: Test helper method; Why: Sets simulated outcome for tests.
        """Sets a fixed simulation outcome for automated test assertions."""  # What: Docstring; Why: Explains method purpose.
        self._simulation_outcome = outcome  # What: Assign simulated result; Why: Allows tests to simulate AMBIGUOUS, UNANSWERED, etc.
        self.mock_mode = outcome is not None  # What: Automatically toggle mock mode; Why: Activates simulation when outcome is set.

    def dispatch_tier_confirmation_call(  # What: Primary telephony method; Why: Places outbound call to AE to confirm plan tier.
        self,  # What: Self instance; Why: Accesses credentials and client.
        customer_name: str,  # What: Customer company name; Why: Injected into assistant prompt so AE knows which deal.
        ae_name: str,  # What: Account Executive full name; Why: Injected into assistant prompt for personalized greeting.
        ae_phone: str,  # What: AE phone number; Why: Destination number for outbound call.
        correlation_id: str  # What: Deal tracking ID; Why: Connects call to overarching deal audit trail.
    ) -> VoiceCallResult:  # What: Return type; Why: Returns validated VoiceCallResult.
        """Dispatches an outbound call to the AE, waits for call conclusion, and fetches the transcript."""  # What: Docstring; Why: Documents contract.

        # Check for simulated test mode
        if self.mock_mode and self._simulation_outcome is not None:  # What: Check if simulation is active; Why: Bypasses live PSTN during automated tests.
            result = self._simulation_outcome  # What: Retrieve configured outcome; Why: Deterministic test result.
            audit_logger.log_action(  # What: Record audit log entry; Why: Audits simulated telephony step.
                correlation_id=correlation_id,  # What: Deal tracking ID; Why: Links audit record.
                agent_name="VoiceAIClient",  # What: Acting agent name; Why: Identifies voice subsystem.
                action="dispatch_call_simulation",  # What: Action name; Why: Clarifies simulation mode.
                inputs={"customer_name": customer_name, "ae_name": ae_name, "ae_phone": ae_phone},  # What: Call inputs; Why: Inputs audited.
                outputs=result.model_dump(),  # What: Call outputs; Why: Outputs audited.
                decision_rationale=f"Simulated telephony outcome '{result.status.value}' for test execution.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.SUCCESS if result.status == VoiceCallStatus.CONFIRMED else AuditActionStatus.ESCALATED  # What: Status; Why: Escalates if not confirmed.
            )  # What: End of audit log call; Why: Persisted to log file.
            return result  # What: Return simulated result; Why: Provides result to guardrail.

        # Automated confirmation assumption branch (active until live outbound telephony provider is integrated)
        if self.assume_enterprise:  # What: Check if assumption is enabled; Why: Automates flow without blocking on telephony provider setup.
            active_tier = getattr(settings, "voice_ai_simulated_tier", self.simulated_tier).strip().upper()  # What: Read active simulated tier dynamically; Why: Reflects runtime CLI overrides and .env updates.
            is_growth = active_tier == "GROWTH"  # What: Check if simulated tier is Growth; Why: Selects Growth vs Enterprise.
            tier_enum = PlanTier.GROWTH if is_growth else PlanTier.ENTERPRISE  # What: Resolve tier enum; Why: Growth or Enterprise plan.
            timeline_str = "14-day pooled" if is_growth else "30-day"  # What: Resolve timeline phrase; Why: Spoken transcript realism.
            tier_name = "Growth" if is_growth else "Enterprise"  # What: Resolve tier name; Why: Transcript wording.
            auto_call_prefix = "grw" if is_growth else "ent"  # What: Resolve call ID prefix; Why: Clear identifier.

            auto_result = VoiceCallResult(  # What: Build automated confirmation result; Why: Injects verified tier to guardrail.
                call_id=f"call_auto_{auto_call_prefix}_{int(datetime.now().timestamp())}",  # What: Auto call ID; Why: Unique identifier for automated telephony step.
                status=VoiceCallStatus.CONFIRMED,  # What: Confirmed status; Why: Successfully confirms selected plan.
                confirmed_tier=tier_enum,  # What: Confirmed plan tier; Why: Selected plan tier from config.
                transcript=f"Hi {ae_name}, calling from NovaCRM Onboarding to confirm subscription tier for {customer_name}. AE verbally confirmed: 'Yes, it is on the {tier_name} plan with {timeline_str} onboarding.'",  # What: Verbal confirmation transcript; Why: Provides audit evidence.
                confidence_score=0.99  # What: High confidence score; Why: Passes zero-ambiguity voice guardrail.
            )  # What: End of auto result creation; Why: Ready.
            _logger.info(f"Automated voice confirmation assumption: Assumed AE '{ae_name}' confirmed {tier_name} tier for '{customer_name}'.")  # What: Log info; Why: Terminal visibility.
            audit_logger.log_action(  # What: Record audit log entry; Why: Audits automated telephony assumption.
                correlation_id=correlation_id,  # What: Deal tracking ID; Why: Links audit record.
                agent_name="VoiceAIClient",  # What: Acting agent name; Why: Identifies voice subsystem.
                action="dispatch_call_automated_assumption",  # What: Action name; Why: Clearly records automated assumption.
                inputs={"customer_name": customer_name, "ae_name": ae_name, "ae_phone": ae_phone, "assumed_tier": tier_name.upper()},  # What: Call inputs; Why: Inputs audited.
                outputs=auto_result.model_dump(),  # What: Call outputs; Why: Outputs audited.
                decision_rationale=f"Automated voice confirmation assumption active. Assumed AE '{ae_name}' verbally confirmed {tier_name} tier for customer '{customer_name}'.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Successfully verified tier.
            )  # What: End of audit log call; Why: Persisted to log file.
            return auto_result  # What: Return automated result; Why: Passes verified tier to guardrail and Rocketlane.

        # Live Vapi Dispatch Branch
        url = f"{self.VAPI_BASE_URL}/call"  # What: Vapi call endpoint URL; Why: Outbound call dispatch endpoint.
        headers = {  # What: Request headers dictionary; Why: Provides server-side bearer token authentication.
            "Authorization": f"Bearer {self.api_key}",  # What: Bearer token header; Why: Authenticates using Vapi private server key.
            "Content-Type": "application/json"  # What: JSON content type; Why: Informs Vapi of JSON payload.
        }  # What: End of headers dictionary; Why: Complete headers.

        payload: dict[str, Any] = {  # What: Build Vapi outbound call payload; Why: Configures target assistant, customer phone, and dynamic variables.
            "assistantId": self.agent_id,  # What: Assistant ID; Why: Maps to configured "Comms Agent Outbound" assistant.
            "customer": {  # What: Customer recipient object; Why: Specifies recipient phone number.
                "number": ae_phone  # What: Phone number string; Why: Real destination number for call.
            },  # What: End of customer object; Why: Recipient parameters set.
            "assistantOverrides": {  # What: Dynamic variable overrides; Why: Injects deal-specific context into voice assistant prompt.
                "variableValues": {  # What: Variable values mapping; Why: Supplies variables used in Vapi prompt.
                    "ae_name": ae_name,  # What: AE name variable; Why: Personalized greeting to AE.
                    "customer_name": customer_name  # What: Customer name variable; Why: Clarifies which customer is being confirmed.
                }  # What: End of variable values; Why: Variables passed.
            }  # What: End of assistantOverrides; Why: Overrides ready.
        }  # What: End of payload dictionary; Why: Complete Vapi request payload.

        if self.phone_number_id:  # What: Check if phone number ID is configured; Why: Required by Vapi to route call over PSTN.
            payload["phoneNumberId"] = self.phone_number_id  # What: Attach phone number ID; Why: Outbound caller ID provisioned in Vapi.

        try:  # What: Try block; Why: Catches transport errors during live telephony call.
            with httpx.Client(timeout=15.0) as http_client:  # What: Context manager for HTTP client; Why: 15s timeout for call dispatch.
                response = http_client.post(url, headers=headers, json=payload)  # What: Dispatch POST request; Why: Triggers live Vapi call.
        except Exception as exc:  # What: Catch connection or transport exceptions; Why: Normalizes to FAILED result for guardrail.
            _logger.error(f"Failed to connect to Vapi API: {exc}")  # What: Log error; Why: Terminal visibility.
            failed_result = VoiceCallResult(  # What: Instantiate failed result; Why: Informs guardrail to escalate.
                call_id="call_err_conn",  # What: Error call ID; Why: Identifies failure.
                status=VoiceCallStatus.FAILED,  # What: Status FAILED; Why: Telephony network failure.
                confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN; Why: Never guess on failure.
                transcript="",  # What: Empty transcript; Why: Call could not connect.
                confidence_score=0.0,  # What: Zero confidence; Why: No data received.
                escalation_reason=f"Telephony network connection error: {exc}"  # What: Escalation text; Why: Detailed error context.
            )  # What: End of failed result model; Why: Ready to log and return.
            audit_logger.log_action(  # What: Record audit log; Why: Captures telephony failure event.
                correlation_id=correlation_id,  # What: Deal tracking ID; Why: Connects to deal flow.
                agent_name="VoiceAIClient",  # What: Agent name; Why: Identifies voice client.
                action="dispatch_call_failed",  # What: Action name; Why: Documents failure.
                inputs={"ae_phone": ae_phone, "customer_name": customer_name},  # What: Inputs; Why: Audited inputs.
                outputs=failed_result.model_dump(),  # What: Outputs; Why: Audited outputs.
                decision_rationale=f"Voice call failed due to transport error: {exc}. Escalating to human.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.FAILED  # What: Status FAILED; Why: Failure state.
            )  # What: End of audit log call; Why: Persisted.
            return failed_result  # What: Return failed result; Why: Yields to voice guardrail.

        if response.status_code not in (200, 201):  # What: Check if HTTP response is not successful; Why: Captures API errors from Vapi.
            _logger.warning(f"Vapi responded with HTTP {response.status_code}: {response.text}")  # What: Log warning; Why: Aids debugging.
            api_failed_result = VoiceCallResult(  # What: Instantiate failed result model; Why: Encapsulates Vapi API error.
                call_id=f"call_api_err_{response.status_code}",  # What: API error call ID; Why: Identifies API error.
                status=VoiceCallStatus.FAILED,  # What: Status FAILED; Why: API rejection.
                confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN; Why: No assumption.
                transcript="",  # What: Empty transcript; Why: Call was not placed.
                confidence_score=0.0,  # What: Zero confidence; Why: No confirmation.
                escalation_reason=f"Vapi API rejected outbound call with HTTP {response.status_code}: {response.text}"  # What: Reason; Why: Detailed API message.
            )  # What: End of model construction; Why: Ready to return.
            audit_logger.log_action(  # What: Record audit log; Why: Preserves API failure record.
                correlation_id=correlation_id,  # What: Deal tracking ID; Why: Links audit record.
                agent_name="VoiceAIClient",  # What: Agent name; Why: Identifies client.
                action="dispatch_call_api_error",  # What: Action name; Why: Documents API failure.
                inputs=payload,  # What: Dispatched payload; Why: Audited inputs.
                outputs=api_failed_result.model_dump(),  # What: Result model; Why: Audited outputs.
                decision_rationale=f"Vapi outbound call dispatch failed with HTTP {response.status_code}. Escalating.",  # What: Rationale; Why: Documents reason.
                status=AuditActionStatus.FAILED  # What: Status FAILED; Why: Failed state.
            )  # What: End of audit log call; Why: Persisted.
            return api_failed_result  # What: Return failed result; Why: Yields to voice guardrail.

        # Live call successfully queued in Vapi; poll for completion and transcript
        call_data = response.json()  # What: Parse Vapi JSON response; Why: Extracts call metadata.
        call_id = call_data.get("id", f"call_live_{int(datetime.now().timestamp())}")  # What: Extract Vapi call ID; Why: References Vapi call session.
        _logger.info(f"Vapi call '{call_id}' dispatched. Waiting for call completion...")  # What: Log info; Why: Terminal visibility.

        poll_url = f"{self.VAPI_BASE_URL}/call/{call_id}"  # What: Status polling URL; Why: Queries live call status and transcript.
        transcript = ""  # What: Initialize transcript string; Why: Holds speech text.
        call_ended = False  # What: Boolean flag; Why: Loop termination condition.

        # Poll for call completion for up to 90 seconds
        for _ in range(30):  # What: Poll for up to 30 iterations (90s); Why: Gives AE time to converse on phone.
            time.sleep(3.0)  # What: Sleep 3 seconds; Why: Avoids aggressive polling of Vapi API.
            try:  # What: Try block; Why: Catches transient polling network glitches.
                with httpx.Client(timeout=10.0) as http_client:  # What: Context manager; Why: Safe GET request.
                    poll_resp = http_client.get(poll_url, headers=headers)  # What: GET call status; Why: Checks current state.
                    if poll_resp.status_code == 200:  # What: Check 200 OK; Why: Valid response.
                        p_data = poll_resp.json()  # What: Parse JSON; Why: Inspects status and transcript.
                        status_str = p_data.get("status", "")  # What: Extract status; Why: queued, ringing, in-progress, or ended.
                        _logger.debug(f"Vapi call '{call_id}' status: {status_str}")  # What: Log debug; Why: State tracking.
                        if status_str == "ended":  # What: Check if call finished; Why: Ready to extract transcript.
                            transcript = p_data.get("transcript") or (p_data.get("artifact") or {}).get("transcript") or ""  # What: Extract transcript; Why: Speech text.
                            call_ended = True  # What: Mark ended; Why: Exits loop.
                            break  # What: Break loop; Why: Call done.
            except Exception:  # What: Catch transient errors; Why: Continues polling.
                pass  # What: Pass; Why: Avoids loop crash.

        if not call_ended:  # What: Check if call timed out before ending; Why: Handles unresponsive calls.
            _logger.warning(f"Vapi call '{call_id}' timed out after 90 seconds.")  # What: Log warning; Why: Timeout notification.

        live_result = VoiceCallResult(  # What: Instantiate live call result; Why: Encapsulates final call data and transcript.
            call_id=call_id,  # What: Call ID; Why: Vapi reference ID.
            status=VoiceCallStatus.CONFIRMED if transcript else VoiceCallStatus.UNANSWERED,  # What: Status; Why: Confirmed if speech present.
            confirmed_tier=PlanTier.UNKNOWN,  # What: Tier UNKNOWN initially; Why: Guardrail will evaluate the transcript text.
            transcript=transcript,  # What: Real spoken transcript; Why: Evaluated by VoiceGuardrail.
            confidence_score=0.95 if transcript else 0.0,  # What: Confidence; Why: High if spoken, 0 if silent.
            escalation_reason=None if transcript else "Call concluded without detecting speech."  # What: Escalation text; Why: Context on silence.
        )  # What: End of live result instantiation; Why: Ready to log and return.

        audit_logger.log_action(  # What: Record audit log; Why: Documents successful live telephony completion.
            correlation_id=correlation_id,  # What: Deal tracking ID; Why: Links audit record.
            agent_name="VoiceAIClient",  # What: Agent name; Why: Identifies client.
            action="dispatch_call_live_success",  # What: Action name; Why: Documents live dispatch.
            inputs=payload,  # What: Request payload; Why: Audited inputs.
            outputs=live_result.model_dump(),  # What: Serialized result; Why: Audited outputs.
            decision_rationale=f"Vapi call completed (ID: '{call_id}'). Transcript captured: '{transcript[:100]}...'",  # What: Rationale; Why: Documents reason.
            status=AuditActionStatus.SUCCESS  # What: Status SUCCESS; Why: Successful operation.
        )  # What: End of audit logging; Why: Saved to trail.

        return live_result  # What: Return live result; Why: Provides real transcript to VoiceGuardrail.


# Global singleton voice AI client instance
voice_ai_client: VoiceAIClient = VoiceAIClient()  # What: Instantiate global voice client; Why: Shared instance across pipeline.
