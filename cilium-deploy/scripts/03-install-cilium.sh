#!/bin/bash
# Run on gpu1. Installs Helm if missing, adds cilium repo, helm install.
set -e

VALUES_FILE="${1:-/tmp/cilium-values.yaml}"
CILIUM_VERSION="${CILIUM_VERSION:-1.16.5}"

if ! command -v helm >/dev/null 2>&1; then
  echo "[cilium] installing helm"
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

export KUBECONFIG=/home/ubuntu/.kube/config

echo "[cilium] add helm repo"
helm repo add cilium https://helm.cilium.io/ 2>&1 | tail -1
helm repo update 2>&1 | tail -2

echo "[cilium] helm install cilium ${CILIUM_VERSION}"
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version "${CILIUM_VERSION}" \
  --values "${VALUES_FILE}" \
  --wait --timeout 5m 2>&1 | tail -10

echo "[cilium] waiting for cilium DaemonSet to roll out"
kubectl -n kube-system rollout status ds/cilium --timeout=5m

echo "[cilium] cluster status"
kubectl get nodes -o wide
kubectl get pods -n kube-system
