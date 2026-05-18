#!/bin/bash
# Verify HBN post-deploy: BGP/EVPN sessions, ECMP routes, nl2docad offload.
set -euo pipefail

CID=$(sudo crictl ps -q --name doca-hbn 2>/dev/null | head -1)
if [[ -z "${CID}" ]]; then
  echo "[verify] FAIL: no doca-hbn container running"
  exit 1
fi

echo "=== supervisord status ==="
sudo crictl exec "${CID}" supervisorctl status

echo
echo "=== HBN FRR BGP summary ==="
sudo crictl exec "${CID}" vtysh -c "show ip bgp summary"

echo
echo "=== HBN FRR L2VPN-EVPN summary ==="
sudo crictl exec "${CID}" vtysh -c "show bgp l2vpn evpn summary"

echo
echo "=== ECMP routes (default VRF) ==="
sudo crictl exec "${CID}" vtysh -c "show ip route"

echo
echo "=== EVPN VNIs ==="
sudo crictl exec "${CID}" vtysh -c "show evpn vni"

echo
echo "=== nl2docad software tables (ASIC offload state) ==="
sudo crictl exec "${CID}" ls /cumulus/nl2docad/run/software-tables/
sudo crictl exec "${CID}" wc -l /cumulus/nl2docad/run/software-tables/17_l2_table     2>/dev/null || true
sudo crictl exec "${CID}" wc -l /cumulus/nl2docad/run/software-tables/18_l3_table     2>/dev/null || true
sudo crictl exec "${CID}" wc -l /cumulus/nl2docad/run/software-tables/19_ecmp_table   2>/dev/null || true

echo
echo "=== nl2doca supervisor status ==="
sudo crictl exec "${CID}" supervisorctl status nl2doca
