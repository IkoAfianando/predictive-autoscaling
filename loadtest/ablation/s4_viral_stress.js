
import { runWorkload, resolveBaseUrls, resolveSub } from './common.js';

const BASE_URLS = resolveBaseUrls();
const SUB = resolveSub();

const CEIL_BY_SUB = { 1: 200, 2: 400, 3: 600, 4: 1000 };
const CEIL = parseInt(__ENV.CEIL || String(CEIL_BY_SUB[SUB]), 10);

const STEP_DUR    = __ENV.STEP_DUR    || '2m';
const PEAK_HOLD   = __ENV.PEAK_HOLD   || '2m';
const RECOVER_DUR = __ENV.RECOVER_DUR || '1m';

const step = Math.max(1, Math.round(CEIL / 5));
const stages = [
  { duration: STEP_DUR, target: step * 1 },
  { duration: STEP_DUR, target: step * 2 },
  { duration: STEP_DUR, target: step * 3 },
  { duration: STEP_DUR, target: step * 4 },
  { duration: STEP_DUR, target: CEIL },       // reach saturation point
  { duration: PEAK_HOLD, target: CEIL },      // hold at saturation
  { duration: RECOVER_DUR, target: 0 },       // recover
];

export const options = {
  scenarios: {
    viral_stress: {
      executor: 'ramping-vus',
      startVUs: step,
      stages,
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<6000'],
    http_req_failed: ['rate<0.30'],
    workload_duration: ['p(95)<25000'],
  },
  tags: {
    scenario: 's4_viral_stress',
    sub: String(SUB),
    saturation_vu: String(CEIL),
    stack: BASE_URLS.stack,
  },
};

export default function () {
  runWorkload(BASE_URLS);
}
