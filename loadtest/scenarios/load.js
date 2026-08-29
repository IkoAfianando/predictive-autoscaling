
import { runWorkload, resolveBaseUrls } from '../lib/workload.js';

const BASE_URLS = resolveBaseUrls();

export const options = {
  scenarios: {
    load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 50 },   // warm up to half
        { duration: '3m', target: 100 },  // ramp to peak
        { duration: '4m', target: 100 },  // hold at peak
        { duration: '1m', target: 0 },    // ramp down
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<1500', 'p(99)<3000'],
    http_req_failed: ['rate<0.05'],
    workload_duration: ['p(95)<8000'],
    workload_errors: ['count<100'],
    checks: ['rate>0.95'],
  },
  tags: { scenario: 'load', stack: BASE_URLS.stack },
};

export default function () {
  runWorkload(BASE_URLS);
}
