#!/bin/bash
# Run ON gpu1 (control plane). kubeadm init with pod-cidr matching Cilium defaults.
set -e

CRI_SOCKET="unix:///run/spectro/containerd/containerd.sock"
ADVERTISE_ADDR="172.16.30.90"
POD_CIDR="10.244.0.0/16"
SVC_CIDR="10.96.0.0/12"

echo "[init] kubeadm init on $(hostname) advertise=${ADVERTISE_ADDR} pod=${POD_CIDR}"
sudo kubeadm init \
  --cri-socket="${CRI_SOCKET}" \
  --apiserver-advertise-address="${ADVERTISE_ADDR}" \
  --pod-network-cidr="${POD_CIDR}" \
  --service-cidr="${SVC_CIDR}" \
  --skip-phases=addon/kube-proxy \
  --upload-certs 2>&1 | tee /tmp/kubeadm-init.log

echo "[init] populate ubuntu kubeconfig"
mkdir -p /home/ubuntu/.kube
sudo cp /etc/kubernetes/admin.conf /home/ubuntu/.kube/config
sudo chown ubuntu:ubuntu /home/ubuntu/.kube/config
chmod 600 /home/ubuntu/.kube/config

echo "[init] also populate root kubeconfig"
sudo mkdir -p /root/.kube
sudo cp /etc/kubernetes/admin.conf /root/.kube/config

echo "[init] capture join command"
sudo kubeadm token create --print-join-command --ttl 24h \
  --description "gpu2 join" 2>&1 | tee /tmp/kubeadm-join.txt

echo "[init] done. control plane up. join command stored at /tmp/kubeadm-join.txt"
echo "       (Cilium will be installed via helm — kube-proxy was skipped on purpose)"
