# Mobile Backend DB Schema

## Правило поддержки схемы

При любом изменении SQLAlchemy-моделей, Alembic-миграций или структуры таблиц необходимо обновлять этот документ. Документ является актуальной картой mobile backend БД и должен соответствовать фактической схеме PostgreSQL.

## Назначение mobile backend БД

Mobile Backend DB хранит только мобильную инфраструктуру приложения Oysyn / AI Scan. Она не является копией основной БД Oysyn.

Источник истины по пользователям, организациям, ролям, правам и паролям - Oysyn Core API и основная production БД Oysyn.

Mobile Backend DB хранит:

- мобильные профили-связки с `core_user_id`;
- устройства;
- сессии и refresh-токены;
- push-токены;
- QR login;
- 2FA;
- уведомления;
- проверки документов, созданные или отслеживаемые из мобилки;
- делегирование доступа;
- админские действия;
- аудит;
- события безопасности;
- настройки мобильного пользователя;
- логи обращений к Core API;
- фоновые sync jobs.

## Core identifiers

Поля `core_user_id`, `core_organization_id`, `core_check_id`, `core_request_id` - это ссылки на сущности основной системы Oysyn. Они не являются foreign key внутри mobile DB.

Правила:

- mobile DB не создает таблицы `users`, `organizations`, `roles`, `permissions`;
- mobile DB не хранит пароли пользователей Core;
- `role_snapshot` в `mobile_users` - только кэш последнего известного состояния;
- актуальные пользовательские данные всегда проверяются через Oysyn Core API.

## Что хранится в PostgreSQL и Redis

PostgreSQL хранит долговременные записи: устройства, сессии, hash refresh-токенов, push-токены, факты QR/2FA challenge, уведомления, статусы проверок, аудит, события безопасности, настройки и интеграционные логи.

Redis хранит только краткоживущие и чувствительные runtime-значения:

- 2FA/SMS-коды;
- cooldown resend;
- counters попыток;
- временные raw QR tokens до hash/consume;
- rate limit keys;
- временные locks;
- transient cache ответов Core API, если нужен.

Сырые 2FA-коды, raw QR tokens и полные чувствительные тела запросов не должны храниться в PostgreSQL.

## Логические блоки миграций

### 001 core

Таблицы: `mobile_users`, `mobile_devices`, `mobile_sessions`, `push_tokens`, `notifications`, `notification_deliveries`, `audit_logs`.

### 002 security

Таблицы: `qr_login_sessions`, `qr_login_events`, `two_factor_challenges`, `two_factor_attempts`, `security_events`.

### 003 checks

Таблицы: `mobile_check_requests`, `mobile_check_files`, `mobile_check_results`, `mobile_check_status_events`.

### 004 admin

Таблицы: `access_delegation_requests`, `admin_action_requests`, `admin_action_events`.

### 005 settings and integrations

Таблицы: `mobile_user_settings`, `notification_preferences`, `app_versions`, `core_api_requests`, `sync_jobs`.

## Таблицы

### mobile_users

Локальная мобильная связка с пользователем из Oysyn Core.

Поля: `id`, `core_user_id`, `core_organization_id`, `phone`, `email`, `full_name`, `role_snapshot`, `status`, `last_synced_at`, `created_at`, `updated_at`.

Индексы: `core_user_id`, `core_organization_id`, `phone`, `email`, `status`, `created_at`.

Связи: one-to-many с устройствами, сессиями, push-токенами, уведомлениями, проверками, аудитом, настройками.

### mobile_devices

Устройства мобильного пользователя.

Поля: `id`, `mobile_user_id`, `device_id`, `platform`, `device_name`, `device_model`, `os_version`, `app_version`, `push_token`, `push_provider`, `is_active`, `last_seen_at`, `created_at`, `updated_at`, `revoked_at`.

Индексы: `mobile_user_id`, `device_id`, `platform`, `is_active`, `created_at`.

Ограничение: `device_id` уникален в рамках `mobile_user_id`.

### mobile_sessions

Активные и исторические мобильные сессии.

Поля: `id`, `mobile_user_id`, `device_id`, `access_token_jti`, `refresh_token_hash`, `ip_address`, `user_agent`, `status`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`, `revoked_by_user_id`, `revocation_reason`.

Статусы: `active`, `expired`, `revoked`, `blocked`.

Индексы: `mobile_user_id`, `device_id`, `status`, `refresh_token_hash`, `expires_at`, `created_at`.

### qr_login_sessions

QR-авторизация web-сессии через мобильное приложение.

Поля: `id`, `qr_token_hash`, `status`, `web_session_id`, `requested_ip`, `requested_user_agent`, `approved_by_mobile_user_id`, `approved_device_id`, `created_at`, `expires_at`, `approved_at`, `rejected_at`, `consumed_at`.

Статусы: `pending`, `approved`, `rejected`, `expired`, `consumed`.

Важно: raw `qr_token` не хранится, только hash.

### qr_login_events

Аудит QR-login.

Поля: `id`, `qr_login_session_id`, `event_type`, `mobile_user_id`, `device_id`, `ip_address`, `user_agent`, `metadata`, `created_at`.

Типы событий: `created`, `scanned`, `approved`, `rejected`, `expired`, `consumed`.

### two_factor_challenges

Запросы второго фактора для входа и чувствительных действий.

Поля: `id`, `mobile_user_id`, `challenge_type`, `delivery_channel`, `destination_masked`, `status`, `attempts_count`, `created_at`, `expires_at`, `verified_at`, `failed_at`, `metadata`.

Типы: `login`, `delegate_access`, `role_change`, `password_reset`, `sensitive_action`.

Каналы: `sms`, `push`, `email`, `mobile_app`.

Статусы: `pending`, `verified`, `failed`, `expired`, `cancelled`.

Важно: сам 2FA-код хранится в Redis, не в PostgreSQL.

### two_factor_attempts

История попыток ввода 2FA-кода.

Поля: `id`, `challenge_id`, `mobile_user_id`, `attempt_result`, `ip_address`, `device_id`, `created_at`.

Результаты: `success`, `wrong_code`, `expired`, `blocked`.

### push_tokens

Push-токены устройств для FCM/APNs.

Поля: `id`, `mobile_user_id`, `device_id`, `provider`, `token`, `platform`, `is_active`, `last_used_at`, `created_at`, `updated_at`, `revoked_at`.

Provider: `fcm`, `apns`.

Индексы: `mobile_user_id`, `device_id`, `token`, `is_active`, `created_at`.

### notifications

Уведомления внутри мобильного приложения.

Поля: `id`, `mobile_user_id`, `notification_type`, `title`, `body`, `payload`, `status`, `priority`, `created_at`, `sent_at`, `read_at`, `archived_at`.

Типы: `check_completed`, `check_failed`, `access_delegated`, `role_changed`, `password_reset_requested`, `qr_login_requested`, `two_factor_required`, `system_message`.

Статусы: `created`, `queued`, `sent`, `delivered`, `read`, `failed`, `archived`.

### notification_deliveries

Попытки доставки уведомлений.

Поля: `id`, `notification_id`, `mobile_user_id`, `device_id`, `channel`, `provider`, `provider_message_id`, `status`, `error_message`, `created_at`, `sent_at`, `delivered_at`, `failed_at`.

Каналы: `push`, `sms`, `email`, `in_app`.

### mobile_check_requests

Проверки документов, созданные или отслеживаемые из мобильного приложения.

Поля: `id`, `mobile_user_id`, `core_user_id`, `core_organization_id`, `core_check_id`, `source`, `status`, `title`, `document_name`, `document_type`, `created_from_device_id`, `created_at`, `submitted_at`, `completed_at`, `failed_at`, `error_message`.

Статусы: `draft`, `submitted`, `processing`, `completed`, `failed`, `cancelled`.

Важно: `core_check_id` - ID проверки в основной системе Oysyn.

### mobile_check_files

Метаданные файлов, загруженных через мобильное приложение.

Поля: `id`, `mobile_check_request_id`, `file_name`, `file_type`, `file_size`, `storage_provider`, `storage_key`, `file_url`, `checksum`, `upload_status`, `created_at`, `uploaded_at`, `deleted_at`.

Важно: файлы не хранятся в PostgreSQL; в БД лежат только `storage_key`, `file_url`, `checksum` и статус.

### mobile_check_results

Краткий результат проверки для мобильного приложения.

Поля: `id`, `mobile_check_request_id`, `core_check_id`, `status`, `originality_percent`, `ai_probability_percent`, `plagiarism_percent`, `report_url`, `summary`, `received_at`, `created_at`, `updated_at`.

### mobile_check_status_events

История изменения статусов проверки.

Поля: `id`, `mobile_check_request_id`, `old_status`, `new_status`, `event_source`, `message`, `metadata`, `created_at`.

### access_delegation_requests

Заявки на предоставление доступа пользователю через мобильное приложение.

Поля: `id`, `requested_by_mobile_user_id`, `target_core_user_id`, `target_phone`, `target_email`, `core_organization_id`, `requested_role`, `status`, `requires_2fa`, `two_factor_challenge_id`, `created_at`, `approved_at`, `rejected_at`, `completed_at`, `error_message`.

Статусы: `draft`, `pending_2fa`, `approved`, `rejected`, `completed`, `failed`, `cancelled`.

Важно: фактическое предоставление доступа выполняется через Oysyn Core API.

### admin_action_requests

Чувствительные админские действия из мобильного приложения.

Поля: `id`, `requested_by_mobile_user_id`, `target_core_user_id`, `core_organization_id`, `action_type`, `payload`, `status`, `requires_2fa`, `two_factor_challenge_id`, `core_request_id`, `created_at`, `approved_at`, `completed_at`, `failed_at`, `error_message`.

Типы действий: `grant_access`, `revoke_access`, `change_role`, `reset_password`, `force_logout`, `block_user`, `unblock_user`.

Статусы: `draft`, `pending_2fa`, `approved`, `sent_to_core`, `completed`, `failed`, `cancelled`.

`payload` хранится как JSONB.

### admin_action_events

Аудит жизненного цикла админского действия.

Поля: `id`, `admin_action_request_id`, `event_type`, `actor_mobile_user_id`, `message`, `metadata`, `created_at`.

Типы событий: `created`, `2fa_requested`, `2fa_verified`, `sent_to_core`, `completed`, `failed`, `cancelled`.

### audit_logs

Общий аудит действий в mobile backend.

Поля: `id`, `mobile_user_id`, `core_user_id`, `device_id`, `session_id`, `action`, `entity_type`, `entity_id`, `ip_address`, `user_agent`, `metadata`, `created_at`.

Примеры действий: `login_success`, `login_failed`, `logout`, `session_revoked`, `qr_login_approved`, `2fa_verified`, `push_token_updated`, `check_created`, `check_completed`, `role_change_requested`, `password_reset_requested`.

### security_events

События безопасности.

Поля: `id`, `mobile_user_id`, `event_type`, `severity`, `ip_address`, `device_id`, `message`, `metadata`, `created_at`, `resolved_at`.

Типы событий: `too_many_login_attempts`, `too_many_sms_requests`, `suspicious_device`, `session_hijack_suspected`, `blocked_2fa`, `unknown_device_login`.

Severity: `low`, `medium`, `high`, `critical`.

### mobile_user_settings

Настройки мобильного пользователя.

Поля: `id`, `mobile_user_id`, `language`, `timezone`, `push_enabled`, `sms_enabled`, `email_enabled`, `biometric_enabled`, `created_at`, `updated_at`.

### notification_preferences

Настройки уведомлений по типам.

Поля: `id`, `mobile_user_id`, `notification_type`, `push_enabled`, `sms_enabled`, `email_enabled`, `in_app_enabled`, `created_at`, `updated_at`.

### app_versions

Контроль версий мобильного приложения.

Поля: `id`, `platform`, `version`, `build_number`, `min_supported_version`, `force_update`, `release_notes`, `created_at`.

### core_api_requests

Логирование обращений mobile backend к Oysyn Core API.

Поля: `id`, `mobile_user_id`, `method`, `endpoint`, `status_code`, `request_id`, `duration_ms`, `error_message`, `created_at`.

Важно: не хранить чувствительные тела запросов полностью.

### sync_jobs

Фоновые синхронизации с Core API.

Поля: `id`, `job_type`, `status`, `started_at`, `finished_at`, `error_message`, `metadata`, `created_at`.

Типы: `sync_user_profile`, `sync_check_status`, `sync_organization`, `sync_roles`.

## Связи между таблицами

- `mobile_users.id` -> `mobile_devices.mobile_user_id`, `mobile_sessions.mobile_user_id`, `push_tokens.mobile_user_id`, `notifications.mobile_user_id`, `mobile_check_requests.mobile_user_id`, `audit_logs.mobile_user_id`, `security_events.mobile_user_id`, `mobile_user_settings.mobile_user_id`, `notification_preferences.mobile_user_id`.
- `mobile_devices.device_id` используется как стабильный внешний идентификатор устройства в сессиях, push-токенах, QR-login и аудитах.
- `notifications.id` -> `notification_deliveries.notification_id`.
- `qr_login_sessions.id` -> `qr_login_events.qr_login_session_id`.
- `two_factor_challenges.id` -> `two_factor_attempts.challenge_id`, `access_delegation_requests.two_factor_challenge_id`, `admin_action_requests.two_factor_challenge_id`.
- `mobile_check_requests.id` -> `mobile_check_files.mobile_check_request_id`, `mobile_check_results.mobile_check_request_id`, `mobile_check_status_events.mobile_check_request_id`.
- `admin_action_requests.id` -> `admin_action_events.admin_action_request_id`.

Core IDs связывают mobile DB с Oysyn Core логически, но не через PostgreSQL foreign key.
