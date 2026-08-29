
import { runWorkload, resolveBaseUrls, resolveSub } from './common.js';

const BASE_URLS = resolveBaseUrls();
const SUB = resolveSub();

const LEVEL_BY_SUB = { 1: 50, 2: 100, 3: 200, 4: 400 };
const LEVEL = parseInt(__ENV.LEVEL || String(LEVEL_BY_SUB[SUB]), 10);

const RAMP_UP   = __ENV.RAMP_UP   || '2m';
const SOAK_HOLD = __ENV.SOAK_HOLD || '20m';
const RAMP_DOWN = __ENV.RAMP_DOWN || '2m';

export const options = {
  scenarios: {
    payday_soak: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: RAMP_UP,   target: LEVEL },  // ramp to soak level
        { duration: SOAK_HOLD, target: LEVEL },  // long flat sustain
        { duration: RAMP_DOWN, target: 0 },      // ramp down
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000', 'p(99)<6000'],
    http_req_failed: ['rate<0.10'],
    workload_duration: ['p(95)<12000'],
  },
  tags: {
    scenario: 's3_payday_soak',
    sub: String(SUB),
    level_vu: String(LEVEL),
    stack: BASE_URLS.stack,
  },
};

export default function () {
  runWorkload(BASE_URLS);
}
