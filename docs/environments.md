# Oysyn Mobile environments

The mobile backend runs as two isolated services on the same host.

| Environment | Public API | Local port | Core API | Database | Redis DB |
| --- | --- | --- | --- | --- | --- |
| Stage | `api-mobile-stage.oysyn.asia` | `8101` | Core Test | `oysyn_mobile_stage` | `1` |
| Production | `api-mobile.oysyn.asia` | `8102` | Core Production | `oysyn_mobile_prod` | `2` |

## Server layout

```text
/opt/oysyn-mobile-backend-stage
/opt/oysyn-mobile-backend-production
/etc/oysyn-mobile/stage.env
/etc/oysyn-mobile/production.env
```

Both environments use the same application code but have independent service
processes, secrets, databases, Redis namespaces, logs, and Core API credentials.

## Safety rules

- Stage credentials must never authorize requests to Core Production.
- Production credentials must never be copied to a developer workstation.
- Stage and Production must use different database users and databases.
- Environment files must be readable only by the service administrator and the
  `oysyn` service account.
- Production deployment requires a database backup and a verified health check.
- Nginx must not be switched to a new Production process until its local health
  endpoint returns success.

## Service commands

```bash
sudo systemctl status oysyn-mobile-backend@stage
sudo systemctl status oysyn-mobile-backend@production
sudo systemctl restart oysyn-mobile-backend@stage
sudo systemctl restart oysyn-mobile-backend@production
```

## Deployment order

1. Deploy and migrate Stage.
2. Verify Stage against Core Test.
3. Back up the Production database.
4. Deploy and migrate Production.
5. Verify `http://127.0.0.1:8102/health`.
6. Reload Nginx only after `nginx -t` succeeds.
7. Verify the public Production health endpoint.
