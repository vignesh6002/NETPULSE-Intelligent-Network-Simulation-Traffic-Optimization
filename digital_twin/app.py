"""NETPULSE Digital Twin (Streamlit + PyVis)."""
import csv
import sys
from pathlib import Path

import networkx as nx
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.topology import build_topology  # noqa: E402

RESULTS = ROOT / "results"
NODE_STYLE = {
    "pc": ("#2ecc71", "dot", 14),
    "switch": ("#9b59b6", "square", 12),
    "router": ("#3498db", "dot", 18),
}

st.set_page_config(page_title="NETPULSE Digital Twin", layout="wide")


def load_graph():
    topo_path = ROOT / "configs" / "topology.json"
    mtime = topo_path.stat().st_mtime if topo_path.exists() else 0
    return _load_graph_cached(mtime)


@st.cache_data
def _load_graph_cached(mtime):
    G = build_topology()
    pos = nx.spring_layout(G, seed=7, k=0.6, iterations=200)
    return G, pos


def load_csv(name):
    path = RESULTS / name
    if not path.exists():
        return None
    return _load_csv_cached(name, path.stat().st_mtime)


@st.cache_data
def _load_csv_cached(name, mtime):
    path = RESULTS / name
    return pd.read_csv(path)


def util_color(u):
    if u >= 60:
        return "#e74c3c"
    if u >= 35:
        return "#f39c12"
    if u >= 15:
        return "#f1c40f"
    return "#95a5a6"


def build_view(G, pos, link_df, route_nodes):
    net = Network(height="680px", width="100%", bgcolor="#111827",
                  font_color="white", directed=False)
    net.toggle_physics(False)
    route_edges = set()
    if route_nodes:
        route_edges = {frozenset(p) for p in zip(route_nodes, route_nodes[1:])}
    on_route = set(route_nodes or [])

    for n, d in G.nodes(data=True):
        color, shape, size = NODE_STYLE[d["type"]]
        if route_nodes and n in on_route:
            color = "#ff3b3b"
        net.add_node(n, label=n, color=color, shape=shape, size=size,
                     x=float(pos[n][0]) * 1000, y=float(pos[n][1]) * 1000,
                     title=f"{n} ({d['type']})")

    lookup = {}
    if link_df is not None:
        for r in link_df.itertuples():
            lookup[(r.from_node, r.to_node)] = r

    for a, b, d in G.edges(data=True):
        fwd, rev = lookup.get((a, b)), lookup.get((b, a))
        u_f = fwd.utilization_pct if fwd else 0.0
        u_r = rev.utilization_pct if rev else 0.0
        u = max(u_f, u_r)
        title = (f"{a} to {b}: {d['bandwidth_mbps']:.1f} Mbps\n"
                 f"{a}->{b}: {fwd.offered_mbps:.2f} Mbps ({u_f:.1f}%)\n"
                 f"{b}->{a}: {rev.offered_mbps:.2f} Mbps ({u_r:.1f}%)"
                 if fwd and rev else f"{a} - {b}")
        highlighted = frozenset((a, b)) in route_edges
        net.add_edge(a, b, color="#ff3b3b" if highlighted else util_color(u),
                     width=6 if highlighted else 1 + u / 12, title=title)
    return net.generate_html()


G, pos = load_graph()

st.title("NETPULSE Digital Twin")
st.caption("Every packet has a path. Every path has a story.")

tab_twin, tab_ws = st.tabs(["Network twin", "Wireshark / real UDP capture"])

with tab_twin:
    loads = load_csv("link_loads.csv")
    summary = load_csv("link_load_summary.csv")
    routes = load_csv("dijkstra_routes.csv")

    if loads is None or summary is None:
        st.warning("Run simulation/link_load_engine.py first.")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    mode = c1.radio("Load view", ["Average over simulation", "Single time step"])
    step = None
    if mode == "Single time step":
        step = c2.slider("Time step (s)", int(loads.step.min()), int(loads.step.max()), 0)
    
    algo_view = c2.selectbox("Path routing algorithm", ["dijkstra", "llq_standalone", "ml_routing"])
    pcs = [f"PC{i}" for i in range(1, 11)]
    src = c3.selectbox("Route source", ["(none)"] + pcs)
    dst = c4.selectbox("Route destination", ["(none)"] + pcs)

    if step is None:
        view = summary.rename(columns={"avg_offered_mbps": "offered_mbps",
                                       "avg_utilization_pct": "utilization_pct"})
    else:
        view = loads[loads.step == step]

    route_nodes, route_info = None, None
    if src != "(none)" and dst != "(none)" and src != dst:
        if algo_view == "ml_routing":
            ml_sched = load_csv("packet_schedule_ml_routing.csv")
            if ml_sched is not None:
                sub_ml = ml_sched[(ml_sched.source == src) & (ml_sched.destination == dst) & (ml_sched.priority == 0)]
                if not sub_ml.empty:
                    p = sub_ml.iloc[0].path
                    route_nodes = p.split(" -> ")
                    route_info = {
                        "path": p,
                        "hops": len(route_nodes) - 1,
                        "delay_ms": round(sub_ml.delay_ms.mean(), 2),
                        "p99_ms": round(sub_ml.delay_ms.quantile(0.99), 2),
                        "algo": "🤖 ML Cluster-Aware Bypass Routing"
                    }
        elif algo_view == "llq_standalone":
            llq_sched = load_csv("packet_schedule_llq_standalone.csv")
            if llq_sched is not None:
                sub_llq = llq_sched[(llq_sched.source == src) & (llq_sched.destination == dst) & (llq_sched.priority == 0)]
                if not sub_llq.empty:
                    p = sub_llq.iloc[0].path
                    route_nodes = p.split(" -> ")
                    route_info = {
                        "path": p,
                        "hops": len(route_nodes) - 1,
                        "delay_ms": round(sub_llq.delay_ms.mean(), 2),
                        "p99_ms": round(sub_llq.delay_ms.quantile(0.99), 2),
                        "algo": "⚖️ LLQ Priority Queue Routing"
                    }
        else:
            dij_sched = load_csv("packet_schedule_dijkstra_fifo.csv")
            if dij_sched is not None:
                sub_dij = dij_sched[(dij_sched.source == src) & (dij_sched.destination == dst) & (dij_sched.priority == 0)]
                if not sub_dij.empty:
                    p = sub_dij.iloc[0].path
                    route_nodes = p.split(" -> ")
                    route_info = {
                        "path": p,
                        "hops": len(route_nodes) - 1,
                        "delay_ms": round(sub_dij.delay_ms.mean(), 2),
                        "p99_ms": round(sub_dij.delay_ms.quantile(0.99), 2),
                        "algo": "🔵 Dijkstra FIFO (Bufferbloated Core)"
                    }

    components.html(build_view(G, pos, view, route_nodes), height=700, scrolling=False)
    st.caption("Green PC | purple square switch | blue router. Link colour/width = max directional "
               "utilisation (grey <15%, yellow, orange, red >=60%). Hover a link for details.")

    if route_info is not None:
        st.subheader(f"Selected route: {src} → {dst} ({route_info['algo']})")
        st.code(route_info["path"])
        m1, m2, m3 = st.columns(3)
        m1.metric("Hops", route_info["hops"])
        m2.metric("Mean Latency — P0 Combat (ms)", route_info["delay_ms"])
        m3.metric("P99 Tail Latency (ms)", route_info["p99_ms"])

    # ── 3-Algorithm Benchmark (prominent in main tab) ──────────────────────────
    three_algo = load_csv("three_algo_comparison.csv")
    if three_algo is not None:
        st.divider()
        st.subheader("🏆 3-Algorithm Benchmark: Dijkstra vs LLQ vs ML Model")
        p0 = three_algo[three_algo["class"] == "P0_combat"].copy()
        bm1, bm2, bm3 = st.columns(3)
        for col, algo, label, icon in [
            (bm1, "dijkstra_fifo",   "Dijkstra FIFO",        "🔵"),
            (bm2, "llq_standalone",  "LLQ Priority Queue",   "⚖️"),
            (bm3, "ml_routing",      "ML Cluster Bypass",    "🤖"),
        ]:
            row = p0[p0.algorithm == algo]
            if not row.empty:
                r = row.iloc[0]
                col.markdown(f"**{icon} {label}**")
                col.metric("Mean Latency", f"{r.mean_delay_ms:.1f} ms")
                col.metric("P99 Tail", f"{r.p99_delay_ms:.1f} ms")
                col.metric("Jitter", f"{r.jitter_ms:.2f} ms")
                col.metric("Packet Loss", f"{r.loss_pct:.1f}%")
        bc1, bc2 = st.columns(2)
        bc1.caption("P0 Combat — Mean Latency by Algorithm (ms)")
        bc1.bar_chart(p0.set_index("algorithm")["mean_delay_ms"])
        bc2.caption("P0 Combat — P99 Tail Latency by Algorithm (ms)")
        bc2.bar_chart(p0.set_index("algorithm")["p99_delay_ms"])
        with st.expander("Full benchmark table (all priority classes)"):
            st.dataframe(three_algo, use_container_width=True, hide_index=True)

    rec_10k = load_csv("ten_k_recommendations.csv")
    if rec_10k is not None:
        st.divider()
        st.subheader("High-Contention 10,000-Packet Experiment & ML Path Recommender")
        st.caption("Demonstration of 10,000 packets: 2,000 High-Priority Bullet/Combat packets + 8,000 Bulk packets under bottleneck link saturation.")
        
        pair_choices = [f"{r.source} -> {r.destination}" for r in rec_10k.itertuples()]
        sel_pair = st.selectbox("Select Flow to View ML Priority Path Recommendation", pair_choices)
        
        chosen_rec = rec_10k[[f"{r.source} -> {r.destination}" == sel_pair for r in rec_10k.itertuples()]].iloc[0]
        
        col_rec1, col_rec2 = st.columns(2)
        with col_rec1:
            st.error(f"Conventional Dijkstra (All 10,000 Packets Funneled Together)")
            st.write(f"**Path**: `{chosen_rec.dijkstra_shared_path}`")
            st.metric("Bottleneck Link Load", chosen_rec.dijkstra_bottleneck_load_pct)
            st.metric("High-Priority p99 Latency", f"{chosen_rec.dijkstra_p0_p99_ms} ms")
            st.caption("Result: Severe bufferbloat, queue bloat, packet drops, high tail latency.")
            
        with col_rec2:
            st.success(f"ML Priority Recommender (Traffic Split by Class)")
            st.write(f"**P0 High-Priority Path (2,000 pkts)**: `{chosen_rec.ml_p0_recommended_path}`")
            st.write(f"**Bulk Path (8,000 pkts)**: `{chosen_rec.ml_bulk_recommended_path}`")
            st.metric("ML Express Path Load", chosen_rec.ml_p0_path_load_pct)
            st.metric("High-Priority p99 Latency", f"{chosen_rec.ml_p0_p99_ms} ms", delta=f"-{chosen_rec.latency_saving_ms} ms Faster!")
            st.caption("Result: 2,000 critical bullet packets bypass saturation with optimal headroom.")
            
        st.dataframe(rec_10k[["source", "destination", "dijkstra_p0_p99_ms", "ml_p0_p99_ms", "latency_saving_ms", "ml_p0_path_load_pct"]], use_container_width=True, hide_index=True)

    st.subheader("Most utilised directed links")
    top = view.sort_values("utilization_pct", ascending=False).head(10)
    st.dataframe(top[["from_node", "to_node", "offered_mbps", "bandwidth_mbps",
                      "utilization_pct"]], use_container_width=True)

with tab_ws:
    # ---------- per-route Wireshark view ----------
    st.subheader("Route as seen in Wireshark")
    schemes = [p.stem.replace("router_", "") for p in sorted(RESULTS.glob("router_*.csv"))
               if (RESULTS / f"packet_schedule_{p.stem.replace('router_', '')}.csv").exists()]
    if not schemes:
        st.warning("No router capture yet. Run packet_capture/run_router_capture.ps1.")
    else:
        pcs_all = [f"PC{i}" for i in range(1, 11)]
        w1, w2, w3 = st.columns(3)
        ws_scheme = w1.selectbox("Scheme", schemes)
        ws_src = w2.selectbox("From", pcs_all, index=1, key="ws_src")
        ws_dst = w3.selectbox("To", pcs_all, index=4, key="ws_dst")

        @st.cache_data
        def load_router_capture(scheme, mtime):
            from packet_capture.analyze_router_capture import parse
            frames = parse(RESULTS / f"router_{scheme}.csv")
            sched = pd.read_csv(RESULTS / f"packet_schedule_{scheme}.csv")
            sched["pkt_id"] = sched.index
            return frames, sched

        mtime = (RESULTS / f"router_{ws_scheme}.csv").stat().st_mtime
        frames, sched = load_router_capture(ws_scheme, mtime)
        captured_ids = set(frames.pkt_id.unique())
        pair = sched[(sched.source == ws_src) & (sched.destination == ws_dst)
                     & sched.pkt_id.isin(captured_ids)]

        if ws_src == ws_dst:
            st.warning("Choose different source and destination PCs.")
        elif pair.empty:
            st.warning(f"No captured packets for {ws_src} to {ws_dst} in this capture. "
                       "Capture more steps with run_router_capture.ps1 -Steps 30.")
        else:
            names = ["P0 combat", "P1 movement/voice", "P2 sync", "P3 idle"]
            c1, c2 = st.columns(2)
            prio_opts = sorted(pair.priority.unique())
            prio = c1.selectbox("Priority class", prio_opts, format_func=lambda k: names[k])
            sub = pair[pair.priority == prio]
            pid = c2.selectbox(
                "Packet", sub.pkt_id.tolist(),
                format_func=lambda i: f"packet {i} (t = {sub[sub.pkt_id == i].time_s.iloc[0]} s)")
            row = sub[sub.pkt_id == pid].iloc[0]

            g = frames[frames.pkt_id == pid].sort_values("epoch").reset_index(drop=True)
            hop_delays = [float(x) for x in row.hop_delays_ms.split(";")]
            ip_of = lambda n: ("127.0.1." + n[1:] if n.startswith("R")
                               else "127.0.2." + n[1:] if n.startswith("S")
                               else "127.0.3." + n[2:])
            t_ref = g.t0.iloc[0] + g.nominal.iloc[0]
            hops = pd.DataFrame({
                "hop": range(1, len(g) + 1),
                "from": g.src, "from_ip": [ip_of(n) for n in g.src],
                "to": g.dst, "to_ip": [ip_of(n) for n in g.dst],
                "sim_hop_delay_ms": hop_delays[:len(g)],
                "captured_at_ms": ((g.epoch - t_ref) * 1000).round(3),
                "dscp": g.dscp,
            })
            captured_path = [g.src.iloc[0]] + list(g.dst)
            cap_delay = (g.epoch.iloc[-1] - t_ref) * 1000
            dscp_val = int(g.dscp.iloc[0])

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Hops (datagrams)", len(g))
            m2.metric("Simulated delay (ms)", f"{row.delay_ms:.3f}")
            m3.metric("Captured delay (ms)", f"{cap_delay:.3f}")
            m4.metric("DSCP", dscp_val)

            if " -> ".join(captured_path) == row.path:
                st.success("Path seen in Wireshark matches the Dijkstra route.")
            else:
                st.error("Captured path differs from the Dijkstra route.")
            if int(row.dropped):
                st.warning(f"The simulation dropped this packet at hop {int(row.drop_hop) + 1}.")
            st.write(" -> ".join(captured_path))
            st.dataframe(hops, use_container_width=True, hide_index=True)
            st.caption("Wireshark display filters: "
                       f"`ip.addr == {ip_of(ws_src)} && udp.port == 40000` (this PC's traffic), "
                       f"`ip.dsfield.dscp == {dscp_val}` (this priority class). "
                       "Open results/router_" + ws_scheme + ".pcapng to inspect the raw frames.")
            st.bar_chart(hops.set_index("hop")["sim_hop_delay_ms"])

    three_algo = load_csv("three_algo_comparison.csv")
    if three_algo is not None:
        st.subheader("3-Algorithm Benchmark: Dijkstra vs LLQ vs ML Model")
        p0_comp = three_algo[three_algo["class"] == "P0_combat"]
        b1, b2 = st.columns(2)
        b1.caption("P0 Combat Jitter (ms) across Algorithms")
        b1.bar_chart(p0_comp.set_index("algorithm")["jitter_ms"])
        b2.caption("P0 Combat Mean Latency (ms)")
        b2.bar_chart(p0_comp.set_index("algorithm")["mean_delay_ms"])
        with st.expander("Full benchmark table"):
            st.dataframe(three_algo, use_container_width=True, hide_index=True)

    router_cmp = load_csv("router_comparison.csv")
    if router_cmp is not None:
        st.subheader("Router-network capture: captured vs simulated, per class")
        st.dataframe(router_cmp, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Single-hop replay capture")
    st.caption("Earlier test: end-to-end delay replayed over one hop (not router-level).")
    cmp_df = load_csv("wireshark_comparison.csv")
    if cmp_df is not None:
        st.subheader("Captured vs simulated, per priority class and scheme")
        st.dataframe(cmp_df, use_container_width=True)
        pivot = cmp_df.pivot(index="class", columns="scheme", values="cap_jitter_ms")
        st.caption("Jitter measured in the Wireshark capture (ms)")
        st.bar_chart(pivot)
        pivot99 = cmp_df.pivot(index="class", columns="scheme", values="cap_p99_ms")
        st.caption("p99 delay measured in the Wireshark capture (ms)")
        st.bar_chart(pivot99)
    else:
        st.warning("Run packet_capture/run_emulated_capture.ps1 then analyze_emulation.py.")
    st.subheader("Raw replay capture (constant-rate test)")
    cap = load_csv("capture_summary.csv")
    if cap is None:
        st.warning("No capture yet. Run packet_capture/run_capture.ps1 on Windows, then "
                   "packet_capture/analyze_capture.py.")
    else:
        a, b, c = st.columns(3)
        a.metric("Packets received", int(cap.packets.sum()))
        b.metric("Mean latency (ms)", f"{cap.mean_latency_ms.mean():.3f}")
        c.metric("Real vs simulated rate (Mbps)",
                 f"{cap.real_mbps.mean():.2f} / {cap.simulated_mbps.mean():.2f}")
        st.line_chart(cap.set_index("step")[["real_mbps", "simulated_mbps"]])
    ws = RESULTS / "wireshark_udp.csv"
    if ws.exists():
        st.subheader("TShark export (first rows)")
        st.dataframe(pd.read_csv(ws).head(200), use_container_width=True)
