
import { runWorkload, resolveBaseUrls } from '../lib/workload.js';

const BASE_URLS = resolveBaseUrls();

export const options = {
  scenarios: {
    soak: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 30 },    // ramp to soak level
        { duration: '36m', target: 30 },   // sustain
        { duration: '2m', target: 0 },     // ramp down
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<2000', 'p(99)<4000'],
    http_req_failed: ['rate<0.05'],
    workload_duration: ['p(95)<10000'],
    checks: ['rate>0.95'],
  },
  tags: { scenario: 'soak', stack: BASE_URLS.stack },
};

export default function () {
  runWorkload(BASE_URLS);
}
