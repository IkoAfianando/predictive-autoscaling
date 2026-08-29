
import { runWorkload, resolveBaseUrls, resolveSub } from './common.js';

const BASE_URLS = resolveBaseUrls();
const SUB = resolveSub();

const MULT_BY_SUB = { 1: 5, 2: 10, 3: 20, 4: 50 };
const MULT = MULT_BY_SUB[SUB];

const BASE = parseInt(__ENV.BASE || '10', 10);
const SPIKE = BASE * MULT;

const BASELINE_HOLD = __ENV.BASELINE_HOLD || '1m';
const SPIKE_RISE    = __ENV.SPIKE_RISE    || '15s';
const SPIKE_HOLD    = __ENV.SPIKE_HOLD    || '2m';
const SPIKE_FALL    = __ENV.SPIKE_FALL    || '15s';
const RECOVER_HOLD  = __ENV.RECOVER_HOLD  || '1m';
const RAMP_DOWN     = __ENV.RAMP_DOWN     || '30s';

export const options = {
  scenarios: {
    flash_sale: {
      executor: 'ramping-vus',
      startVUs: BASE,
      stages: [
        { duration: BASELINE_HOLD, target: BASE },   // steady baseline
        { duration: SPIKE_RISE,    target: SPIKE },   // sudden flash-sale spike
        { duration: SPIKE_HOLD,    target: SPIKE },   // sustain the spike
        { duration: SPIKE_FALL,    target: BASE },    // sudden drop
        { duration: RECOVER_HOLD,  target: BASE },    // recovery baseline
        { duration: RAMP_DOWN,     target: 0 },       // ramp down
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<4000'],
    http_req_failed: ['rate<0.20'],
    workload_duration: ['p(95)<15000'],
  },
  tags: {
    scenario: 's1_flash_sale',
    sub: String(SUB),
    magnitude: `${MULT}x`,
    stack: BASE_URLS.stack,
  },
};

export default function () {
  runWorkload(BASE_URLS);
}
