#!/bin/bash
#
# DPF Host Discovery Script
#
# Run inside the dpf-discovery privileged pod to collect all hardware and
# network information needed to fill in CONFIG_REQUIREMENTS.md variables.
#
# Usage (from your workstation):
#   kubectl cp scripts/discover.sh dpf-discovery/<pod>:/tmp/discover.sh
#   kubectl exec -n dpf-discovery <pod> -- bash /tmp/discover.sh
#
# Or run against all nodes at once:
#   for pod in $(kubectl get pods -n dpf-discovery -o name); do
#     echo "===== $pod ====="
#     kubectl exec -n dpf-discovery ${pod##*/} -- bash /tmp/discover.sh
#   done

set -euo pipefail

REPORT="/results/discovery-$(hostname).txt"

header() {
  echo ""
  echo "================================================================"
  echo "  $1"
  echo "================================================================"
}

# ─────────────────────────────────────────────────────────────────────
# 1. HOST IDENTITY
# ─────────────────────────────────────────────────────────────────────
header "HOST IDENTITY"

echo "Hostname: $(hostname)"
echo "Date:     $(date -u)"
echo ""

echo "--- /etc/os-release ---"
cat /host/etc/os-release 2>/dev/null | head -5
echo ""

echo "--- Kernel ---"
chroot /host uname -a 2>/dev/null || uname -a

# ─────────────────────────────────────────────────────────────────────
# 2. CPU / MEMORY / NUMA
# ─────────────────────────────────────────────────────────────────────
header "CPU / MEMORY / NUMA"

echo "--- CPU Summary ---"
chroot /host lscpu 2>/dev/null | grep -E "^(Architecture|CPU\(s\)|Thread|Core|Socket|Model name|NUMA)"
echo ""

echo "--- Memory ---"
grep -E "MemTotal|MemFree|MemAvailable|HugePages|Hugepagesize" /host/proc/meminfo
echo ""

echo "--- NUMA Topology ---"
ls /host/sys/devices/system/node/ 2>/dev/null | grep node || echo "NUMA info not available"

# ─────────────────────────────────────────────────────────────────────
# 3. NETWORK INTERFACES  →  controlPlaneInterface
# ─────────────────────────────────────────────────────────────────────
header "NETWORK INTERFACES (discover controlPlaneInterface)"

echo "--- Default Route ---"
chroot /host ip route show default 2>/dev/null
echo ""

echo "--- All Interfaces (state, IP, MTU) ---"
chroot /host ip -br addr show 2>/dev/null
echo ""

echo "--- Interface Details ---"
for iface in $(ls /host/sys/class/net/ | grep -v "^lo$"); do
  DRIVER=$(cat /host/sys/class/net/$iface/device/driver/module/drivers/*/name 2>/dev/null | head -1 || echo "unknown")
  MTU=$(cat /host/sys/class/net/$iface/mtu 2>/dev/null || echo "?")
  OPERSTATE=$(cat /host/sys/class/net/$iface/operstate 2>/dev/null || echo "?")
  SPEED=$(cat /host/sys/class/net/$iface/speed 2>/dev/null || echo "?")
  MAC=$(cat /host/sys/class/net/$iface/address 2>/dev/null || echo "?")
  echo "  $iface: driver=$DRIVER mtu=$MTU state=$OPERSTATE speed=${SPEED}Mbps mac=$MAC"
done
echo ""

echo "--- RECOMMENDATION: controlPlaneInterface ---"
DEFAULT_IFACE=$(chroot /host ip route show default 2>/dev/null | awk '{print $5; exit}')
DEFAULT_IP=$(chroot /host ip -4 addr show dev "$DEFAULT_IFACE" 2>/dev/null | grep inet | awk '{print $2}')
echo "  Interface: $DEFAULT_IFACE"
echo "  IP:        $DEFAULT_IP"

# ─────────────────────────────────────────────────────────────────────
# 4. PCI DEVICES / BLUEFIELD  →  DPU variable
# ─────────────────────────────────────────────────────────────────────
header "BLUEFIELD / MELLANOX PCI DEVICES (discover DPU prefix)"

echo "--- Mellanox/NVIDIA PCI Devices ---"
chroot /host lspci -d 15b3: -v 2>/dev/null | grep -E "^[0-9a-f]|Product Name|Serial" || echo "No Mellanox devices found"
echo ""

echo "--- BlueField Devices ---"
chroot /host lspci -d 15b3: 2>/dev/null | grep -i -E "bluefield|connectx" || echo "No BlueField found"
echo ""

echo "--- Network Interfaces Backed by Mellanox ---"
for iface in $(ls /host/sys/class/net/); do
  VENDOR=$(cat /host/sys/class/net/$iface/device/vendor 2>/dev/null || continue)
  if [ "$VENDOR" = "0x15b3" ]; then
    PCI_ADDR=$(basename $(readlink /host/sys/class/net/$iface/device 2>/dev/null) 2>/dev/null || echo "?")
    DRIVER=$(basename $(readlink /host/sys/class/net/$iface/device/driver 2>/dev/null) 2>/dev/null || echo "?")
    echo "  $iface: pci=$PCI_ADDR driver=$DRIVER"
  fi
done
echo ""

echo "--- RECOMMENDATION: DPU PCI Prefix ---"
# Find BF PF interfaces (typically named enp<bus>s0f0np0 or similar)
for iface in $(ls /host/sys/class/net/); do
  if echo "$iface" | grep -qE "f0np0$"; then
    PREFIX=$(echo "$iface" | sed 's/f0np0$//')
    echo "  DPU prefix: $PREFIX  (port 0: ${PREFIX}f0np0, port 1: ${PREFIX}f1np1)"
  fi
done

# ─────────────────────────────────────────────────────────────────────
# 5. SR-IOV CAPABILITIES  →  DPUNumVFs
# ─────────────────────────────────────────────────────────────────────
header "SR-IOV CAPABILITIES (discover DPUNumVFs)"

echo "--- SR-IOV Capable Devices ---"
for dev in /host/sys/bus/pci/devices/*/sriov_totalvfs; do
  [ -f "$dev" ] || continue
  PCI=$(echo "$dev" | sed 's|/host/sys/bus/pci/devices/||;s|/sriov_totalvfs||')
  TOTAL=$(cat "$dev")
  CURRENT=$(cat "$(dirname $dev)/sriov_numvfs" 2>/dev/null || echo "0")
  VENDOR=$(cat "$(dirname $dev)/vendor" 2>/dev/null || echo "?")
  [ "$VENDOR" = "0x15b3" ] || continue
  IFACE=""
  for net in $(dirname $dev)/net/*; do
    [ -d "$net" ] && IFACE=$(basename "$net")
  done
  echo "  PCI $PCI: totalVFs=$TOTAL currentVFs=$CURRENT iface=$IFACE"
done

# ─────────────────────────────────────────────────────────────────────
# 6. DPU SERIAL NUMBERS  →  HBN hostname patterns
# ─────────────────────────────────────────────────────────────────────
header "DPU SERIAL NUMBERS (discover HBN hostname patterns)"

echo "--- PCI Device Serial Numbers (Mellanox) ---"
for dev in /host/sys/bus/pci/devices/*; do
  VENDOR=$(cat "$dev/vendor" 2>/dev/null || continue)
  [ "$VENDOR" = "0x15b3" ] || continue
  CLASS=$(cat "$dev/class" 2>/dev/null || echo "?")
  # Only show network controllers (0x0200xx)
  echo "$CLASS" | grep -q "0x0200" || continue
  PCI=$(basename "$dev")
  SERIAL=""
  # Try to read serial from vpd or config space
  if [ -f "$dev/vpd" ]; then
    SERIAL=$(strings "$dev/vpd" 2>/dev/null | grep -oP "SN\K.*" | head -1 || echo "")
  fi
  # Alternative: lspci verbose
  if [ -z "$SERIAL" ]; then
    SERIAL=$(chroot /host lspci -vvv -s "$PCI" 2>/dev/null | grep -i "serial" | head -1 | awk -F: '{print $NF}' | xargs || echo "not found")
  fi
  echo "  PCI $PCI: serial=$SERIAL"
done
echo ""

echo "--- MST Devices (if mst tools installed) ---"
if chroot /host which mst 2>/dev/null; then
  chroot /host mst status 2>/dev/null || echo "mst not running"
else
  echo "mst tools not installed (will be available after DPF deployment)"
fi
echo ""

echo "--- RSHIM Devices (DPU management) ---"
ls /host/dev/rshim* 2>/dev/null || echo "No rshim devices found"

# ─────────────────────────────────────────────────────────────────────
# 7. DPU BMC / OOB NETWORK  →  dpfDiscoveryStartIP / EndIP
# ─────────────────────────────────────────────────────────────────────
header "DPU BMC / OOB NETWORK (discover dpfDiscovery IPs)"

echo "--- IPMI / BMC Interfaces ---"
if chroot /host which ipmitool &>/dev/null; then
  chroot /host ipmitool lan print 2>/dev/null | grep -E "IP Address|MAC Address|Subnet" || echo "ipmitool available but no output"
else
  echo "ipmitool not installed"
fi
echo ""

echo "--- BMC-related Network Interfaces ---"
for iface in $(ls /host/sys/class/net/); do
  # Look for USB-based or tmfifo interfaces (BF BMC)
  if echo "$iface" | grep -qiE "tmfifo|usb|bmc|oob"; then
    IP=$(chroot /host ip -4 addr show dev "$iface" 2>/dev/null | grep inet | awk '{print $2}')
    echo "  $iface: $IP"
  fi
done
echo ""

echo "--- ARP Table (may show DPU BMC neighbors) ---"
chroot /host arp -an 2>/dev/null | head -20

# ─────────────────────────────────────────────────────────────────────
# 8. DISK / STORAGE  →  Longhorn requirements
# ─────────────────────────────────────────────────────────────────────
header "DISK / STORAGE (Longhorn readiness)"

echo "--- Block Devices ---"
chroot /host lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT 2>/dev/null
echo ""

echo "--- Disk Space ---"
chroot /host df -h / /var 2>/dev/null
echo ""

echo "--- /var/lib/longhorn (if exists) ---"
if [ -d /host/var/lib/longhorn ]; then
  du -sh /host/var/lib/longhorn
else
  echo "Directory does not exist yet (will be created by Longhorn)"
  echo "Available on /var: $(df -h /host/var 2>/dev/null | tail -1 | awk '{print $4}')"
fi

# ─────────────────────────────────────────────────────────────────────
# 9. NETWORK FABRIC  →  MTU / jumbo frames
# ─────────────────────────────────────────────────────────────────────
header "NETWORK FABRIC (MTU / jumbo frame check)"

echo "--- Current MTU per interface ---"
for iface in $(ls /host/sys/class/net/ | grep -v "^lo$"); do
  MTU=$(cat /host/sys/class/net/$iface/mtu 2>/dev/null || echo "?")
  MAX_MTU=$(cat /host/sys/class/net/$iface/mtu_max 2>/dev/null || echo "?")
  STATE=$(cat /host/sys/class/net/$iface/operstate 2>/dev/null || echo "?")
  [ "$STATE" = "up" ] || continue
  echo "  $iface: mtu=$MTU max_mtu=$MAX_MTU"
done

# ─────────────────────────────────────────────────────────────────────
# 10. EXISTING VRRP / KEEPALIVED  →  virtualRouterID conflicts
# ─────────────────────────────────────────────────────────────────────
header "EXISTING VRRP / KEEPALIVED (check for virtualRouterID conflicts)"

echo "--- Running keepalived processes ---"
chroot /host ps aux 2>/dev/null | grep -i keepalived | grep -v grep || echo "No keepalived running"
echo ""

echo "--- VRRP advertisements on management interface ---"
echo "(Would require tcpdump; skipping in automated run)"
echo "Manual check: tcpdump -i $DEFAULT_IFACE -n 'vrrp' -c 5 -t"

# ─────────────────────────────────────────────────────────────────────
# 11. FIRMWARE VERSIONS
# ─────────────────────────────────────────────────────────────────────
header "FIRMWARE VERSIONS"

echo "--- NIC Firmware (ethtool) ---"
for iface in $(ls /host/sys/class/net/); do
  VENDOR=$(cat /host/sys/class/net/$iface/device/vendor 2>/dev/null || continue)
  [ "$VENDOR" = "0x15b3" ] || continue
  echo "  $iface:"
  chroot /host ethtool -i "$iface" 2>/dev/null | grep -E "driver|version|firmware" | sed 's/^/    /'
done

# ─────────────────────────────────────────────────────────────────────
# 12. SUBNET SCAN FOR FREE VIP  →  controlPlaneVIP candidate
# ─────────────────────────────────────────────────────────────────────
header "FREE IP SCAN (controlPlaneVIP candidates)"

if [ -n "$DEFAULT_IFACE" ] && [ -n "$DEFAULT_IP" ]; then
  SUBNET=$(echo "$DEFAULT_IP" | sed 's|/.*||' | awk -F. '{print $1"."$2"."$3}')
  echo "Scanning $SUBNET.240-250 for free IPs (high range, likely outside DHCP)..."
  for i in $(seq 240 250); do
    IP="$SUBNET.$i"
    if ! chroot /host ping -c 1 -W 1 "$IP" &>/dev/null; then
      echo "  $IP — no response (candidate)"
    else
      echo "  $IP — in use"
    fi
  done
  echo ""
  echo "NOTE: Verify with your network team that the chosen IP is outside DHCP range"
else
  echo "Could not determine subnet to scan"
fi

# ─────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────
header "DISCOVERY SUMMARY"

echo "controlPlaneInterface = $DEFAULT_IFACE"
echo "controlPlaneVIP       = <pick from free IP scan above>"
echo "dpuOobPassword        = <obtain from hardware team>"

# DPU prefix
DPU_PREFIX=""
for iface in $(ls /host/sys/class/net/); do
  if echo "$iface" | grep -qE "f0np0$"; then
    DPU_PREFIX=$(echo "$iface" | sed 's/f0np0$//')
    break
  fi
done
echo "DPU                   = $DPU_PREFIX"

# VFs
for dev in /host/sys/bus/pci/devices/*/sriov_totalvfs; do
  [ -f "$dev" ] || continue
  VENDOR=$(cat "$(dirname $dev)/vendor" 2>/dev/null || continue)
  [ "$VENDOR" = "0x15b3" ] || continue
  VFS=$(cat "$dev")
  echo "DPUNumVFs             = $VFS"
  break
done

echo "dpfDiscoveryStartIP   = <DPU BMC IPs from section 7>"
echo "dpfDiscoveryEndIP     = <DPU BMC IPs from section 7>"
echo ""
echo "Report saved to: $REPORT"

# Save to file
exec > >(tee -a "$REPORT") 2>&1
