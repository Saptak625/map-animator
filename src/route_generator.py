import os
import time
import numpy as np
import requests
import polyline
from geographiclib.geodesic import Geodesic

from geometry import project


class RouteGenerator:

    # ============================================================
    # Configuration
    # ============================================================

    GOOGLE_ROUTES_URL = (
        "https://routes.googleapis.com/directions/v2:computeRoutes"
    )

    GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

    OSRM_BASE_URL = "https://router.project-osrm.org"

    OSRM_PROFILES = {
        "walk": "foot",
        "bike": "cycling",
        "bus": "driving",
        "train": "driving",
    }

    REQUEST_RETRIES = 3
    REQUEST_RETRY_DELAY = 1.5

    GOOGLE_TIMEOUT = 20
    OSRM_TIMEOUT = 15

    # ============================================================
    # Initialization
    # ============================================================

    def __init__(self, request_timeout=20):

        self.geodesic = Geodesic.WGS84

        self.request_timeout = request_timeout

        if self.GOOGLE_API_KEY:
            print("Google Routes API: ENABLED")
        else:
            print(
                "Google Routes API: DISABLED "
                "(GOOGLE_MAPS_API_KEY not set)"
            )

    # ============================================================
    # Public interface
    # ============================================================

    def generate(
        self,
        segment,
        points=300
    ):

        mode = segment["mode"]

        start = segment["from"]
        end = segment["to"]

        print(
            f"\nRouting {mode}: "
            f"{start.get('name', '?')} -> "
            f"{end.get('name', '?')}"
        )

        # --------------------------------------------------------
        # Plane
        # --------------------------------------------------------

        if mode == "plane":

            return self.plane_route(
                start,
                end,
                points
            )

        # --------------------------------------------------------
        # Google routing
        # --------------------------------------------------------

        # if self.GOOGLE_API_KEY and mode == "walk":
        if self.GOOGLE_API_KEY and mode in ["walk", "bike", "bus", "train", "car"]:
            try:

                return self.google_route(
                    start,
                    end,
                    mode,
                    points
                )

            except Exception as exc:

                print(
                    f"Google routing failed for {mode} leg: "
                    f"{exc}"
                )

        # --------------------------------------------------------
        # OSRM fallback
        # --------------------------------------------------------

        if mode in self.OSRM_PROFILES: # Attempt to use OSRM for walk, bike, bus/train.

            try:

                print(
                    f"Falling back to OSRM for {mode}..."
                )

                return self.planned_route_osrm(
                    start,
                    end,
                    mode,
                    points
                )

            except Exception as exc:

                print(
                    f"OSRM routing also failed: {exc}"
                )

        # --------------------------------------------------------
        # Last resort
        # --------------------------------------------------------

        print(
            f"WARNING: Using straight-line fallback for "
            f"{mode}: "
            f"{start.get('name', '?')} -> "
            f"{end.get('name', '?')}"
        )

        return self.linear_route(
            start,
            end,
            points
        )

    # ============================================================
    # Google Routes API
    # ============================================================

    def google_route(
        self,
        start,
        end,
        mode,
        points
    ):

        # --------------------------------------------------------
        # Map our modes onto Google's travel modes.
        # --------------------------------------------------------

        google_modes = {
            "walk": "WALK",
            "bike": "BICYCLE",
            "bus": "TRANSIT",
            "train": "TRANSIT",
            "car": "DRIVE",
        }

        if mode not in google_modes:

            raise ValueError(
                f"Google routing does not support mode '{mode}'"
            )

        travel_mode = google_modes[mode]

        # --------------------------------------------------------
        # Request body.
        # --------------------------------------------------------

        body = {

            "origin": {
                "location": {
                    "latLng": {
                        "latitude": start["lat"],
                        "longitude": start["lon"],
                    }
                }
            },

            "destination": {
                "location": {
                    "latLng": {
                        "latitude": end["lat"],
                        "longitude": end["lon"],
                    }
                }
            },

            "travelMode": travel_mode,

            "computeAlternativeRoutes": False,

        }

        # --------------------------------------------------------
        # Transit-specific configuration.
        #
        # Google transit can return combinations of walking,
        # buses, trains, etc. We can tell it which modes we
        # prefer, but Google may still use another transit mode
        # when that produces the better route.
        # --------------------------------------------------------

        if mode == "train":

            body["transitPreferences"] = {
                "allowedTravelModes": [
                    "TRAIN",
                    "RAIL",
                    "SUBWAY",
                    "LIGHT_RAIL",
                ]
            }

        elif mode == "bus":

            body["transitPreferences"] = {
                "allowedTravelModes": [
                    "BUS",
                ]
            }

        # --------------------------------------------------------
        # Headers.
        # --------------------------------------------------------

        headers = {

            "Content-Type": "application/json",

            "X-Goog-Api-Key":
                self.GOOGLE_API_KEY,

            # Only request the fields we actually need.
            #
            # This is important with Google Routes because field
            # masks control what is returned and help avoid
            # unnecessarily expensive responses.
            "X-Goog-FieldMask":
                "routes.polyline.encodedPolyline,"
                "routes.distanceMeters,"
                "routes.duration",

        }

        # --------------------------------------------------------
        # Request with retries.
        # --------------------------------------------------------

        last_error = None

        for attempt in range(self.REQUEST_RETRIES):

            try:

                response = requests.post(
                    self.GOOGLE_ROUTES_URL,
                    headers=headers,
                    json=body,
                    timeout=self.GOOGLE_TIMEOUT,
                )

                response.raise_for_status()

                data = response.json()

                routes = data.get("routes")

                if not routes:

                    raise RuntimeError(
                        "Google returned no routes"
                    )

                encoded = (
                    routes[0]
                    .get("polyline", {})
                    .get("encodedPolyline")
                )

                if not encoded:

                    raise RuntimeError(
                        "Google route contained no polyline"
                    )

                # ------------------------------------------------
                # Decode Google's encoded polyline.
                #
                # polyline.decode() returns:
                #
                # [(lat, lon), ...]
                # ------------------------------------------------

                coordinates = polyline.decode(
                    encoded
                )

                if len(coordinates) < 2:

                    raise RuntimeError(
                        "Google returned fewer than two "
                        "route coordinates"
                    )

                print(
                    f"Google route successful: "
                    f"{len(coordinates)} geometry points"
                )

                distance = routes[0].get(
                    "distanceMeters"
                )

                duration = routes[0].get(
                    "duration"
                )

                if distance is not None:

                    print(
                        f"    Distance: "
                        f"{distance / 1000:.2f} km"
                    )

                if duration:

                    print(
                        f"    Duration: "
                        f"{duration}"
                    )

                # ------------------------------------------------
                # Google -> projected coordinates.
                # ------------------------------------------------

                projected = [

                    project(
                        lon,
                        lat
                    )

                    for lat, lon in coordinates

                ]

                return self._resample(
                    projected,
                    points
                )

            except Exception as exc:

                last_error = exc

                if attempt < self.REQUEST_RETRIES - 1:

                    wait = (
                        self.REQUEST_RETRY_DELAY
                        *
                        (2 ** attempt)
                    )

                    print(
                        f"Google request failed "
                        f"(attempt {attempt + 1}/"
                        f"{self.REQUEST_RETRIES}): "
                        f"{exc}"
                    )

                    print(
                        f"Retrying in {wait:.1f}s..."
                    )

                    time.sleep(wait)

        raise last_error

    # ============================================================
    # Plane route
    # ============================================================

    def plane_route(
        self,
        start,
        end,
        points
    ):

        line = self.geodesic.InverseLine(

            start["lat"],
            start["lon"],

            end["lat"],
            end["lon"]

        )

        route = []

        for i in range(points):

            distance = (
                line.s13
                *
                i
                /
                (points - 1)
            )

            pos = line.Position(
                distance
            )

            route.append(
                project(
                    pos["lon2"],
                    pos["lat2"]
                )
            )

        return route

    # ============================================================
    # OSRM fallback
    # ============================================================

    def planned_route_osrm(
        self,
        start,
        end,
        mode,
        points
    ):

        profile = self.OSRM_PROFILES[mode]

        coordinates = self._fetch_osrm_route(
            start,
            end,
            profile
        )

        if len(coordinates) < 2:

            raise RuntimeError(
                "OSRM returned no usable geometry"
            )

        projected = [

            project(
                lon,
                lat
            )

            for lon, lat in coordinates

        ]

        return self._resample(
            projected,
            points
        )

    # ============================================================
    # OSRM request
    # ============================================================

    def _fetch_osrm_route(
        self,
        start,
        end,
        profile
    ):

        url = (
            f"{self.OSRM_BASE_URL}/route/v1/"
            f"{profile}/"
            f"{start['lon']},{start['lat']};"
            f"{end['lon']},{end['lat']}"
        )

        params = {

            "overview": "full",

            "geometries": "geojson",

        }

        headers = {

            "User-Agent":
                "trip-animator/1.0"

        }

        last_error = None

        for attempt in range(
            self.REQUEST_RETRIES
        ):

            try:

                response = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.OSRM_TIMEOUT,
                )

                response.raise_for_status()

                data = response.json()

                if (
                    data.get("code") != "Ok"
                    or
                    not data.get("routes")
                ):

                    raise RuntimeError(
                        "OSRM returned no route "
                        f"(code={data.get('code')})"
                    )

                coordinates = (
                    data["routes"][0]
                    ["geometry"]
                    ["coordinates"]
                )

                return [
                    (lon, lat)
                    for lon, lat in coordinates
                ]

            except Exception as exc:

                last_error = exc

                if attempt < self.REQUEST_RETRIES - 1:

                    time.sleep(
                        self.REQUEST_RETRY_DELAY
                        *
                        (2 ** attempt)
                    )

        raise last_error

    # ============================================================
    # Resampling
    # ============================================================

    def _resample(
        self,
        waypoints,
        points
    ):

        xs = np.array(
            [p[0] for p in waypoints],
            dtype=float
        )

        ys = np.array(
            [p[1] for p in waypoints],
            dtype=float
        )

        # Remove consecutive duplicate coordinates.
        keep = np.ones(
            len(xs),
            dtype=bool
        )

        if len(xs) > 1:

            keep[1:] = (
                (np.diff(xs) != 0)
                |
                (np.diff(ys) != 0)
            )

        xs = xs[keep]
        ys = ys[keep]

        if len(xs) == 1:

            return [
                (xs[0], ys[0])
            ] * points

        segment_lengths = np.hypot(
            np.diff(xs),
            np.diff(ys)
        )

        cumulative = np.concatenate(
            (
                [0.0],
                np.cumsum(segment_lengths)
            )
        )

        total_length = cumulative[-1]

        if total_length <= 0:

            return [
                (xs[0], ys[0])
            ] * points

        sample_distances = np.linspace(
            0.0,
            total_length,
            points
        )

        sampled_x = np.interp(
            sample_distances,
            cumulative,
            xs
        )

        sampled_y = np.interp(
            sample_distances,
            cumulative,
            ys
        )

        return list(
            zip(
                sampled_x.tolist(),
                sampled_y.tolist()
            )
        )

    # ============================================================
    # Straight-line fallback
    # ============================================================

    def linear_route(
        self,
        start,
        end,
        points
    ):

        start_xy = project(
            start["lon"],
            start["lat"]
        )

        end_xy = project(
            end["lon"],
            end["lat"]
        )

        route = []

        for i in range(points):

            t = i / (points - 1)

            x = (
                start_xy[0]
                +
                t
                *
                (
                    end_xy[0]
                    -
                    start_xy[0]
                )
            )

            y = (
                start_xy[1]
                +
                t
                *
                (
                    end_xy[1]
                    -
                    start_xy[1]
                )
            )

            route.append(
                (x, y)
            )

        return route