# Mobile Backend Production cutover

This runbook is for the server `192.168.75.103`. Stage uses port `8101` and
Production uses port `8102`. Never use Stage Core credentials in Prod.

## Current state (2026-09-16)

- Administrative access was verified through a temporary shared root session.
  The server's `/etc/hosts` now maps `oysyn.asia` to `192.168.75.100` (backup:
  `/etc/hosts.bak-codex-20260916`); an unauthenticated Core request returned
  `401` over verified HTTPS. Production code and a Python venv are installed in
  `/opt/oysyn-mobile-backend-production`. The separate `oysyn_mobile_prod` DB
  and `/etc/oysyn-mobile/production.env` were created, the Production Core
  token was installed without exposing its value, and migrations completed
  through `007_linked_ua_fields`. `oysyn-mobile-backend@production.service` is
  enabled and active on `127.0.0.1:8102`, including after a restart.
- The test account logged in through the internal and public Production routes.
  `/me`, `/organizations`, and `/checks` returned `200` on both. Synthetic text
  check `141899` was accepted (`201`), moved from `PR` to `CH`, returned both
  result percentages, and its report returned `200`. The detail response omits
  `finished_at`; the app uses `CH` as the completed state.
- The public `https://api-mobile.oysyn.asia` route now targets port `8102`; its
  health response is `environment=production`. Stage public health remains
  `environment=stage`. The old port `8000` service and DB remain for rollback.
  Backups are in `/root/oysyn-mobile-backups/`. The temporary shared root tmux
  session `codex-prod-setup` was closed after verification.
- Stage: `/opt/oysyn-mobile-backend-stage`, DB `oysyn_mobile_stage`, port
  `8101`, Core Test. The process is running, but the `@stage` systemd unit is
  inactive; do not start that unit while the manual process owns port `8101`.
- Legacy rollback deployment: `/opt/oysyn-mobile-backend`, DB
  `aiscan_mobile_db`, port `8000`. Its Core URL still points to Core Test.
  That DB currently contains 3 technical users and 44 mobile sessions. Do not
  copy these sessions into the new Production DB: they belong to the old
  Core-Test-backed deployment. Users will need to sign in again after cutover.
- `oysyn.asia` resolves to internal Nginx `192.168.75.100` on this server via
  `/etc/hosts`, while `OYSYN_CORE_API_URL` retains the HTTPS hostname for
  certificate and SNI validation. Replace the hosts entry with split DNS when
  that is available.

## Prerequisites

An administrator must provide:

1. Passwordless or interactive sudo access for the deployment session.
2. A Production Core service token, stored only in
   `/etc/oysyn-mobile/production.env` (root-owned, group `oysyn`, mode `0640`).
3. A Production test account for a read/write smoke test. Never use a Stage
   account or upload a real customer's document for this check.

Do not put tokens, JWT secrets, or database passwords in Git or shell history.

## Prepare in parallel

1. Confirm `getent ahostsv4 oysyn.asia` still resolves to the internal Nginx IP from
   this server and that an unauthenticated request to
   `https://oysyn.asia/api/internal/v1/auth/verify` returns `401` rather than
   timing out. A `401` confirms only routing, not service-token validity.
2. Already done. `deploy/prepare-production.py` created PostgreSQL
   role/database `oysyn_mobile_prod` and a private env with unique secrets.
   Never re-run it against an existing Production env.
   Keep `aiscan_mobile_db` intact for rollback.
3. Create `/opt/oysyn-mobile-backend-production` from a pinned, reviewed Git
   commit. Make it owned by `oysyn:oysyn` and create its own Python venv.
4. Fill `/etc/oysyn-mobile/production.env` from `.env.production.example`:
   `ENVIRONMENT=production`, `PORT=8102`, prod DB and Redis DB `2`, a unique JWT
   secret, `OYSYN_CORE_API_URL=https://oysyn.asia/api/internal/v1`, and the
   distinct Production Core service token. Compare values with `stage.env`
   without printing secrets.
5. Back up the new DB before any later migrations, install requirements, and
   run `alembic upgrade head` with only the Production env loaded.
6. Enable/start `oysyn-mobile-backend@production.service`. Verify
   `http://127.0.0.1:8102/health` returns `environment=production`.

For future deployments, do not change Nginx before the private smoke test.

## Smoke test before switching

Using the Production test account and the local port `8102`:

1. Log in via `/api/v1/auth/login` and confirm the returned user belongs to
   Core Production, not Core Test.
2. Verify `/api/v1/me`, organizations, balance, and an existing document list.
3. Upload a small, non-sensitive test document; wait for completion and verify
   its report. This is the only check that proves the complete Mobile → Core
   upload/results path.
4. Verify `@production` remains active after a restart and that Stage
   `https://api-mobile-stage.oysyn.asia/health` still responds.

If any check fails, fix Production while leaving the public route unchanged.

## Switch only the Production route

1. Back up `aiscan_mobile_db` and
   `/etc/nginx/sites-available/api-mobile.oysyn.asia` to timestamped,
   administrator-only files. Keep the old service and DB available.
2. Change only the existing Production site's `proxy_pass` target from
   `127.0.0.1:8000` to `127.0.0.1:8102`, retaining its other proxy settings.
   `deploy/nginx/api-mobile-production.conf.example` records the deployed
   configuration. The Stage site remains on `127.0.0.1:8101`.
3. Run `nginx -t`; reload Nginx only if the test succeeds.
4. Confirm the public `https://api-mobile.oysyn.asia/health` returns
   `environment=production`, repeat login and one read-only Core request
   through the public URL, and re-check public Stage health.
5. If any public check fails, restore the saved Production site, run
   `nginx -t`, and reload. Do not alter the Stage site.

After a stable observation period, retire port `8000` in a separate change.
App Store / Play production builds must explicitly use `APP_ENV=production`;
ordinary Flutter builds default to Stage.
