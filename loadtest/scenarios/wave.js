import http from 'k6/http';
import { check, sleep } from 'k6';
const STACK = __ENV.STACK || 'go';
const PORTS = {
  go:{user:8001,product:8002,order:8003}, rust:{user:8011,product:8012,order:8013},
  java:{user:8021,product:8022,order:8023}, node:{user:8031,product:8032,order:8033},
};
const p = PORTS[STACK];
const U=`http://localhost:${p.user}`, P=`http://localhost:${p.product}`, O=`http://localhost:${p.order}`;
export const options = {
  scenarios: { wave: { executor:'ramping-vus', startVUs:5, gracefulStop:'5s',
    stages:[
      {duration:'60s',target:15},{duration:'60s',target:45},{duration:'60s',target:15},  // gentle wave
      {duration:'45s',target:70},{duration:'45s',target:20},                              // bigger wave
      {duration:'30s',target:120},{duration:'30s',target:10},                             // spike + drop
      {duration:'60s',target:35},{duration:'60s',target:60},{duration:'60s',target:15},   // sustained wave
      {duration:'45s',target:5},                                                          // cooldown
    ] } },
  thresholds: {},
};
export default function () {
  const u=`u_${STACK}_${__VU}_${__ITER}`;
  const r=http.post(`${U}/users/register`,JSON.stringify({username:u,password:'pw123'}),{headers:{'content-type':'application/json'}});
  check(r,{'reg':(x)=>[200,201,409].includes(x.status)});
  http.post(`${U}/users/login`,JSON.stringify({username:u,password:'pw123'}),{headers:{'content-type':'application/json'}});
  http.post(`${P}/products`,JSON.stringify({name:'W',price:1.5}),{headers:{'content-type':'application/json'}});
  http.get(`${P}/products/1`);
  http.post(`${O}/orders`,JSON.stringify({user_id:1,product_id:1,qty:1}),{headers:{'content-type':'application/json'}});
  sleep(0.3);
}
