#!/usr/bin/env python3
"""Verify the public Production route with an interactive test login."""

import getpass
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://api-mobile.oysyn.asia/api/v1"


def request(path: str, *, method: str = "GET", payload=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=35) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except (ValueError, UnicodeError):
            return exc.code, {}


def main() -> int:
    email = getpass.getpass("Production test email: ")
    password = getpass.getpass("Production test password: ")
    try:
        status, result = request(
            "/auth/login",
            method="POST",
            payload={"email": email, "password": password, "device_id": "public-production-smoke"},
        )
    except URLError as exc:
        print(f"login transport error: {type(exc.reason).__name__}")
        return 1
    finally:
        password = ""
    print(f"public login HTTP {status}")
    if status != 200:
        print(f"login detail: {str(result.get('detail', ''))[:200]}")
        return 1
    token = result.get("access_token")
    if not token:
        print("No mobile access token returned")
        return 1
    failed = False
    for path in ("/me", "/organizations", "/checks?page=1&page_size=1"):
        try:
            status, _ = request(path, token=token)
            print(f"public GET {path}: HTTP {status}")
            failed |= status != 200
        except URLError as exc:
            print(f"public GET {path}: {type(exc.reason).__name__}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
