# AI Scan / Oysyn Mobile Backend

FastAPI backend для мобильного приложения ScanAI / Oysyn.

## Текущий статус

Публичный API подключен в `main.py` как `/api/v1/*` и реализован в `routes/mobile_v1.py`.

Backend:

- логинит пользователя через Oysyn Core Internal API;
- выпускает mobile JWT access token;
- создаёт `mobile_sessions` и хранит SHA-256 hash refresh token; refresh/logout/revoke flow ещё не реализован;
- поддерживает QR-login flow: подтверждает Oysyn Core QR token через `/auth/qr-confirm` и сохраняет local QR sessions/events для собственного fallback-flow;
- проксирует profile, organizations, checks и reports в Oysyn Core;
- получает и отзывает подключённые веб-сессии пользователя через Oysyn Core, кэшируя нормализованные snapshots в `linked_device_sessions`;
- хранит local mobile DB schema через SQLAlchemy/Alembic; QR-login пишет sessions/events в mobile DB.

## Основные файлы

| Путь | Назначение |
| --- | --- |
| `main.py` | FastAPI app, CORS, `/health`, `/api/docs`, router |
| `routes/mobile_v1.py` | Public mobile API |
| `services/oysyn_core_client.py` | Service-to-service client в Oysyn Core |
| `database.py` | SQLAlchemy engine/session |
| `mobile_models.py` | Mobile infrastructure models |
| `alembic/versions/*.py` | Migrations 001-007 |
| `docs/mobile_backend_db_schema.md` | DB schema documentation |
| `.env.example` | Env template |

## Локальный запуск

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn main:app --host 127.0.0.1 --port 8000
```

Healthcheck:

```bash
curl http://127.0.0.1:8000/health
```

Swagger:

```text
http://127.0.0.1:8000/api/docs
```

## Env

Минимально нужны:

```env
DATABASE_URL=postgresql://aiscan_mobile_user:<REAL_PASSWORD>@127.0.0.1:5432/aiscan_mobile_db
JWT_SECRET_KEY=<jwt-secret-min-32-chars>
OYSYN_CORE_API_URL=<oysyn-core-internal-api-url>
OYSYN_CORE_SERVICE_TOKEN=<oysyn-core-service-token>
```

Поддерживаются legacy aliases:

```env
SECRET_KEY=<jwt-secret-min-32-chars>
OYSYN_INTERNAL_API_BASE_URL=<oysyn-core-internal-api-url>
MOBILE_BACKEND_SECRET=<oysyn-core-service-token>
```

## Документация

Frontend repo содержит общий handoff и API docs:

- `../ai_scan_text/docs/CODEX_HANDOFF.md`
- `../ai_scan_text/docs/TECHNICAL_DOCUMENTATION.md`
- `../ai_scan_text/docs/API_DOCUMENTATION.md`
- `../ai_scan_text/docs/OYSYN_MOBILE_BACKEND_CONFIG_REFERENCE.md`

Backend DB schema:

- `docs/mobile_backend_db_schema.md`

Environment separation and deployment templates:

- `docs/environments.md`
- `.env.stage.example`
- `.env.production.example`
- `deploy/systemd/oysyn-mobile-backend@.service`
- `deploy/nginx/api-mobile-stage.oysyn.asia.conf`
- `deploy/nginx/api-mobile-production.conf.example`
- `deploy/INITIAL_SERVER_SETUP.md`
