#!/usr/bin/env bash
set -Eeuo pipefail

backup_dir=/var/backups/oysyn-mobile
timestamp=$(date -u +%Y%m%dT%H%M%SZ)

umask 077
install -d -m 0770 -o root -g postgres "$backup_dir"

for database in oysyn_mobile_stage oysyn_mobile_prod; do
  output="$backup_dir/${database}_${timestamp}.dump"
  runuser -u postgres -- pg_dump --format=custom --no-owner --no-privileges \
    --file="$output" "$database"
done

find "$backup_dir" -type f -name 'oysyn_mobile_*.dump' -mtime +14 -delete
