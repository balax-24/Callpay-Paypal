{{- define "callpay.labels" -}}
app.kubernetes.io/part-of: callpay
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "callpay.image" -}}
{{ .root.Values.image.registry }}/callpay-{{ .name }}:{{ .root.Values.image.tag }}
{{- end -}}

{{- define "callpay.secretName" -}}
{{ default (printf "%s-secrets" .Release.Name) .Values.existingSecret }}
{{- end -}}

{{- define "callpay.env" -}}
- name: DATABASE_URL
  value: {{ tpl .Values.endpoints.databaseUrl . | quote }}
- name: KAFKA_BOOTSTRAP
  value: {{ tpl .Values.endpoints.kafka . | quote }}
- name: REDIS_URL
  value: {{ tpl .Values.endpoints.redis . | quote }}
- name: CLICKHOUSE_URL
  value: {{ tpl .Values.endpoints.clickhouse . | quote }}
- name: TEMPORAL_ADDRESS
  value: {{ tpl .Values.endpoints.temporal . | quote }}
- name: S3_URL
  value: {{ .Values.endpoints.s3 | quote }}
- name: API_INTERNAL_URL
  value: "http://{{ .Release.Name }}-api:8000"
- name: SQLITE_FALLBACK_URL
  value: "sqlite+aiosqlite:////tmp/callpay.db"
{{- range $k, $v := .Values.config }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}
