"""Build the three client-facing artifacts from optimizer output:
  1. Interactive Folium/Leaflet HTML map
  2. District-level KML polygons
  3. Two-tab Excel workbook (assignments + zone summary with cap checks)
"""
import argparse
import colorsys

import folium
import pandas as pd
import simplekml

from territory_optimizer import Caps, optimize, zone_summary


def palette(n):
    out = []
    for i in range(n):
        r, g, b = colorsys.hsv_to_rgb(i / n, 0.65, 0.95)
        out.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")
    return out


def build_map(df, polys, summary, city, path):
    center = [df["lat"].mean(), df["lon"].mean()]
    m = folium.Map(location=center, zoom_start=11, tiles="cartodbpositron")
    reps = sorted(df["rep"].unique())
    cols = dict(zip(reps, palette(len(reps))))
    z2rep = df.drop_duplicates("zone").set_index("zone")["rep"].to_dict()

    # zone polygons
    for z, ring in polys.items():
        rep = z2rep.get(z)
        latlon = [[p[1], p[0]] for p in ring]
        s = summary[summary["rep"] == rep].iloc[0]
        folium.Polygon(
            latlon, color=cols[rep], weight=2, fill=True,
            fill_color=cols[rep], fill_opacity=0.18,
            popup=folium.Popup(
                f"<b>Zone {rep}</b><br>Customers: {s['customers']}<br>"
                f"Monthly visits: {s['monthly_visits']} "
                f"({s['visits_per_day']}/day)<br>"
                f"Monthly sales: {s['monthly_sales']:,.0f}", max_width=260),
        ).add_to(m)

    # customer points sized by sales
    smax = df["avg_monthly_sales"].max()
    for _, r in df.iterrows():
        folium.CircleMarker(
            [r["lat"], r["lon"]],
            radius=3 + 7 * (r["avg_monthly_sales"] / smax),
            color=cols[r["rep"]], fill=True, fill_color=cols[r["rep"]],
            fill_opacity=0.85, weight=0,
            popup=folium.Popup(
                f"<b>{r['customer_id']}</b><br>Zone/Rep: {r['rep']}<br>"
                f"Monthly sales: {r['avg_monthly_sales']:,.0f}<br>"
                f"Recommended visits: {int(r['recommended_visits'])}/mo",
                max_width=240),
        ).add_to(m)

    # summary panel
    rows = "".join(
        f"<tr><td>{s.rep}</td><td>{s.customers}</td>"
        f"<td>{s.monthly_visits}</td><td>{s.monthly_sales:,.0f}</td></tr>"
        for s in summary.itertuples())
    panel = f"""
    <div style="position:fixed;top:12px;right:12px;z-index:9999;background:#fff;
      padding:10px 12px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.2);
      font:12px system-ui;max-height:80vh;overflow:auto">
      <b>{city} — {len(summary)} zones</b>
      <table style="border-collapse:collapse;margin-top:6px">
      <tr style="border-bottom:1px solid #ccc"><th>Z</th><th>Cust</th>
      <th>Visits</th><th>Sales</th></tr>{rows}</table>
      <div style="margin-top:6px;color:#666">Caps: 240 cust / 520 visits</div>
    </div>"""
    m.get_root().html.add_child(folium.Element(panel))
    m.save(path)
    return path


def build_kml(df, polys, summary, city, path):
    kml = simplekml.Kml()
    z2rep = df.drop_duplicates("zone").set_index("zone")["rep"].to_dict()
    cols = dict(zip(sorted(df["rep"].unique()),
                    palette(df["rep"].nunique())))
    for z, ring in polys.items():
        rep = z2rep.get(z)
        s = summary[summary["rep"] == rep].iloc[0]
        pol = kml.newpolygon(
            name=f"{city} - Zone {rep}",
            outerboundaryis=[(p[0], p[1]) for p in ring])
        pol.description = (f"Customers: {s['customers']}, "
                           f"Visits/mo: {s['monthly_visits']}, "
                           f"Sales/mo: {s['monthly_sales']:,.0f}")
        hexc = cols[rep].lstrip("#")
        abgr = f"80{hexc[4:6]}{hexc[2:4]}{hexc[0:2]}"
        pol.style.polystyle.color = abgr
        pol.style.linestyle.width = 2
    kml.save(path)
    return path


def build_excel(df, summary, path):
    keep = ["customer_id", "rep", "recommended_visits", "avg_monthly_sales",
            "avg_monthly_invoices", "lat", "lon",
            "sales_m1", "sales_m2", "sales_m3", "sales_m4"]
    keep = [c for c in keep if c in df.columns]
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        df[keep].rename(columns={"rep": "zone_rep"}).to_excel(
            xl, sheet_name="assignments", index=False)
        summary.to_excel(xl, sheet_name="zone_summary", index=False)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--city", default="Riyadh")
    ap.add_argument("--out", default="demo_output")
    ap.add_argument("--zones", type=int, default=12)
    ap.add_argument("--customer-cap", type=int, default=240)
    a = ap.parse_args()

    caps = Caps(customer_cap=a.customer_cap, n_zones=a.zones)
    df = pd.read_csv(a.input)
    df, polys = optimize(df, caps)
    summary = zone_summary(df, caps)

    import os
    os.makedirs(a.out, exist_ok=True)
    pre = f"{a.out}/{a.city.lower()}"
    build_map(df, polys, summary, a.city, f"{pre}_territory_map.html")
    build_kml(df, polys, summary, a.city, f"{pre}_zones.kml")
    build_excel(df, summary, f"{pre}_territories.xlsx")
    print(summary.to_string(index=False))
    print(f"\nartifacts written to {a.out}/ for {a.city}")
    print(f"customer caps ok: {summary['customer_cap_ok'].all()} | "
          f"visit caps ok: {summary['visit_cap_ok'].all()}")


if __name__ == "__main__":
    main()
