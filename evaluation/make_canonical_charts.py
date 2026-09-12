#!/usr/bin/env python3
"""Regenerate every forecasting chart from the canonical evaluation outputs."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = "/Users/ikoafian/LEARN/RISET/predictive-autoscaling-thesis/2026-09-12_paper-revisi"
D = f"{OUT}/data"
STACKS = ["go", "rust", "java", "node"]


def rd(name):
    with open(f"{D}/{name}") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------- 1. four-model compare
summ = {(r["model"], r["stack"]): (float(r["rmse_mean"]), float(r["rmse_std"]))
        for r in rd("e1_summary.csv")}
MODELS = [("gru", "GRU (deep learning)", "#1f77b4"),
          ("lstm", "LSTM (deep learning)", "#17becf"),
          ("xgboost", "XGBoost (baseline)", "#2ca02c"),
          ("prophet", "Prophet (baseline)", "#d62728")]
fig, ax = plt.subplots(figsize=(12, 6))
x = np.arange(len(STACKS)); w = 0.2
for i, (k, lab, c) in enumerate(MODELS):
    if not any((k, s) in summ for s in STACKS):
        continue
    mu = [summ.get((k, s), (0, 0))[0] for s in STACKS]
    sd = [summ.get((k, s), (0, 0))[1] for s in STACKS]
    ax.bar(x + (i - 1.5) * w, mu, w, yerr=sd, capsize=3, label=lab, color=c, edgecolor="white")
    for xi, m in zip(x + (i - 1.5) * w, mu):
        ax.text(xi, m, f"{m:.2f}", ha="center", va="bottom", fontsize=8)
ax.set_xticks(x); ax.set_xticklabels([s.upper() for s in STACKS])
ax.set_ylabel("Test RMSE (seconds) - lower is better")
ax.set_title("P95 Latency Forecast Accuracy per Stack\n"
             "Recurrent models: mean over 10 seeds, error bars show std", fontweight="bold")
ax.legend(ncol=2, fontsize=9.5); ax.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(f"{OUT}/can_01_model_comparison.png", dpi=150); plt.close()
print("  can_01_model_comparison.png")

# ------------------------------------------------------- 2. GRU versus LSTM
sig = {r["stack"]: r for r in rd("e1_significance.csv")}
fig, ax = plt.subplots(figsize=(10, 5.5))
w = 0.34
gm = [summ[("gru", s)][0] for s in STACKS]; gs = [summ[("gru", s)][1] for s in STACKS]
lm = [summ[("lstm", s)][0] for s in STACKS]; ls_ = [summ[("lstm", s)][1] for s in STACKS]
ax.bar(x - w / 2, gm, w, yerr=gs, capsize=4, label="GRU", color="#1f77b4", edgecolor="white")
ax.bar(x + w / 2, lm, w, yerr=ls_, capsize=4, label="LSTM", color="#17becf", edgecolor="white")
for xi, m in zip(x - w / 2, gm): ax.text(xi, m, f"{m:.3f}", ha="center", va="bottom", fontsize=8)
for xi, m in zip(x + w / 2, lm): ax.text(xi, m, f"{m:.3f}", ha="center", va="bottom", fontsize=8)
top = max(max(gm), max(lm))
for xi, s in zip(x, STACKS):
    p = float(sig[s]["seed_wilcoxon_p"])
    ax.text(xi, top * 1.06, f"p={p:.3f}", ha="center", fontsize=9,
            color="#1a7f37" if p < 0.05 else "#666")
ax.set_ylim(0, top * 1.18)
ax.set_xticks(x); ax.set_xticklabels([s.upper() for s in STACKS])
ax.set_ylabel("Test RMSE (seconds)")
ax.set_title("GRU versus LSTM over 10 Random Initializations\n"
             "p from Wilcoxon signed-rank across seeds", fontweight="bold")
ax.legend(); ax.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(f"{OUT}/can_02_gru_vs_lstm.png", dpi=150); plt.close()
print("  can_02_gru_vs_lstm.png")

# --------------------------------------------------- 3. per-scenario winner
tal = rd("e2_win_tally.csv")
stab = {(r["scenario"], r["stack"]): int(r["dl_wins_in_seeds"]) for r in rd("e2_win_stability.csv")}
labels = [f"{r['scenario']}\n{r['stack']}" for r in tal]
dl = [float(r["dl_rmse"]) for r in tal]
bl = [float(r["baseline_rmse"]) for r in tal]
xx = np.arange(len(tal)); w = 0.36
fig, ax = plt.subplots(figsize=(13, 5.5))
ax.bar(xx - w / 2, dl, w, label="Best deep learning (GRU/LSTM)", color="#1f77b4", edgecolor="white")
ax.bar(xx + w / 2, bl, w, label="Best baseline (XGBoost/Prophet)", color="#2ca02c", edgecolor="white")
top = max(max(dl), max(bl))
for i, r in enumerate(tal):
    k = stab.get((r["scenario"], r["stack"]), 0)
    win = r["winner"] == "deep_learning"
    ax.text(xx[i], top * 1.04, ("DL" if win else "BASE") + f" ({k}/10)", ha="center", fontsize=8,
            color="#1f77b4" if win else "#2ca02c", fontweight="bold")
ax.set_ylim(0, top * 1.15)
ax.set_xticks(xx); ax.set_xticklabels(labels, fontsize=9)
ax.set_ylabel("Test RMSE (seconds)")
ax.set_title("Per-Scenario Forecast Winner\n"
             "Label shows the winner and in how many of 10 seeds deep learning won",
             fontweight="bold")
ax.legend(); ax.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(f"{OUT}/can_03_scenario_winner.png", dpi=150); plt.close()
print("  can_03_scenario_winner.png")

# ------------------------------------------------------- 4. transfer matrix
tr = rd("e3_transfer.csv")
M = np.zeros((len(STACKS), len(STACKS)))
for r in tr:
    M[STACKS.index(r["train_stack"]), STACKS.index(r["test_stack"])] = float(r["smape"])
fig, ax = plt.subplots(figsize=(8, 6.5))
im = ax.imshow(M, cmap="RdYlGn_r")
ax.set_xticks(range(4)); ax.set_xticklabels([s.upper() for s in STACKS])
ax.set_yticks(range(4)); ax.set_yticklabels([s.upper() for s in STACKS])
ax.set_xlabel("Tested on"); ax.set_ylabel("Trained on")
for i in range(4):
    for j in range(4):
        ax.text(j, i, f"{M[i, j]:.0f}", ha="center", va="center",
                fontweight="bold" if i == j else "normal",
                color="black")
ax.set_title("Cross-Stack Transfer (sMAPE %)\nDiagonal = self-trained; lower is better",
             fontweight="bold")
fig.colorbar(im, label="sMAPE (%)")
fig.tight_layout(); fig.savefig(f"{OUT}/can_04_transfer_heatmap.png", dpi=150); plt.close()
print("  can_04_transfer_heatmap.png")
