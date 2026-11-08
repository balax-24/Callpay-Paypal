#!/bin/sh
# Submit the analytics job once the JobManager is up; skip if it is already running.
JM=http://flink-jobmanager:8081
until curl -sf $JM/overview >/dev/null; do echo "waiting for flink"; sleep 3; done
if curl -s $JM/jobs/overview | grep -q '"name":"callpay-analytics"[^}]*"state":"RUNNING"'; then
  echo "callpay-analytics already running"; exit 0
fi
# Point the SQL client at the cluster (the image entrypoint only applies FLINK_PROPERTIES to jm/tm)
mkdir -p /tmp/conf && cp -r /opt/flink/conf/. /tmp/conf/
CONF=/tmp/conf/config.yaml; [ -f "$CONF" ] || CONF=/tmp/conf/flink-conf.yaml
sed -i 's/address: localhost/address: flink-jobmanager/' "$CONF"
sed -i '/^rest:/,/^[a-z]/ s/^  address: .*/  address: flink-jobmanager/' "$CONF"
export FLINK_CONF_DIR=/tmp/conf
exec /opt/flink/bin/sql-client.sh -f /jobs/analytics.sql
