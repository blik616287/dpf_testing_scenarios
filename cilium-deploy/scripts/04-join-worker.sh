#!/bin/bash
# Run on gpu2. Expects /tmp/kubeadm-join.txt to be present (copy from gpu1).
set -e

CRI_SOCKET="unix:///run/spectro/containerd/containerd.sock"

if [[ ! -f /tmp/kubeadm-join.txt ]]; then
  echo "[join] ERROR: /tmp/kubeadm-join.txt missing. Copy from gpu1 first."
  exit 1
fi

JOIN_CMD=$(grep -E '^kubeadm join' /tmp/kubeadm-join.txt | head -1)
if [[ -z "${JOIN_CMD}" ]]; then
  echo "[join] ERROR: could not parse join command from /tmp/kubeadm-join.txt"
  cat /tmp/kubeadm-join.txt
  exit 1
fi

echo "[join] executing: ${JOIN_CMD} --cri-socket=${CRI_SOCKET}"
sudo ${JOIN_CMD} --cri-socket="${CRI_SOCKET}"

echo "[join] done. check 'kubectl get nodes' on gpu1"
