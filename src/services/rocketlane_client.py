"""Resilient Rocketlane API client for NovaCRM customer onboarding.

Implements retry mechanics via Tenacity, four-level idempotency protection,
template resolution, and self-healing cloud reconciliation against Rocketlane's
REST API (v1.0).
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.core.audit_logger import audit_logger
from src.core.config import settings
from src.core.exceptions import RocketlaneAPIError
from src.models.schemas import (
    AuditActionStatus,
    PlanTier,
    RocketlaneProjectCreateRequest,
    RocketlaneProjectResponse,
)

_logger = logging.getLogger("rocketlane_client")


def _is_retryable_error(exception: BaseException) -> bool:
    """Determines whether an exception is an HTTP 5xx or transient network error.

    Args:
        exception: The exception raised during HTTP request execution.

    Returns:
        True if the exception warrants an automated retry, False otherwise.
    """
    if isinstance(exception, RocketlaneAPIError):
        return exception.status_code is not None and exception.status_code >= 500
    if isinstance(exception, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return False


class RocketlaneClient:
    """Client for Rocketlane API with built-in idempotency, template resolution, and retry policies.

    Encapsulates all REST communication with the Rocketlane Projects API, providing
    transparent retries on server errors, automated template and duration mapping
    by subscription tier, and multi-tier idempotency with cloud self-healing.
    """

    # Template and staffing configuration matrix mapping tiers to requirements
    TIER_CONFIG: dict[PlanTier, dict[str, Any]] = {
        PlanTier.ENTERPRISE: {
            "template_id": getattr(settings, "rocketlane_enterprise_template_id", "5000000095997"),
            "duration_days": 30,
            "csm_type": "Dedicated CSM",
            "default_csm": "Sarah Connor (Enterprise Lead)",
        },
        PlanTier.GROWTH: {
            "template_id": getattr(settings, "rocketlane_growth_template_id", "5000000096288"),
            "duration_days": 14,
            "csm_type": "Pooled CSM",
            "default_csm": "Pooled CSM Team",
        },
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        mock_mode: Optional[bool] = None,
        cache_file_path: Optional[Path] = None,
    ) -> None:
        """Initializes the Rocketlane API client and idempotency cache.

        Args:
            api_key: Optional API key override. Defaults to settings.rocketlane_api_key.
            base_url: Optional base URL override. Defaults to settings.rocketlane_base_url.
            mock_mode: Optional mock mode flag override. Defaults to settings.rocketlane_mock_mode.
            cache_file_path: Optional file path for the persistent idempotency cache.
                Defaults to 'logs/idempotency_cache.json'.
        """
        self.api_key: str = api_key or settings.rocketlane_api_key
        self.base_url: str = base_url or settings.rocketlane_base_url
        self.mock_mode: bool = mock_mode if mock_mode is not None else settings.rocketlane_mock_mode
        self.cache_file_path: Path = cache_file_path or Path("logs/idempotency_cache.json")
        self._idempotency_cache: dict[str, RocketlaneProjectResponse] = {}
        # 60s read timeout accommodates live template cloning which typically takes ~35s
        self._client: httpx.Client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))

        if not self.mock_mode or cache_file_path is not None:
            self._load_idempotency_cache()

    def _load_idempotency_cache(self) -> None:
        """Loads cached idempotency responses from local JSON file if present."""
        if not self.cache_file_path.exists():
            return
        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for key, val in data.items():
                    self._idempotency_cache[key] = RocketlaneProjectResponse.model_validate(val)
        except Exception as exc:
            _logger.warning(f"Could not load idempotency cache from {self.cache_file_path}: {exc}")

    def _persist_idempotency_cache(self) -> None:
        """Persists idempotency mappings to local JSON file for durability across process restarts."""
        # Prevent test runs from polluting production cache file
        if self.mock_mode and self.cache_file_path == Path("logs/idempotency_cache.json"):
            return
        try:
            if self.cache_file_path.parent:
                self.cache_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                serializable = {k: v.model_dump(mode="json") for k, v in self._idempotency_cache.items()}
                json.dump(serializable, f, indent=2)
        except Exception as exc:
            _logger.warning(f"Could not persist idempotency cache to {self.cache_file_path}: {exc}")

    def resolve_tier_payload(
        self,
        customer_name: str,
        customer_email: str,
        tier: PlanTier,
        idempotency_key: str,
    ) -> RocketlaneProjectCreateRequest:
        """Maps customer details and verified tier to the appropriate Rocketlane project parameters.

        Args:
            customer_name: Customer company name.
            customer_email: Primary customer contact email address.
            tier: Verified subscription plan tier (ENTERPRISE or GROWTH).
            idempotency_key: Unique deterministic SHA-256 deal hash.

        Returns:
            A validated RocketlaneProjectCreateRequest model ready for dispatch.

        Raises:
            ValueError: If the tier is UNKNOWN or not supported in TIER_CONFIG.
        """
        if tier not in self.TIER_CONFIG:
            raise ValueError(f"Cannot provision project for unverified or unsupported tier: {tier}")

        config = self.TIER_CONFIG[tier]
        project_name = f"{customer_name.strip()} - Onboarding ({tier.value})"

        return RocketlaneProjectCreateRequest(
            project_name=project_name,
            template_id=config["template_id"],
            tier=tier,
            duration_days=config["duration_days"],
            csm_type=config["csm_type"],
            csm_assigned=config["default_csm"],
            customer_email=customer_email,
            idempotency_key=idempotency_key,
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
        retry=retry_if_exception(_is_retryable_error),
    )
    def _execute_http_post(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Executes an HTTP POST request against Rocketlane API with retries on HTTP 500.

        Args:
            endpoint: API endpoint path (e.g. '/projects').
            payload: JSON request body dictionary.

        Returns:
            Parsed JSON response dictionary from Rocketlane.

        Raises:
            RocketlaneAPIError: On HTTP 4xx, HTTP 5xx, or network connection failure.
        """
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._client.post(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            _logger.warning(f"Rocketlane connection error on {url}: {exc}")
            raise RocketlaneAPIError(f"Network error connecting to Rocketlane: {exc}") from exc

        if response.status_code >= 500:
            _logger.warning(f"Rocketlane API returned HTTP {response.status_code}. Retrying...")
            raise RocketlaneAPIError(
                message=f"Rocketlane server error HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details={"response_body": response.text},
            )

        if response.status_code >= 400:
            raise RocketlaneAPIError(
                message=f"Rocketlane client error HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details={"response_body": response.text},
            )

        return response.json()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
        retry=retry_if_exception(_is_retryable_error),
    )
    def _execute_http_get(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Executes an HTTP GET request against Rocketlane API with retries on HTTP 500.

        Args:
            endpoint: API endpoint path (e.g. '/projects').
            params: Optional query parameters dictionary.

        Returns:
            Parsed JSON response dictionary from Rocketlane.

        Raises:
            RocketlaneAPIError: On HTTP 4xx, HTTP 5xx, or network connection failure.
        """
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "api-key": self.api_key,
            "Accept": "application/json",
        }

        try:
            response = self._client.get(url, params=params, headers=headers)
        except httpx.RequestError as exc:
            _logger.warning(f"Rocketlane connection error on {url}: {exc}")
            raise RocketlaneAPIError(f"Network error connecting to Rocketlane: {exc}") from exc

        if response.status_code >= 500:
            _logger.warning(f"Rocketlane API returned HTTP {response.status_code}. Retrying...")
            raise RocketlaneAPIError(
                message=f"Rocketlane server error HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details={"response_body": response.text},
            )

        if response.status_code >= 400:
            raise RocketlaneAPIError(
                message=f"Rocketlane client error HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details={"response_body": response.text},
            )

        return response.json()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
        retry=retry_if_exception(_is_retryable_error),
    )
    def _execute_http_put(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Executes an authenticated HTTP PUT request against the Rocketlane API with retries.

        Args:
            endpoint: API path (e.g. '/tasks/123').
            payload: Request body to be serialized as JSON.

        Returns:
            Parsed JSON response dictionary from Rocketlane.

        Raises:
            RocketlaneAPIError: On HTTP 4xx, HTTP 5xx, or network connection failure.
        """
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self._client.put(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            _logger.warning(f"Rocketlane connection error on {url}: {exc}")
            raise RocketlaneAPIError(f"Network error connecting to Rocketlane: {exc}") from exc

        if response.status_code >= 500:
            _logger.warning(f"Rocketlane API returned HTTP {response.status_code}. Retrying...")
            raise RocketlaneAPIError(
                message=f"Rocketlane server error HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details={"response_body": response.text},
            )

        if response.status_code >= 400:
            raise RocketlaneAPIError(
                message=f"Rocketlane client error HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details={"response_body": response.text},
            )

        return response.json() if response.text else {}

    def get_task(self, task_id: int | str) -> Optional[dict[str, Any]]:
        """Fetches task details by task ID from Rocketlane."""
        if self.mock_mode:
            return {
                "taskId": int(task_id) if str(task_id).isdigit() else 1,
                "taskName": "Data migration and data onboarding",
                "status": {"value": 1, "label": "To do"},
            }
        try:
            return self._execute_http_get(f"/tasks/{task_id}")
        except Exception as exc:
            _logger.warning(f"Failed to fetch task {task_id}: {exc}")
            return None

    def update_task_status(self, task_id: int | str, status_value: int) -> bool:
        """Updates task status in Rocketlane (1=To do, 2=In progress, 3=Completed)."""
        if self.mock_mode:
            return True
        try:
            self._execute_http_put(f"/tasks/{task_id}", {"status": {"value": status_value}})
            return True
        except Exception as exc:
            _logger.warning(f"Failed to update task {task_id} status to {status_value}: {exc}")
            return False

    def post_task_comment(self, task_id: int | str, content: str) -> bool:
        """Posts an audit comment directly to the task conversation stream in Rocketlane."""
        if self.mock_mode:
            return True
        try:
            tid = int(task_id) if str(task_id).isdigit() else task_id
            payload = {
                "content": content,
                "source": {
                    "sourceType": "TASK",
                    "sourceId": tid,
                },
            }
            self._execute_http_post("/comments", payload)
            return True
        except Exception as exc:
            _logger.warning(f"Failed to post comment to task {task_id}: {exc}")
            return False

    def _reconcile_cloud_project(
        self,
        request: RocketlaneProjectCreateRequest,
        correlation_id: str,
    ) -> Optional[RocketlaneProjectResponse]:
        """Queries Rocketlane for an existing project with the given externalReferenceId and updates local cache.

        Args:
            request: The project creation request model containing the idempotency key.
            correlation_id: Deal correlation ID for audit logging.

        Returns:
            The recovered RocketlaneProjectResponse if found, or None if reconciliation failed.
        """
        try:
            query_res = self._execute_http_get(
                "/projects",
                params={"externalReferenceId.EQUALS": request.idempotency_key},
            )
            data = query_res.get("data", [])
            if data and isinstance(data, list):
                matched = data[0]
                proj_id = str(matched.get("projectId") or matched.get("id"))
                proj_name = str(matched.get("projectName") or request.project_name)
                portal_url_val = f"https://app.rocketlane.com/projects/{proj_id}"

                reconciled = RocketlaneProjectResponse(
                    project_id=proj_id,
                    project_name=proj_name,
                    tier=request.tier,
                    template_id=request.template_id,
                    portal_url=portal_url_val,
                    created_at=datetime.now(timezone.utc),
                    is_duplicate=True,
                )
                self._idempotency_cache[request.idempotency_key] = reconciled
                self._persist_idempotency_cache()

                audit_logger.log_action(
                    correlation_id=correlation_id,
                    agent_name="RocketlaneClient",
                    action="create_project_idempotent_cloud_reconciliation",
                    inputs=request.model_dump(),
                    outputs=reconciled.model_dump(),
                    decision_rationale=(
                        f"Cloud externalReferenceId collision detected for key '{request.idempotency_key}'. "
                        f"Successfully reconciled existing Rocketlane project ID '{proj_id}' and updated local cache."
                    ),
                    status=AuditActionStatus.SUCCESS,
                )
                return reconciled
        except Exception as exc:
            _logger.warning(f"Failed to reconcile cloud project for key '{request.idempotency_key}': {exc}")
        return None

    def create_project(
        self,
        request: RocketlaneProjectCreateRequest,
        correlation_id: str,
    ) -> RocketlaneProjectResponse:
        """Creates an onboarding project in Rocketlane with strict idempotency and audit logging.

        Args:
            request: Validated project creation request model.
            correlation_id: Unique correlation identifier linking this action to the deal trail.

        Returns:
            The created or reconciled RocketlaneProjectResponse model.

        Raises:
            RocketlaneAPIError: If the remote API call fails and cannot be reconciled.
        """
        # IDEMPOTENCY GUARDRAIL: Check if project already exists in local cache for this deal key
        if request.idempotency_key in self._idempotency_cache:
            cached_project = self._idempotency_cache[request.idempotency_key]
            audit_logger.log_action(
                correlation_id=correlation_id,
                agent_name="RocketlaneClient",
                action="create_project_idempotent_hit",
                inputs=request.model_dump(),
                outputs=cached_project.model_dump(),
                decision_rationale=(
                    f"Idempotency hit for key '{request.idempotency_key}'. Returning existing "
                    f"Rocketlane project ID '{cached_project.project_id}' without creating duplicate."
                ),
                status=AuditActionStatus.SUCCESS,
            )
            return cached_project

        # Handle Mock Mode for local testing and offline execution
        if self.mock_mode:
            mock_id = f"proj_mock_{abs(hash(request.idempotency_key)) % 100000:05d}"
            mock_portal = f"https://app.rocketlane.com/projects/{mock_id}"
            project_response = RocketlaneProjectResponse(
                project_id=mock_id,
                project_name=request.project_name,
                tier=request.tier,
                template_id=request.template_id,
                portal_url=mock_portal,
                created_at=datetime.now(timezone.utc),
                is_duplicate=False,
            )
        else:
            current_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            customer_company_name = (
                request.project_name.split(" - ")[0]
                if " - " in request.project_name
                else request.project_name
            )
            api_payload: dict[str, Any] = {
                "projectName": request.project_name,
                "customer": {"companyName": customer_company_name},
                "autoCreateCompany": True,
                "owner": {"emailId": settings.rocketlane_owner_email},
                "externalReferenceId": request.idempotency_key,
                "startDate": current_date_str,
            }

            if request.template_id.isdigit():
                api_payload["sources"] = [{
                    "templateId": int(request.template_id),
                    "startDate": current_date_str,
                }]

            try:
                raw_response = self._execute_http_post("/projects", api_payload)
                project_id_val = str(
                    raw_response.get("projectId")
                    or raw_response.get("id")
                    or int(datetime.now().timestamp())
                )
                portal_url_val = f"https://app.rocketlane.com/projects/{project_id_val}"

                project_response = RocketlaneProjectResponse(
                    project_id=project_id_val,
                    project_name=request.project_name,
                    tier=request.tier,
                    template_id=request.template_id,
                    portal_url=portal_url_val,
                    created_at=datetime.now(timezone.utc),
                    is_duplicate=False,
                )
            except RocketlaneAPIError as exc:
                if exc.status_code == 400 and "Invalid External Reference Key specified" in str(exc.message):
                    _logger.info(
                        f"Duplicate externalReferenceId '{request.idempotency_key}' detected in "
                        f"Rocketlane cloud. Reconciling..."
                    )
                    reconciled_project = self._reconcile_cloud_project(request, correlation_id)
                    if reconciled_project:
                        return reconciled_project
                raise

        # Save to idempotency store to guard against future duplicate requests
        duplicate_view = project_response.model_copy(update={"is_duplicate": True})
        self._idempotency_cache[request.idempotency_key] = duplicate_view
        self._persist_idempotency_cache()

        # AUDIT LOG: Record successful project provisioning
        audit_logger.log_action(
            correlation_id=correlation_id,
            agent_name="RocketlaneClient",
            action="create_project_success",
            inputs=request.model_dump(),
            outputs=project_response.model_dump(),
            decision_rationale=(
                f"Successfully provisioned Rocketlane project '{project_response.project_id}' for "
                f"tier '{request.tier.value}' using template '{request.template_id}' with {request.duration_days}-day "
                f"timeline and '{request.csm_type}' assignment."
            ),
            status=AuditActionStatus.SUCCESS,
        )

        return project_response


# Global singleton client instance
rocketlane_client: RocketlaneClient = RocketlaneClient()
