# Methodology Note (template)

*This is the 1–2 page note that ships with each city. Numbers below are from the
synthetic Riyadh demo and are illustrative.*

## 1. Objective
Partition a city's customer base (GPS points + 4-month sales history) into a set
of sales-rep territories that are (a) geographically compact and contiguous,
(b) within capacity caps, and (c) as evenly loaded as the geography allows.

## 2. Recommended visits (frequency matrix)
Each customer is assigned a recommended monthly visit count from a
**value tier × activity tier** grid:
- Value tier = tertile of average monthly sales.
- Activity tier = tertile of average monthly invoices.
- Inactive customers (no invoices in the window) → 0 visits.

The grid used here ranges 1–8 visits/month. **We replace this with your exact
Jeddah frequency matrix** — the code change is a single dictionary.

## 3. Clustering
KMeans on `(lat, lon × cos(lat))` so Euclidean distance approximates real ground
distance. KMeans gives compact, convex, non-overlapping seed regions — the
correct starting point for territories a single rep can service without
crossing the city. The number of zones is a parameter (default 12).

*Alternatives considered:* k-medoids (robust to outliers, slower), DBSCAN
(finds density clusters but won't honour a fixed zone count or caps), and
road-network / drive-time clustering (most realistic — see §6).

## 4. Capacity balancing
Seed clusters ignore caps, so we rebalance:
- Identify zones over the **customer cap (240)** or **visit cap (520/mo, hard)**.
- From the most-overloaded zone, move **border** customers (those with a nearest
  neighbour in another zone) to the **adjacent** zone with the most spare visit
  capacity.
- Only border points move, so zones never fragment into islands.
- Iterate until all hard caps hold and soft caps are met as far as geography allows.

## 5. Boundaries & outputs
A convex hull per zone becomes the territory polygon, exported to **KML**
(Google Earth/Maps) and drawn on the **interactive Leaflet map**. Production can
use concave (alpha-shape) boundaries for tighter outlines.

## 6. Assumptions & options
- Distances are great-circle approximations, adequate at city scale.
- **Drive-time aware zoning** (OSRM / OSMnx road network) is available as an
  add-on if straight-line compactness is not enough.
- Caps and zone count are CLI parameters — the client can re-run unaided.

## 7. Demo result (synthetic Riyadh, 1,300 customers, 12 zones)
All 12 zones within both caps; visit load 273–519/mo against the 520 hard cap;
customer counts 74–174 against the 240 soft cap.
