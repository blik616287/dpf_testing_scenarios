#!/bin/bash
# Snapshot current working state before HBN takeover.
# Captures: FRR config, OVS topology, IP/route state, running pods,
# IPs/MACs on every interface. Saved to /var/lib/hbn/pre-takeover/<timestamp>/.
set -euo pipefail

TS=$(date -u +%Y%m%dT%H%M%SZ)
DEST="/var/lib/hbn/pre-takeover/${TS}"
sudo mkdir -p "${DEST}"

echo "[snapshot] writing to ${DEST}"

sudo vtysh -c "show running-config"          | sudo tee "${DEST}/frr-running.conf"  >/dev/null
sudo vtysh -c "show ip bgp summary"          | sudo tee "${DEST}/bgp-summary.txt"   >/dev/null
sudo vtysh -c "show ip route"                | sudo tee "${DEST}/ip-route.txt"      >/dev/null
sudo ovs-vsctl show                          | sudo tee "${DEST}/ovs-show.txt"      >/dev/null
sudo ovs-ofctl dump-flows br-sfc             | sudo tee "${DEST}/of-br-sfc.txt"     >/dev/null || true
sudo ovs-ofctl dump-flows br-p1              | sudo tee "${DEST}/of-br-p1.txt"      >/dev/null || true
sudo ovs-ofctl dump-flows br-int             | sudo tee "${DEST}/of-br-int.txt"     >/dev/null || true
ip -j addr                                   | sudo tee "${DEST}/ip-addr.json"      >/dev/null
ip -j route                                  | sudo tee "${DEST}/ip-route.json"     >/dev/null
ip -j link                                   | sudo tee "${DEST}/ip-link.json"      >/dev/null
sudo crictl ps -a                            | sudo tee "${DEST}/crictl-ps.txt"     >/dev/null
sudo ovs-vsctl list Open_vSwitch             | sudo tee "${DEST}/ovs-config.txt"    >/dev/null

# Symlink "latest" for easy reference
sudo ln -sfn "${TS}" /var/lib/hbn/pre-takeover/latest

echo "[snapshot] done. latest -> ${TS}"
ls -la "${DEST}"
