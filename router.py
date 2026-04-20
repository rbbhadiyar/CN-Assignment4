import socket
import json
import threading
import time
import os

MY_IP = os.getenv("MY_IP", "127.0.0.1")
NEIGHBORS = os.getenv("NEIGHBORS", "").split(",")
PORT = 5000

# routing_table = { subnet: [distance, next_hop] }
routing_table = {}

# seed directly connected subnets at distance 0
for ip in MY_IP.split(","):
    ip = ip.strip()
    parts = ip.split(".")
    subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    routing_table[subnet] = [0, "0.0.0.0"]


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
                os.system(f"ip route replace {subnet} via {next_hop}")


if __name__ == "__main__":
    print(f"Router started at {MY_IP}")
    print(f"Neighbors: {NEIGHBORS}")
    threading.Thread(target=broadcast_updates, daemon=True).start()
    listen_for_updates()
