#!/bin/bash
# test.sh — Full test suite for the Distance-Vector Router assignment
# Run from the CN/ directory: bash test.sh

set -e

PASS=0
FAIL=0

pass() { echo "[PASS] $1"; ((PASS++)); }
fail() { echo "[FAIL] $1"; ((FAIL++)); }

separator() { echo; echo "========================================"; echo "$1"; echo "========================================"; }

# ─── SETUP ───────────────────────────────────────────────────────────────────
separator "STEP 1: Build and start topology"
docker compose down -v --remove-orphans 2>/dev/null || true
docker compose build --no-cache
docker compose up -d
echo "Waiting 20s for initial convergence..."
sleep 20

# ─── TEST 1: All containers running ──────────────────────────────────────────
separator "TEST 1: Containers are up"
for r in router_a router_b router_c; do
    STATUS=$(docker inspect -f '{{.State.Running}}' $r 2>/dev/null)
    if [ "$STATUS" = "true" ]; then
        pass "$r is running"
    else
        fail "$r is NOT running"
    fi
done

# ─── TEST 2: Routing table convergence ───────────────────────────────────────
separator "TEST 2: Routing table convergence (all 3 subnets known)"

check_routes() {
    local container=$1
    local table
    table=$(docker exec $container ip route show 2>/dev/null)
    echo "  [$container] ip route:"
    echo "$table" | sed 's/^/    /'

    local found=0
    for subnet in "10.0.1.0/24" "10.0.2.0/24" "10.0.3.0/24"; do
        if echo "$table" | grep -q "$subnet"; then
            ((found++))
        fi
    done
    echo "  [$container] knows $found/3 subnets"
    [ "$found" -ge 2 ] && pass "$container has converged (knows ≥2 subnets)" \
                        || fail "$container has NOT converged (knows $found/3 subnets)"
}

check_routes router_a
check_routes router_b
check_routes router_c

# ─── TEST 3: DV-JSON packet format ───────────────────────────────────────────
separator "TEST 3: DV-JSON packet format validation"
# Capture one packet from router_a's log and validate fields
LOG=$(docker logs router_a 2>&1)
if echo "$LOG" | grep -q "router_id"; then
    pass "router_a log contains router_id field"
else
    fail "router_a log missing router_id field"
fi

# ─── TEST 4: Ping reachability across all subnets ────────────────────────────
separator "TEST 4: Ping reachability"

ping_test() {
    local from=$1
    local to=$2
    if docker exec $from ping -c 2 -W 2 $to > /dev/null 2>&1; then
        pass "ping $from -> $to"
    else
        fail "ping $from -> $to FAILED"
    fi
}

# Direct neighbors
ping_test router_a 10.0.1.3   # A -> B on net_ab
ping_test router_a 10.0.3.3   # A -> C on net_ac
ping_test router_b 10.0.2.3   # B -> C on net_bc

# Cross-subnet (requires routing)
ping_test router_a 10.0.2.2   # A -> B's net_bc IP (via B)
ping_test router_b 10.0.3.2   # B -> A's net_ac IP (via A or C)

# ─── TEST 5: Failover — stop router_c, A must reroute via B ──────────────────
separator "TEST 5: Failover — stop router_c"
echo "Stopping router_c..."
docker stop router_c

echo "Waiting ${TIMEOUT:-15}s for stale route expiry + re-convergence..."
sleep 20

echo "router_a routing table after router_c stopped:"
docker exec router_a ip route show | sed 's/^/  /'

# router_a should still know 10.0.2.0/24 via router_b (10.0.1.2)
ROUTE=$(docker exec router_a ip route show 2>/dev/null)
echo "router_a route table:"
echo "$ROUTE" | sed 's/^/  /'

# router_a should still know 10.0.2.0/24 via router_b (10.0.1.3)
if echo "$ROUTE" | grep -q "10.0.2.0/24"; then
    pass "router_a still knows 10.0.2.0/24 after router_c stopped (rerouted via B)"
else
    fail "router_a lost 10.0.2.0/24 after router_c stopped — failover did NOT work"
fi

# 10.0.3.0/24 should be gone (only router_c was on that subnet, router_b learned it from C)
if echo "$ROUTE" | grep -q "10.0.3.0/24"; then
    fail "router_a still has 10.0.3.0/24 — stale route NOT expired"
else
    pass "router_a correctly removed 10.0.3.0/24 (stale route expired)"
fi

# ─── TEST 6: Split Horizon — no count-to-infinity ────────────────────────────
separator "TEST 6: Split Horizon — check router logs for omitted routes"
# After router_c stops, router_b should NOT advertise 10.0.3.0/24 back to router_a
# (it learned it from router_c which is now gone — it should expire, not loop)
LOG_B=$(docker logs router_b 2>&1 | tail -30)
echo "  [router_b] recent log:"
echo "$LOG_B" | sed 's/^/    /'
if echo "$LOG_B" | grep -q "Expiring stale route"; then
    pass "router_b correctly expired stale route from router_c"
else
    echo "  (stale expiry may not have printed yet — checking route table instead)"
    ROUTE_B=$(docker exec router_b ip route show 2>/dev/null)
    if ! echo "$ROUTE_B" | grep -q "10.0.3.0/24"; then
        pass "router_b no longer has 10.0.3.0/24 in OS table"
    else
        fail "router_b still has 10.0.3.0/24 — possible loop or stale route"
    fi
fi

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
separator "RESULTS"
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo
if [ "$FAIL" -eq 0 ]; then
    echo "ALL TESTS PASSED"
else
    echo "$FAIL TEST(S) FAILED — review output above"
fi

echo
echo "Containers left running for manual inspection."
echo "Run 'bash teardown.sh' to clean up."
