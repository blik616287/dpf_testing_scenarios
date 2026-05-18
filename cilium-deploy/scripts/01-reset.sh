#!/bin/bash
# Run ON the target node. Resets kubeadm + wipes k8s/CNI state.
# Idempotent. Designed for spectro-containerd (socket at /run/spectro/containerd/containerd.sock).
set +e

CRI_SOCKET="unix:///run/spectro/containerd/containerd.sock"

echo "[reset] $(hostname) — kubeadm reset (with 60s timeout; falls back to manual wipe)"
sudo timeout 60 kubeadm reset --force --cri-socket="${CRI_SOCKET}" --skip-phases=cleanup-node 2>&1 | head -20 || \
  echo "[reset]   kubeadm reset timed out/failed — proceeding with manual wipe"

echo "[reset] stop kubelet + remove static pod manifests"
sudo systemctl stop kubelet 2>/dev/null
sudo rm -f /etc/kubernetes/manifests/*.yaml

echo "[reset] stop any control-plane containers via crictl"
sudo crictl --runtime-endpoint unix:///run/spectro/containerd/containerd.sock ps -q 2>/dev/null | \
  xargs -r sudo crictl --runtime-endpoint unix:///run/spectro/containerd/containerd.sock stop --timeout 5 2>/dev/null
sudo crictl --runtime-endpoint unix:///run/spectro/containerd/containerd.sock pods -q 2>/dev/null | \
  xargs -r sudo crictl --runtime-endpoint unix:///run/spectro/containerd/containerd.sock rmp -f 2>/dev/null

echo "[reset] wipe kubernetes config + etcd"
sudo rm -rf /etc/kubernetes /var/lib/etcd /var/lib/kubelet/* /var/lib/dockershim

echo "[reset] wipe CNI state"
sudo rm -rf /etc/cni/net.d/* /var/lib/cni/* /var/run/calico /var/run/multus /var/lib/cilium /var/run/cilium

echo "[reset] iptables flush + nft flush"
sudo iptables -F      2>/dev/null
sudo iptables -t nat -F   2>/dev/null
sudo iptables -t mangle -F 2>/dev/null
sudo iptables -X      2>/dev/null
sudo iptables -t nat -X   2>/dev/null
sudo iptables -t mangle -X 2>/dev/null
sudo nft flush ruleset 2>/dev/null
sudo ipvsadm -C       2>/dev/null

echo "[reset] remove cilium/cni interfaces if lingering"
for ifc in cilium_host cilium_net cilium_vxlan lxc_health flannel.1 cni0 docker0; do
  sudo ip link delete "${ifc}" 2>/dev/null && echo "  deleted ${ifc}"
done

echo "[reset] kubelet down (will be brought back up by kubeadm init/join)"
sudo systemctl stop kubelet

echo "[reset] done on $(hostname)"
