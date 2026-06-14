"""Generate a realistic synthetic Riyadh customer base for the demo.

Points are seeded around real Riyadh district centroids so the clustering
output looks like genuine city geography. No real customer data is used.
"""
import argparse
import numpy as np
import pandas as pd

# (name, lat, lon, weight) — approximate Riyadh district centroids
RIYADH_DISTRICTS = [
    ("Olaya", 24.6900, 46.6850, 1.4),
    ("Al Malaz", 24.6600, 46.7300, 1.1),
    ("Al Murabba", 24.6470, 46.7100, 0.8),
    ("Al Naseem", 24.7300, 46.8200, 1.0),
    ("Al Rawdah", 24.7600, 46.7500, 1.2),
    ("Al Suwaidi", 24.5900, 46.6700, 1.0),
    ("Al Shifa", 24.5500, 46.7300, 0.9),
    ("Al Aziziyah", 24.5400, 46.7800, 0.8),
    ("King Fahd", 24.7600, 46.6500, 1.1),
    ("Al Wurud", 24.7100, 46.6700, 0.9),
    ("Al Yasmin", 24.8500, 46.6400, 1.0),
    ("Al Nakheel", 24.7500, 46.6300, 0.9),
    ("Irqah", 24.7000, 46.5600, 0.7),
    ("Al Hamra", 24.7800, 46.7900, 0.8),
]


def make(n: int, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    weights = np.array([d[3] for d in RIYADH_DISTRICTS])
    weights = weights / weights.sum()
    counts = rng.multinomial(n, weights)

    rows = []
    cid = 1000
    for (name, lat, lon, _), k in zip(RIYADH_DISTRICTS, counts):
        for _ in range(k):
            jlat = lat + rng.normal(0, 0.012)
            jlon = lon + rng.normal(0, 0.013)
            # sales: log-normal so a few high-value customers dominate
            sales = float(rng.lognormal(mean=8.4, sigma=0.8))
            invoices = int(max(0, rng.poisson(4) - rng.integers(0, 2)))
            rows.append((f"C{cid}", jlat, jlon, sales, invoices, name))
            cid += 1

    df = pd.DataFrame(rows, columns=[
        "customer_id", "lat", "lon", "avg_monthly_sales",
        "avg_monthly_invoices", "true_district"])

    # expand into the 4-month window the client provides
    for m in range(1, 5):
        df[f"sales_m{m}"] = (df["avg_monthly_sales"]
                             * rng.normal(1, 0.15, len(df))).round(0)
        df[f"invoices_m{m}"] = np.maximum(
            0, (df["avg_monthly_invoices"]
                + rng.integers(-1, 2, len(df)))).astype(int)
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1300)
    ap.add_argument("--out", default="sample_data/riyadh_customers.csv")
    a = ap.parse_args()
    df = make(a.n)
    df.to_csv(a.out, index=False)
    print(f"wrote {len(df)} customers -> {a.out}")
