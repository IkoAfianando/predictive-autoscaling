
import { runWorkload, resolveBaseUrls, resolveSub } from './common.js';

const BASE_URLS = resolveBaseUrls();
const SUB = resolveSub();

const PEAK = parseInt(__ENV.PEAK || '120', 10);
const HOLD = __ENV.HOLD || '1m';

const RAMP_BY_SUB = {
  1: '4m',
  2: '2m30s',
  3: '1m30s',
  4: '45s',
};
const RAMP = __ENV.RAMP || RAMP_BY_SUB[SUB];
const RATE_LABEL = { 1: 'gentle', 2: 'medium', 3: 'brisk', 4: 'steep' }[SUB];

export const options = {
  scenarios: {
    daily_peak: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: RAMP, target: PEAK },  // gradual build-up to peak
        { duration: HOLD, target: PEAK },  // hold at daily peak
        { duration: RAMP, target: 0 },     // gradual decline
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.10'],
    workload_duration: ['p(95)<12000'],
  },
  tags: {
    scenario: 's2_daily_peak',
    sub: String(SUB),
    ramp_rate: RATE_LABEL,
    stack: BASE_URLS.stack,
  },
};

export default function () {
  runWorkload(BASE_URLS);
}
