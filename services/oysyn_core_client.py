import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

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
        parsed_url = urlparse(self.base_url)
        environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        if environment == "production" and parsed_url.scheme != "https":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Oysyn Core API must use HTTPS in production",
            )
        jwt_secret = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
        if jwt_secret and self.secret == jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT and Core API secrets must be different",
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
            logger.warning(
                "Oysyn Core request failed: method=%s path=%s error=%s",
                method,
                path,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Oysyn Core API is temporarily unavailable",
            ) from exc

        if response.status_code >= 400:
            detail = (
                self._extract_error(response)
                if response.status_code < 500
                else "Oysyn Core API is temporarily unavailable"
            )
            raise HTTPException(
                status_code=response.status_code,
                detail=detail,
            )

        return response

    @staticmethod
    def _extract_error(response: requests.Response) -> Any:
        try:
            payload = response.json()
        except ValueError:
            return "Oysyn Core API rejected the request"

        if isinstance(payload, dict):
            value = (
                payload.get("error")
                or payload.get("detail")
                or payload.get("message")
            )
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
        return "Oysyn Core API rejected the request"

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

    def register(self, email: str, password: str) -> tuple[int, Any]:
        self._ensure_configured()
        normalized_email = email.strip().lower()
        technical_username = (
            "mobile_"
            + hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()[:32]
        )
        try:
            response = requests.post(
                f"{self.base_url}/auth/register",
                headers=self._headers(),
                json={
                    "email": normalized_email,
                    "username": technical_username,
                    "password1": password,
                    "password2": password,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Oysyn Core API unavailable: {exc}",
            ) from exc

        try:
            payload: Any = response.json()
        except ValueError:
            payload = {
                "code": "registration_unavailable",
                "message": "Сервис регистрации временно недоступен.",
            }
        return response.status_code, payload

    def confirm_qr(self, user_id: int, token: str) -> Any:
        response = self._request(
            "POST",
            "/auth/qr-confirm",
            user_id=user_id,
            json={"token": token},
        )
        payload = self._json(response)
        logger.info(
            "Oysyn Core QR confirm succeeded: user_id=%s",
            user_id,
        )
        return payload

    def verify(self, user_id: int) -> Any:
        response = self._request("GET", "/auth/verify", user_id=user_id)
        return self._json(response)

    def get_me(self, user_id: int) -> Any:
        response = self._request("GET", "/users/me", user_id=user_id)
        return self._json(response)

    def update_me(self, user_id: int, payload: Dict[str, Any]) -> Any:
        response = self._request(
            "PATCH", "/users/me", user_id=user_id, json=payload
        )
        return self._json(response)

    def get_me_statistics(self, user_id: int) -> Any:
        response = self._request(
            "GET", "/users/me/statistics", user_id=user_id
        )
        return self._json(response)

    def get_user_sessions(self, user_id: int) -> Any:
        response = self._request("GET", "/sessions/devices", user_id=user_id)
        return self._json(response)

    def revoke_user_session(self, user_id: int, session_id: int) -> Any:
        response = self._request(
            "POST",
            f"/sessions/devices/{session_id}/revoke",
            user_id=user_id,
        )
        return self._json(response)

    def get_checks(self, user_id: int, params: Dict[str, Any]) -> Any:
        response = self._request("GET", "/checks", user_id=user_id, params=params)
        return self._json(response)

    def get_check_modules(self, user_id: int) -> Any:
        response = self._request("GET", "/checks/modules", user_id=user_id)
        return self._json(response)

    def get_folders(self, user_id: int) -> Any:
        response = self._request("GET", "/folders", user_id=user_id)
        return self._json(response)

    def create_folder(self, user_id: int, payload: Dict[str, Any]) -> Any:
        response = self._request(
            "POST",
            "/folders",
            user_id=user_id,
            json=payload,
        )
        return self._json(response)

    def rename_folder(
        self,
        user_id: int,
        folder_id: int,
        payload: Dict[str, Any],
    ) -> Any:
        response = self._request(
            "PATCH",
            f"/folders/{folder_id}",
            user_id=user_id,
            json=payload,
        )
        return self._json(response)

    def get_organization(self, user_id: int, organization_id: int) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}",
            user_id=user_id,
        )
        return self._json(response)

    def update_organization(
        self, user_id: int, organization_id: int, payload: Dict[str, Any]
    ) -> Any:
        response = self._request(
            "PATCH",
            f"/organizations/{organization_id}",
            user_id=user_id,
            json=payload,
        )
        return self._json(response)

    def get_organizations(self, user_id: int) -> Any:
        response = self._request("GET", "/organizations", user_id=user_id)
        return self._json(response)

    def get_organization_users(self, user_id: int, organization_id: int) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}/users/",
            user_id=user_id,
        )
        return self._json(response)

    def create_organization_user(
        self, user_id: int, organization_id: int, payload: Dict[str, Any]
    ) -> Any:
        response = self._request(
            "POST",
            f"/organizations/{organization_id}/users/",
            user_id=user_id,
            json=payload,
        )
        return self._json(response)

    def update_organization_user(
        self,
        user_id: int,
        organization_id: int,
        target_user_id: int,
        payload: Dict[str, Any],
    ) -> Any:
        response = self._request(
            "PATCH",
            f"/organizations/{organization_id}/users/{target_user_id}/",
            user_id=user_id,
            json=payload,
        )
        return self._json(response)

    def get_organization_api_settings(
        self, user_id: int, organization_id: int
    ) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}/api_settings/",
            user_id=user_id,
        )
        return self._json(response)

    def create_organization_api_setting(
        self, user_id: int, organization_id: int, payload: Dict[str, Any]
    ) -> Any:
        response = self._request(
            "POST",
            f"/organizations/{organization_id}/api_settings/",
            user_id=user_id,
            json=payload,
        )
        return self._json(response)

    def get_organization_thresholds(
        self, user_id: int, organization_id: int
    ) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}/thresholds/",
            user_id=user_id,
        )
        return self._json(response)

    def update_organization_thresholds(
        self, user_id: int, organization_id: int, payload: Dict[str, Any]
    ) -> Any:
        response = self._request(
            "PATCH",
            f"/organizations/{organization_id}/thresholds/",
            user_id=user_id,
            json=payload,
        )
        return self._json(response)

    def get_organization_billing(self, user_id: int, organization_id: int) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}/billing/",
            user_id=user_id,
        )
        return self._json(response)

    def update_organization_billing(
        self,
        user_id: int,
        organization_id: int,
        target_user_id: int,
        payload: Dict[str, Any],
    ) -> Any:
        response = self._request(
            "PATCH",
            f"/organizations/{organization_id}/billing/{target_user_id}/",
            user_id=user_id,
            json=payload,
        )
        return self._json(response)

    def get_organization_billing_journal(
        self, user_id: int, organization_id: int
    ) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}/billing-journal/",
            user_id=user_id,
        )
        return self._json(response)

    def get_organization_reports(self, user_id: int, organization_id: int) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}/reports/",
            user_id=user_id,
        )
        return self._json(response)

    def get_organization_deleted_checks(
        self,
        user_id: int,
        organization_id: int,
        params: Dict[str, Any],
    ) -> Any:
        response = self._request(
            "GET",
            f"/organizations/{organization_id}/checks/deleted/",
            user_id=user_id,
            params=params,
        )
        return self._json(response)

    def restore_organization_check(
        self,
        user_id: int,
        organization_id: int,
        check_id: int,
    ) -> Any:
        response = self._request(
            "POST",
            f"/organizations/{organization_id}/checks/{check_id}/restore/",
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
        filename, document_bytes, content_type = await self._read_upload(document)
        files = {
            "document": (
                filename,
                document_bytes,
                content_type,
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

    def get_pair_checks(self, user_id: int, params: Dict[str, Any]) -> Any:
        response = self._request(
            "GET",
            "/checks/pair_check/",
            user_id=user_id,
            params=params,
        )
        return self._json(response)

    async def create_pair_check(
        self,
        user_id: int,
        *,
        first_document: UploadFile,
        second_document: UploadFile,
        form: Dict[str, Any],
    ) -> Any:
        first_name, first_bytes, first_type = await self._read_upload(first_document)
        second_name, second_bytes, second_type = await self._read_upload(second_document)
        files = {
            "a_document": (
                first_name,
                first_bytes,
                first_type,
            ),
            "b_document": (
                second_name,
                second_bytes,
                second_type,
            ),
        }
        response = self._request(
            "POST",
            "/checks/pair_check/",
            user_id=user_id,
            data=form,
            files=files,
        )
        return self._json(response)

    def get_pair_report_pdf(
        self,
        user_id: int,
        pair_check_id: int,
        report_type: str,
        params: Dict[str, Any],
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/checks/pair_check/{pair_check_id}/report/pdf/{report_type}/",
            user_id=user_id,
            params=params,
        )

    @staticmethod
    async def _read_upload(document: UploadFile) -> tuple[str, bytes, str]:
        max_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
        filename = Path(document.filename or "").name
        extension = Path(filename).suffix.lower()
        allowed_extensions = {
            ".pdf",
            ".doc",
            ".docx",
            ".txt",
            ".rtf",
            ".pptx",
            ".odt",
        }
        if not filename or extension not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported document format",
            )

        chunks = bytearray()
        while True:
            chunk = await document.read(64 * 1024)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Document exceeds the upload size limit",
                )
        if not chunks:
            raise HTTPException(status_code=422, detail="Document is empty")

        header = bytes(chunks[:16])
        is_valid = {
            ".pdf": header.startswith(b"%PDF-"),
            ".doc": header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")),
            ".docx": header.startswith(b"PK"),
            ".pptx": header.startswith(b"PK"),
            ".odt": header.startswith(b"PK"),
            ".rtf": header.lstrip().startswith(b"{\\rtf"),
            ".txt": b"\x00" not in bytes(chunks[:4096]),
        }[extension]
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Document content does not match its extension",
            )

        content_types = {
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".odt": "application/vnd.oasis.opendocument.text",
            ".rtf": "application/rtf",
            ".txt": "text/plain",
        }
        return filename, bytes(chunks), content_types[extension]

    def get_check(self, user_id: int, check_id: int) -> Any:
        response = self._request("GET", f"/checks/{check_id}", user_id=user_id)
        return self._json(response)

    def update_check_folder(
        self, user_id: int, check_id: int, folder_id: Optional[int]
    ) -> Any:
        response = self._request(
            "PATCH",
            f"/checks/{check_id}",
            user_id=user_id,
            json={"folder_id": folder_id},
        )
        return self._json(response)

    def delete_check(self, user_id: int, check_id: int) -> None:
        self._request("DELETE", f"/checks/{check_id}", user_id=user_id)

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
