#!/bin/bash
# teardown.sh — Remove all containers and networks from the test topology
docker compose down -v --remove-orphans
echo "Cleaned up."
