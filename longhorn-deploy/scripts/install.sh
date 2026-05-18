#!/bin/bash
# Run on gpu1 (control plane). Installs Longhorn via Helm.
set -e

VALUES_FILE="${1:-/tmp/longhorn-values.yaml}"
LONGHORN_VERSION="${LONGHORN_VERSION:-1.7.2}"

export KUBECONFIG=/home/ubuntu/.kube/config

echo "[longhorn] add helm repo"
helm repo add longhorn https://charts.longhorn.io 2>&1 | tail -1
helm repo update 2>&1 | tail -1

echo "[longhorn] create namespace"
kubectl create ns longhorn-system 2>/dev/null || true

echo "[longhorn] helm install ${LONGHORN_VERSION}"
helm upgrade --install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --version "${LONGHORN_VERSION}" \
  --values "${VALUES_FILE}" \
  --wait --timeout 10m 2>&1 | tail -8

echo
echo "[longhorn] post-install state"
kubectl -n longhorn-system get pods -o wide
echo
kubectl get sc
