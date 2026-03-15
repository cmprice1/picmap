#!/usr/bin/env python3
"""
Build data.json from the captured Colab output (154 stops with GPS).

This is a one-time bootstrap script that uses the stop data captured from
the successful extract_metadata.py run before the Colab session expired.
"""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Raw data from successful Colab run (154 stops)
# ---------------------------------------------------------------------------

RAW_STOPS = [
    (1, 34.0255, -118.4035, "Los Angeles", "overnight", 13),
    (2, 34.0269, -118.4061, "Los Angeles", "day", 28),
    (3, 34.3857, -119.5020, "Carpinteria", "day", 816),
    (4, 34.4158, -119.6807, "Santa Barbara", "day", 25),
    (5, 34.4108, -119.6838, "Santa Barbara", "day", 30),
    (6, 34.4160, -119.6781, "Santa Barbara", "day", 52),
    (7, 34.4156, -119.6895, "Santa Barbara", "day", 13),
    (8, 34.4230, -119.7049, "Santa Barbara", "day", 12),
    (9, 34.6006, -120.0995, "Santa Barbara County", "day", 51),
    (10, 34.6664, -120.1154, "Santa Barbara County", "day", 26),
    (11, 35.6280, -120.6882, "Paso Robles", "day", 11),
    (12, 35.5767, -120.6906, "San Luis Obispo County", "day", 15),
    (13, 35.5648, -120.7460, "San Luis Obispo County", "day", 67),
    (14, 35.5649, -120.7465, "San Luis Obispo County", "day", 11),
    (15, 35.5963, -120.6946, "Paso Robles", "day", 4),
    (16, 35.6157, -119.7351, "Kern County", "day", 3),
    (17, 36.3728, -117.6104, "Inyo County", "day", 11),
    (18, 36.6070, -117.1154, "Inyo County", "day", 12),
    (19, 36.2299, -116.7679, "Inyo County", "day", 38),
    (20, 36.3547, -116.7964, "Inyo County", "day", 14),
    (21, 36.4484, -116.8525, "Inyo County", "day", 6),
    (22, 36.1695, -115.1409, "Las Vegas", "day", 10),
    (23, 36.3629, -116.8017, "Inyo County", "day", 45),
    (24, 36.4203, -116.8119, "Inyo County", "day", 74),
    (25, 36.0606, -115.1806, "Clark County", "day", 2),
    (26, 37.1890, -112.9969, "Springdale", "day", 17),
    (27, 37.2148, -112.9596, "Washington County", "day", 25),
    (28, 37.2448, -112.7997, "Kane County", "day", 27),
    (29, 37.2956, -112.9465, "Washington County", "day", 242),
    (30, 37.2534, -112.9600, "Washington County", "day", 8),
    (31, 37.2556, -112.9613, "Washington County", "day", 24),
    (32, 37.2442, -112.7990, "Kane County", "day", 23),
    (33, 37.2458, -112.8021, "Kane County", "day", 184),
    (34, 37.2443, -112.7988, "Kane County", "day", 17),
    (35, 37.2442, -112.7990, "Kane County", "day", 43),
    (36, 37.2446, -112.7996, "Kane County", "overnight", 161),
    (37, 37.2442, -112.7990, "Kane County", "day", 20),
    (38, 37.5158, -112.6993, "Kane County", "day", 5),
    (39, 37.5192, -112.7659, "Kane County", "day", 13),
    (40, 37.6132, -112.8381, "Iron County", "day", 63),
    (41, 37.8200, -114.4103, "Lincoln County", "day", 82),
    (42, 37.9387, -114.4457, "Lincoln County", "day", 11),
    (43, 40.6467, -114.1207, "Elko County", "day", 21),
    (44, 40.7412, -113.8526, "Tooele County", "day", 43),
    (45, 40.7414, -113.8529, "Tooele County", "day", 20),
    (46, 40.7405, -114.0729, "West Wendover", "day", 37),
    (47, 40.7373, -114.0426, "Wendover", "day", 20),
    (48, 42.5978, -114.4772, "Twin Falls", "day", 21),
    (49, 42.5939, -114.4017, "Twin Falls", "day", 37),
    (50, 43.8730, -114.7298, "Blaine County", "day", 74),
    (51, 43.9062, -114.7970, "Blaine County", "day", 38),
    (52, 43.9062, -114.7971, "Blaine County", "day", 17),
    (53, 43.9065, -114.7979, "Blaine County", "day", 22),
    (54, 44.1467, -114.9223, "Custer County", "day", 286),
    (55, 43.9072, -114.7975, "Blaine County", "day", 55),
    (56, 43.9064, -114.7971, "Blaine County", "day", 25),
    (57, 43.9054, -114.7973, "Blaine County", "day", 26),
    (58, 43.9069, -114.7974, "Blaine County", "day", 62),
    (59, 44.1431, -114.9186, "Custer County", "day", 49),
    (60, 44.2692, -114.7425, "Custer County", "day", 20),
    (61, 44.3979, -114.3134, "Custer County", "day", 49),
    (62, 45.6597, -113.9760, "Lemhi County", "day", 4),
    (63, 45.6938, -113.9481, "Ravalli County", "day", 4),
    (64, 46.8681, -113.9972, "Missoula", "day", 29),
    (65, 46.8698, -113.9944, "Missoula", "day", 51),
    (66, 47.9353, -114.1874, "Lake County", "day", 6),
    (67, 48.7341, -113.7456, "Flathead County", "day", 82),
    (68, 48.7267, -113.7242, "Flathead County", "day", 45),
    (69, 48.7005, -113.7118, "Glacier County", "day", 33),
    (70, 48.6764, -113.5814, "Glacier County", "day", 30),
    (71, 48.7468, -113.4380, "Glacier County", "day", 41),
    (72, 48.6940, -113.6766, "Glacier County", "day", 71),
    (73, 48.5713, -113.9165, "Flathead County", "day", 66),
    (74, 48.4404, -114.0410, "Flathead County", "day", 23),
    (75, 48.4212, -114.3409, "Whitefish", "day", 14),
    (76, 48.2665, -114.3303, "Flathead County", "overnight", 2),
    (77, 48.4160, -114.3413, "Whitefish", "day", 11),
    (78, 48.1951, -114.3219, "Kalispell", "day", 18),
    (79, 45.5204, -110.5780, "Park County", "overnight", 36),
    (80, 45.5200, -110.5768, "Park County", "day", 11),
    (81, 45.5206, -110.5778, "Park County", "day", 6),
    (82, 45.5198, -110.5759, "Park County", "day", 41),
    (83, 45.5198, -110.5782, "Park County", "day", 33),
    (84, 45.5193, -110.5790, "Park County", "day", 53),
    (85, 45.5202, -110.5776, "Park County", "day", 21),
    (86, 45.0296, -110.7074, "Park County", "day", 44),
    (87, 44.9662, -110.7150, "Park County", "day", 5),
    (88, 44.6786, -110.7464, "Park County", "day", 11),
    (89, 44.6597, -111.0978, "West Yellowstone", "day", 14),
    (90, 43.7547, -111.0364, "Teton County", "day", 12),
    (91, 43.7544, -111.0424, "Teton County", "day", 26),
    (92, 43.6533, -110.7182, "Teton County", "day", 25),
    (93, 43.8662, -110.5483, "Teton County", "day", 30),
    (94, 43.4799, -110.7623, "Jackson", "day", 54),
    (95, 44.1904, -110.6559, "Teton County", "day", 27),
    (96, 44.5263, -110.8376, "Teton County", "day", 155),
    (97, 44.6558, -111.1011, "West Yellowstone", "day", 9),
    (98, 44.6553, -111.1005, "West Yellowstone", "day", 8),
    (99, 44.5253, -110.8351, "Teton County", "day", 71),
    (100, 44.4602, -110.8297, "Teton County", "day", 107),
    (101, 44.7216, -110.4801, "Park County", "day", 44),
    (102, 44.7316, -110.4872, "Park County", "day", 3),
    (103, 44.7255, -110.4765, "Park County", "day", 74),
    (104, 44.8725, -110.3826, "Park County", "day", 4),
    (105, 44.9141, -110.4166, "Park County", "day", 12),
    (106, 45.3900, -109.1340, "Carbon County", "day", 3),
    (107, 45.6220, -106.4194, "Rosebud County", "day", 46),
    (108, 44.6744, -103.8529, "Belle Fourche", "day", 29),
    (109, 44.3509, -103.9286, "Lawrence County", "day", 85),
    (110, 44.3519, -103.7628, "Lead", "day", 19),
    (111, 43.8280, -103.6314, "Custer County", "day", 99),
    (112, 43.8468, -103.5641, "Custer County", "day", 283),
    (113, 44.3516, -103.9313, "Lawrence County", "day", 13),
    (114, 44.0842, -103.2414, "Rapid City", "day", 14),
    (115, 43.8695, -102.2325, "Pennington County", "day", 36),
    (116, 43.8515, -102.2168, "Pennington County", "day", 104),
    (117, 43.7664, -102.0036, "Jackson County", "day", 37),
    (118, 43.8767, -99.7948, "Lyman County", "day", 10),
    (119, 43.5144, -96.7745, "Sioux Falls", "day", 3),
    (120, 43.6085, -96.3551, "Beaver Creek Township", "day", 10),
    (121, 44.2889, -94.4499, "New Ulm", "day", 33),
    (122, 44.9779, -93.2555, "Minneapolis", "day", 10),
    (123, 44.9777, -93.2552, "Minneapolis", "day", 8),
    (124, 44.9894, -93.2707, "Minneapolis", "day", 65),
    (125, 44.9776, -93.2547, "Minneapolis", "day", 7),
    (126, 44.9775, -93.2535, "Minneapolis", "day", 29),
    (127, 44.9172, -93.2155, "Minneapolis", "day", 7),
    (128, 44.9434, -91.3956, "Chippewa Falls", "day", 13),
    (129, 45.0090, -87.2945, "Town of Egg Harbor", "day", 6),
    (130, 45.2964, -87.0638, "Town of Liberty Grove", "day", 66),
    (131, 45.2075, -87.1205, "Town of Liberty Grove", "day", 19),
    (132, 45.1023, -87.6283, "Marinette", "day", 24),
    (133, 45.4353, -87.4915, "Stephenson Township", "day", 6),
    (134, 45.4353, -87.4915, "Stephenson Township", "overnight", 27),
    (135, 45.4352, -87.4915, "Stephenson Township", "day", 45),
    (136, 45.4352, -87.4915, "Stephenson Township", "day", 7),
    (137, 45.4354, -87.4913, "Stephenson Township", "day", 30),
    (138, 45.4345, -87.4908, "Stephenson Township", "day", 40),
    (139, 45.8740, -84.8082, "Moran Township", "day", 3),
    (140, 44.7476, -85.6467, "Garfield Township", "day", 35),
    (141, 44.7646, -85.6140, "Traverse City", "day", 33),
    (142, 44.7644, -85.6200, "Traverse City", "day", 62),
    (143, 44.7645, -85.6204, "Traverse City", "day", 36),
    (144, 44.9671, -85.9243, "Cleveland Township", "day", 95),
    (145, 44.9377, -85.9368, "Glen Arbor Township", "day", 12),
    (146, 43.9523, -86.4483, "Ludington", "day", 6),
    (147, 41.6252, -87.2062, "Portage", "day", 173),
    (148, 41.5981, -87.3067, "Gary", "day", 53),
    (149, 39.0922, -84.5655, "Cincinnati", "day", 20),
    (150, 38.1481, -81.2145, "Fayette County", "day", 5),
    (151, 38.1542, -81.1793, "Gauley Bridge", "day", 154),
    (152, 38.1222, -81.1291, "Fayette County", "day", 85),
    (153, 38.0702, -81.0780, "Fayette County", "day", 141),
    (154, 36.5610, -80.7460, "Surry County", "day", 20),
]

# Location-aware name mapping: (geocoded_name, lon_range) -> better_name
# Uses longitude ranges to disambiguate same-named counties in different states
def get_better_name(geocoded_name, lat, lon):
    """Return a better name based on geocoded name and location."""
    # Exact or specific names that don't need disambiguation
    SIMPLE_RENAMES = {
        "Carpinteria": "Carpinteria",
        "Kern County": "Bakersfield Area",
        "Clark County": "Las Vegas",
        "Springdale": "Zion / Springdale",
        "Iron County": "Cedar Breaks",
        "Elko County": "Wells / NV",
        "West Wendover": "Wendover",
        "Wendover": "Wendover",
        "Blaine County": "Sun Valley",
        "Lemhi County": "Salmon River",
        "Ravalli County": "Bitterroot Valley",
        "Lake County": "Flathead Lake",
        "Flathead County": "Kalispell / Glacier",
        "Glacier County": "Glacier National Park",
        "Carbon County": "Red Lodge",
        "Rosebud County": "Eastern Montana",
        "Lyman County": "Chamberlain / SD",
        "Beaver Creek Township": "Sioux Falls Area",
        "Town of Egg Harbor": "Door County",
        "Town of Liberty Grove": "Door County",
        "Stephenson Township": "Stephenson, MI",
        "Moran Township": "Mackinac Area",
        "Garfield Township": "Traverse City Area",
        "Cleveland Township": "Sleeping Bear Dunes",
        "Glen Arbor Township": "Sleeping Bear Dunes",
        "Surry County": "Blue Ridge / NC",
        "New Ulm": "New Ulm, MN",
        "Chippewa Falls": "Chippewa Falls, WI",
        "Marinette": "Marinette, WI",
        "Portage": "Portage, IN",
        "Gary": "Gary, IN",
        "Gauley Bridge": "New River Gorge",
    }

    if geocoded_name in SIMPLE_RENAMES:
        return SIMPLE_RENAMES[geocoded_name]

    # Disambiguate by location
    if geocoded_name == "Inyo County":
        if lon < -117:
            return "Lone Pine"
        else:
            return "Death Valley"

    if geocoded_name == "Washington County":
        return "Zion National Park"

    if geocoded_name == "Kane County":
        if lat > 37.4:
            return "Bryce Canyon"
        else:
            return "Zion Area"

    if geocoded_name == "Lincoln County":
        return "Caliente, NV"

    if geocoded_name == "Tooele County":
        return "Bonneville Salt Flats"

    if geocoded_name == "Custer County":
        if lon < -110:  # Idaho
            return "Sawtooth Valley"
        else:  # South Dakota
            return "Custer State Park"

    if geocoded_name == "Park County":
        if lat > 45:  # Montana (Livingston)
            return "Livingston, MT"
        else:  # Wyoming (Yellowstone)
            return "Yellowstone"

    if geocoded_name == "Teton County":
        if lat < 44:
            return "Jackson Hole"
        else:
            return "Yellowstone / Tetons"

    if geocoded_name == "Lawrence County":
        return "Deadwood / Spearfish"

    if geocoded_name == "Pennington County":
        return "Badlands"

    if geocoded_name == "Jackson County":
        return "Badlands Area"

    if geocoded_name == "Fayette County":
        if lon < -81:  # West Virginia
            return "New River Gorge"
        else:
            return "Fayette County"

    if geocoded_name == "San Luis Obispo County":
        return "Paso Robles Area"

    if geocoded_name == "Santa Barbara County":
        return "Gaviota Coast"

    return geocoded_name

# ---------------------------------------------------------------------------
# Consolidation: merge micro-stops within ~10km into macro-stops
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def consolidate_stops(raw, radius_km=15):
    """Merge micro-stops that are within radius_km of each other."""
    groups = []
    used = set()

    for i, stop in enumerate(raw):
        if i in used:
            continue
        group = [stop]
        used.add(i)
        for j, other in enumerate(raw):
            if j in used:
                continue
            dist = haversine_km(stop[1], stop[2], other[1], other[2])
            if dist <= radius_km:
                group.append(other)
                used.add(j)
        groups.append(group)

    # Build consolidated stops
    consolidated = []
    for group in groups:
        lat = sum(s[1] for s in group) / len(group)
        lon = sum(s[2] for s in group) / len(group)
        total_photos = sum(s[5] for s in group)

        # Use best name from location-aware mapping
        # Pick the name from the sub-stop with most photos
        best_sub = max(group, key=lambda s: s[5])
        name = get_better_name(best_sub[3], best_sub[1], best_sub[2])

        # Type: overnight if any sub-stop is overnight
        stop_type = "day"
        for s in group:
            if s[4] == "overnight":
                stop_type = "overnight"
                break
        # Promote to overnight if total photos > 100
        if total_photos > 150 and stop_type == "day":
            stop_type = "overnight"

        consolidated.append({
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "name": name,
            "type": stop_type,
            "photo_count": total_photos,
            "sub_stops": len(group),
        })

    return consolidated


# ---------------------------------------------------------------------------
# Build data.json
# ---------------------------------------------------------------------------

def build_route(stops):
    """Build GeoJSON LineString through ordered stops."""
    coords = []
    pts = [[s["lng"], s["lat"]] for s in stops]

    for i in range(len(pts) - 1):
        p1, p2 = pts[i], pts[i + 1]
        for j in range(20):
            t = j / 20
            coords.append([
                round(p1[0] + (p2[0] - p1[0]) * t, 6),
                round(p1[1] + (p2[1] - p1[1]) * t, 6),
            ])

    if pts:
        coords.append(pts[-1])

    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}}


def main():
    # Consolidate 154 micro-stops into meaningful locations
    consolidated = consolidate_stops(RAW_STOPS, radius_km=15)

    # Sort roughly west-to-east (approximation of trip order by longitude)
    # Actually sort by the first sub-stop's original order
    # Since RAW_STOPS is already in chronological order, and consolidation
    # preserves the order of the first occurrence, this should be fine.

    # Generate approximate dates (Jun 28 - Aug 3 = 37 days)
    start_date = datetime(2025, 6, 28, tzinfo=timezone.utc)
    end_date = datetime(2025, 8, 3, tzinfo=timezone.utc)
    total_days = (end_date - start_date).days
    n_stops = len(consolidated)

    stops = []
    for i, s in enumerate(consolidated):
        # Distribute dates evenly across the trip
        day_offset = int(i * total_days / n_stops)
        arrival = start_date + timedelta(days=day_offset, hours=10)
        if s["type"] == "overnight":
            departure = arrival + timedelta(hours=18)
        else:
            departure = arrival + timedelta(hours=2)

        order = i + 1
        stop_id = f"stop_{order:02d}"

        # No real photos yet, use empty list
        stops.append({
            "id": stop_id,
            "name": s["name"],
            "location": s["name"],
            "lat": s["lat"],
            "lng": s["lon"],
            "arrival": arrival.isoformat(),
            "departure": departure.isoformat(),
            "duration_hours": round((departure - arrival).total_seconds() / 3600, 1),
            "type": s["type"],
            "order": order,
            "photo_count": s["photo_count"],
            "representative_photo": "",
            "photos": [],
        })

    route = build_route(stops)

    # Hero photos from overnight stops
    hero_stops = [s for s in stops if s["type"] == "overnight"][:3]
    hero_photos = [s["representative_photo"] for s in hero_stops if s["representative_photo"]]

    data = {
        "trip": {
            "title": "Great American Road Trip",
            "subtitle": "LA to Raleigh \u00b7 Summer 2025",
            "start_date": "2025-06-28",
            "end_date": "2025-08-03",
            "hero_photos": hero_photos,
        },
        "stops": stops,
        "waypoints": [],
        "route": route,
    }

    # Save
    output = Path("output")
    output.mkdir(exist_ok=True)
    with open(output / "data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Report
    overnight = sum(1 for s in stops if s["type"] == "overnight")
    day = sum(1 for s in stops if s["type"] == "day")
    print(f"\nBuilt data.json with {len(stops)} stops ({overnight} overnight, {day} day)")
    print(f"Route: {len(route['geometry']['coordinates'])} coordinates")
    print(f"\nStops:")
    for s in stops:
        marker = "*" if s["type"] == "overnight" else " "
        print(f"  {marker} {s['order']:2d}. {s['name'][:35]:<35} ({s['type']}, {s['photo_count']} photos)")


if __name__ == "__main__":
    main()
