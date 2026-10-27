# Initial server setup

This is the only environment setup phase that requires a server administrator.
Do not replace the existing Production Nginx configuration during Stage setup.

## 1. Application and configuration directories

```bash
sudo install -d -o oysyn -g oysyn /opt/oysyn-mobile-backend-stage
sudo install -d -o oysyn -g oysyn /opt/oysyn-mobile-backend-production
sudo install -d -m 0750 -o root -g oysyn /etc/oysyn-mobile
```

## 2. Databases

Create independent users and databases. `--pwprompt` reads each password without
placing it in shell history.

```bash
sudo -u postgres createuser --pwprompt oysyn_mobile_stage
sudo -u postgres createdb --owner=oysyn_mobile_stage oysyn_mobile_stage

sudo -u postgres createuser --pwprompt oysyn_mobile_prod
sudo -u postgres createdb --owner=oysyn_mobile_prod oysyn_mobile_prod
```

The Stage and Production passwords must be different. Store them only in the
corresponding files under `/etc/oysyn-mobile`.

## 3. Systemd template

```bash
sudo install -m 0644 \
  deploy/systemd/oysyn-mobile-backend@.service \
  /etc/systemd/system/oysyn-mobile-backend@.service
sudo systemctl daemon-reload
```

## 4. Stage Nginx route

Install only the Stage site at first:

```bash
sudo install -m 0644 \
  deploy/nginx/api-mobile-stage.oysyn.asia.conf \
  /etc/nginx/sites-available/api-mobile-stage.oysyn.asia
sudo ln -s \
  /etc/nginx/sites-available/api-mobile-stage.oysyn.asia \
  /etc/nginx/sites-enabled/api-mobile-stage.oysyn.asia
sudo nginx -t
sudo systemctl reload nginx
```

The existing `api-mobile.oysyn.asia` site remains unchanged until the new
Production service passes its local and public health checks.

When running `deploy/bootstrap-stage.sh`, provide the Core Test connection
details explicitly. Never use the Core Production token for this command:

```bash
sudo \
  OYSYN_STAGE_CORE_API_URL='http://core-test-host/api/internal/v1' \
  OYSYN_STAGE_CORE_SERVICE_TOKEN='<core-test-service-token>' \
  deploy/bootstrap-stage.sh
```

## 5. Narrow operational permissions

After initial setup, deployment automation only needs permission to inspect and
restart the two Oysyn services and reload Nginx after a successful config test.
Do not grant unrestricted passwordless sudo to the `oysyn` account.
