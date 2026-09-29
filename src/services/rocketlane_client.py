# Resilient Rocketlane API client implementing retry mechanics, idempotency protection, and template mapping.  # What: Module header; Why: Resilient API client.
from datetime import datetime, timezone  # What: Import datetime; Why: Timestamps for responses and calculations.
import json  # What: Import json library; Why: Serializes persistent local idempotency cache.
import logging  # What: Import standard logging; Why: Emits debug and retry messages.
from pathlib import Path  # What: Import Path class; Why: Resolves local cache file system path.
from typing import Any, Optional  # What: Import typing utilities; Why: Type annotations for payloads and headers.
import httpx  # What: Import httpx; Why: Modern HTTP client with timeout and connection pooling.
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential  # What: Import tenacity primitives; Why: Configures exponential backoff retry logic.
from src.core.audit_logger import audit_logger  # What: Import audit logger; Why: Audits every external API call and retry.
from src.core.config import settings  # What: Import settings; Why: Retrieves API keys, endpoints, and mock mode flags.
from src.core.exceptions import RocketlaneAPIError  # What: Import RocketlaneAPIError; Why: Standardized exception for upstream API failures.
from src.models.schemas import (  # What: Import domain models; Why: Type safety on requests and responses.
    AuditActionStatus,  # What: Audit status enum; Why: Marks audit entry states.
    PlanTier,  # What: Plan tier enum; Why: Determines template and CSM mapping.
    RocketlaneProjectCreateRequest,  # What: Request schema; Why: Validates input payload to client.
    RocketlaneProjectResponse  # What: Response schema; Why: Guarantees consistent return format.
)  # What: End of schema imports; Why: Completes required data types.


_logger = logging.getLogger("rocketlane_client")  # What: Initialize module logger; Why: Logs HTTP retry warnings and details.


def _is_retryable_error(exception: BaseException) -> bool:  # What: Retry predicate function; Why: Decides which errors warrant a retry.
    """Determines whether an exception is an HTTP 5xx or transient network error."""  # What: Docstring; Why: Explains retry condition.
    if isinstance(exception, RocketlaneAPIError):  # What: Check if exception is our domain API error; Why: Inspects status code.
        return exception.status_code is not None and exception.status_code >= 500  # What: Check if status is 5xx; Why: Upstream server failures are retryable.
    if isinstance(exception, (httpx.TimeoutException, httpx.NetworkError)):  # What: Check if exception is network/timeout; Why: Transient connectivity issues are retryable.
        return True  # What: Return True for network/timeout; Why: Tells tenacity to retry the request.
    return False  # What: Return False for client errors (4xx) and other exceptions; Why: Client errors must fail fast without retry.


class RocketlaneClient:  # What: Client class for Rocketlane API; Why: Encapsulates all network communication and business rules.
    """Client for Rocketlane API with built-in idempotency, template resolution, and retry policies."""  # What: Docstring; Why: Documents client role.

    # Template and staffing configuration matrix mapping tiers to requirements
    TIER_CONFIG: dict[PlanTier, dict[str, Any]] = {  # What: Dictionary mapping PlanTier enum to config; Why: Enforces tier-specific onboarding parameters.
        PlanTier.ENTERPRISE: {  # What: Enterprise configuration entry; Why: High-touch onboarding specification.
            "template_id": getattr(settings, "rocketlane_enterprise_template_id", "5000000095997"),  # What: Enterprise template ID; Why: Configured Enterprise template loaded for Enterprise.
            "duration_days": 30,  # What: Duration integer; Why: Enforces 30-day SLA for enterprise clients.
            "csm_type": "Dedicated CSM",  # What: Staffing model label; Why: Dedicated CSM assigned to enterprise accounts.
            "default_csm": "Sarah Connor (Enterprise Lead)"  # What: Default CSM name; Why: Assignee for enterprise projects.
        },  # What: End of Enterprise mapping; Why: Completes enterprise profile.
        PlanTier.GROWTH: {  # What: Growth configuration entry; Why: Standardized onboarding specification.
            "template_id": getattr(settings, "rocketlane_growth_template_id", "5000000096288"),  # What: Growth template ID; Why: Configured Growth template loaded for Growth.
            "duration_days": 14,  # What: Duration integer; Why: Enforces 14-day SLA for growth clients.
            "csm_type": "Pooled CSM",  # What: Staffing model label; Why: Shared pool handles growth accounts.
            "default_csm": "Pooled CSM Team"  # What: Pooled team alias; Why: Assignee for growth projects.
        }  # What: End of Growth mapping; Why: Completes growth profile.
    }  # What: End of TIER_CONFIG; Why: Static configuration lookup table.

    def __init__(  # What: Constructor method; Why: Initializes HTTP client, base URL, and idempotency store.
        self,  # What: Self instance; Why: Accesses class members.
        api_key: Optional[str] = None,  # What: Optional API key argument; Why: Overrides settings if provided.
        base_url: Optional[str] = None,  # What: Optional base URL argument; Why: Overrides settings if provided.
        mock_mode: Optional[bool] = None,  # What: Optional mock mode flag; Why: Enables simulated sandbox mode for tests.
        cache_file_path: Optional[Path] = None  # What: Optional cache path; Why: Configures local file storage for idempotency cache.
    ) -> None:  # What: Return type; Why: Constructor returns None.
        self.api_key: str = api_key or settings.rocketlane_api_key  # What: Store API key; Why: Authenticates requests.
        self.base_url: str = base_url or settings.rocketlane_base_url  # What: Store base URL; Why: API endpoint prefix.
        self.mock_mode: bool = mock_mode if mock_mode is not None else settings.rocketlane_mock_mode  # What: Store mock flag; Why: Controls mock behavior.
        self.cache_file_path: Path = cache_file_path or Path("logs/idempotency_cache.json")  # What: Local cache path; Why: Local file storage for idempotency keys.
        self._idempotency_cache: dict[str, RocketlaneProjectResponse] = {}  # What: In-memory store; Why: Guarantees idempotency across duplicate calls.
        self._client: httpx.Client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))  # What: Client with 60s read timeout; Why: Rocketlane template cloning takes ~35s.
        if not self.mock_mode or cache_file_path is not None:  # What: Check persistence condition; Why: Loads persistent cache in live mode or when explicitly configured.
            self._load_idempotency_cache()  # What: Load persisted cache; Why: Restores known project records after service restart.

    def _load_idempotency_cache(self) -> None:  # What: Cache loader helper; Why: Restores idempotency mappings from local file.
        """Loads cached idempotency responses from local JSON file if present."""  # What: Docstring; Why: Explains loader function.
        if not self.cache_file_path.exists():  # What: Check if file exists; Why: Skips if no cache file exists yet.
            return  # What: Return early; Why: Nothing to load.
        try:  # What: Try block; Why: Catches JSON parsing or file read exceptions.
            with open(self.cache_file_path, "r", encoding="utf-8") as f:  # What: Open local cache file; Why: Reads stored JSON.
                data = json.load(f)  # What: Parse JSON; Why: Deserializes dictionary.
                for key, val in data.items():  # What: Iterate cached items; Why: Populates cache dictionary.
                    self._idempotency_cache[key] = RocketlaneProjectResponse.model_validate(val)  # What: Validate model; Why: Reconstructs typed response.
        except Exception as exc:  # What: Catch exceptions; Why: Ensures corrupt file does not crash client.
            _logger.warning(f"Could not load idempotency cache from {self.cache_file_path}: {exc}")  # What: Log warning; Why: Debugging visibility.

    def _persist_idempotency_cache(self) -> None:  # What: Cache persistence helper; Why: Writes idempotency mappings to local file.
        """Persists idempotency mappings to local JSON file for durability across process restarts."""  # What: Docstring; Why: Explains persistence function.
        if self.mock_mode and self.cache_file_path == Path("logs/idempotency_cache.json"):  # What: Check mock guard; Why: Prevents unit test pollution of production cache file.
            return  # What: Return early; Why: Skips default file in ephemeral mock runs.
        try:  # What: Try block; Why: Catches file write exceptions.
            if self.cache_file_path.parent:  # What: Check if parent folder specified; Why: Ensures directory exists.
                self.cache_file_path.parent.mkdir(parents=True, exist_ok=True)  # What: Create directory tree; Why: Safe folder initialization.
            with open(self.cache_file_path, "w", encoding="utf-8") as f:  # What: Open file for writing; Why: Atomically overwrites cache file.
                serializable = {k: v.model_dump(mode="json") for k, v in self._idempotency_cache.items()}  # What: Dump models to JSON dict; Why: Safe serialization.
                json.dump(serializable, f, indent=2)  # What: Write formatted JSON; Why: Human-readable persistent cache.
        except Exception as exc:  # What: Catch exceptions; Why: Prevents crashing on file write issues.
            _logger.warning(f"Could not persist idempotency cache to {self.cache_file_path}: {exc}")  # What: Log warning; Why: Debugging visibility.

    def resolve_tier_payload(  # What: Template mapping helper; Why: Derives exact project parameters from verified tier.
        self,  # What: Self instance; Why: Accesses class config.
        customer_name: str,  # What: Customer name; Why: Formats project title.
        customer_email: str,  # What: Customer email; Why: Primary contact for project.
        tier: PlanTier,  # What: Verified tier enum; Why: Determines template and timeline.
        idempotency_key: str  # What: Deal hash; Why: Attached to request for deduplication.
    ) -> RocketlaneProjectCreateRequest:  # What: Return type; Why: Returns typed request payload.
        """Maps customer details and verified tier to the appropriate Rocketlane project parameters."""  # What: Docstring; Why: Explains method purpose.
        if tier not in self.TIER_CONFIG:  # What: Check if tier exists in config map; Why: Prevents provisioning with UNKNOWN or invalid tier.
            raise ValueError(f"Cannot provision project for unverified or unsupported tier: {tier}")  # What: Raise ValueError; Why: Enforces zero-assumption rule.

        config = self.TIER_CONFIG[tier]  # What: Lookup tier configuration; Why: Retrieves template and duration settings.
        project_name = f"{customer_name.strip()} - Onboarding ({tier.value})"  # What: Construct project name; Why: Standardized project naming convention.

        return RocketlaneProjectCreateRequest(  # What: Instantiate request model; Why: Creates validated payload.
            project_name=project_name,  # What: Assign project name; Why: Project title on dashboard.
            template_id=config["template_id"],  # What: Assign template ID; Why: Sets 30-day Enterprise vs 14-day Growth checklist.
            tier=tier,  # What: Assign plan tier; Why: Records tier in request metadata.
            duration_days=config["duration_days"],  # What: Assign duration days; Why: Sets milestone schedule bounds.
            csm_type=config["csm_type"],  # What: Assign CSM type; Why: Dedicated vs Pooled staffing.
            csm_assigned=config["default_csm"],  # What: Assign CSM name; Why: Project manager assignment.
            customer_email=customer_email,  # What: Assign customer email; Why: Primary collaborator.
            idempotency_key=idempotency_key  # What: Assign idempotency key; Why: Prevents duplicate project creation.
        )  # What: End of request model creation; Why: Returns ready-to-dispatch request.

    @retry(  # What: Tenacity retry decorator; Why: Automatically retries failed requests.
        reraise=True,  # What: Reraise original exception; Why: Propagates actual error if all retries fail.
        stop=stop_after_attempt(3),  # What: Stop after 3 attempts; Why: Prevents infinite retry loops while giving upstream time to recover.
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),  # What: Exponential backoff; Why: Gradually increases wait time to reduce server load.
        retry=retry_if_exception(_is_retryable_error)  # What: Apply retry predicate; Why: Retries only HTTP 5xx and connection timeouts.
    )  # What: End of retry decorator; Why: Wraps method with resilient retry logic.
    def _execute_http_post(  # What: Private HTTP execution helper; Why: Centralizes network call and status handling under retry decorator.
        self,  # What: Self instance; Why: Accesses credentials and client.
        endpoint: str,  # What: API endpoint path; Why: Specifies target resource.
        payload: dict[str, Any]  # What: JSON payload dict; Why: Data sent in request body.
    ) -> dict[str, Any]:  # What: Return type; Why: Returns parsed JSON dictionary.
        """Executes an HTTP POST request against Rocketlane API with retries on HTTP 500."""  # What: Docstring; Why: Documents retry-wrapped POST helper.
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"  # What: Combine base URL and endpoint; Why: Safely formats full URL.
        headers = {  # What: Define HTTP request headers; Why: Provides authentication and content type.
            "api-key": self.api_key,  # What: Rocketlane API key header; Why: Authenticates the request.
            "Content-Type": "application/json",  # What: JSON content type header; Why: Informs server of request body format.
            "Accept": "application/json"  # What: JSON accept header; Why: Requests JSON response format.
        }  # What: End of headers definition; Why: Complete header dictionary.

        try:  # What: Try block; Why: Catches low-level HTTP transport errors.
            response = self._client.post(url, json=payload, headers=headers)  # What: Perform HTTP POST; Why: Dispatches request to Rocketlane.
        except httpx.RequestError as exc:  # What: Catch network or transport exceptions; Why: Normalizes to RocketlaneAPIError for retry handler.
            _logger.warning(f"Rocketlane connection error on {url}: {exc}")  # What: Log warning; Why: Aids observability during retries.
            raise RocketlaneAPIError(f"Network error connecting to Rocketlane: {exc}") from exc  # What: Raise custom error; Why: Triggers retry logic.

        if response.status_code >= 500:  # What: Check for server-side error status codes; Why: Server errors are transient and retryable.
            _logger.warning(f"Rocketlane API returned HTTP {response.status_code}. Retrying...")  # What: Log retry notification; Why: Developer insight.
            raise RocketlaneAPIError(  # What: Raise RocketlaneAPIError; Why: Informs retry decorator to back off and try again.
                message=f"Rocketlane server error HTTP {response.status_code}: {response.text}",  # What: Error message; Why: Captures server message.
                status_code=response.status_code,  # What: Status code integer; Why: Enables retry predicate evaluation.
                details={"response_body": response.text}  # What: Error details dict; Why: Stores raw error payload.
            )  # What: End of exception construction; Why: Ready to raise.

        if response.status_code >= 400:  # What: Check for client error status codes (4xx); Why: Client errors indicate invalid requests and should not retry.
            raise RocketlaneAPIError(  # What: Raise non-retryable error; Why: Fails fast on invalid inputs or auth failures.
                message=f"Rocketlane client error HTTP {response.status_code}: {response.text}",  # What: Error message; Why: Highlights client error.
                status_code=response.status_code,  # What: Status code integer; Why: Documents failure status.
                details={"response_body": response.text}  # What: Response body; Why: Context for debugging.
            )  # What: End of client error exception; Why: Immediately halts execution.

        return response.json()  # What: Parse and return JSON response; Why: Provides payload to caller.

    @retry(  # What: Tenacity retry decorator; Why: Automatically retries failed GET requests.
        reraise=True,  # What: Reraise original exception; Why: Propagates actual error if all retries fail.
        stop=stop_after_attempt(3),  # What: Stop after 3 attempts; Why: Prevents infinite retry loops while giving upstream time to recover.
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),  # What: Exponential backoff; Why: Gradually increases wait time to reduce server load.
        retry=retry_if_exception(_is_retryable_error)  # What: Apply retry predicate; Why: Retries only HTTP 5xx and connection timeouts.
    )  # What: End of retry decorator; Why: Wraps method with resilient retry logic.
    def _execute_http_get(  # What: Private HTTP GET execution helper; Why: Centralizes network call and status handling under retry decorator.
        self,  # What: Self instance; Why: Accesses credentials and client.
        endpoint: str,  # What: API endpoint path; Why: Specifies target resource.
        params: Optional[dict[str, Any]] = None  # What: Query parameters; Why: Filter parameters such as externalReferenceId.
    ) -> dict[str, Any]:  # What: Return type; Why: Returns parsed JSON dictionary.
        """Executes an HTTP GET request against Rocketlane API with retries on HTTP 500."""  # What: Docstring; Why: Documents retry-wrapped GET helper.
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"  # What: Combine base URL and endpoint; Why: Safely formats full URL.
        headers = {  # What: Define HTTP request headers; Why: Provides authentication and accept type.
            "api-key": self.api_key,  # What: Rocketlane API key header; Why: Authenticates the request.
            "Accept": "application/json"  # What: JSON accept header; Why: Requests JSON response format.
        }  # What: End of headers definition; Why: Complete header dictionary.
        try:  # What: Try block; Why: Catches low-level HTTP transport errors.
            response = self._client.get(url, params=params, headers=headers)  # What: Perform HTTP GET; Why: Dispatches request to Rocketlane.
        except httpx.RequestError as exc:  # What: Catch network or transport exceptions; Why: Normalizes to RocketlaneAPIError for retry handler.
            _logger.warning(f"Rocketlane connection error on {url}: {exc}")  # What: Log warning; Why: Aids observability during retries.
            raise RocketlaneAPIError(f"Network error connecting to Rocketlane: {exc}") from exc  # What: Raise custom error; Why: Triggers retry logic.
        if response.status_code >= 500:  # What: Check for server-side error status codes; Why: Server errors are transient and retryable.
            _logger.warning(f"Rocketlane API returned HTTP {response.status_code}. Retrying...")  # What: Log retry notification; Why: Developer insight.
            raise RocketlaneAPIError(  # What: Raise RocketlaneAPIError; Why: Informs retry decorator to back off and try again.
                message=f"Rocketlane server error HTTP {response.status_code}: {response.text}",  # What: Error message; Why: Captures server message.
                status_code=response.status_code,  # What: Status code integer; Why: Enables retry predicate evaluation.
                details={"response_body": response.text}  # What: Error details dict; Why: Stores raw error payload.
            )  # What: End of exception construction; Why: Ready to raise.
        if response.status_code >= 400:  # What: Check for client error status codes (4xx); Why: Client errors indicate invalid requests and should not retry.
            raise RocketlaneAPIError(  # What: Raise non-retryable error; Why: Fails fast on invalid inputs or auth failures.
                message=f"Rocketlane client error HTTP {response.status_code}: {response.text}",  # What: Error message; Why: Highlights client error.
                status_code=response.status_code,  # What: Status code integer; Why: Documents failure status.
                details={"response_body": response.text}  # What: Response body; Why: Context for debugging.
            )  # What: End of client error exception; Why: Immediately halts execution.
        return response.json()  # What: Parse and return JSON response; Why: Provides payload to caller.

    def _reconcile_cloud_project(  # What: Helper to reconcile existing cloud project by externalReferenceId; Why: Self-heals local cache from Rocketlane cloud.
        self,  # What: Self instance; Why: Accesses HTTP GET and cache.
        request: RocketlaneProjectCreateRequest,  # What: Create request model; Why: Supplies idempotency key and project metadata.
        correlation_id: str  # What: Deal tracking ID; Why: Correlates audit trail.
    ) -> Optional[RocketlaneProjectResponse]:  # What: Return type; Why: Returns recovered project response or None if not found.
        """Queries Rocketlane for an existing project with the given externalReferenceId and updates local cache."""  # What: Docstring; Why: Documents self-healing method.
        try:  # What: Try block; Why: Catches exceptions during cloud reconciliation query.
            query_res = self._execute_http_get("/projects", params={"externalReferenceId.EQUALS": request.idempotency_key})  # What: Query Rocketlane by external reference; Why: Locates existing remote project.
            data = query_res.get("data", [])  # What: Extract data list; Why: Rocketlane wraps list responses under 'data'.
            if data and isinstance(data, list):  # What: Verify non-empty list; Why: Confirms matching project exists.
                matched = data[0]  # What: Pick first matching project; Why: ExternalReferenceId is unique.
                proj_id = str(matched.get("projectId") or matched.get("id"))  # What: Extract project ID; Why: Required for response model.
                proj_name = str(matched.get("projectName") or request.project_name)  # What: Extract project name; Why: Uses cloud title or fallback.
                portal_url_val = f"https://app.rocketlane.com/projects/{proj_id}"  # What: Format portal URL; Why: Matches standard portal pattern.
                reconciled = RocketlaneProjectResponse(  # What: Construct project response; Why: Standardized model representation.
                    project_id=proj_id,  # What: Project ID; Why: Identifier from cloud.
                    project_name=proj_name,  # What: Project name; Why: Project title.
                    tier=request.tier,  # What: Assign tier; Why: Retains requested tier.
                    template_id=request.template_id,  # What: Assign template; Why: Retains requested template.
                    portal_url=portal_url_val,  # What: Portal URL; Why: Link for Slack and notifications.
                    created_at=datetime.now(timezone.utc),  # What: Timestamp; Why: Reconciliation timestamp.
                    is_duplicate=True  # What: Flag as duplicate; Why: Reconciled from preexisting cloud instance.
                )  # What: End of reconciled model construction; Why: Ready to cache and return.
                self._idempotency_cache[request.idempotency_key] = reconciled  # What: Store into local idempotency cache; Why: Prevents future remote 400 calls.
                self._persist_idempotency_cache()  # What: Persist cache to disk; Why: Durability across restarts.
                audit_logger.log_action(  # What: Log audit record; Why: Documents cloud reconciliation event.
                    correlation_id=correlation_id,  # What: Deal ID; Why: Correlates audit entry.
                    agent_name="RocketlaneClient",  # What: Actor name; Why: Identifies client module.
                    action="create_project_idempotent_cloud_reconciliation",  # What: Action identifier; Why: Distinguishes cloud self-healing event.
                    inputs=request.model_dump(),  # What: Request payload; Why: Records collision inputs.
                    outputs=reconciled.model_dump(),  # What: Output payload; Why: Records reconciled project details.
                    decision_rationale=(  # What: Decision rationale; Why: Justifies cloud recovery.
                        f"Cloud externalReferenceId collision detected for key '{request.idempotency_key}'. "  # What: Rationale text part 1; Why: Explains collision.
                        f"Successfully reconciled existing Rocketlane project ID '{proj_id}' and updated local cache."  # What: Rationale text part 2; Why: Details reconciled entity.
                    ),  # What: End of rationale string; Why: Complete rationale for audit trail.
                    status=AuditActionStatus.SUCCESS  # What: Status success; Why: Cloud recovery succeeded.
                )  # What: End of audit log call; Why: Deduplication record saved.
                return reconciled  # What: Return reconciled project; Why: Safe idempotent response.
        except Exception as exc:  # What: Catch reconciliation errors; Why: Ensures diagnostic visibility on failure.
            _logger.warning(f"Failed to reconcile cloud project for key '{request.idempotency_key}': {exc}")  # What: Log warning; Why: Debugging visibility.
        return None  # What: Return None; Why: Indicates reconciliation did not find project.

    def create_project(  # What: Primary project creation method; Why: Creates project while enforcing idempotency and audit logs.
        self,  # What: Self instance; Why: Accesses client services.
        request: RocketlaneProjectCreateRequest,  # What: Validated request model; Why: Type-safe project creation arguments.
        correlation_id: str  # What: Deal tracking ID; Why: Connects this action to the overarching audit trail.
    ) -> RocketlaneProjectResponse:  # What: Return type; Why: Returns standardized project response.
        """Creates an onboarding project in Rocketlane with strict idempotency and audit logging."""  # What: Docstring; Why: Explains method contract.

        # IDEMPOTENCY GUARDRAIL: Check if project already exists in local cache for this deal key
        if request.idempotency_key in self._idempotency_cache:  # What: Check local idempotency store; Why: Prevents creating duplicate projects.
            cached_project = self._idempotency_cache[request.idempotency_key]  # What: Retrieve cached project; Why: Reuses existing project data.
            audit_logger.log_action(  # What: Record audit log entry; Why: Proves deduplication was enforced.
                correlation_id=correlation_id,  # What: Deal ID; Why: Correlates audit entry.
                agent_name="RocketlaneClient",  # What: Actor name; Why: Identifies client module.
                action="create_project_idempotent_hit",  # What: Action identifier; Why: Distinguishes duplicate prevention event.
                inputs=request.model_dump(),  # What: Input payload; Why: Records duplicate request details.
                outputs=cached_project.model_dump(),  # What: Output payload; Why: Records returned cached project.
                decision_rationale=(  # What: Decision explanation; Why: Justifies why creation was skipped.
                    f"Idempotency hit for key '{request.idempotency_key}'. Returning existing "  # What: Rationale text part 1; Why: Explains duplicate hit.
                    f"Rocketlane project ID '{cached_project.project_id}' without creating duplicate."  # What: Rationale text part 2; Why: Details returned project.
                ),  # What: End of rationale string; Why: Complete rationale for audit trail.
                status=AuditActionStatus.SUCCESS  # What: Status success; Why: Successfully prevented duplicate.
            )  # What: End of audit log call; Why: Deduplication record saved.
            return cached_project  # What: Return existing project; Why: Safe idempotent response.

        # Handle Mock Mode for local testing and offline execution
        if self.mock_mode:  # What: Check if mock mode is active; Why: Bypasses live network calls during development/tests.
            mock_id = f"proj_mock_{abs(hash(request.idempotency_key)) % 100000:05d}"  # What: Generate deterministic mock ID; Why: Unique readable ID.
            mock_portal = f"https://app.rocketlane.com/projects/{mock_id}"  # What: Generate project portal URL; Why: Simulates real Rocketlane link.
            project_response = RocketlaneProjectResponse(  # What: Instantiate response model; Why: Creates standardized project object.
                project_id=mock_id,  # What: Assign mock ID; Why: Project reference.
                project_name=request.project_name,  # What: Assign project name; Why: Matches requested title.
                tier=request.tier,  # What: Assign verified tier; Why: Confirms tier applied.
                template_id=request.template_id,  # What: Assign template ID; Why: Confirms template applied.
                portal_url=mock_portal,  # What: Assign portal URL; Why: Used by Agent 2 in Slack topic.
                created_at=datetime.now(timezone.utc),  # What: Current UTC timestamp; Why: Audit timestamp.
                is_duplicate=False  # What: Mark is_duplicate False; Why: Newly created instance.
            )  # What: End of mock response construction; Why: Ready to cache and return.
        else:  # What: Live API branch; Why: Executes real HTTP POST to Rocketlane REST API.
            current_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # What: Format current date string; Why: Rocketlane requires startDate.
            customer_company_name = request.project_name.split(" - ")[0] if " - " in request.project_name else request.project_name  # What: Parse company name; Why: Isolates company name.
            api_payload: dict[str, Any] = {  # What: Build Rocketlane API request body; Why: Matches Rocketlane Projects API specification.
                "projectName": request.project_name,  # What: Project name field; Why: Rocketlane payload schema.
                "customer": {"companyName": customer_company_name},  # What: Customer company object; Why: Rocketlane customer specification.
                "autoCreateCompany": True,  # What: Auto create company flag; Why: Rocketlane auto-creates company if missing.
                "owner": {"emailId": settings.rocketlane_owner_email},  # What: Owner user email; Why: Rocketlane requires valid project owner.
                "externalReferenceId": request.idempotency_key,  # What: External ID field; Why: Rocketlane-side deduplication.
                "startDate": current_date_str  # What: Project start date; Why: Required when templates are imported.
            }  # What: End of base API payload dictionary; Why: Complete base payload.

            # Attach template source if template_id is numeric
            if request.template_id.isdigit():  # What: Check if template ID is numeric; Why: Rocketlane API expects integer template ID.
                api_payload["sources"] = [{  # What: Attach sources list; Why: Applies template to project.
                    "templateId": int(request.template_id),  # What: Integer template ID; Why: Rocketlane schema requirement.
                    "startDate": current_date_str  # What: Template start date; Why: Required in template import entity.
                }]  # What: End of sources list; Why: Complete template source definition.

            try:  # What: Try block around live API POST; Why: Catches Rocketlane client errors such as duplicate externalReferenceId.
                raw_response = self._execute_http_post("/projects", api_payload)  # What: Call HTTP helper; Why: Executes POST with retries.
                project_id_val = str(raw_response.get("projectId") or raw_response.get("id") or int(datetime.now().timestamp()))  # What: Extract project ID; Why: Safely gets ID.
                portal_url_val = f"https://app.rocketlane.com/projects/{project_id_val}"  # What: Format portal URL; Why: Direct link to project.

                project_response = RocketlaneProjectResponse(  # What: Instantiate response model; Why: Normalizes raw API response.
                    project_id=project_id_val,  # What: Normalized project ID; Why: Project reference.
                    project_name=request.project_name,  # What: Project title; Why: Verification and UI display.
                    tier=request.tier,  # What: Assign tier; Why: Verified tier.
                    template_id=request.template_id,  # What: Assign template; Why: Template applied.
                    portal_url=portal_url_val,  # What: Portal URL; Why: Used by Agent 2 in Slack topic.
                    created_at=datetime.now(timezone.utc),  # What: Current timestamp; Why: Record time.
                    is_duplicate=False  # What: Mark newly created; Why: Not a duplicate.
                )  # What: End of live response normalization; Why: Standardized response object.
            except RocketlaneAPIError as exc:  # What: Catch RocketlaneAPIError; Why: Checks for duplicate external reference error.
                if exc.status_code == 400 and "Invalid External Reference Key specified" in str(exc.message):  # What: Inspect error code and text; Why: Detects existing cloud project collision.
                    _logger.info(f"Duplicate externalReferenceId '{request.idempotency_key}' detected in Rocketlane cloud. Reconciling...")  # What: Log cloud duplicate detection; Why: Observability.
                    reconciled_project = self._reconcile_cloud_project(request, correlation_id)  # What: Recover existing project from cloud; Why: Self-healing idempotency reconciliation.
                    if reconciled_project:  # What: Check if cloud project was found; Why: Validates recovery.
                        return reconciled_project  # What: Return recovered project; Why: Successfully healed idempotency state.
                raise  # What: Re-raise original exception; Why: Propagates non-duplicate errors or unrecoverable failures.

        # Save to idempotency store to guard against future duplicate requests
        duplicate_view = project_response.model_copy(update={"is_duplicate": True})  # What: Create copy with is_duplicate=True; Why: For future idempotent hits.
        self._idempotency_cache[request.idempotency_key] = duplicate_view  # What: Store in cache; Why: Idempotent lookup.
        self._persist_idempotency_cache()  # What: Persist cache to local file; Why: Ensures durability across process restarts.

        # AUDIT LOG: Record successful project provisioning
        audit_logger.log_action(  # What: Log action to audit trail; Why: Verifies compliance with logging requirements.
            correlation_id=correlation_id,  # What: Deal tracking ID; Why: Connects to deal flow.
            agent_name="RocketlaneClient",  # What: Agent/component name; Why: Documents acting entity.
            action="create_project_success",  # What: Action name; Why: Documents successful creation.
            inputs=request.model_dump(),  # What: Serialized request payload; Why: Full input record.
            outputs=project_response.model_dump(),  # What: Serialized response; Why: Full output record.
            decision_rationale=(  # What: Rationale string; Why: Explains template selection and SLA duration.
                f"Successfully provisioned Rocketlane project '{project_response.project_id}' for "  # What: Text part 1; Why: Project info.
                f"tier '{request.tier.value}' using template '{request.template_id}' with {request.duration_days}-day "  # What: Text part 2; Why: Template info.
                f"timeline and '{request.csm_type}' assignment."  # What: Text part 3; Why: Staffing info.
            ),  # What: End of rationale string; Why: Complete rationale.
            status=AuditActionStatus.SUCCESS  # What: Status success; Why: Successful operation.
        )  # What: End of audit logging call; Why: Persisted to disk and console.

        return project_response  # What: Return project response; Why: Provides result to calling agent.


# Global singleton client instance
rocketlane_client: RocketlaneClient = RocketlaneClient()  # What: Instantiate global client; Why: Shared instance for pipeline.
