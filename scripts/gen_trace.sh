#!/usr/bin/env bash
# =============================================================================
# GENERATE TRACE → Jaeger  (buat demo distributed tracing)
#
# Nyuntik satu (atau beberapa) trace REALISTIS ke Jaeger lewat OTel Collector.
# Satu trace = alur request microservice: order -> panggil user + product,
# lengkap sama span bcrypt (CPU), redis GET (cache), dan db query (SQL).
# Di Jaeger bakal keliatan waterfall antar-service yang jelas.
#
# PAKAI:
#   bash scripts/gen_trace.sh                # 1 trace, stack go
#   bash scripts/gen_trace.sh rust           # 1 trace, stack rust
#   bash scripts/gen_trace.sh java 5         # 5 trace, stack java
#   bash scripts/gen_trace.sh node 3 error   # 3 trace dengan 1 error (503)
#
# Hasil: tiap trace ngeprint TRACE ID + link langsung ke Jaeger.
# =============================================================================
set -uo pipefail

STACK="${1:-go}"
COUNT="${2:-1}"
MODE="${3:-ok}"              # ok | error
OTLP="${OTLP_URL:-http://localhost:4318/v1/traces}"
JAEGER_UI="${JAEGER_UI:-http://localhost:16687}"

echo "[trace] stack=$STACK  count=$COUNT  mode=$MODE  →  $OTLP"
echo ""

for i in $(seq 1 "$COUNT"); do
python3 - "$STACK" "$MODE" "$i" "$OTLP" "$JAEGER_UI" <<'PY'
import os, sys, time, json, urllib.request, random

stack, mode, idx, otlp, jaeger_ui = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]

def sid(): return os.urandom(8).hex()
tid = os.urandom(16).hex()
now = time.time_ns()
ms  = 1_000_000
# variasi kecil biar tiap trace beda dikit (index-based, bukan random murni)
jit = (int(idx) * 7) % 20
err = (mode == "error" and int(idx) == 1)   # trace pertama yg error kalau mode=error

# --- span ids ---
s_order  = sid(); s_c_user = sid(); s_user = sid(); s_bcrypt = sid()
s_c_prod = sid(); s_prod = sid(); s_redis = sid(); s_db = sid()

def span(spid, name, kind, start_off, dur, parent=None, attrs=None, status_ok=True, err_msg=None):
    s = {
        "traceId": tid, "spanId": spid, "name": name, "kind": kind,
        "startTimeUnixNano": str(now + start_off*ms),
        "endTimeUnixNano":   str(now + (start_off+dur)*ms),
        "attributes": [{"key": k, "value": {"stringValue": str(v)} if isinstance(v,str)
                        else {"intValue": v}} for k,v in (attrs or {}).items()],
        "status": {"code": 2 if not status_ok else 1},
    }
    if parent: s["parentSpanId"] = parent
    if err_msg: s["status"]["message"] = err_msg
    return s

user_code = 503 if err else 200

# spans dikelompokin per service (resourceSpans terpisah = service.name beda di Jaeger)
services = {
  f"{stack}-order": [
    span(s_order, "POST /orders", 2, 0, 120+jit, None,
         {"http.method":"POST","http.route":"/orders","http.status_code": (503 if err else 201),"stack":stack}, status_ok=not err,
         err_msg=("upstream user service 503" if err else None)),
    span(s_c_user, "GET user-svc /users/{id}", 3, 5, 48, s_order,
         {"http.method":"GET","net.peer.name":f"{stack}-user","http.status_code":user_code}, status_ok=not err),
    span(s_c_prod, "GET product-svc /products/{id}", 3, 58, 57+jit, s_order,
         {"http.method":"GET","net.peer.name":f"{stack}-product","http.status_code":200}),
  ],
  f"{stack}-user": [
    span(s_user, "GET /users/{id}", 2, 8, 44, s_c_user,
         {"http.method":"GET","http.route":"/users/{id}","http.status_code":user_code,"stack":stack}, status_ok=not err,
         err_msg=("bcrypt pool exhausted" if err else None)),
    span(s_bcrypt, "bcrypt.compare (cost=10)", 1, 12, 36, s_user,
         {"component":"bcrypt","cpu.bound":"true"}),
  ],
  f"{stack}-product": [
    span(s_prod, "GET /products/{id}", 2, 60, 52+jit, s_c_prod,
         {"http.method":"GET","http.route":"/products/{id}","http.status_code":200,"stack":stack}),
    span(s_redis, "redis GET product:{id}", 3, 62, 6, s_prod,
         {"db.system":"redis","db.operation":"GET","cache.hit":"true"}),
    span(s_db, "SELECT products WHERE id=$1", 3, 72, 34+jit, s_prod,
         {"db.system":"postgresql","db.statement":"SELECT * FROM products WHERE id=$1"}),
  ],
}

resource_spans = []
for svc, spans in services.items():
    resource_spans.append({
        "resource":{"attributes":[
            {"key":"service.name","value":{"stringValue":svc}},
            {"key":"stack","value":{"stringValue":stack}},
        ]},
        "scopeSpans":[{"scope":{"name":"pas-thesis-demo"},"spans":spans}],
    })

payload = {"resourceSpans": resource_spans}
req = urllib.request.Request(otlp, data=json.dumps(payload).encode(),
                             headers={"content-type":"application/json"})
code = urllib.request.urlopen(req, timeout=5).status
tag = " \033[1;31m[ERROR 503]\033[0m" if err else ""
print(f"  \033[1;32m✓\033[0m trace {idx}: {tid}{tag}")
print(f"     → {jaeger_ui}/trace/{tid}")
PY
done

echo ""
echo "[trace] SELESAI. Buka Jaeger → pilih service '${STACK}-order' → Find Traces"
echo "        atau klik link /trace/<id> di atas langsung."
echo "        Jaeger UI: $JAEGER_UI"
