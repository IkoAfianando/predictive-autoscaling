
import { runWorkload, resolveBaseUrls } from '../lib/workload.js';

const BASE_URLS = resolveBaseUrls();

export const options = {
  scenarios: {
    spike: {
      executor: 'ramping-vus',
      startVUs: 20,
      stages: [
        { duration: '1m', target: 20 },     // steady baseline
        { duration: '10s', target: 200 },   // sudden spike
        { duration: '2m30s', target: 200 }, // sustain the spike
        { duration: '10s', target: 20 },    // sudden drop
        { duration: '1m', target: 20 },     // recovery baseline
        { duration: '40s', target: 0 },     // ramp down
      ], // total = 5.5 min
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<4000'],
    http_req_failed: ['rate<0.15'],
    workload_duration: ['p(95)<15000'],
    checks: ['rate>0.85'],
  },
  tags: { scenario: 'spike', stack: BASE_URLS.stack },
};

export default function () {
  runWorkload(BASE_URLS);
}
