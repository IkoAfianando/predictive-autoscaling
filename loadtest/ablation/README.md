# Ablation Study Harness (k6)

Harness beban k6 untuk **ablation study** skripsi *Machine Learning-Based
Predictive Auto-Scaling for Microservices*. Tujuannya menghasilkan data latih /
evaluasi terkontrol: **4 skenario pola beban e-commerce × 4 sub-skenario = 16
pengujian** per stack, dijalankan terhadap cluster Kubernetes yang sedang
di-scale oleh predictive controller.

Semua script konsisten dengan sistem yang ada:
- workload 5-langkah yang sama seperti `loadtest/lib/workload.js`
  (register → login → create product → get product → create order),
- port target = layout **port-forward** dari `loadtest/pf_keeper.sh`
  (`1800x` go / `1801x` rust / `1802x` java / `1803x` node → pod `:8080`),
  sama seperti `loadtest/scenarios/allstacks-demo.js`,
- metrik custom bernama sama (`workload_duration`, `step_*_duration`,
  `workload_errors`) sehingga pipeline ML memperlakukan run ablation identik
  dengan run demo.

---

## Isi folder

| File | Fungsi |
|---|---|
| `common.js` | Modul bersama: port map port-forward, `resolveBaseUrls()`, `resolveSub()`, metrik custom, dan `runWorkload()`. |
| `s1_flash_sale.js` | **S1 Flash-Sale (spike)** — lonjakan mendadak. |
| `s2_daily_peak.js` | **S2 Daily-Peak (load/ramp)** — naik bertahap lalu turun. |
| `s3_payday_soak.js` | **S3 Payday-Soak (soak)** — beban tinggi datar berdurasi panjang. |
| `s4_viral_stress.js` | **S4 Viral-Stress (stress)** — eskalasi sampai jenuh. |
| `run_ablation.sh` | Runner: menjalankan ke-16 kombinasi untuk satu stack + menangkap log lengkap. |

Output log semua run masuk ke:
`../../2026-08-28_e2e-ablation-training/logs/`

---

## Prasyarat (HARUS sudah jalan — runner TIDAK menyalakannya)

Ablation menjalankan beban NYATA (`k6 run`) terhadap cluster hidup. Jangan
dijalankan saat cluster sedang dipakai proses lain. Nyalakan dulu:

```bash
# 1. Cluster + namespace pas-thesis + stack target ter-deploy
kubectl apply -k infra/k8s/demo-allstacks     # semua 4 stack (atau .../demo utk go saja)

# 2. Port-forward user/product/order tiap stack + prometheus (13 forward)
bash loadtest/pf_keeper.sh &

# 3. ML serve (forecast P95 live dari prometheus in-cluster)
PROMETHEUS_URL=http://localhost:9092 ml/.venv/bin/python ml/serve.py &

# 4. Predictive controller yang mengelola stack target
#    (lihat loadtest/run_allstacks_demo.sh untuk blok env lengkap:
#     MANAGED_STACKS, PREDICT_URL, threshold per-stack, dst.)
DRY_RUN=false NAMESPACE=pas-thesis MANAGED_STACKS=go \
  PREDICT_URL=http://localhost:8000/predict INTERVAL_SECONDS=10 \
  MIN_REPLICAS=1 MAX_REPLICAS=4 \
  ml/.venv/bin/python controller/predictive_controller.py &
```

Cek cepat sebelum mulai: `curl localhost:18001/health` (go-user) harus 200.
Port referensi lengkap ada di `PORTS.md`.

---

## Cara menjalankan

### Satu pengujian (satu skenario, satu sub) — verifikasi cepat
```bash
# S1 Flash-Sale, sub 2 (spike 10x), stack go
k6 run -e STACK=go -e SUB=2 loadtest/ablation/s1_flash_sale.js
```

### Semua 16 kombinasi untuk satu stack (via runner)
```bash
STACK=go bash loadtest/ablation/run_ablation.sh
```

### Opsi runner (semua lewat env var)
```bash
STACK=rust  bash loadtest/ablation/run_ablation.sh     # stack lain
ONLY=s1,s3  bash loadtest/ablation/run_ablation.sh      # subset skenario
SUBS=1,2    bash loadtest/ablation/run_ablation.sh      # subset sub-skenario
IDLE_TAIL=180 bash loadtest/ablation/run_ablation.sh    # jeda idle antar-run (detik)
SOAK_HOLD=5m  bash loadtest/ablation/run_ablation.sh    # perpendek soak S3
DRY_RUN=1   bash loadtest/ablation/run_ablation.sh      # cetak rencana, tidak menjalankan apa pun
```

`IDLE_TAIL` (default 120s) memberi jeda tanpa beban setelah tiap run supaya
controller sempat scale-down kembali ke baseline sebelum run berikutnya.

### Cek sintaks tanpa mengirim beban
```bash
k6 inspect -e STACK=go -e SUB=1 loadtest/ablation/s1_flash_sale.js
```
`k6 inspect` hanya meng-evaluasi opsi (stages/threshold) — **tidak** mengirim
request.

---

## Makna skenario & sub-skenario

Baseline/level default di bawah bisa dioverride lewat env (kolom "override").

### S1 — Flash-Sale (spike) · `s1_flash_sale.js`
Lonjakan mendadak seperti flash sale. Profil: baseline → naik ~15s ke puncak →
tahan → jatuh → pulih. Sub mengubah **magnitude** puncak (kelipatan baseline
`BASE`, default 10 VU).

| SUB | Magnitude | Target puncak (BASE=10) | Override |
|---|---|---|---|
| 1 | 5× | 50 VU | `BASE`, `SPIKE_HOLD`, ... |
| 2 | 10× | 100 VU | |
| 3 | 20× | 200 VU | |
| 4 | 50× | 500 VU | |

### S2 — Daily-Peak (load/ramp) · `s2_daily_peak.js`
Kurva harian: naik bertahap ke `PEAK` (default 120 VU), tahan, lalu turun
bertahap. Sub mengubah **laju ramp** (landai → curam), puncak tetap.

| SUB | Laju | Durasi ramp naik/turun | Override |
|---|---|---|---|
| 1 | gentle (landai) | 4m / 4m | `PEAK`, `HOLD`, `RAMP` |
| 2 | medium | 2m30s / 2m30s | |
| 3 | brisk | 1m30s / 1m30s | |
| 4 | steep (curam) | 45s / 45s | |

### S3 — Payday-Soak (soak) · `s3_payday_soak.js`
Beban tinggi **datar berdurasi panjang**. Profil: ramp-up 2m → tahan
`SOAK_HOLD` (default **20m**) → ramp-down 2m. Sub mengubah **level beban**.

| SUB | Level | Override |
|---|---|---|
| 1 | 50 VU | `LEVEL`, `SOAK_HOLD`, `RAMP_UP`, `RAMP_DOWN` |
| 2 | 100 VU | |
| 3 | 200 VU | |
| 4 | 400 VU | |

> Total S3 default ≈ 4×24m. Untuk smoke test cepat pakai `SOAK_HOLD=5m`.

### S4 — Viral-Stress (stress) · `s4_viral_stress.js`
Eskalasi bertahap (5 tangga, 2m/tangga) sampai **titik jenuh** `CEIL`, tahan 2m,
lalu pulih. Sub mengubah titik jenuh. Threshold bersifat informational (tujuan =
mengamati degradasi, bukan lulus).

| SUB | Titik jenuh | Override |
|---|---|---|
| 1 | 200 VU | `CEIL`, `STEP_DUR`, `PEAK_HOLD` |
| 2 | 400 VU | |
| 3 | 600 VU | |
| 4 | 1000 VU | |

---

## Struktur output log

Runner menulis, per run, ke `2026-08-28_e2e-ablation-training/logs/` dengan pola
nama `s<N>_<scenario>_sub<S>_<stack>_<timestamp>`:

| File | Isi |
|---|---|
| `..._<ts>.log` | **Full stdout+stderr k6** — laporan run lengkap (ringkasan metrik, checks, threshold). |
| `..._<ts>.summary.json` | **JSON summary** dari flag k6 `--summary-export` — metrik machine-readable untuk analisis. |
| `..._<ts>.meta.json` | **Metadata run**: run_id, scenario, sub, stack, script, started_at/ended_at, exit_code, versi k6, env override. |

Plus satu indeks per invocation runner:
`ablation_index_<stack>_<run_id>.csv`
(kolom: `scenario,sub,stack,timestamp,log,summary,meta,exit_code,started_at,ended_at`).

Contoh:
```
2026-08-28_e2e-ablation-training/logs/
  s1_flash_sale_sub2_go_20260828_181500.log
  s1_flash_sale_sub2_go_20260828_181500.summary.json
  s1_flash_sale_sub2_go_20260828_181500.meta.json
  ...
  ablation_index_go_20260828_181455.csv
```

Catatan exit code k6: `0` = sukses, `99` = ada threshold yang terlampaui
(tetap dicatat, bukan kegagalan — run ablation bersifat observasional), lainnya =
error k6 (lihat `.log`).
