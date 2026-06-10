import logging
import os
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile, status

load_dotenv()

logger = logging.getLogger("uvicorn.error")


class OysynCoreClient:
    def __init__(self) -> None:
        self.base_url = (
            os.getenv("OYSYN_CORE_API_URL")
            or os.getenv("OYSYN_INTERNAL_API_BASE_URL")
            or ""
        ).rstrip("/")
        self.secret = (
            os.getenv("OYSYN_CORE_SERVICE_TOKEN")
            or os.getenv("MOBILE_BACKEND_SECRET")
        )
        self.timeout = float(
            os.getenv("OYSYN_CORE_API_TIMEOUT")
            or os.getenv("OYSYN_INTERNAL_API_TIMEOUT", "30")
        )

    def _ensure_configured(self) -> None:
        if not self.base_url or not self.secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Oysyn Core API env variables are missing",
            )

    def _headers(self, user_id: Optional[int] = None) -> Dict[str, str]:
        self._ensure_configured()
        headers = {"Authorization": f"Bearer {self.secret}"}
        if user_id is not None:
            headers["X-Mobile-User-Id"] = str(user_id)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        user_id: Optional[int] = None,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"

        try:
            response = requests.request(
                method,
                url,
                headers=self._headers(user_id),
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Oysyn Core API unavailable: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=self._extract_error(response),
            )

        return response

    @staticmethod
    def _extract_error(response: requests.Response) -> Any:
        try:
            payload = response.json()
        except ValueError:
            return response.text or "Oysyn Core API error"

        if isinstance(payload, dict):
            return payload.get("error") or payload.get("detail") or payload
        return payload

    @staticmethod
    def _json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Oysyn Core API returned invalid JSON",
            ) from exc

    def login(self, email: str, password: str) -> Any:
        response = self._request(
            "POST",
            "/auth/login",
            json={"email": email, "password": password},
        )
        return self._json(response)

    def confirm_qr(self, user_id: int, token: str) -> Any:
        response = self._request(
            "POST",
            "/auth/qr-confirm",
            user_id=user_id,
            json={"token": token},
        )
        payload = self._json(response)
        masked_token = (
            f"{token[:8]}...{token[-6:]}" if len(token) > 16 else "<short-token>"
        )
        logger.info(
            "Oysyn Core QR confirm succeeded: user_id=%s token=%s response=%s",
            user_id,
            masked_token,
            payload,
        )
        return payload

    def verify(self, user_id: int) -> Any:
        response = self._request("GET", "/auth/verify", user_id=user_id)
        return self._json(response)

    def get_me(self, user_id: int) -> Any:
        response = self._request("GET", "/users/me", user_id=user_id)
        return self._json(response)

    def get_checks(self, user_id: int, params: Dict[str, Any]) -> Any:
        response = self._request("GET", "/checks", user_id=user_id, params=params)
        return self._json(response)

    def get_organization(self, user_id: int, organization_id: int) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}",
            user_id=user_id,
        )
        return self._json(response)

    async def create_check(
        self,
        user_id: int,
        *,
        document: UploadFile,
        form: Dict[str, Any],
    ) -> Any:
        document_bytes = await document.read()
        files = {
            "document": (
                document.filename,
                document_bytes,
                document.content_type or "application/octet-stream",
            )
        }
        response = self._request(
            "POST",
            "/checks",
            user_id=user_id,
            data=form,
            files=files,
        )
        return self._json(response)

    def get_check(self, user_id: int, check_id: int) -> Any:
        response = self._request("GET", f"/checks/{check_id}", user_id=user_id)
        return self._json(response)

    def get_report(self, user_id: int, check_id: int) -> Any:
        response = self._request(
            "GET",
            f"/checks/{check_id}/report",
            user_id=user_id,
        )
        return self._json(response)

    def get_report_pdf(
        self,
        user_id: int,
        check_id: int,
        report_type: str,
        params: Dict[str, Any],
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/checks/{check_id}/report/pdf/{report_type}/",
            user_id=user_id,
            params=params,
        )


oysyn_core_client = OysynCoreClient()
