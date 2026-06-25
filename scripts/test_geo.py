"""Unit tests for insight.geo (pure). Run: .venv/bin/python scripts/test_geo.py"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.insight.geo import normalize_location, cluster_locations  # noqa: E402

def test_normalize():
    assert normalize_location("  Blue Bottle Coffee.  ") == "blue bottle coffee"
    assert normalize_location("BLUE BOTTLE coffee") == "blue bottle coffee"
    assert normalize_location("") is None
    assert normalize_location(None) is None
    assert normalize_location(123) is None

def test_cluster_groups_and_counts():
    out = cluster_locations(["Blue Bottle", "blue bottle", None, "Home", "Home", "Home", ""])
    # Home (3) ranks above Blue Bottle (2); 2 unknowns (None + "")
    assert out["unknown_count"] == 2, out
    names = [(p["name"], p["count"]) for p in out["places"]]
    assert names[0] == ("Home", 3), names
    assert ("Blue Bottle", 2) in names, names

def test_name_is_most_common_spelling():
    out = cluster_locations(["the gym", "The Gym", "The Gym"])
    assert len(out["places"]) == 1
    assert out["places"][0]["name"] == "The Gym" and out["places"][0]["count"] == 3

def main():
    test_normalize(); test_cluster_groups_and_counts(); test_name_is_most_common_spelling()
    print("\033[32mPASS\033[0m geo")

if __name__ == "__main__":
    main()
