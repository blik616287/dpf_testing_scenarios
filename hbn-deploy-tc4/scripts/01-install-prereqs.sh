#!/bin/bash
# Run on gpu1 (control plane). Installs all DPF Operator prerequisite charts.
# Per https://docs.nvidia.com/networking/display/dpf25100/helm-prerequisites
set -e

export KUBECONFIG=/home/ubuntu/.kube/config

echo "[prereqs] add helm repos"
helm repo add jetstack          https://charts.jetstack.io                  2>&1 | tail -1
helm repo add nfd               https://kubernetes-sigs.github.io/node-feature-discovery/charts 2>&1 | tail -1
helm repo add argo              https://argoproj.github.io/argo-helm        2>&1 | tail -1
helm repo add nvidia            https://helm.ngc.nvidia.com/nvidia          2>&1 | tail -1
helm repo update 2>&1 | tail -3

# 1.1 cert-manager
echo
echo "[prereqs] cert-manager v1.18.1"
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --version v1.18.1 \
  --set installCRDs=true \
  --wait --timeout 5m 2>&1 | tail -3

# 1.2 node-feature-discovery
echo
echo "[prereqs] node-feature-discovery v0.17.1"
helm upgrade --install nfd nfd/node-feature-discovery \
  --namespace node-feature-discovery --create-namespace \
  --version 0.17.1 \
  --wait --timeout 5m 2>&1 | tail -3

# 1.3 argo-cd
echo
echo "[prereqs] argo-cd v7.8.2"
helm upgrade --install argo-cd argo/argo-cd \
  --namespace argocd --create-namespace \
  --version 7.8.2 \
  --set server.service.type=ClusterIP \
  --set configs.params."server\.insecure"=true \
  --wait --timeout 5m 2>&1 | tail -3

# 1.4 maintenance-operator (NVIDIA NGC)
echo
echo "[prereqs] maintenance-operator v0.2.0"
helm upgrade --install maintenance-operator oci://nvcr.io/nvidia/cloud-native/charts/maintenance-operator-chart \
  --namespace maintenance-operator --create-namespace \
  --version 0.2.0 \
  --wait --timeout 5m 2>&1 | tail -3 || echo "  (maintenance-operator may need NGC auth; will retry alternative path)"

# 1.5 local-path-provisioner
echo
echo "[prereqs] local-path-provisioner"
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.27/deploy/local-path-storage.yaml 2>&1 | tail -5
kubectl -n local-path-storage rollout status deployment/local-path-provisioner --timeout=180s 2>&1 | tail -2

echo
echo "[prereqs] status"
kubectl get pods -A 2>&1 | grep -E "cert-manager|nfd|argo|maintenance|local-path" | head -15
echo
echo "[prereqs] storage classes"
kubectl get sc
