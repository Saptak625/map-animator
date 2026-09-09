import json
import os
import time
from pathlib import Path

import yaml
import matplotlib.pyplot as plt
import contextily as ctx
import requests

from pyproj import Transformer

from util import data_dir, map_source


# ============================================================
# Configuration
# ============================================================

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

GOOGLE_GEOCODING_URL = (
    "https://maps.googleapis.com/maps/api/geocode/json"
)

GOOGLE_REQUEST_RETRIES = 3
GOOGLE_REQUEST_RETRY_DELAY = 1.5
GOOGLE_REQUEST_TIMEOUT = 10


if not GOOGLE_API_KEY:
    raise RuntimeError(
        "GOOGLE_API_KEY environment variable is not set.\n"
        "Set it to your Google Maps Platform API key before "
        "running the trip builder."
    )


CACHE_FILE = os.path.join(
    data_dir,
    "json",
    "geocode_cache.json"
)


# ============================================================
# Transformer for plotting
# ============================================================
#
# Geocoding returns WGS84 (lat/lon).
# Contextily uses Web Mercator.
# ============================================================

transformer = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:3857",
    always_xy=True
)


# ============================================================
# Load geocode cache
# ============================================================

if Path(CACHE_FILE).exists():

    with open(
        CACHE_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        cache = json.load(f)

else:

    cache = {}


# ============================================================
# Geocoding helpers
# ============================================================

def _cache_key(place, country):

    if country:
        return f"{place}::{country}"

    return place


def _build_query_variants(
    place,
    country=None
):

    variants = []

    base = place.strip()

    variants.append(base)

    # --------------------------------------------------------
    # Country-qualified version
    # --------------------------------------------------------

    if country and country.lower() not in base.lower():

        variants.append(
            f"{base}, {country}"
        )

    # --------------------------------------------------------
    # Strip parenthetical notes
    #
    # Example:
    #
    #     Central Station (Main Entrance)
    #
    # becomes:
    #
    #     Central Station
    # --------------------------------------------------------

    if "(" in base:

        stripped = (
            base
            .split("(")[0]
            .strip()
            .rstrip(",")
        )

        if (
            stripped
            and stripped not in variants
        ):

            variants.append(stripped)

    # --------------------------------------------------------
    # Try first comma-separated component.
    #
    # This can help when a YAML entry contains excessive
    # descriptive information.
    # --------------------------------------------------------

    if "," in base:

        first_component = (
            base
            .split(",")[0]
            .strip()
        )

        if (
            first_component
            and first_component not in variants
        ):

            variants.append(first_component)

    return variants


# ============================================================
# Google Maps API request
# ============================================================

def _google_geocode_one(
    query,
    near=None,
    country=None,
    max_retries=GOOGLE_REQUEST_RETRIES,
    base_delay=GOOGLE_REQUEST_RETRY_DELAY
):

    # --------------------------------------------------------
    # Base request parameters
    # --------------------------------------------------------

    params = {

        "address": query,

        "key": GOOGLE_API_KEY,

    }

    # --------------------------------------------------------
    # Country restriction
    #
    # Google expects ISO country codes here, so this is only
    # used when the supplied country value looks like one.
    #
    # For names such as "France", the address itself already
    # contains the country.
    # --------------------------------------------------------

    if country and len(country.strip()) == 2:

        params["components"] = (
            f"country:{country.strip()}"
        )

    # --------------------------------------------------------
    # Soft geographic bias
    #
    # Google doesn't use Nominatim's viewbox format.
    #
    # Instead, use bounds around the previous stop. This biases
    # results toward the previous geographic region without
    # forcing the result to be there.
    # --------------------------------------------------------

    if near is not None:

        lat, lon = near

        # Roughly ±2 degrees.
        #
        # This is deliberately generous so that a long-distance
        # flight is not accidentally forced into the origin
        # region.
        pad = 2.0

        params["bounds"] = (
            f"{lat - pad},{lon - pad}|"
            f"{lat + pad},{lon + pad}"
        )

    # --------------------------------------------------------
    # Request with retry handling
    # --------------------------------------------------------

    last_error = None

    for attempt in range(max_retries):

        try:

            response = requests.get(
                GOOGLE_GEOCODING_URL,
                params=params,
                timeout=GOOGLE_REQUEST_TIMEOUT,
                headers={
                    "User-Agent": "travel-animator/1.0"
                }
            )

            response.raise_for_status()

            data = response.json()

            status = data.get("status")

            # ------------------------------------------------
            # Successful request
            # ------------------------------------------------

            if status == "OK":

                results = data.get(
                    "results",
                    []
                )

                if not results:

                    return None

                return results[0]

            # ------------------------------------------------
            # No result
            # ------------------------------------------------

            if status == "ZERO_RESULTS":

                return None

            # ------------------------------------------------
            # Invalid API configuration
            #
            # Don't retry these because another request won't
            # fix the problem.
            # ------------------------------------------------

            if status in {
                "REQUEST_DENIED",
                "INVALID_REQUEST",
            }:

                error_message = data.get(
                    "error_message",
                    "No additional information."
                )

                raise RuntimeError(
                    f"Google Geocoding API returned "
                    f"{status}: {error_message}"
                )

            # ------------------------------------------------
            # Potentially transient error
            # ------------------------------------------------

            raise RuntimeError(
                f"Google Geocoding API returned "
                f"{status}"
            )

        except (
            requests.RequestException,
            RuntimeError
        ) as exc:

            last_error = exc

            if attempt >= max_retries - 1:

                print(
                    f"    Google Geocoding error for "
                    f"'{query}': {exc} "
                    f"(giving up after "
                    f"{max_retries} attempts)"
                )

                return None

            wait = (
                base_delay *
                (2 ** attempt)
            )

            print(
                f"    Google Geocoding error for "
                f"'{query}': {exc} "
                f"-- retrying in "
                f"{wait:.1f}s"
            )

            time.sleep(wait)

    return None


# ============================================================
# Geocode a location
# ============================================================

def geocode(
    place,
    preferred_name=None,
    near=None,
    country=None
):

    # --------------------------------------------------------
    # Check cache first
    # --------------------------------------------------------

    key = _cache_key(
        place,
        country
    )

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
    # Build query variants
    # --------------------------------------------------------

    print(
        f"Looking up: {place}"
    )

    variants = _build_query_variants(
        place,
        country
    )

    attempted = []

    # --------------------------------------------------------
    # Try each query variant
    # --------------------------------------------------------

    for query in variants:

        attempted.append(
            f"Google:'{query}'"
        )

        location = _google_geocode_one(
            query,
            near=near,
            country=country
        )

        # ----------------------------------------------------
        # Small delay between requests.
        #
        # Google is not the same kind of free public service
        # as Nominatim, but keeping requests serialized is
        # still sensible for this batch workflow.
        # ----------------------------------------------------

        time.sleep(0.25)

        if location is None:
            continue

        # ----------------------------------------------------
        # Extract geometry
        # ----------------------------------------------------

        geometry = location.get(
            "geometry",
            {}
        )

        coordinates = geometry.get(
            "location"
        )

        if not coordinates:

            continue

        lat = coordinates["lat"]
        lon = coordinates["lng"]

        # ----------------------------------------------------
        # Build result in the SAME structure used by the
        # rest of the project.
        # ----------------------------------------------------

        result = {

            "name": (
                place
                if preferred_name is None
                else preferred_name
            ),

            "lat": lat,

            "lon": lon,

            "display_name": location.get(
                "formatted_address",
                place
            ),

            "geocoder": "Google",

            "place_id": location.get(
                "place_id"
            ),

            "location_type": geometry.get(
                "location_type"
            ),

            "types": location.get(
                "types",
                []
            ),

        }

        # ----------------------------------------------------
        # Diagnostics
        # ----------------------------------------------------

        print(
            f"Looking up: {place} -> "
            f"Lat: {result['lat']}, "
            f"Lon: {result['lon']}"
        )

        print(
            f"    Resolved as: "
            f"{result['display_name']} "
            f"(via Google)"
        )

        if result.get("location_type"):

            print(
                f"    Location type: "
                f"{result['location_type']}"
            )

        if result.get("types"):

            print(
                f"    Google types: "
                f"{', '.join(result['types'])}"
            )

        # ----------------------------------------------------
        # Cache
        # ----------------------------------------------------

        cache[key] = result

        return result

    # --------------------------------------------------------
    # Nothing resolved
    # --------------------------------------------------------

    raise RuntimeError(
        f"Couldn't geocode '{place}'. "
        f"Tried: {', '.join(attempted)}. "
        f"If this is a real place that still doesn't resolve "
        f"correctly, you can skip geocoding entirely by adding "
        f"'lat' and 'lon' directly to that stop in the trip YAML."
    )


# ============================================================
# Resolve YAML location
# ============================================================

def resolve_location(
    spec,
    near=None
):

    # --------------------------------------------------------
    # Manual override
    # --------------------------------------------------------

    if (
        "lat" in spec
        and "lon" in spec
    ):

        return {

            "name": spec.get(
                "label",
                spec["name"]
            ),

            "lat": spec["lat"],

            "lon": spec["lon"],

            "display_name": spec.get(
                "display_name",
                f"Manually specified location: "
                f"{spec['name']}"
            )

        }

    # --------------------------------------------------------
    # Previous resolved location
    # --------------------------------------------------------

    near_coords = (
        (
            near["lat"],
            near["lon"]
        )
        if near is not None
        else None
    )

    return geocode(
        spec["name"],
        preferred_name=spec.get(
            "label"
        ),
        near=near_coords,
        country=spec.get(
            "country"
        )
    )


# ============================================================
# Coordinate projection
# ============================================================

def project(
    lon,
    lat
):

    return transformer.transform(
        lon,
        lat
    )


# ============================================================
# Interactive route verification map
# ============================================================

def plot_geocoded_trip(
    segments,
    output_file=None,
):

    """
    Generate an interactive HTML map showing the complete trip.

    Routes are generated using the same RouteGenerator used by
    the animation pipeline.

    The map can be zoomed to street level in a browser without
    losing vector route geometry.
    """

    import folium

    from route_generator import (
        RouteGenerator
    )

    if not segments:

        print(
            "No segments to plot."
        )

        return

    # --------------------------------------------------------
    # Route generator
    # --------------------------------------------------------

    route_generator = RouteGenerator()

    # --------------------------------------------------------
    # Collect locations in itinerary order
    # --------------------------------------------------------

    locations = []

    for segment in segments:

        start = segment["from"]
        end = segment["to"]

        if (
            not locations
            or locations[-1]["name"]
            != start["name"]
        ):

            locations.append(start)

        locations.append(end)

    # --------------------------------------------------------
    # Initial map center
    # --------------------------------------------------------

    center_lat = (
        sum(
            location["lat"]
            for location in locations
        )
        / len(locations)
    )

    center_lon = (
        sum(
            location["lon"]
            for location in locations
        )
        / len(locations)
    )

    fmap = folium.Map(
        location=[
            center_lat,
            center_lon,
        ],
        zoom_start=4,
        tiles="CartoDB Voyager",
        control_scale=True,
    )

    # --------------------------------------------------------
    # Alternative basemap
    # --------------------------------------------------------

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        control=True,
    ).add_to(fmap)

    # --------------------------------------------------------
    # Route groups
    # --------------------------------------------------------

    route_groups = {

        "Flights": folium.FeatureGroup(
            name="✈ Flights",
            show=True,
        ),

        "Walking": folium.FeatureGroup(
            name="🚶 Walking",
            show=True,
        ),

        "Bus": folium.FeatureGroup(
            name="🚌 Bus",
            show=True,
        ),

        "Train": folium.FeatureGroup(
            name="🚆 Train",
            show=True,
        ),

        "Car": folium.FeatureGroup(
            name="🚗 Car",
            show=True,
        ),

    }

    for group in route_groups.values():

        group.add_to(fmap)

    # --------------------------------------------------------
    # Debug colors
    # --------------------------------------------------------

    route_colors = {

        "plane": "#d62728",
        "walk": "#2ca02c",
        "bus": "#ff7f0e",
        "train": "#1f77b4",
        "car": "#9467bd",

    }

    # --------------------------------------------------------
    # Generate routes
    # --------------------------------------------------------

    all_route_points = []

    for index, segment in enumerate(
        segments
    ):

        mode = segment["mode"]

        start = segment["from"]
        end = segment["to"]

        print(
            f"Generating debug route "
            f"{index + 1}/{len(segments)}: "
            f"{start['name']} -> "
            f"{end['name']} "
            f"({mode})"
        )

        route = route_generator.generate(
            segment,
            points=500,
        )

        # ----------------------------------------------------
        # Convert projected coordinates back to lat/lon
        # ----------------------------------------------------

        route_latlon = []

        for x, y in route:

            lon, lat = transformer.transform(
                x,
                y,
                direction="INVERSE"
            )

            route_latlon.append(
                [
                    lat,
                    lon
                ]
            )

        all_route_points.extend(
            route_latlon
        )

        # ----------------------------------------------------
        # Select route group
        # ----------------------------------------------------

        if mode == "plane":

            group = route_groups["Flights"]

        elif mode == "walk":

            group = route_groups["Walking"]

        elif mode == "bus":

            group = route_groups["Bus"]

        elif mode == "train":

            group = route_groups["Train"]

        elif mode == "car":

            group = route_groups["Car"]

        else:

            group = folium.FeatureGroup(
                name=f"Other ({mode})",
                show=True,
            )

            group.add_to(fmap)

        # ----------------------------------------------------
        # Tooltip
        # ----------------------------------------------------

        tooltip = (
            f"Leg {index + 1}: "
            f"{start['name']} → "
            f"{end['name']} "
            f"({mode})"
        )

        color = route_colors.get(
            mode,
            "#000000"
        )

        # ----------------------------------------------------
        # Route outline
        # ----------------------------------------------------

        folium.PolyLine(
            locations=route_latlon,
            color="#000000",
            weight=9,
            opacity=0.25,
        ).add_to(group)

        # ----------------------------------------------------
        # Actual route
        # ----------------------------------------------------

        folium.PolyLine(
            locations=route_latlon,
            color=color,
            weight=5,
            opacity=0.9,
            tooltip=tooltip,
        ).add_to(group)

        # ----------------------------------------------------
        # Midpoint label
        # ----------------------------------------------------

        midpoint = route_latlon[
            len(route_latlon) // 2
        ]

        folium.Marker(
            location=midpoint,

            icon=folium.DivIcon(
                html=f"""
                <div style="
                    font-size: 11px;
                    font-weight: bold;
                    color: {color};
                    background-color:
                        rgba(255,255,255,0.9);
                    border: 1px solid #555;
                    border-radius: 4px;
                    padding: 2px 4px;
                    white-space: nowrap;
                ">
                    {index + 1}. {mode}
                </div>
                """
            ),
        ).add_to(group)

    # --------------------------------------------------------
    # Destination markers
    # --------------------------------------------------------

    marker_group = folium.FeatureGroup(
        name="Destinations",
        show=True,
    )

    marker_group.add_to(fmap)

    for index, location in enumerate(
        locations,
        start=1
    ):

        lat = location["lat"]
        lon = location["lon"]

        popup_html = f"""
        <div style="
            font-family: Arial;
            min-width: 250px;
        ">

            <h4 style="margin-bottom: 8px;">
                {index}. {location["name"]}
            </h4>

            <b>Latitude:</b>
            {lat:.7f}

            <br>

            <b>Longitude:</b>
            {lon:.7f}

            <br><br>

            <b>Resolved as:</b>
            <br>
            {location.get(
                "display_name",
                "N/A"
            )}

            <br><br>

            <b>Geocoder:</b>
            {location.get(
                "geocoder",
                "Manual"
            )}

            <br>

            <b>Location type:</b>
            {location.get(
                "location_type",
                "N/A"
            )}

        </div>
        """

        # ----------------------------------------------------
        # Actual marker
        # ----------------------------------------------------

        folium.Marker(

            location=[
                lat,
                lon
            ],

            popup=folium.Popup(
                popup_html,
                max_width=400,
            ),

            tooltip=(
                f"{index}. "
                f"{location['name']}"
            ),

            icon=folium.Icon(
                color="red",
                icon="map-marker",
                prefix="fa",
            ),

        ).add_to(marker_group)

        # ----------------------------------------------------
        # Number label
        # ----------------------------------------------------

        folium.Marker(

            location=[
                lat,
                lon
            ],

            icon=folium.DivIcon(

                html=f"""
                <div style="
                    font-size: 12px;
                    font-weight: bold;
                    color: white;
                    background: #222;
                    border-radius: 50%;
                    width: 22px;
                    height: 22px;
                    line-height: 22px;
                    text-align: center;
                    border: 2px solid white;
                    box-shadow:
                        0 1px 4px
                        rgba(0,0,0,0.5);
                        transform:
                        translate(-50%, -50%);
                ">
                    {index}
                </div>
                """

            ),

        ).add_to(marker_group)

    # --------------------------------------------------------
    # Fit map to route geometry
    # --------------------------------------------------------

    if all_route_points:

        fmap.fit_bounds(
            all_route_points,
            padding=(30, 30)
        )

    else:

        fmap.fit_bounds(

            [
                [
                    location["lat"],
                    location["lon"]
                ]

                for location in locations

            ],

            padding=(30, 30)
        )

    # --------------------------------------------------------
    # Controls
    # --------------------------------------------------------

    folium.LayerControl(
        collapsed=False
    ).add_to(fmap)

    from folium.plugins import (
        Fullscreen,
        MousePosition,
        MeasureControl
    )

    Fullscreen(
        position="topright",
        title="Full screen",
        title_cancel="Exit full screen",
        force_separate_button=True,
    ).add_to(fmap)

    MousePosition(
        position="bottomright",
        separator=" | ",
        prefix="Coordinates:",
        num_digits=6,
    ).add_to(fmap)

    fmap.add_child(
        MeasureControl(
            position="topleft",
            primary_length_unit="kilometers",
            secondary_length_unit="miles",
        )
    )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    if output_file is None:

        output_file = os.path.join(
            data_dir,
            "html",
            "trip_debug_map.html",
        )

    os.makedirs(
        os.path.dirname(output_file),
        exist_ok=True
    )

    fmap.save(
        output_file
    )

    print(
        f"\nSaved interactive route map:"
        f"\n    {output_file}"
    )

    return output_file


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
    # Resolve segments
    # --------------------------------------------------------

    previous_to_location = None

    for segment in trip["segments"]:

        # ----------------------------------------------------
        # Origin
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
        # Destination
        # ----------------------------------------------------

        to_location = resolve_location(
            segment["to"],
            near=from_location
        )

        # ----------------------------------------------------
        # Build segment
        # ----------------------------------------------------

        segment_dict = {

            "mode": segment["mode"],

            "duration": segment["duration"],

            "from": from_location,

            "to": to_location,

        }

        if "color" in segment:

            segment_dict["color"] = (
                segment["color"]
            )

        segments.append(
            segment_dict
        )

        previous_to_location = (
            to_location
        )

    # --------------------------------------------------------
    # Validate metadata
    # --------------------------------------------------------

    if "fps" not in trip:

        raise ValueError(
            "Trip YAML is missing 'fps' "
            "(frames per second) specification."
        )

    if "dpi" not in trip:

        raise ValueError(
            "Trip YAML is missing 'dpi' "
            "(dots per inch) specification."
        )

    output = {

        "fps": trip["fps"],

        "dpi": trip["dpi"],

        "segments": segments,

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
    # Generate verification map
    # --------------------------------------------------------

    if plot:

        plot_geocoded_trip(
            segments,
            output_file=os.path.join(
                data_dir,
                "html",
                "trip_debug_map.html",
            ),
        )
