
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

export const PF_PORT_MAP = {
  go:   { user: 18001, product: 18002, order: 18003 },
  rust: { user: 18011, product: 18012, order: 18013 },
  java: { user: 18021, product: 18022, order: 18023 },
  node: { user: 18031, product: 18032, order: 18033 },
};

export const HOST = __ENV.HOST || 'localhost';

export const workloadDuration   = new Trend('workload_duration', true);
export const registerDuration   = new Trend('step_register_duration', true);
export const loginDuration       = new Trend('step_login_duration', true);
export const productPostDuration = new Trend('step_product_post_duration', true);
export const productGetDuration  = new Trend('step_product_get_duration', true);
export const orderDuration       = new Trend('step_order_duration', true);
export const workloadErrors      = new Counter('workload_errors');

/**
 */
export function resolveBaseUrls() {
  const stack = (__ENV.STACK || 'go').toLowerCase();
  const ports = PF_PORT_MAP[stack];
  if (!ports) {
    throw new Error(
      `Unknown STACK "${stack}". Expected one of: ${Object.keys(PF_PORT_MAP).join(', ')}`
    );
  }
  return {
    stack,
    user:    __ENV.BASE_USER    || `http://${HOST}:${ports.user}`,
    product: __ENV.BASE_PRODUCT || `http://${HOST}:${ports.product}`,
    order:   __ENV.BASE_ORDER   || `http://${HOST}:${ports.order}`,
  };
}

/**
 */
export function resolveSub() {
  const sub = parseInt(__ENV.SUB || '1', 10);
  if (!Number.isInteger(sub) || sub < 1 || sub > 4) {
    throw new Error(`Invalid SUB "${__ENV.SUB}". Expected an integer 1..4.`);
  }
  return sub;
}

function uniqueUsername(stack) {
  const vu = (typeof __VU !== 'undefined') ? __VU : 0;
  const iter = (typeof __ITER !== 'undefined') ? __ITER : 0;
  return `abl_${stack}_${vu}_${iter}_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
}

const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' } };

const THINK = parseFloat(__ENV.THINK || '1');

/**
 */
export function runWorkload(baseUrls) {
  const start = Date.now();
  const stackTag = { stack: baseUrls.stack };

  const username = uniqueUsername(baseUrls.stack);
  const password = 'P@ssw0rd-ablation';

  const regRes = http.post(
    `${baseUrls.user}/users/register`,
    JSON.stringify({ username, password }),
    { ...JSON_HEADERS, tags: { ...stackTag, step: 'register' } }
  );
  registerDuration.add(regRes.timings.duration, stackTag);
  const regOk = check(regRes, {
    'register status 2xx/409': (r) => [200, 201, 409].includes(r.status),
  });
  if (!regOk) workloadErrors.add(1, stackTag);
  let userId = 1;
  try { userId = regRes.json('id') || 1; } catch (_) { userId = 1; }

  const loginRes = http.post(
    `${baseUrls.user}/users/login`,
    JSON.stringify({ username, password }),
    { ...JSON_HEADERS, tags: { ...stackTag, step: 'login' } }
  );
  loginDuration.add(loginRes.timings.duration, stackTag);
  const loginOk = check(loginRes, {
    'login status 200/401': (r) => [200, 401].includes(r.status),
  });
  if (!loginOk) workloadErrors.add(1, stackTag);

  const prodRes = http.post(
    `${baseUrls.product}/products`,
    JSON.stringify({ name: `widget-${username}`, price: 19.99 }),
    { ...JSON_HEADERS, tags: { ...stackTag, step: 'product_post' } }
  );
  productPostDuration.add(prodRes.timings.duration, stackTag);
  const prodOk = check(prodRes, {
    'product create 2xx': (r) => [200, 201].includes(r.status),
  });
  if (!prodOk) workloadErrors.add(1, stackTag);
  let productId = 1;
  try { productId = prodRes.json('id') || 1; } catch (_) { productId = 1; }

  for (let i = 0; i < 2; i++) {
    const getRes = http.get(`${baseUrls.product}/products/${productId}`, {
      tags: { ...stackTag, step: 'product_get' },
    });
    productGetDuration.add(getRes.timings.duration, stackTag);
    const getOk = check(getRes, { 'product get 200': (r) => r.status === 200 });
    if (!getOk) workloadErrors.add(1, stackTag);
  }

  const orderRes = http.post(
    `${baseUrls.order}/orders`,
    JSON.stringify({ user_id: userId, product_id: productId, qty: 2 }),
    { ...JSON_HEADERS, tags: { ...stackTag, step: 'order' } }
  );
  orderDuration.add(orderRes.timings.duration, stackTag);
  const orderOk = check(orderRes, {
    'order create 2xx': (r) => [200, 201].includes(r.status),
  });
  if (!orderOk) workloadErrors.add(1, stackTag);

  workloadDuration.add(Date.now() - start, stackTag);
  if (THINK > 0) sleep(THINK);
}

export default runWorkload;
