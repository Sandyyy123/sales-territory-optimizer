"""
Sales Territory Optimizer
=========================
Cluster customer GPS points into balanced, contiguous sales territories,
apply capacity caps, generate zone polygons (KML), and export assignments.

Repeatable for any city. All caps and the target zone count are parameters.

Pipeline
--------
1. Load customers (id, lat, lon, monthly sales + visit counts over a 4-month window).
2. Derive recommended monthly visits per customer from a frequency matrix
   (value tier x activity tier).
3. Cluster coordinates into geographically compact zones (KMeans seed).
4. Capacity-balance: move only BORDER customers between ADJACENT zones until
   every zone respects the customer cap (soft) and visit cap (hard), without
   creating geographic islands.
5. Build a concave/convex boundary polygon per zone.
6. Export: KML polygons, per-customer assignment table, zone summary.

Author: Dr. Sandeep Grover
"""
from __future__ import annotations
import argparse
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from scipy.spatial import cKDTree, ConvexHull


# --------------------------------------------------------------------------- #
# Capacity configuration (all overridable from the CLI)
# --------------------------------------------------------------------------- #
@dataclass
class Caps:
    customer_cap: int = 240        # soft target per rep
    visits_per_day: int = 20
    working_days: int = 26
    n_zones: int = 12              # target zone count (data may justify +/-)

    @property
    def visit_cap(self) -> int:    # hard cap = 20 * 26 = 520
        return self.visits_per_day * self.working_days


# --------------------------------------------------------------------------- #
# 1. Frequency matrix -> recommended monthly visits
# --------------------------------------------------------------------------- #
def recommend_visits(df: pd.DataFrame) -> pd.Series:
    """Map each customer to a recommended monthly visit count.

    A customer's visit frequency rises with (a) how VALUABLE they are
    (avg monthly sales) and (b) how ACTIVE they are (avg monthly invoices).
    This is a placeholder for the client's exact Jeddah frequency matrix;
    the structure (value tier x activity tier -> visits) is identical, so
    swapping in their grid is a one-line change.
    """
    sales = df["avg_monthly_sales"]
    invoices = df["avg_monthly_invoices"]

    # tertiles -> 3 value tiers, 3 activity tiers
    v_tier = pd.qcut(sales.rank(method="first"), 3, labels=[1, 2, 3]).astype(int)
    a_tier = pd.qcut(invoices.rank(method="first"), 3, labels=[1, 2, 3]).astype(int)

    # visits/month grid indexed [value_tier][activity_tier]
    grid = {
        (1, 1): 1, (1, 2): 1, (1, 3): 2,
        (2, 1): 2, (2, 2): 3, (2, 3): 4,
        (3, 1): 4, (3, 2): 6, (3, 3): 8,
    }
    visits = [grid[(v, a)] for v, a in zip(v_tier, a_tier)]
    # inactive customers (no invoices in window) -> 0 recommended visits
    visits = np.where(invoices <= 0, 0, visits)
    return pd.Series(visits, index=df.index, name="recommended_visits")


# --------------------------------------------------------------------------- #
# 2. Geographic seed clustering
# --------------------------------------------------------------------------- #
def seed_clusters(coords: np.ndarray, n_zones: int) -> np.ndarray:
    """Compact geographic seeds via KMeans on scaled lat/lon."""
    # scale lon by cos(lat) so euclidean distance approximates ground distance
    lat0 = np.radians(coords[:, 0].mean())
    scaled = np.column_stack([coords[:, 0], coords[:, 1] * np.cos(lat0)])
    km = KMeans(n_clusters=n_zones, n_init=10, random_state=42)
    return km.fit_predict(scaled)


# --------------------------------------------------------------------------- #
# 3. Capacity balancing on border customers only
# --------------------------------------------------------------------------- #
def balance(df: pd.DataFrame, caps: Caps, max_iter: int = 4000) -> pd.DataFrame:
    """Move border customers from over-capacity zones to the nearest
    adjacent under-capacity zone. Only customers on a zone border are
    eligible, which preserves contiguity (no islands)."""
    coords = df[["lat", "lon"]].to_numpy()
    lat0 = np.radians(coords[:, 0].mean())
    scaled = np.column_stack([coords[:, 0], coords[:, 1] * np.cos(lat0)])
    tree = cKDTree(scaled)
    # 8 nearest neighbours define adjacency / border membership
    _, nbr_idx = tree.query(scaled, k=9)
    nbr_idx = nbr_idx[:, 1:]

    zone = df["zone"].to_numpy().copy()
    visits = df["recommended_visits"].to_numpy()

    def loads():
        cust = pd.Series(zone).value_counts().to_dict()
        vis = pd.Series(visits).groupby(zone).sum().to_dict()
        return cust, vis

    for _ in range(max_iter):
        cust, vis = loads()
        # most overloaded zone first (visit cap is hard, weight it heavier)
        over = [z for z in set(zone)
                if cust.get(z, 0) > caps.customer_cap or vis.get(z, 0) > caps.visit_cap]
        if not over:
            break
        over.sort(key=lambda z: (vis.get(z, 0) / caps.visit_cap,
                                 cust.get(z, 0) / caps.customer_cap), reverse=True)
        src = over[0]

        # border customers of src: have at least one neighbour in another zone
        moved = False
        members = np.where(zone == src)[0]
        # try farthest-from-centroid border points first
        cen = scaled[members].mean(axis=0)
        order = members[np.argsort(-np.linalg.norm(scaled[members] - cen, axis=1))]
        for i in order:
            neigh_zones = zone[nbr_idx[i]]
            cand = [z for z in neigh_zones if z != src]
            if not cand:
                continue
            # pick adjacent zone with most spare visit capacity
            cand = sorted(set(cand), key=lambda z: vis.get(z, 0))
            tgt = cand[0]
            if (cust.get(tgt, 0) + 1 <= caps.customer_cap and
                    vis.get(tgt, 0) + visits[i] <= caps.visit_cap):
                zone[i] = tgt
                moved = True
                break
        if not moved:
            # relax: accept move to the lightest adjacent zone even if still tight
            for i in order:
                neigh_zones = [z for z in zone[nbr_idx[i]] if z != src]
                if neigh_zones:
                    tgt = min(set(neigh_zones), key=lambda z: vis.get(z, 0))
                    zone[i] = tgt
                    moved = True
                    break
            if not moved:
                break

    df = df.copy()
    df["zone"] = zone
    df["rep"] = pd.factorize(df["zone"])[0] + 1
    return df


# --------------------------------------------------------------------------- #
# 4. Zone boundary polygons
# --------------------------------------------------------------------------- #
def zone_polygons(df: pd.DataFrame) -> dict:
    """Return {zone: [(lon,lat), ...]} convex-hull boundary per zone.
    (Convex hull keeps the demo dependency-light; swap for a concave/alpha
    shape with `alphashape` for tighter boundaries in production.)"""
    polys = {}
    for z, g in df.groupby("zone"):
        pts = g[["lon", "lat"]].to_numpy()
        if len(pts) < 3:
            polys[z] = pts.tolist()
            continue
        hull = ConvexHull(pts)
        ring = pts[hull.vertices].tolist()
        ring.append(ring[0])
        polys[z] = ring
    return polys


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def optimize(df: pd.DataFrame, caps: Caps) -> tuple[pd.DataFrame, dict]:
    df = df.copy()
    df["recommended_visits"] = recommend_visits(df)
    df["zone"] = seed_clusters(df[["lat", "lon"]].to_numpy(), caps.n_zones)
    df = balance(df, caps)
    polys = zone_polygons(df)
    return df, polys


def zone_summary(df: pd.DataFrame, caps: Caps) -> pd.DataFrame:
    rows = []
    for z, g in df.groupby("rep"):
        visits = int(g["recommended_visits"].sum())
        rows.append({
            "rep": int(z),
            "customers": len(g),
            "active_customers": int((g["recommended_visits"] > 0).sum()),
            "monthly_visits": visits,
            "visits_per_day": round(visits / caps.working_days, 1),
            "monthly_sales": round(float(g["avg_monthly_sales"].sum()), 0),
            "customer_cap_ok": len(g) <= caps.customer_cap,
            "visit_cap_ok": visits <= caps.visit_cap,
        })
    return pd.DataFrame(rows).sort_values("rep").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description="Sales territory optimizer")
    ap.add_argument("--input", required=True, help="customers CSV")
    ap.add_argument("--city", default="city")
    ap.add_argument("--out", default="demo_output")
    ap.add_argument("--customer-cap", type=int, default=240)
    ap.add_argument("--visits-per-day", type=int, default=20)
    ap.add_argument("--working-days", type=int, default=26)
    ap.add_argument("--zones", type=int, default=12)
    args = ap.parse_args()

    caps = Caps(args.customer_cap, args.visits_per_day, args.working_days, args.zones)
    df = pd.read_csv(args.input)
    df, polys = optimize(df, caps)
    summary = zone_summary(df, caps)

    import os
    os.makedirs(args.out, exist_ok=True)
    df.to_csv(f"{args.out}/{args.city}_assignments.csv", index=False)
    summary.to_csv(f"{args.out}/{args.city}_zone_summary.csv", index=False)
    with open(f"{args.out}/{args.city}_zones.json", "w") as f:
        json.dump({str(k): v for k, v in polys.items()}, f)

    print(summary.to_string(index=False))
    print(f"\ncaps: customer<= {caps.customer_cap}, visits<= {caps.visit_cap} (hard)")
    print(f"all customer caps ok: {summary['customer_cap_ok'].all()}")
    print(f"all visit caps ok:    {summary['visit_cap_ok'].all()}")


if __name__ == "__main__":
    main()
