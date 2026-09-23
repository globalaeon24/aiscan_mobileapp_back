#!/usr/bin/env python3
"""Create isolated Stage database credentials without starting the service."""

import grp
import os
from pathlib import Path
import secrets
import subprocess


DB_NAME = "oysyn_mobile_stage"
ROLE_NAME = "oysyn_mobile_stage"
ENV_PATH = Path("/etc/oysyn-mobile/stage.env")


def psql(sql: str) -> str:
    result = subprocess.run(
        ["runuser", "-u", "postgres", "--", "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run as root.")
    if ENV_PATH.exists():
        raise SystemExit(f"Refusing to overwrite {ENV_PATH}.")
    if psql(f"SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}';"):
        raise SystemExit(f"Role {ROLE_NAME} already exists; inspect it before retrying.")
    if psql(f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}';"):
        raise SystemExit(f"Database {DB_NAME} already exists; inspect it before retrying.")

    db_password = secrets.token_hex(32)
    jwt_secret = secrets.token_hex(48)
    app_secret = secrets.token_hex(48)
    psql(f"CREATE ROLE {ROLE_NAME} LOGIN PASSWORD '{db_password}';")
    psql(f"CREATE DATABASE {DB_NAME} OWNER {ROLE_NAME};")

    values = {
        "ENVIRONMENT": "stage",
        "PORT": "8101",
        "DATABASE_URL": f"postgresql://{ROLE_NAME}:{db_password}@127.0.0.1:5432/{DB_NAME}",
        "REDIS_URL": "redis://127.0.0.1:6379/1",
        "JWT_SECRET_KEY": jwt_secret,
        "SECRET_KEY": app_secret,
        "JWT_ALGORITHM": "HS256",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
        "REFRESH_TOKEN_EXPIRE_DAYS": "30",
        "OYSYN_CORE_API_URL": "",
        "OYSYN_CORE_SERVICE_TOKEN": "",
        "OYSYN_CORE_API_TIMEOUT": "30",
        "CORS_ALLOWED_ORIGINS": "",
    }
    ENV_PATH.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    content = "".join(f"{key}={value}\n" for key, value in values.items())
    fd = os.open(ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        os.fchown(fd, 0, grp.getgrnam("oysyn").gr_gid)
        with os.fdopen(fd, "w", encoding="ascii") as env_file:
            env_file.write(content)
    except BaseException:
        ENV_PATH.unlink(missing_ok=True)
        raise
    print("Stage database and private env created. Core settings are not set; do not start the service yet.")


if __name__ == "__main__":
    main()
