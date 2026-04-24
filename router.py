import socket
import json
import threading
import time
import os
import subprocess

MY_IP = os.getenv("MY_IP", "127.0.0.1")
NEIGHBORS = os.getenv("NEIGHBORS", "").split(",")
PORT = 5000

# routing_table = { subnet: [distance, next_hop] }
routing_table = {}


def get_local_subnets():
    """Read directly connected subnets from kernel routing table (proto kernel = always correct)."""
    subnets = {}
    try:
        out = subprocess.check_output("ip route show proto kernel", shell=True, text=True)
        for line in out.strip().split("\n"):
            parts = line.split()
            # format: 10.0.1.0/24 dev eth0 proto kernel scope link src 10.0.1.10
            if len(parts) >= 3 and parts[0].startswith("10."):
                subnet = parts[0]
                dev = parts[2]
                subnets[subnet] = dev
    except Exception:
        pass
    return subnets


def install_route(subnet, next_hop):
    """Install route, finding the correct dev for the next_hop automatically."""
    ret = os.system(f"ip route replace {subnet} via {next_hop} 2>/dev/null")
    if ret != 0:
        # fallback: let kernel pick the interface
        os.system(f"ip route replace {subnet} via {next_hop} onlink 2>/dev/null")


# Wait briefly so all interfaces are attached before seeding
time.sleep(2)

local_subnets = get_local_subnets()
for subnet in local_subnets:
    routing_table[subnet] = [0, "0.0.0.0"]

print(f"Router started at {MY_IP}")
print(f"Neighbors: {NEIGHBORS}")
print(f"Directly connected: {list(routing_table.keys())}")


def broadcast_updates():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        for neighbor in NEIGHBORS:
            neighbor = neighbor.strip()
            if not neighbor:
                continue
            # Split Horizon: omit routes learned via this neighbor
            routes = [
                {"subnet": s, "distance": d}
                for s, (d, nh) in routing_table.items()
                if nh != neighbor
            ]
            packet = json.dumps({
                "router_id": MY_IP,
                "version": 1.0,
                "routes": routes
            }).encode()
            try:
                sock.sendto(packet, (neighbor, PORT))
            except Exception:
                pass
        time.sleep(5)


def listen_for_updates():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    while True:
        data, addr = sock.recvfrom(4096)
        neighbor_ip = addr[0]
        try:
            packet = json.loads(data.decode())
            if packet.get("version") != 1.0:
                continue
            update_logic(neighbor_ip, packet["routes"])
        except Exception:
            continue


def update_logic(neighbor_ip, routes_from_neighbor):
    updated = False
    for route in routes_from_neighbor:
        subnet = route["subnet"]
        new_distance = route["distance"] + 1

        if subnet not in routing_table or new_distance < routing_table[subnet][0]:
            routing_table[subnet] = [new_distance, neighbor_ip]
            updated = True
        elif routing_table[subnet][1] == neighbor_ip and new_distance != routing_table[subnet][0]:
            routing_table[subnet] = [new_distance, neighbor_ip]
            updated = True

    if updated:
        print(f"\n[{MY_IP}] Routing Table Updated:")
        for subnet, (distance, next_hop) in routing_table.items():
            print(f"  {subnet} -> dist={distance} via {next_hop}")
            if next_hop != "0.0.0.0":
                install_route(subnet, next_hop)


if __name__ == "__main__":
    threading.Thread(target=broadcast_updates, daemon=True).start()
    listen_for_updates()
