"""Fetch a GMU's real boundary polygon from CPW's public ArcGIS
FeatureServer and derive that unit's own analysis bbox. GMU 38 and 59 are
~85 miles apart, so each unit gets its own bbox -- never a bbox unioned
across units (see spec, Data sources)."""

from geo_utils import bounds_of_coords, buffer_bounds
from net import SESSION

FEATURESERVER_URL = (
    "https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/arcgis/rest/services/"
    "CPWAdminData/FeatureServer/6/query"
)


def fetch_gmu_geometry(gmu, timeout=30):
    params = {
        "where": f"GMUID={int(gmu)}",
        "outFields": "GMUID",
        "returnGeometry": "true",
        "f": "geojson",
    }
    resp = SESSION.get(FEATURESERVER_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return parse_gmu_geometry(resp.json(), gmu)


def parse_gmu_geometry(geojson_obj, gmu):
    for feature in geojson_obj.get("features", []):
        if feature["properties"]["GMUID"] == int(gmu):
            return feature["geometry"]
    return None


def unit_bbox(geometry, buffer_mi=2.0):
    bounds = bounds_of_coords(geometry["coordinates"])
    return buffer_bounds(bounds, buffer_mi)
