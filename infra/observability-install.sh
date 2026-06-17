#!/usr/bin/env bash
# ABOUTME: Installs the observability stack (Prometheus, Grafana, Alertmanager, Tempo, OTel Collector)
# ABOUTME: into the monitoring namespace. Ephemeral storage; no --wait (avoids the rev3 hang).
set -euo pipefail

log() { printf '\n==> %s\n' "$*" >&2; }

log "helm repos"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null

log "kube-prometheus-stack (Prometheus + Grafana + Alertmanager), ephemeral, modest requests"
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  --set grafana.persistence.enabled=false \
  --set prometheus.prometheusSpec.retention=2h \
  --set prometheus.prometheusSpec.resources.requests.cpu=200m \
  --set prometheus.prometheusSpec.resources.requests.memory=512Mi \
  --set alertmanager.alertmanagerSpec.resources.requests.memory=64Mi \
  --set grafana.additionalDataSources[0].name=Tempo \
  --set grafana.additionalDataSources[0].type=tempo \
  --set grafana.additionalDataSources[0].url=http://tempo.monitoring:3100 \
  --set grafana.additionalDataSources[0].access=proxy

log "Tempo (traces backend), ephemeral"
helm upgrade --install tempo grafana/tempo -n monitoring \
  --set persistence.enabled=false

log "OpenTelemetry Collector (deployment): OTLP in -> Tempo, with a redaction processor"
helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
  -n monitoring --set mode=deployment --set image.repository=otel/opentelemetry-collector-contrib \
  -f - <<'VALUES'
config:
  receivers:
    otlp:
      protocols:
        grpc: { endpoint: 0.0.0.0:4317 }
        http: { endpoint: 0.0.0.0:4318 }
  processors:
    batch: {}
    # re-leak-trap mitigation: drop captured GenAI content if it is ever enabled upstream
    attributes/redact:
      actions:
        - { key: gen_ai.input.messages, action: delete }
        - { key: gen_ai.output.messages, action: delete }
        - { key: gen_ai.system_instructions, action: delete }
  exporters:
    otlp/tempo:
      endpoint: tempo.monitoring:4317
      tls: { insecure: true }
  service:
    pipelines:
      traces:
        receivers: [otlp]
        processors: [attributes/redact, batch]
        exporters: [otlp/tempo]
VALUES

log "observability install issued (no --wait); check: kubectl get pods -n monitoring"
