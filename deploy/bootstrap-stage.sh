#!/usr/bin/env bash
set -Eeuo pipefail

CURRENT_APP=/opt/oysyn-mobile-backend
STAGE_APP=/opt/oysyn-mobile-backend-stage
STAGE_ENV=/etc/oysyn-mobile/stage.env
UNIT_SOURCE=/home/oysyn/deployment-prep/oysyn-mobile-environments/deploy/systemd/oysyn-mobile-backend@.service
NGINX_SOURCE=/home/oysyn/deployment-prep/oysyn-mobile-environments/deploy/nginx/api-mobile-stage.oysyn.asia.conf

if [[ $EUID -ne 0 ]]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

for required in "$CURRENT_APP" "$UNIT_SOURCE" "$NGINX_SOURCE"; do
    if [[ ! -e "$required" ]]; then
        echo "Required path is missing: $required" >&2
        exit 1
    fi
done

: "${OYSYN_STAGE_CORE_API_URL:?Set OYSYN_STAGE_CORE_API_URL to the Core Test API URL.}"
: "${OYSYN_STAGE_CORE_SERVICE_TOKEN:?Set OYSYN_STAGE_CORE_SERVICE_TOKEN to the Core Test service token.}"

install -d -o oysyn -g oysyn "$STAGE_APP"
install -d -m 0750 -o root -g oysyn /etc/oysyn-mobile

rsync -a --delete \
    --exclude='.env' \
    --exclude='venv/' \
    "$CURRENT_APP/" "$STAGE_APP/"
chown -R oysyn:oysyn "$STAGE_APP"

if [[ ! -x "$STAGE_APP/venv/bin/python" ]]; then
    sudo -u oysyn python3 -m venv "$STAGE_APP/venv"
fi
sudo -u oysyn "$STAGE_APP/venv/bin/pip" install --disable-pip-version-check -r "$STAGE_APP/requirements.txt"

if [[ -f "$STAGE_ENV" ]]; then
    DB_PASSWORD=$(sed -nE 's#^DATABASE_URL=postgresql://oysyn_mobile_stage:([^@]+)@.*#\1#p' "$STAGE_ENV")
fi
DB_PASSWORD=${DB_PASSWORD:-$(openssl rand -hex 24)}
JWT_SECRET=$(openssl rand -hex 48)
APP_SECRET=$(openssl rand -hex 48)

sudo -u postgres psql --set=ON_ERROR_STOP=1 <<SQL
SELECT 'CREATE ROLE oysyn_mobile_stage LOGIN PASSWORD ''$DB_PASSWORD'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'oysyn_mobile_stage')\gexec
ALTER ROLE oysyn_mobile_stage PASSWORD '$DB_PASSWORD';
SELECT 'CREATE DATABASE oysyn_mobile_stage OWNER oysyn_mobile_stage'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'oysyn_mobile_stage')\gexec
ALTER DATABASE oysyn_mobile_stage OWNER TO oysyn_mobile_stage;
SQL

cat >"$STAGE_ENV" <<EOF
ENVIRONMENT=stage
PORT=8101
DATABASE_URL=postgresql://oysyn_mobile_stage:${DB_PASSWORD}@127.0.0.1:5432/oysyn_mobile_stage
REDIS_URL=redis://127.0.0.1:6379/1
JWT_SECRET_KEY=${JWT_SECRET}
SECRET_KEY=${APP_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30
OYSYN_CORE_API_URL=${OYSYN_STAGE_CORE_API_URL}
OYSYN_CORE_SERVICE_TOKEN=${OYSYN_STAGE_CORE_SERVICE_TOKEN}
OYSYN_CORE_API_TIMEOUT=30
CORS_ALLOWED_ORIGINS=
EOF
chown root:oysyn "$STAGE_ENV"
chmod 0640 "$STAGE_ENV"

install -m 0644 "$UNIT_SOURCE" /etc/systemd/system/oysyn-mobile-backend@.service
systemctl daemon-reload

sudo -u oysyn -H bash -c "set -a; source '$STAGE_ENV'; set +a; cd '$STAGE_APP'; '$STAGE_APP/venv/bin/alembic' upgrade head"

install -m 0644 "$NGINX_SOURCE" /etc/nginx/sites-available/api-mobile-stage.oysyn.asia
ln -sfn /etc/nginx/sites-available/api-mobile-stage.oysyn.asia /etc/nginx/sites-enabled/api-mobile-stage.oysyn.asia
nginx -t

systemctl enable --now oysyn-mobile-backend@stage.service
systemctl reload nginx

curl --fail --silent --show-error http://127.0.0.1:8101/health >/dev/null
curl --fail --silent --show-error -H 'Host: api-mobile-stage.oysyn.asia' http://127.0.0.1/health >/dev/null

echo "Stage mobile backend is active on 127.0.0.1:8101."
