import json
import os
import time
from pathlib import Path

import yaml
import matplotlib.pyplot as plt
import contextily as ctx

from geopy.geocoders import Nominatim, Photon
from geopy.exc import GeocoderTimedOut, GeocoderServiceError, GeocoderUnavailable
from pyproj import Transformer

from util import data_dir, map_source


# ============================================================
# Configuration
# ============================================================

_nominatim = Nominatim(
    user_agent="travel_animator"
)

_photon = Photon(
    user_agent="travel_animator"
)

# Tried in order for each query variant. Nominatim first (better
# structured/address matching); Photon second (different OSM-backed
# index, often more forgiving of informal or fuzzy place names).
_PROVIDERS = [
    ("Nominatim", _nominatim),
    ("Photon", _photon),
]

CACHE_FILE = os.path.join(
    data_dir,
    "json",
    "geocode_cache.json"
)


# Transformer for plotting on an OSM basemap.
# Geocoding returns WGS84 (lat/lon), while contextily
# uses Web Mercator.
transformer = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:3857",
    always_xy=True
)


# ============================================================
# Load geocode cache
# ============================================================

if Path(CACHE_FILE).exists():

    with open(CACHE_FILE, "r", encoding="utf-8") as f:

        cache = json.load(f)

else:

    cache = {}


# ============================================================
# Geocoding
# ============================================================

def _cache_key(place, country):

    # Only change the key shape when a country hint is actually
    # used, so existing cache files (keyed by bare place string)
    # stay valid for the common case.

    if country:
        return f"{place}::{country}"

    return place


def _build_query_variants(place, country=None):

    variants = []

    base = place.strip()

    variants.append(base)

    if country and country.lower() not in base.lower():
        variants.append(f"{base}, {country}")

    # Strip parenthetical notes:
    # "Central Station (Main Entrance)" -> "Central Station"
    if "(" in base:

        stripped = base.split("(")[0].strip().rstrip(",")

        if stripped and stripped not in variants:
            variants.append(stripped)

    # If it reads like "Thing, extra detail", also try just the
    # first component -- trailing detail sometimes confuses
    # geocoders more than it helps them.
    if "," in base:

        first_component = base.split(",")[0].strip()

        if first_component and first_component not in variants:
            variants.append(first_component)

    return variants


def _geocode_one(geocoder_obj, provider_name, query, viewbox=None, max_retries=3, base_delay=1.5):

    for attempt in range(max_retries):

        try:

            kwargs = {"exactly_one": True}

            # viewbox/bounded is a Nominatim-specific param; other
            # providers don't accept it.
            if viewbox is not None and provider_name == "Nominatim":
                kwargs["viewbox"] = viewbox
                kwargs["bounded"] = False  # bias towards the box, don't exclude results outside it

            return geocoder_obj.geocode(query, **kwargs)

        except (GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError) as exc:

            if attempt == max_retries - 1:

                print(
                    f"    {provider_name} error for '{query}': {exc} "
                    f"(giving up after {max_retries} attempts)"
                )

                return None

            wait = base_delay * (2 ** attempt)

            print(
                f"    {provider_name} error for '{query}': {exc} "
                f"-- retrying in {wait:.1f}s"
            )

            time.sleep(wait)

    return None


def geocode(place, preferred_name=None, near=None, country=None):

    # --------------------------------------------------------
    # Check cache first
    # --------------------------------------------------------

    key = _cache_key(place, country)

    if key in cache:

        result = cache[key]

        print(
            f"Using cached geocode for "
            f"{place} -> "
            f"Lat: {result['lat']}, "
            f"Lon: {result['lon']}"
        )

        if "display_name" in result:

            print(
                f"    Resolved as: "
                f"{result['display_name']}"
            )

        return result


    # --------------------------------------------------------
    # Build a soft geographic bias from the previous stop.
    #
    # This nudges ambiguous/common place names ("Central
    # Station", "Main Street") toward the right region without
    # excluding legitimately distant matches -- bounded=False
    # in _geocode_one() means it's a ranking preference, not a
    # hard filter, so a transcontinental flight leg still
    # resolves fine.
    # --------------------------------------------------------

    viewbox = None

    if near is not None:

        lat, lon = near

        pad = 2.0  # degrees -- generous, just a bias

        viewbox = [(lon - pad, lat - pad), (lon + pad, lat + pad)]


    print(f"Looking up: {place}")

    variants = _build_query_variants(place, country)

    attempted = []

    for provider_name, geocoder_obj in _PROVIDERS:

        for query in variants:

            attempted.append(f"{provider_name}:'{query}'")

            location = _geocode_one(
                geocoder_obj,
                provider_name,
                query,
                viewbox=viewbox
            )

            # Be polite to whichever free service we just hit,
            # success or failure.
            time.sleep(1)

            if location is None:
                continue

            result = {

                "name": place if preferred_name is None else preferred_name,

                "lat": location.latitude,

                "lon": location.longitude,

                "display_name": getattr(location, "address", str(location))

            }

            if provider_name != "Nominatim":
                result["geocoder"] = provider_name

            print(
                f"Looking up: {place} -> "
                f"Lat: {result['lat']}, "
                f"Lon: {result['lon']}"
            )

            print(
                f"    Resolved as: "
                f"{result['display_name']} (via {provider_name})"
            )

            cache[key] = result

            return result


    # --------------------------------------------------------
    # Every provider and every query variant came up empty.
    # --------------------------------------------------------

    raise RuntimeError(
        f"Couldn't geocode '{place}'. Tried: {', '.join(attempted)}. "
        f"If this is a real place that just doesn't resolve well "
        f"(a trailhead, an informal meeting point, a specific "
        f"building entrance, etc.), you can skip geocoding for it "
        f"entirely by adding 'lat' and 'lon' directly to that stop "
        f"in the trip YAML."
    )


def resolve_location(spec, near=None):

    # --------------------------------------------------------
    # Manual override: if lat/lon are given directly in the
    # YAML, skip geocoding entirely. This is the escape hatch
    # for places no geocoder will ever find correctly.
    # --------------------------------------------------------

    if "lat" in spec and "lon" in spec:

        return {

            "name": spec.get("label", spec["name"]),

            "lat": spec["lat"],

            "lon": spec["lon"],

            "display_name": spec.get(
                "display_name",
                f"Manually specified location: {spec['name']}"
            )

        }

    near_coords = (near["lat"], near["lon"]) if near is not None else None

    return geocode(
        spec["name"],
        preferred_name=spec.get("label"),
        near=near_coords,
        country=spec.get("country")
    )


# ============================================================
# Coordinate projection
# ============================================================

def project(lon, lat):

    return transformer.transform(
        lon,
        lat
    )


# ============================================================
# Plot verification map
# ============================================================

def plot_geocoded_trip(
    segments
):

    if not segments:

        print("No segments to plot.")

        return


    fig, ax = plt.subplots(
        figsize=(4, 4),
        dpi=300
    )


    # --------------------------------------------------------
    # Collect all locations
    # --------------------------------------------------------

    locations = {}

    for segment in segments:

        start = segment["from"]
        end = segment["to"]

        locations[start["name"]] = start
        locations[end["name"]] = end


    # --------------------------------------------------------
    # Plot segment lines first
    # --------------------------------------------------------
    #
    # These are ONLY verification lines.
    #
    # They are not the actual travel routes that the
    # animation engine will eventually generate.
    #
    # For now they simply show:
    #
    # from location ----------------> to location
    #
    # --------------------------------------------------------

    for segment in segments:

        start = segment["from"]
        end = segment["to"]


        x1, y1 = project(
            start["lon"],
            start["lat"]
        )

        x2, y2 = project(
            end["lon"],
            end["lat"]
        )


        ax.plot(
            [x1, x2],
            [y1, y2],
            linewidth=2,
            alpha=0.5,
            zorder=1
        )


    # --------------------------------------------------------
    # Plot locations
    # --------------------------------------------------------

    for index, (name, location) in enumerate(
        locations.items(),
        start=1
    ):

        x, y = project(
            location["lon"],
            location["lat"]
        )


        ax.scatter(
            x,
            y,
            s=100,
            zorder=5
        )


        # Numbered marker

        ax.text(
            x,
            y,
            str(index),
            fontsize=9,
            ha="center",
            va="center",
            zorder=6
        )


        # Name label

        ax.annotate(
            name,
            xy=(x, y),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            zorder=7
        )


    # --------------------------------------------------------
    # Add OpenStreetMap basemap
    # --------------------------------------------------------

    ctx.add_basemap(
        ax,
        source=map_source,
        zorder=0
    )


    # --------------------------------------------------------
    # Determine bounds
    # --------------------------------------------------------

    xs = []
    ys = []


    for location in locations.values():

        x, y = project(
            location["lon"],
            location["lat"]
        )

        xs.append(x)
        ys.append(y)


    min_x = min(xs)
    max_x = max(xs)

    min_y = min(ys)
    max_y = max(ys)


    # Add padding around trip

    x_padding = (max_x - min_x) * 0.10
    y_padding = (max_y - min_y) * 0.10


    # Handle trips where all points are very close together.

    if x_padding == 0:

        x_padding = 5000


    if y_padding == 0:

        y_padding = 5000


    ax.set_xlim(
        min_x - x_padding,
        max_x + x_padding
    )

    ax.set_ylim(
        min_y - y_padding,
        max_y + y_padding
    )


    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    ax.set_title(
        "Geocoding Verification",
        fontsize=18,
        pad=15
    )


    ax.axis("off")
    plt.show(block=False)


# ============================================================
# Build JSON trip
# ============================================================

def make_json_trip_file_from_yaml(
    yaml_file,
    output_json_file,
    plot=False
):

    # --------------------------------------------------------
    # Load YAML
    # --------------------------------------------------------

    with open(
        yaml_file,
        "r",
        encoding="utf-8"
    ) as f:

        trip = yaml.safe_load(f)


    segments = []


    # --------------------------------------------------------
    # Process segments
    # --------------------------------------------------------
    #
    # `previous_to_location` carries the FULL resolved location
    # dict forward (not just a name string), so an implicitly
    # inherited "from" reuses the exact coordinates already
    # resolved for the prior segment's "to" -- including a
    # manually-specified lat/lon override -- instead of
    # silently re-geocoding it by name.
    # --------------------------------------------------------

    previous_to_location = None


    for segment in trip["segments"]:

        # ----------------------------------------------------
        # Determine origin
        # ----------------------------------------------------

        if "from" in segment:

            from_location = resolve_location(
                segment["from"],
                near=previous_to_location
            )

        elif previous_to_location is not None:

            from_location = previous_to_location

        else:

            raise ValueError(
                "Segment has no 'from' location "
                "and there is no previous destination."
            )


        # ----------------------------------------------------
        # Determine destination
        # ----------------------------------------------------

        to_location = resolve_location(
            segment["to"],
            near=from_location
        )


        # ----------------------------------------------------
        # Build segment
        # ----------------------------------------------------

        segments.append({

            "mode": segment["mode"],

            "duration": segment["duration"],

            "from": from_location,

            "to": to_location

        })


        # ----------------------------------------------------
        # Next segment starts here
        # ----------------------------------------------------

        previous_to_location = to_location


    # --------------------------------------------------------
    # Build output
    # --------------------------------------------------------

    if "fps" not in trip:
        raise ValueError(
            "Trip YAML is missing 'fps' (frames per second) specification."
        )
    if "dpi" not in trip:
        raise ValueError(
            "Trip YAML is missing 'dpi' (dots per inch) specification."
        )

    output = {

        "fps": trip["fps"],
        "dpi": trip["dpi"],
        "segments": segments

    }


    # --------------------------------------------------------
    # Ensure output directory exists
    # --------------------------------------------------------

    os.makedirs(
        os.path.dirname(output_json_file),
        exist_ok=True
    )


    # --------------------------------------------------------
    # Write JSON
    # --------------------------------------------------------

    with open(
        output_json_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=4
        )


    # --------------------------------------------------------
    # Save geocoding cache
    # --------------------------------------------------------

    os.makedirs(
        os.path.dirname(CACHE_FILE),
        exist_ok=True
    )


    with open(
        CACHE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            cache,
            f,
            indent=4
        )


    print(
        f"\nSaved trip JSON:"
        f"\n    {output_json_file}"
    )


    # --------------------------------------------------------
    # Generate verification plot
    # --------------------------------------------------------

    if plot:
        plot_geocoded_trip(segments)