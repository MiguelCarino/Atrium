#!/usr/bin/env python3
"""Wake-on-LAN: switch on another computer on the local network by sending
its network card the "magic packet" -- six 0xFF bytes and its MAC address
sixteen times, one UDP broadcast (port 9). Settings > Devices > Machines has
a Wake button for every machine with a MAC here.

    wol.py send MAC|NAME [--broadcast IP] [--port N]
                                    wake it (a MAC as aa:bb:cc:dd:ee:ff,
                                    aa-bb-..., aabb.ccdd.eeff or 12 hex digits,
                                    or the name of a machine saved below)
    wol.py add NAME MAC [--peer ID] [--broadcast IP]
                                    remember a machine (--peer: the paired
                                    machine of peers.py it is, so Machines shows
                                    its Wake button)
    wol.py remove NAME              forget it
    wol.py list [--json]            the machines remembered
    wol.py learn PEER_ID IP NAME    remember a paired machine's MAC from this
                                    computer's neighbour table (`ip -j neigh`,
                                    IPv4 and IPv6 neighbours; /proc/net/arp
                                    when ip cannot answer: known once anything
                                    has talked to that IP; no packet is sent).
                                    Quiet when not found

The machines are kept in ~/.config/hypr/wol.json (HYPR_WOL_CONF for the
tests), apart from peers.py's pairings: a machine needs no pairing to be
woken, and forgetting a pairing does not forget its MAC. peers.py also
notes a machine's MAC when it pairs ("mac" in peers.json, PEERS_HOME for
the tests): send and list take a paired machine's MAC from there when
wol.json has no entry for it, so it can be woken without a `learn`.

Waking works only when the other computer allows it: "Wake on LAN" (or
"Power on by PCI-E") on in its firmware setup, and on Linux its card set to
`ethtool -s <card> wol g` (NetworkManager: `nmcli connection modify <conn>
802-3-ethernet.wake-on-lan magic`). Wired cards almost always can; Wi-Fi
almost never. The packet does not cross routers: same network only.
"""
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys

CONF = os.environ.get("HYPR_WOL_CONF") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "hypr", "wol.json")
ARP = "/proc/net/arp"
# peers.py's file (its CONF, without importing it: that needs the crypto modules).
PEERS_CONF = (os.path.join(os.environ["PEERS_HOME"], "peers.json") if os.environ.get("PEERS_HOME") else
              os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                           "hypr", "peers.json"))
PORT = 9
BROADCAST = "255.255.255.255"


# -- pure ---------------------------------------------------------------------------------
def parse_mac(text):
    """"AA-bb:cc.dd ee ff" in any of the usual spellings -> the 6 bytes.
    ValueError for anything that is not 12 hex digits, or the all-zero /
    broadcast address (nothing wakes to those)."""
    digits = re.sub(r"[\s:.\-]", "", str(text or ""))
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", digits):
        raise ValueError(f"not a MAC address: {text!r}")
    raw = bytes.fromhex(digits)
    if raw in (b"\x00" * 6, b"\xff" * 6):
        raise ValueError(f"not a card's MAC address: {text!r}")
    return raw


def format_mac(raw):
    return ":".join(f"{b:02x}" for b in raw)


def magic_packet(mac):
    """The 102-byte packet: 6 x 0xFF, then the MAC 16 times."""
    raw = parse_mac(mac) if not isinstance(mac, bytes) else mac
    return b"\xff" * 6 + raw * 16


def check_ip(text):
    """An IPv4 address (the broadcast to send to), or ValueError."""
    try:
        socket.inet_aton(text)
    except OSError:
        raise ValueError(f"not an IPv4 address: {text!r}") from None
    if text.count(".") != 3:
        raise ValueError(f"not an IPv4 address: {text!r}")
    return text


def arp_lookup(text, ip):
    """The MAC of ip in a /proc/net/arp text, or None (incomplete entries --
    flags 0x0, all-zero MAC -- are not an answer)."""
    for line in (text or "").splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 4 and cols[0] == ip and cols[2] != "0x0":
            try:
                return format_mac(parse_mac(cols[3]))
            except ValueError:
                return None
    return None


def same_ip(a, b):
    """Whether two address texts are the same IP (IPv6 spelled any way, an
    IPv4-mapped IPv6 the same as its IPv4)."""
    def norm(text):
        addr = ipaddress.ip_address(str(text).split("%", 1)[0])
        return getattr(addr, "ipv4_mapped", None) or addr
    try:
        return norm(a) == norm(b)
    except ValueError:
        return False


def neigh_lookup(text, ip):
    """The MAC of ip in `ip -j neigh` output, or None: IPv4 and IPv6
    neighbours; an entry without a link-layer address (INCOMPLETE, FAILED)
    is not an answer."""
    try:
        rows = json.loads(text or "[]")
    except ValueError:
        return None
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not r.get("lladdr") or not same_ip(r.get("dst", ""), ip):
            continue
        if set(r.get("state") or []) & {"FAILED", "INCOMPLETE"}:
            continue
        try:
            return format_mac(parse_mac(r["lladdr"]))
        except ValueError:
            continue
    return None


def lookup_mac(ip, neigh_text, arp_text):
    """The neighbour table's MAC for ip: `ip -j neigh` first, /proc/net/arp
    (IPv4 only) for an IPv4-mapped or plain IPv4 address it did not have."""
    mac = neigh_lookup(neigh_text, ip)
    if mac:
        return mac
    try:
        addr = ipaddress.ip_address(str(ip))
        v4 = str(getattr(addr, "ipv4_mapped", None) or addr)
    except ValueError:
        return None
    return arp_lookup(arp_text, v4)


def with_peers(machines, peers):
    """wol.json's machines plus the paired machines whose MAC peers.py noted
    at pairing and wol.json does not have (by peer id, else by name): a new
    dict. wol.json wins; the added ones say "from": "pairing"."""
    out = dict(machines)
    for p in peers if isinstance(peers, list) else []:
        if not isinstance(p, dict) or not p.get("id") or not p.get("name"):
            continue
        try:
            mac = format_mac(parse_mac(p.get("mac")))
        except ValueError:
            continue
        if for_peer(out, p["id"], str(p["name"])) or str(p["name"]).lower() in (k.lower() for k in out):
            continue
        out[str(p["name"])] = {"name": str(p["name"]), "mac": mac, "peer": p["id"], "from": "pairing"}
    return out


def find(machines, what):
    """The saved machine a name, a peer id or a MAC means, or None."""
    want = str(what or "").strip()
    for key, m in machines.items():
        if want.lower() in (key.lower(), str(m.get("name", "")).lower()) or (m.get("peer") and want == m["peer"]):
            return m
    try:
        mac = format_mac(parse_mac(want))
    except ValueError:
        return None
    return next((m for m in machines.values() if m.get("mac") == mac), None)


def for_peer(machines, peer_id, name=""):
    """The saved machine for a paired machine (by its peer id, else by name)."""
    found = next((m for m in machines.values() if peer_id and m.get("peer") == peer_id), None)
    if found or not name:
        return found
    return next((m for m in machines.values() if str(m.get("name", "")).lower() == name.lower()), None)


def add(machines, name, mac, peer=None, broadcast=None):
    """The machines with this one added (or replaced by name): a new dict."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a machine needs a name")
    entry = {"name": name, "mac": format_mac(parse_mac(mac))}
    if peer:
        entry["peer"] = peer
    if broadcast:
        entry["broadcast"] = check_ip(broadcast)
    out = {k: v for k, v in machines.items() if k.lower() != name.lower()
           and not (peer and v.get("peer") == peer)}
    out[name] = entry
    return out


def options(argv, names):
    """--key value pairs out of argv: (the rest, {key: value})."""
    rest, opts, i = [], {}, 0
    while i < len(argv):
        if argv[i] in names and i + 1 < len(argv):
            opts[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return rest, opts


# -- files and the network ----------------------------------------------------------------
def load(path=None):
    try:
        with open(path or CONF) as handle:
            data = json.load(handle)
        machines = data.get("machines") if isinstance(data, dict) else None
        return machines if isinstance(machines, dict) else {}
    except (OSError, ValueError):
        return {}


def read_peers(path=None):
    """peers.json's paired machines ([] without one)."""
    try:
        with open(path or PEERS_CONF) as handle:
            data = json.load(handle)
        peers = data.get("peers") if isinstance(data, dict) else None
        return peers if isinstance(peers, list) else []
    except (OSError, ValueError):
        return []


def load_all(path=None, peers_path=None):
    """The machines send and list know: wol.json's, then the pairings'."""
    return with_peers(load(path), read_peers(peers_path))


def save(machines, path=None):
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump({"machines": machines}, handle, indent=1)
    os.replace(tmp, path)


def send(mac, broadcast=BROADCAST, port=PORT, sock_factory=None):
    """Send the packet three times (UDP: three copies cover a dropped one).
    Returns the bytes sent."""
    packet = magic_packet(mac)
    sock = (sock_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)))()
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sent = 0
        for _ in range(3):
            sent += sock.sendto(packet, (broadcast, int(port)))
        return sent
    finally:
        sock.close()


def read_arp():
    try:
        with open(ARP) as handle:
            return handle.read()
    except OSError:
        return ""


def read_neigh():
    """`ip -j neigh show` (IPv4 and IPv6 neighbours); "" when ip cannot answer."""
    try:
        return subprocess.run(["ip", "-j", "neigh", "show"], capture_output=True, text=True,
                              timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def neighbour_mac(ip):
    """The MAC the neighbour table has for ip, or None (no packet sent)."""
    return lookup_mac(ip, read_neigh(), read_arp())


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "send" and len(argv) >= 2:
        rest, opts = options(argv[1:], ("--broadcast", "--port"))
        machine = find(load_all(), rest[0]) if rest else None
        mac = machine["mac"] if machine else (rest[0] if rest else "")
        try:
            broadcast = check_ip(opts.get("broadcast") or (machine or {}).get("broadcast") or BROADCAST)
            send(mac, broadcast, int(opts.get("port", PORT)))
        except (ValueError, OSError) as exc:
            sys.exit(f"wol: {exc}")
        who = machine["name"] if machine else format_mac(parse_mac(mac))
        print(f"wol: sent the wake-up to {who} ({format_mac(parse_mac(mac))}); it takes 10-60 s to come up")
    elif cmd == "add" and len(argv) >= 3:
        rest, opts = options(argv[1:], ("--peer", "--broadcast"))
        try:
            save(add(load(), rest[0], rest[1] if len(rest) > 1 else "", opts.get("peer"), opts.get("broadcast")))
        except (ValueError, IndexError) as exc:
            sys.exit(f"wol: {exc}")
    elif cmd == "remove" and len(argv) == 2:
        machines = load()
        machine = find(machines, argv[1])
        if not machine:
            if find(load_all(), argv[1]):
                sys.exit(f"wol: {argv[1]}'s MAC comes from its pairing: forget the pairing to drop it")
            sys.exit(f"wol: no machine {argv[1]!r}")
        save({k: v for k, v in machines.items() if v is not machine})
    elif cmd == "list":
        machines = load_all()
        if "--json" in argv:
            print(json.dumps({"machines": list(machines.values())}))
        else:
            for m in machines.values():
                print(f"{m['name']:<20} {m['mac']}" + (f"  peer {m['peer']}" if m.get("peer") else ""))
    elif cmd == "learn" and len(argv) == 4:
        peer, ip, name = argv[1:]
        machines = load()
        if for_peer(load_all(), peer):
            return
        mac = neighbour_mac(ip)
        if mac:
            save(add(machines, name, mac, peer))
            print(f"wol: {name} is {mac}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
