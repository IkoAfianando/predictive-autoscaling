
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

export const PORT_MAP = {
  go:   { user: 8001, product: 8002, order: 8003 },
  rust: { user: 8011, product: 8012, order: 8013 },
  java: { user: 8021, product: 8022, order: 8023 },
  node: { user: 8031, product: 8032, order: 8033 },
};

export const HOST = __ENV.HOST || 'localhost';

export const workloadDuration = new Trend('workload_duration', true);
export const registerDuration = new Trend('step_register_duration', true);
export const loginDuration    = new Trend('step_login_duration', true);
export const productPostDuration = new Trend('step_product_post_duration', true);
export const productGetDuration  = new Trend('step_product_get_duration', true);
export const orderDuration    = new Trend('step_order_duration', true);
export const workloadErrors   = new Counter('workload_errors');

/**
 */
export function resolveBaseUrls() {
  const stack = (__ENV.STACK || 'go').toLowerCase();
  const ports = PORT_MAP[stack];
  if (!ports) {
    throw new Error(
      `Unknown STACK "${stack}". Expected one of: ${Object.keys(PORT_MAP).join(', ')}`
    );
  }
  return {
    stack,
    user:    `http://${HOST}:${ports.user}`,
    product: `http://${HOST}:${ports.product}`,
    order:   `http://${HOST}:${ports.order}`,
  };
}

function uniqueUsername() {
  const vu = (typeof __VU !== 'undefined') ? __VU : 0;
  const iter = (typeof __ITER !== 'undefined') ? __ITER : 0;
  return `u_${vu}_${iter}_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
}

const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' } };

/**
 */
export function runWorkload(baseUrls) {
  const start = Date.now();
  const stackTag = { stack: baseUrls.stack };

  const username = uniqueUsername();
  const password = 'P@ssw0rd-load-test';

  const regRes = http.post(
    `${baseUrls.user}/users/register`,
    JSON.stringify({ username, password }),
    { ...JSON_HEADERS, tags: { ...stackTag, step: 'register' } }
  );
  registerDuration.add(regRes.timings.duration, stackTag);
  const regOk = check(regRes, {
    'register status 200/201': (r) => r.status === 200 || r.status === 201,
    'register returned id': (r) => {
      try { return r.json('id') !== undefined && r.json('id') !== null; }
      catch (_) { return false; }
    },
  });
  if (!regOk) workloadErrors.add(1, stackTag);

  let userId;
  try { userId = regRes.json('id'); } catch (_) { userId = undefined; }

  const loginRes = http.post(
    `${baseUrls.user}/users/login`,
    JSON.stringify({ username, password }),
    { ...JSON_HEADERS, tags: { ...stackTag, step: 'login' } }
  );
  loginDuration.add(loginRes.timings.duration, stackTag);
  const loginOk = check(loginRes, {
    'login status 200': (r) => r.status === 200,
    'login returned token': (r) => {
      try { return !!r.json('token'); } catch (_) { return false; }
    },
  });
  if (!loginOk) workloadErrors.add(1, stackTag);

  const prodRes = http.post(
    `${baseUrls.product}/products`,
    JSON.stringify({ name: `widget-${username}`, price: 19.99 }),
    { ...JSON_HEADERS, tags: { ...stackTag, step: 'product_post' } }
  );
  productPostDuration.add(prodRes.timings.duration, stackTag);
  const prodOk = check(prodRes, {
    'product create 200/201': (r) => r.status === 200 || r.status === 201,
    'product returned id': (r) => {
      try { return r.json('id') !== undefined && r.json('id') !== null; }
      catch (_) { return false; }
    },
  });
  if (!prodOk) workloadErrors.add(1, stackTag);

  let productId;
  try { productId = prodRes.json('id'); } catch (_) { productId = undefined; }

  if (productId !== undefined && productId !== null) {
    for (let i = 0; i < 2; i++) {
      const getRes = http.get(`${baseUrls.product}/products/${productId}`, {
        tags: { ...stackTag, step: 'product_get' },
      });
      productGetDuration.add(getRes.timings.duration, stackTag);
      const getOk = check(getRes, {
        'product get 200': (r) => r.status === 200,
      });
      if (!getOk) workloadErrors.add(1, stackTag);
    }
  }

  if (userId !== undefined && userId !== null &&
      productId !== undefined && productId !== null) {
    const orderRes = http.post(
      `${baseUrls.order}/orders`,
      JSON.stringify({ user_id: userId, product_id: productId, qty: 2 }),
      { ...JSON_HEADERS, tags: { ...stackTag, step: 'order' } }
    );
    orderDuration.add(orderRes.timings.duration, stackTag);
    const orderOk = check(orderRes, {
      'order create 200/201': (r) => r.status === 200 || r.status === 201,
      'order returned id': (r) => {
        try { return r.json('id') !== undefined && r.json('id') !== null; }
        catch (_) { return false; }
      },
    });
    if (!orderOk) workloadErrors.add(1, stackTag);
  }

  workloadDuration.add(Date.now() - start, stackTag);
  sleep(1);
}

export default runWorkload;
