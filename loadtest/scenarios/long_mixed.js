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
  scenarios: { mixed: { executor:'ramping-vus', startVUs:5, gracefulStop:'5s',
    stages:[
      {duration:'45s',target:10},                                  // warm
      {duration:'60s',target:30},{duration:'60s',target:10},        // gentle wave
      {duration:'30s',target:150},{duration:'30s',target:10},       // FLASH SALE spike 1
      {duration:'120s',target:60},                                  // soak plateau
      {duration:'30s',target:200},{duration:'30s',target:10},       // FLASH SALE spike 2 (bigger)
      {duration:'90s',target:80},{duration:'90s',target:20},        // sustained wave
      {duration:'30s',target:250},{duration:'45s',target:10},       // FLASH SALE spike 3 (huge)
      {duration:'60s',target:100},{duration:'60s',target:180},
      {duration:'60s',target:260},{duration:'45s',target:10},       // stress escalation -> saturasi
      {duration:'90s',target:70},                                   // sustained
      {duration:'45s',target:5},                                    // cooldown
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
