#!/bin/bash
# Install Kamaji + DPF Operator on the mgmt cluster.
# Per https://docs.nvidia.com/networking/display/dpf25101/DPF-Zero-Trust
set -e

export KUBECONFIG=/home/ubuntu/.kube/config

# Kamaji (hosted control plane for DPU tenant cluster)
echo "[dpf] add Kamaji repo + install"
helm repo add --force-update clastix https://clastix.github.io/charts 2>&1 | tail -1
helm repo update 2>&1 | tail -1
helm upgrade --install kamaji clastix/kamaji \
  --namespace kamaji-system --create-namespace \
  --version 1.2.0 \
  --wait --timeout 5m 2>&1 | tail -5

# DPF Operator
echo
echo "[dpf] add DPF Operator repo"
helm repo add --force-update dpf-repository https://helm.ngc.nvidia.com/nvidia/doca 2>&1 | tail -1
helm repo update 2>&1 | tail -1

echo
echo "[dpf] helm install dpf-operator v25.10.1"
cat > /tmp/dpf-operator-values.yaml <<'EOF'
# We have no kube-state-metrics, prometheus or grafana installed.
# Disable optional integrations to keep the operator simple.
kubeStateMetricsCRDMetrics:
  enabled: false
grafanaDashboards:
  enabled: false
prometheusSecureMetrics:
  enabled: false
# NFD is installed, so let the operator create its NodeFeatureRules
enableNodeFeatureRules: true
# Single control plane (gpu1) — keep default affinity
EOF

helm upgrade --install dpf-operator dpf-repository/dpf-operator \
  --namespace dpf-operator-system --create-namespace \
  --version v25.10.1 \
  --values /tmp/dpf-operator-values.yaml \
  --wait --timeout 10m 2>&1 | tail -5

echo
echo "[dpf] verify operator + Kamaji pods"
kubectl -n kamaji-system get pods
kubectl -n dpf-operator-system get pods

echo
echo "[dpf] CRDs registered"
kubectl get crd 2>&1 | grep -iE "dpu|bfb|dpf|kamaji" | head -30
