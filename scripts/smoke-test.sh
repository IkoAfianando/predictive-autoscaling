#!/usr/bin/env bash
# Minimal end-to-end smoke test against one stack (default go)
set -euo pipefail
STACK="${1:-go}"
declare -A BASE=( [go]=8001 [rust]=8011 [java]=8021 [node]=8031 )
declare -A PROD=( [go]=8002 [rust]=8012 [java]=8022 [node]=8032 )
declare -A ORDR=( [go]=8003 [rust]=8013 [java]=8023 [node]=8033 )
U=http://localhost:${BASE[$STACK]}; P=http://localhost:${PROD[$STACK]}; O=http://localhost:${ORDR[$STACK]}
echo "== $STACK =="
curl -sf -X POST "$U/users/register" -H 'content-type: application/json' -d '{"username":"smoke","password":"pw123"}'; echo
curl -sf -X POST "$U/users/login"    -H 'content-type: application/json' -d '{"username":"smoke","password":"pw123"}'; echo
curl -sf -X POST "$P/products"       -H 'content-type: application/json' -d '{"name":"Widget","price":9.99}'; echo
curl -sf "$P/products/1"; echo
curl -sf -X POST "$O/orders"         -H 'content-type: application/json' -d '{"user_id":1,"product_id":1,"qty":2}'; echo
echo "smoke ok"
