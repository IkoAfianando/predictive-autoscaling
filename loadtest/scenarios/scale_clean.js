import http from 'k6/http';
import { check, sleep } from 'k6';
const STACK = __ENV.STACK || 'go';
const PORTS = { go:{user:18001,product:18002,order:18003} };
const p = PORTS[STACK] || {user:18001,product:18002,order:18003};
const U=`http://localhost:${p.user}`, P=`http://localhost:${p.product}`, O=`http://localhost:${p.order}`;
export const options = {
  scenarios: { clean: { executor:'ramping-vus', startVUs:2, gracefulStop:'5s',
    stages:[
      {duration:'30s',target:10},
      {duration:'45s',target:70},
      {duration:'30s',target:130},   // spike -> scale up
      {duration:'60s',target:100},   // hold tinggi
      {duration:'45s',target:20},
      {duration:'30s',target:5},     // turun ke off-peak ringan
      {duration:'150s',target:5},    // sustain 5 VU -> measured P95 rendah -> scale down
    ] } },
  thresholds: {},
};
export default function () {
  const u=`u_${STACK}_${__VU}_${__ITER}`;
  http.post(`${U}/users/register`,JSON.stringify({username:u,password:'pw123'}),{headers:{'content-type':'application/json'}});
  http.post(`${U}/users/login`,JSON.stringify({username:u,password:'pw123'}),{headers:{'content-type':'application/json'}});
  http.post(`${P}/products`,JSON.stringify({name:'W',price:1.5}),{headers:{'content-type':'application/json'}});
  http.get(`${P}/products/1`);
  http.post(`${O}/orders`,JSON.stringify({user_id:1,product_id:1,qty:1}),{headers:{'content-type':'application/json'}});
  sleep(0.3);
}
