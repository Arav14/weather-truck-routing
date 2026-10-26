import bisect
import math

EARTH_RADIUS_MI = 3958.7613


def haversine_mi(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(a)))


def cumulative_miles(coords):
    cum = [0.0]
    for p, q in zip(coords, coords[1:]):
        cum.append(cum[-1] + haversine_mi(*p, *q))
    return cum


def sample_miles(total, spacing):
    """Mile markers 0, spacing, 2*spacing ... plus the destination."""
    if total <= 0:
        return [0.0]
    miles, m = [], 0.0
    while m < total - 1e-9:
        miles.append(m)
        m += spacing
    if len(miles) > 1 and total - miles[-1] < spacing * 0.25:
        miles.pop()  # avoid a near-duplicate checkpoint right before the destination
    miles.append(total)
    return miles


def segment_lengths(miles):
    """Miles of road each checkpoint 'owns' (halfway to its neighbours). Sums to total."""
    n = len(miles)
    out = []
    for i, m in enumerate(miles):
        lo = m if i == 0 else (miles[i - 1] + m) / 2
        hi = m if i == n - 1 else (m + miles[i + 1]) / 2
        out.append(hi - lo)
    return out


def point_at(coords, cum, mile):
    i = bisect.bisect_right(cum, mile) - 1
    i = max(0, min(i, len(coords) - 2))
    seg = cum[i + 1] - cum[i]
    t = 0.0 if seg <= 0 else min(1.0, max(0.0, (mile - cum[i]) / seg))
    return (
        coords[i][0] + (coords[i + 1][0] - coords[i][0]) * t,
        coords[i][1] + (coords[i + 1][1] - coords[i][1]) * t,
    )


def downsample(coords, max_points=1500):
    if len(coords) <= max_points:
        return coords
    step = math.ceil(len(coords) / max_points)
    out = coords[::step]
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out


def bearing_deg(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def destination_point(lat, lng, bearing, dist_mi):
    d = dist_mi / EARTH_RADIUS_MI
    b, p1, l1 = math.radians(bearing), math.radians(lat), math.radians(lng)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2)
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def overlap_fraction(a, b, tol_mi=1.5):
    """Share of route `a` that runs within tol_mi of route `b` (used to reject near-duplicate routes)."""
    ia = a[:: max(1, len(a) // 150)]
    ib = b[:: max(1, len(b) // 400)]
    close = sum(1 for p in ia if min(haversine_mi(*p, *q) for q in ib) <= tol_mi)
    return close / len(ia)
