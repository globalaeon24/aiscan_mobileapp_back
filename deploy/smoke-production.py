#!/usr/bin/env python3
"""Smoke test login and read-only endpoints on the Production mobile API."""

import argparse
import getpass
from pathlib import Path
import sys
import time

import requests


BASE_URL = "http://127.0.0.1:8102/api/v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", type=Path)
    parser.add_argument("--check-id", type=int)
    parser.add_argument("--polls", type=int, default=12)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()
    email = getpass.getpass("Production test email: ")
    password = getpass.getpass("Production test password: ")
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={
                "email": email,
                "password": password,
                "device_id": "production-smoke-test",
                "platform": "test",
            },
            timeout=35,
        )
    except requests.RequestException as exc:
        print(f"login transport error: {type(exc).__name__}")
        return 1
    finally:
        password = ""

    print(f"login HTTP {response.status_code}")
    if response.status_code != 200:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str):
            print(f"login detail: {detail[:200]}")
        return 1

    payload = response.json()
    token = payload.get("access_token")
    user = payload.get("user") or {}
    print(f"core user id present: {bool(user.get('id'))}")
    if not token:
        print("No mobile access token returned")
        return 1

    headers = {"Authorization": f"Bearer {token}"}
    failed = False
    me = None
    for path in ("/me", "/organizations", "/checks?page=1&page_size=1"):
        try:
            result = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=35)
            print(f"GET {path}: HTTP {result.status_code}")
            failed |= result.status_code != 200
            if path == "/me" and result.status_code == 200:
                me = result.json()
        except requests.RequestException as exc:
            print(f"GET {path}: {type(exc).__name__}")
            failed = True
    if failed or (args.upload is None and args.check_id is None):
        return 1 if failed else 0

    check_id = args.check_id
    if args.upload is not None:
        available = me.get("checks_available") if isinstance(me, dict) else None
        print(f"checks_available before upload: {available}")
        if not isinstance(available, int) or available <= 0:
            print("Upload skipped: no confirmed positive test quota")
            return 1

        with args.upload.open("rb") as document:
            result = requests.post(
                f"{BASE_URL}/checks",
                headers=headers,
                data={"title": "Oysyn production integration smoke test", "ai_check": "true"},
                files={"document": (args.upload.name, document, "text/plain")},
                timeout=45,
            )
        print(f"POST /checks: HTTP {result.status_code}")
        if result.status_code != 201:
            try:
                detail = result.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            if isinstance(detail, str):
                print(f"upload detail: {detail[:200]}")
            return 1

        created = result.json()
        check = created.get("check", created) if isinstance(created, dict) else {}
        check_id = check.get("id") if isinstance(check, dict) else None
        print(f"created check id: {check_id}")
        if not check_id:
            print(f"creation response keys: {sorted(created) if isinstance(created, dict) else type(created).__name__}")
            return 1

    for attempt in range(1, args.polls + 1):
        detail = requests.get(f"{BASE_URL}/checks/{check_id}", headers=headers, timeout=35)
        if detail.status_code != 200:
            print(f"GET /checks/{check_id}: HTTP {detail.status_code}")
            return 1
        payload = detail.json()
        current = payload.get("check", payload) if isinstance(payload, dict) else {}
        state = current.get("status") if isinstance(current, dict) else None
        finished = bool(current.get("finished_at")) if isinstance(current, dict) else False
        print(f"check poll {attempt}: status={state!r}, finished_at_set={finished}")
        if attempt == 1 and isinstance(current, dict):
            print(f"check fields: {sorted(current.keys())}")
        if finished or state in ("CH", "completed", "finished", "done", "success"):
            print(
                "result fields present: "
                f"originality={current.get('originality_percentage') is not None}, "
                f"ai={current.get('ai_percentage') is not None}"
            )
            report = requests.get(f"{BASE_URL}/checks/{check_id}/report", headers=headers, timeout=35)
            print(f"GET /checks/{check_id}/report: HTTP {report.status_code}")
            return 0 if report.status_code == 200 else 1
        if attempt < args.polls:
            time.sleep(args.interval)
    print("Check is still processing at the end of the polling window")
    return 1


if __name__ == "__main__":
    sys.exit(main())
