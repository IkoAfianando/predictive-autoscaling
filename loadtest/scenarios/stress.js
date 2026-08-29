
import { runWorkload, resolveBaseUrls } from '../lib/workload.js';

const BASE_URLS = resolveBaseUrls();

export const options = {
  scenarios: {
    stress: {
      executor: 'ramping-vus',
      startVUs: 50,
      stages: [
        { duration: '2m', target: 200 },   // beyond normal
        { duration: '2m', target: 400 },
        { duration: '2m', target: 600 },
        { duration: '2m', target: 800 },
        { duration: '2m', target: 1000 },  // peak stress
        { duration: '2m', target: 1000 },  // hold at peak
        { duration: '1m', target: 0 },     // recover
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<5000'],
    http_req_failed: ['rate<0.25'],
    workload_duration: ['p(95)<20000'],
    checks: ['rate>0.75'],
  },
  tags: { scenario: 'stress', stack: BASE_URLS.stack },
};

export default function () {
  runWorkload(BASE_URLS);
}
