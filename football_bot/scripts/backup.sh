#!/bin/sh
# Daily logical backup, 14-day local retention. Copy /backups off-host and encrypt (see docs/DISASTER_RECOVERY.md).
set -eu
while true; do
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  pg_dump -h postgres -U footballbot -Fc footballbot > "/backups/footballbot_${ts}.dump"
  find /backups -name 'footballbot_*.dump' -mtime +14 -delete
  sleep 86400
done
