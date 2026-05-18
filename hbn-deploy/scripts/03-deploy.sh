#!/bin/bash
# Deploy HBN container as kubelet static pod.
# Pre-reqs: snapshot taken (01), SFs created and br-hbn wired (02).
# Destructive: stops host FRR, drops VPC-OVN.
set -euo pipefail

HBN_HOST_ROLE="${HBN_HOST_ROLE:?must be 'gpu1' or 'gpu2'}"   # set by caller
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "[deploy] role=${HBN_HOST_ROLE}"

# 1. Stage startup.yaml on host (HBN container watches /tmp/config-data
#    which is host-mounted from /var/lib/hbn/config-data)
sudo mkdir -p /var/lib/hbn/config-data
sudo cp "${REPO_ROOT}/${HBN_HOST_ROLE}/startup.yaml" /var/lib/hbn/config-data/startup.yaml
echo "[deploy] startup.yaml staged"

# 2. Tear down conflicting underlay actors
#    a. Stop host-side FRR (kernel BGP) so it doesn't conflict with HBN's BGP
sudo systemctl stop frr 2>/dev/null || true
sudo systemctl disable frr 2>/dev/null || true
echo "[deploy] host FRR stopped"

#    b. Strip current /31 + VLAN497 IPs from kernel internal ports so HBN
#       can claim them on the SF representors
sudo ip addr flush dev p1_l3 2>/dev/null || true
sudo ip addr flush dev ovnvtep 2>/dev/null || true
echo "[deploy] kernel-side underlay IPs flushed"

# 3. (Skipped here: ripping out VPC-OVN br-int / br-ovn-ext is intentionally
#    NOT automated. That step is in 04-vpc-ovn-teardown.sh and requires
#    confirmation. HBN will work alongside VPC-OVN if pod traffic is moved
#    off pf0hpf via pf0hpf_if access port — but until that migration is
#    done, do NOT run 04.)

# 4. Drop static pod manifest
sudo cp "${REPO_ROOT}/manifests/doca_hbn.yaml" /etc/kubelet.d/doca_hbn.yaml
echo "[deploy] static pod manifest installed at /etc/kubelet.d/doca_hbn.yaml"

# 5. Wait for kubelet to pick it up
echo "[deploy] waiting for HBN container..."
for i in $(seq 1 60); do
  if sudo crictl ps 2>/dev/null | grep -q doca-hbn; then
    echo "[deploy] HBN container is running"
    sudo crictl ps | grep doca-hbn
    break
  fi
  sleep 2
done

# 6. Tail supervisor log briefly to confirm
sleep 5
echo "[deploy] checking supervisord status inside container..."
CID=$(sudo crictl ps -q --name doca-hbn 2>/dev/null | head -1 || echo "")
if [[ -n "${CID}" ]]; then
  sudo crictl exec "${CID}" supervisorctl status 2>&1 | head -20 || true
else
  echo "[deploy] ERROR: no doca-hbn container found"
  exit 1
fi
