#!/usr/bin/env python3
"""
Reclassify stops as overnight/day based on the real trip itinerary.
Updates data.json in place.
"""

import json
import math
from pathlib import Path

# Known overnight locations from the itinerary spreadsheet
# (city, approx_lat, approx_lon, arrive_date, depart_date)
OVERNIGHTS = [
    ("Santa Barbara",       34.42,  -119.69,  "2025-06-28", "2025-06-30"),
    ("Paso Robles",         35.63,  -120.69,  "2025-06-30", "2025-07-02"),
    ("Lone Pine",           36.37,  -117.61,  "2025-07-02", "2025-07-03"),
    ("Pahrump",             36.17,  -115.14,  "2025-07-03", "2025-07-04"),
    ("Zion",                37.25,  -112.95,  "2025-07-04", "2025-07-07"),
    ("Wendover",            40.74,  -114.04,  "2025-07-07", "2025-07-08"),
    ("Sun Valley",          43.91,  -114.80,  "2025-07-08", "2025-07-11"),
    ("Missoula",            46.87,  -114.00,  "2025-07-11", "2025-07-12"),
    ("Kalispell",           48.20,  -114.33,  "2025-07-12", "2025-07-15"),
    ("Livingston",          45.52,  -110.58,  "2025-07-15", "2025-07-17"),
    ("Driggs",              43.75,  -111.04,  "2025-07-17", "2025-07-18"),
    ("West Yellowstone",    44.66,  -111.10,  "2025-07-18", "2025-07-19"),
    ("Canyon Village",      44.73,  -110.49,  "2025-07-19", "2025-07-20"),
    ("Billings",            45.39,  -109.13,  "2025-07-20", "2025-07-21"),
    ("Spearfish",           44.49,  -103.86,  "2025-07-21", "2025-07-23"),
    ("Sioux Falls",         43.55,  -96.73,   "2025-07-23", "2025-07-24"),
    ("Minneapolis",         44.98,  -93.27,   "2025-07-24", "2025-07-26"),
    ("Green Bay",           45.01,  -87.29,   "2025-07-26", "2025-07-27"),
    ("Stephenson",          45.44,  -87.49,   "2025-07-27", "2025-07-29"),
    ("Copper Harbor",       45.87,  -84.81,   "2025-07-29", "2025-07-31"),
    ("Traverse City",       44.76,  -85.62,   "2025-07-31", "2025-08-02"),
    ("Columbus area",       39.09,  -84.57,   "2025-08-02", "2025-08-03"),
    ("Raleigh",             36.56,  -80.75,   "2025-08-03", "2025-08-04"),
]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def main():
    data_path = Path("output/data.json")
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    old_overnight = sum(1 for s in data["stops"] if s["type"] == "overnight")

    # Reset all to day first
    for stop in data["stops"]:
        stop["type"] = "day"

    # For each known overnight location, find the closest stop within 30km
    # and mark it as overnight
    matched = []
    for city, olat, olon, arrive, depart in OVERNIGHTS:
        best_stop = None
        best_dist = 999

        for stop in data["stops"]:
            dist = haversine_km(stop["lat"], stop["lng"], olat, olon)
            # Check proximity AND that arrival date overlaps the stay period
            arrival_date = stop.get("arrival", "")[:10]
            in_range = arrive <= arrival_date <= depart if arrival_date >= "2025" else True

            if dist < 60 and dist < best_dist and in_range:
                best_dist = dist
                best_stop = stop

        if best_stop:
            best_stop["type"] = "overnight"
            matched.append(f"  {city:<22} -> stop {best_stop['order']:3d}. {best_stop['name'][:25]:<25} ({best_dist:.1f}km)")
        else:
            matched.append(f"  {city:<22} -> NO MATCH (closest stop too far or wrong date)")

    new_overnight = sum(1 for s in data["stops"] if s["type"] == "overnight")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Reclassified: {old_overnight} -> {new_overnight} overnight stops")
    print(f"\nMatches:")
    for m in matched:
        print(m)


if __name__ == "__main__":
    main()
