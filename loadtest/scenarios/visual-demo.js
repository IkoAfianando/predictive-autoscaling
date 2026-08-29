
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

const U = __ENV.BASE_USER    || 'http://localhost:18001';
const P = __ENV.BASE_PRODUCT || 'http://localhost:18002';
const O = __ENV.BASE_ORDER   || 'http://localhost:18003';

const TARGET    = parseInt(__ENV.TARGET || '80', 10);
const RAMP_UP   = __ENV.RAMP_UP   || '120s';
const HOLD      = __ENV.HOLD      || '60s';
const RAMP_DOWN = __ENV.RAMP_DOWN || '120s';

const e2e = new Trend('workload_e2e_ms', true);
const JSON_HEADERS = { headers: { 'content-type': 'application/json' } };

export const options = {
  scenarios: {
    demo: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: RAMP_UP,   target: TARGET },  // pods scale UP
        { duration: HOLD,      target: TARGET },  // hold at peak
        { duration: RAMP_DOWN, target: 0 },       // load falls -> pods scale DOWN
      ],
      gracefulStop: '5s',
    },
  },
  thresholds: {},
};

export default function () {
  const t0 = Date.now();
  const u = `u_${__VU}_${__ITER}_${Date.now()}`;

  const reg = http.post(`${U}/users/register`,
    JSON.stringify({ username: u, password: 'pw123' }), JSON_HEADERS);
  check(reg, { 'register ok': (r) => [200, 201, 409].includes(r.status) });
  let userId = 1;
  try { userId = reg.json('id') || 1; } catch (_) { userId = 1; }

  const login = http.post(`${U}/users/login`,
    JSON.stringify({ username: u, password: 'pw123' }), JSON_HEADERS);
  check(login, { 'login ok': (r) => [200, 401].includes(r.status) });

  const prod = http.post(`${P}/products`,
    JSON.stringify({ name: 'W', price: 1.5 }), JSON_HEADERS);
  let productId = 1;
  try { productId = prod.json('id') || 1; } catch (_) { productId = 1; }

  http.get(`${P}/products/${productId}`);

  http.post(`${O}/orders`,
    JSON.stringify({ user_id: userId, product_id: productId, qty: 1 }), JSON_HEADERS);

  e2e.add(Date.now() - t0);
  sleep(0.3);
}
