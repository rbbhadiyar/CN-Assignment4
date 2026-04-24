import socket
import json
import threading
import time
import os
import subprocess

MY_IP = os.getenv("MY_IP", "127.0.0.1")
NEIGHBORS = os.getenv("NEIGHBORS", "").split(",")
PORT = 5000
INFINITY = 16

# routing_table = { subnet: [distance, next_hop] }
routing_table = {}


def get_local_subnets():
    """Read directly connected subnets from kernel routing table (proto kernel)."""
    subnets = set()
    try:
        out = subprocess.check_output("ip route show proto kernel", shell=True, text=True)
        for line in out.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 1 and parts[0].startswith("10."):
                subnets.add(parts[0])
    except Exception:
        pass
    return subnets


def install_route(subnet, next_hop):
    ret = os.system(f"ip route replace {subnet} via {next_hop} 2>/dev/null")
    if ret != 0:
        os.system(f"ip route replace {subnet} via {next_hop} onlink 2>/dev/null")


# Wait so all interfaces are attached before seeding
time.sleep(2)

for subnet in get_local_subnets():
    routing_table[subnet] = [0, "0.0.0.0"]

print(f"Router started at {MY_IP}")
print(f"Neighbors: {NEIGHBORS}")
print(f"Directly connected: {list(routing_table.keys())}")


def sync_local_subnets():
    """Periodically sync directly connected subnets — handles link up/down events."""
    while True:
        time.sleep(5)
        current_local = get_local_subnets()

        # Add newly connected subnets
        for subnet in current_local:
            if subnet not in routing_table:
                routing_table[subnet] = [0, "0.0.0.0"]
                print(f"[{MY_IP}] Link up: {subnet}")

        # When a direct link is lost, remove it and all routes via neighbors on that subnet
        for subnet in list(routing_table.keys()):
            d, nh = routing_table[subnet]
            if nh == "0.0.0.0" and subnet not in current_local:
                # find neighbors on the lost subnet
                net_prefix = ".".join(subnet.split(".")[:3]) + "."
                lost_neighbors = {n.strip() for n in NEIGHBORS if n.strip().startswith(net_prefix)}
                del routing_table[subnet]
                os.system(f"ip route del {subnet} 2>/dev/null")
                print(f"[{MY_IP}] Link down: removed {subnet}")
                # purge routes via lost neighbors so they re-converge via other paths
                for s in list(routing_table.keys()):
                    if routing_table[s][1] in lost_neighbors:
                        del routing_table[s]
                        os.system(f"ip route del {s} 2>/dev/null")
                        print(f"[{MY_IP}] Purged route {s} (via lost neighbor)")
                break


def broadcast_updates():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        for neighbor in NEIGHBORS:
            neighbor = neighbor.strip()
            if not neighbor:
                continue
            # Poison Reverse: advertise routes learned from this neighbor back with INFINITY
            # This is better than Split Horizon for link failure recovery
            routes = []
            for s, (d, nh) in routing_table.items():
                if nh == neighbor:
                    routes.append({"subnet": s, "distance": INFINITY})  # poison
                else:
                    routes.append({"subnet": s, "distance": d})
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

        # Ignore poisoned routes (infinity) unless we currently use this neighbor
        if new_distance >= INFINITY:
            if subnet in routing_table and routing_table[subnet][1] == neighbor_ip:
                del routing_table[subnet]
                os.system(f"ip route del {subnet} 2>/dev/null")
                updated = True
            continue

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
    threading.Thread(target=sync_local_subnets, daemon=True).start()
    listen_for_updates()
