import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';
const STACK = __ENV.STACK || 'go';
const PORTS = {
  go:   { user: 8001, product: 8002, order: 8003 },
  rust: { user: 8011, product: 8012, order: 8013 },
  java: { user: 8021, product: 8022, order: 8023 },
  node: { user: 8031, product: 8032, order: 8033 },
};
const p = PORTS[STACK];
const U = `http://localhost:${p.user}`, P = `http://localhost:${p.product}`, O = `http://localhost:${p.order}`;
const e2e = new Trend('workload_e2e_ms', true);
export const options = {
  scenarios: { ramp: { executor: 'ramping-vus', startVUs: 5,
    stages: [ { duration: '15s', target: 40 }, { duration: '30s', target: 80 }, { duration: '15s', target: 10 } ],
    gracefulStop: '5s' } },
  thresholds: { http_req_failed: ['rate<0.30'] },
};
export default function () {
  const t0 = Date.now();
  const u = `u_${STACK}_${__VU}_${__ITER}`;
  const reg = http.post(`${U}/users/register`, JSON.stringify({ username: u, password: 'pw123' }), { headers: { 'content-type': 'application/json' } });
  check(reg, { 'register ok': (r) => [200,201,409].includes(r.status) });
  const login = http.post(`${U}/users/login`, JSON.stringify({ username: u, password: 'pw123' }), { headers: { 'content-type': 'application/json' } });
  check(login, { 'login ok': (r) => [200,401].includes(r.status) });
  http.post(`${P}/products`, JSON.stringify({ name: 'W', price: 1.5 }), { headers: { 'content-type': 'application/json' } });
  http.get(`${P}/products/1`);
  http.post(`${O}/orders`, JSON.stringify({ user_id: 1, product_id: 1, qty: 1 }), { headers: { 'content-type': 'application/json' } });
  e2e.add(Date.now() - t0);
  sleep(0.3);
}
