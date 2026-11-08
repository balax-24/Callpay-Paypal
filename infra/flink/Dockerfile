FROM flink:1.20
# Kafka SQL connector so Flink SQL jobs can read/write the CallPay event stream
ADD --chmod=644 https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.3.0-1.20/flink-sql-connector-kafka-3.3.0-1.20.jar /opt/flink/lib/
COPY analytics.sql /jobs/analytics.sql
COPY submit.sh /jobs/submit.sh
