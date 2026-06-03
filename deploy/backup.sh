#!/usr/bin/env bash
# Daily backup: pg_dump + uploads tarball. Keep last 7 days.
# Schedule: 0 4 * * * /opt/rag/deploy/backup.sh >> /opt/rag/backups/cron.log 2>&1

set -euo pipefail

BACKUP_DIR=/opt/rag/backups
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

echo "[$(date)] backup start $DATE"

# PG dump
docker exec rag_pg pg_dump -U raguser -d ragdb \
  | gzip > "$BACKUP_DIR/pg_$DATE.sql.gz"
echo "  pg dump done: $(du -h "$BACKUP_DIR/pg_$DATE.sql.gz" | cut -f1)"

# uploads tarball (named docker volume → mount via temp container)
docker run --rm -v rag_uploads:/u alpine \
  tar czf - -C /u . > "$BACKUP_DIR/uploads_$DATE.tar.gz"
echo "  uploads done: $(du -h "$BACKUP_DIR/uploads_$DATE.tar.gz" | cut -f1)"

# Retention: keep 7 days
find "$BACKUP_DIR" -name "pg_*.sql.gz" -mtime +7 -delete
find "$BACKUP_DIR" -name "uploads_*.tar.gz" -mtime +7 -delete

echo "[$(date)] backup done"
