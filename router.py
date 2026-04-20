import socket
import json
import threading
import time
import os

# ENV CONFIG
MY_IP = os.getenv("MY_IP", "127.0.0.1")
NEIGHBORS = os.getenv("NEIGHBORS", "").split(",")

PORT = 5000

# routing_table = { subnet: [distance, next_hop] }
routing_table = {}

# directly connected networks (you can infer from IP)
# Example: 10.0.1.1 → subnet 10.0.1.0/24
def get_direct_subnet(ip):
    parts = ip.split(".")
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"

# Initialize own subnet
own_subnet = get_direct_subnet(MY_IP)
routing_table[own_subnet] = [0, "0.0.0.0"]

# -------------------------------
# BROADCAST UPDATES
# -------------------------------
def broadcast_updates():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        routes = []

        for subnet, (distance, next_hop) in routing_table.items():
            routes.append({
                "subnet": subnet,
                "distance": distance
            })

        packet = {
            "router_id": MY_IP,
            "version": 1.0,
            "routes": routes
        }

        message = json.dumps(packet).encode()

        for neighbor in NEIGHBORS:
            if neighbor.strip() == "":
                continue

            try:
                sock.sendto(message, (neighbor.strip(), PORT))
            except:
                pass

        time.sleep(5)


# -------------------------------
# LISTEN FOR UPDATES
# -------------------------------
def listen_for_updates():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))

    while True:
        data, addr = sock.recvfrom(4096)
        neighbor_ip = addr[0]

        try:
            packet = json.loads(data.decode())

            if packet["version"] != 1.0:
                continue

            routes = packet["routes"]
            update_logic(neighbor_ip, routes)

        except:
            continue


# -------------------------------
# BELLMAN-FORD UPDATE LOGIC
# -------------------------------
def update_logic(neighbor_ip, routes_from_neighbor):
    updated = False

    for route in routes_from_neighbor:
        subnet = route["subnet"]
        neighbor_distance = route["distance"]

        # Split Horizon: skip if route learned from this neighbor
        if subnet in routing_table and routing_table[subnet][1] == neighbor_ip:
            continue

        new_distance = neighbor_distance + 1

        if subnet not in routing_table:
            routing_table[subnet] = [new_distance, neighbor_ip]
            updated = True

        else:
            current_distance, current_next_hop = routing_table[subnet]

            if new_distance < current_distance:
                routing_table[subnet] = [new_distance, neighbor_ip]
                updated = True

    # Update OS routing table
    if updated:
        print("\nUpdated Routing Table:")
        for subnet, (distance, next_hop) in routing_table.items():
            print(f"{subnet} → {distance} via {next_hop}")

            if next_hop != "0.0.0.0":
                os.system(f"ip route replace {subnet} via {next_hop}")


# -------------------------------
# MAIN
# -------------------------------
if __name__ == "__main__":
    print(f"Router started at {MY_IP}")
    print(f"Neighbors: {NEIGHBORS}")

    threading.Thread(target=broadcast_updates, daemon=True).start()
    listen_for_updates()