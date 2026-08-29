import { runWorkload, resolveBaseUrls } from '../lib/workload.js';

const BASE_URLS = resolveBaseUrls();
const SCEN = (__ENV.SCEN || 'load').toLowerCase();

const START = { spike: 20, stress: 50, soak: 0, load: 0 };
const STAGES = {
  spike: [
    { duration: '45s', target: 20 },
    { duration: '5s', target: 200 },
    { duration: '2m30s', target: 200 },
    { duration: '5s', target: 20 },
    { duration: '45s', target: 20 },
    { duration: '20s', target: 0 },
  ],
  stress: [
    { duration: '40s', target: 150 },
    { duration: '40s', target: 300 },
    { duration: '40s', target: 450 },
    { duration: '40s', target: 600 },
    { duration: '40s', target: 800 },
    { duration: '30s', target: 800 },
    { duration: '20s', target: 0 },
  ],
  soak: [
    { duration: '20s', target: 30 },
    { duration: '4m', target: 30 },
    { duration: '20s', target: 0 },
  ],
  load: [
    { duration: '1m', target: 40 },
    { duration: '1m30s', target: 100 },
    { duration: '1m30s', target: 100 },
    { duration: '30s', target: 0 },
  ],
};

export const options = {
  scenarios: {
    [SCEN]: {
      executor: 'ramping-vus',
      startVUs: START[SCEN],
      stages: STAGES[SCEN],
      gracefulRampDown: '20s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<10000'],
  },
  tags: { scenario: SCEN, stack: BASE_URLS.stack },
};

export default function () {
  runWorkload(BASE_URLS);
}
