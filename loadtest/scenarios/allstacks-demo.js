
import http from 'k6/http';
import { check, sleep } from 'k6';

const SVC = {
  go:   { u: 'http://localhost:18001', p: 'http://localhost:18002', o: 'http://localhost:18003' },
  rust: { u: 'http://localhost:18011', p: 'http://localhost:18012', o: 'http://localhost:18013' },
  java: { u: 'http://localhost:18021', p: 'http://localhost:18022', o: 'http://localhost:18023' },
  node: { u: 'http://localhost:18031', p: 'http://localhost:18032', o: 'http://localhost:18033' },
};

const TARGET = parseInt(__ENV.TARGET || '70', 10);
const RAMP_UP = __ENV.RAMP_UP || '45s';
const HOLD = __ENV.HOLD || '35s';
const RAMP_DOWN = __ENV.RAMP_DOWN || '15s';
const JSON_HEADERS = { headers: { 'content-type': 'application/json' } };

function scn(startTime, stack) {
  return {
    executor: 'ramping-vus',
    startVUs: 0,
    startTime,
    stages: [
      { duration: RAMP_UP, target: TARGET },
      { duration: HOLD, target: TARGET },
      { duration: RAMP_DOWN, target: 0 },
    ],
    gracefulStop: '3s',
    exec: 'hit',
    env: { STACK: stack },
  };
}

export const options = {
  scenarios: {
    go:   scn('0s',  'go'),
    rust: scn('35s', 'rust'),
    java: scn('70s', 'java'),
    node: scn('105s', 'node'),
  },
  thresholds: {}, // saturation demo, not an SLO gate
};

export function hit() {
  const s = SVC[__ENV.STACK];
  const u = `u_${__ENV.STACK}_${__VU}_${__ITER}_${Date.now()}`;
  const reg = http.post(`${s.u}/users/register`,
    JSON.stringify({ username: u, password: 'pw123' }), JSON_HEADERS);
  check(reg, { 'register ok': (r) => [200, 201, 409].includes(r.status) });
  let userId = 1; try { userId = reg.json('id') || 1; } catch (_) {}
  http.post(`${s.u}/users/login`,
    JSON.stringify({ username: u, password: 'pw123' }), JSON_HEADERS);
  const prod = http.post(`${s.p}/products`,
    JSON.stringify({ name: 'W', price: 1.5 }), JSON_HEADERS);
  let productId = 1; try { productId = prod.json('id') || 1; } catch (_) {}
  http.get(`${s.p}/products/${productId}`);
  http.post(`${s.o}/orders`,
    JSON.stringify({ user_id: userId, product_id: productId, qty: 1 }), JSON_HEADERS);
  sleep(0.25);
}
