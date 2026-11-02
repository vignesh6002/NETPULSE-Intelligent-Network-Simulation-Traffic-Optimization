# NETPULSE Priority-Aware Routing (design)

Goal: reduce **jitter and tail latency of match-critical game packets** under resource contention.

## Priority classes (5 levels)

| Class | Traffic | Examples | Routing policy | Queue |
|---|---|---|---|---|
| P0 | Critical | hit registration, bullets/combat events | lowest-delay path, may preempt | Strict-priority LLQ |
| P1 | Real-time | movement / position updates, voice | low-delay path | LLQ (policed) |
| P2 | Sync | game-state synchronisation | least-congested path | Weighted queue |
| P3 | Idle/keep-alive | idle updates | may wait OR detour | Weighted queue |
| P4 | Background | non-game traffic | any path, may detour/wait | Best effort |

Mapping from current `activity` column: combat -> P0, movement/voice -> P1, synchronisation -> P2, idle -> P3. Background router load -> P4.

## Mechanisms

1. **Low Latency Queue (LLQ):** each directed link has a strict-priority queue for P0/P1 (rate-policed, e.g. at most 30% of link bandwidth to prevent starvation) plus weighted fair queues for P2-P4.
2. **Per-class Dijkstra weights:**
   - P0/P1: `W = delay + queueing delay of priority queue` (ignores bulk load, since LLQ shields them).
   - P2-P4: `W = delay + alpha * U/(1-U)` (current congestion-aware cost).
3. **Wait-or-detour decision (P3/P4):** compare `wait = queue_delay_on_best_path` against `detour = extra_path_delay`; choose the smaller.
4. **Jitter metric:** mean |latency_i - latency_{i-1}| per flow and class, plus p95/p99, evaluated per class.

## Experiments

Compare under identical topology, traffic and contention (scale offered load until links hit 80-100%, e.g. ~10k packets/s):
1. Plain Dijkstra (FIFO, no classes) - baseline
2. LLQ + class-aware Dijkstra - proposed
3. ML routing - later

Metrics: per-class mean/p95/p99 latency, jitter, loss, link utilisation.

Note: the current game flows are ~0.3 Mbps each, so links are only ~16% utilised. A load-scaling factor is needed to create real contention.
