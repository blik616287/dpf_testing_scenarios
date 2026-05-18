#!/bin/bash
# Create SF (sub-function) representors on PF0/PF1 to back HBN's
# p0_if / p1_if / pf0hpf_if interfaces, then add them to br-hbn.
#
# We use devlink to create SFs on each PF, then activate them.
# The kernel netdev name (en3f0pf0sfN) is what we'll rename to p0_if etc.
#
# Idempotent: skips creation if SF already exists; safe to re-run.
set -euo pipefail

# SF numbers — choose unused slots (existing range 0..18 already in use)
SF_P0=30
SF_P1=31
SF_PF0HPF=32

# Helper: create + activate an SF on a given PF
create_sf () {
  local PF_PCI="$1" SF_NUM="$2" RENAME_TO="$3"
  echo "[sf] creating sfnum=${SF_NUM} on ${PF_PCI} -> ${RENAME_TO}"

  # Skip if SF already exists
  if sudo devlink port show | grep -q "pci/${PF_PCI}.*sfnum ${SF_NUM}\b"; then
    echo "[sf]   already exists; skipping creation"
  else
    sudo devlink port add "pci/${PF_PCI}" flavour pcisf pfnum 0 sfnum "${SF_NUM}"
    SF_PORT=$(sudo devlink port show | awk -v p="${PF_PCI}" -v n="${SF_NUM}" \
      '$0 ~ p && $0 ~ "sfnum "n {print $1}' | head -1 | sed 's/://')
    sudo devlink port function set "${SF_PORT}" state active
  fi

  # Find netdev name and rename
  CUR_NAME=$(sudo devlink port show -j | python3 -c "
import json,sys;d=json.load(sys.stdin)
for k,v in d['port'].items():
  if v.get('flavour')=='pcisf' and str(v.get('pfnum'))=='0' and str(v.get('sfnum'))=='${SF_NUM}':
    print(v.get('netdev','')); break
")
  if [[ -n "${CUR_NAME}" && "${CUR_NAME}" != "${RENAME_TO}" ]]; then
    sudo ip link set dev "${CUR_NAME}" down
    sudo ip link set dev "${CUR_NAME}" name "${RENAME_TO}"
    sudo ip link set dev "${RENAME_TO}" up mtu 9216
    echo "[sf]   renamed ${CUR_NAME} -> ${RENAME_TO}"
  else
    echo "[sf]   netdev already named ${RENAME_TO}"
  fi
}

# PF0 PCI address (for p0_if and pf0hpf_if)
PF0_PCI=$(sudo lspci | awk '/Mellanox.*ConnectX-7/ && /^03:00\.0/ {print "0000:"$1; exit}')
PF1_PCI=$(sudo lspci | awk '/Mellanox.*ConnectX-7/ && /^03:00\.1/ {print "0000:"$1; exit}')
echo "[sf] PF0=${PF0_PCI} PF1=${PF1_PCI}"

create_sf "${PF0_PCI}" "${SF_P0}"     "p0_if"
create_sf "${PF1_PCI}" "${SF_P1}"     "p1_if"
create_sf "${PF0_PCI}" "${SF_PF0HPF}" "pf0hpf_if"

# Add SFs to br-hbn
echo "[sf] wiring SFs into br-hbn"
sudo ovs-vsctl --may-exist add-port br-hbn p0_if     -- set Interface p0_if     type=dpdk mtu_request=9216
sudo ovs-vsctl --may-exist add-port br-hbn p1_if     -- set Interface p1_if     type=dpdk mtu_request=9216
sudo ovs-vsctl --may-exist add-port br-hbn pf0hpf_if -- set Interface pf0hpf_if type=dpdk mtu_request=9216

# Patch ports br-hbn <-> br-sfc (for p0 uplink path)
sudo ovs-vsctl --may-exist add-port br-hbn  hbn-to-sfc -- set Interface hbn-to-sfc type=patch options:peer=sfc-to-hbn
sudo ovs-vsctl --may-exist add-port br-sfc  sfc-to-hbn -- set Interface sfc-to-hbn type=patch options:peer=hbn-to-sfc

# Patch ports br-hbn <-> br-p1 (for p1 uplink path)
sudo ovs-vsctl --may-exist add-port br-hbn  hbn-to-p1  -- set Interface hbn-to-p1  type=patch options:peer=p1-to-hbn
sudo ovs-vsctl --may-exist add-port br-p1   p1-to-hbn  -- set Interface p1-to-hbn  type=patch options:peer=hbn-to-p1

echo "[sf] done"
sudo ovs-vsctl show
