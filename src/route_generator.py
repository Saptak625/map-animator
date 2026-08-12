import time

import numpy as np
import requests

from geographiclib.geodesic import Geodesic

from geometry import project


class RouteGenerator:

    # --------------------------------------------------
    # Public OSRM demo server. It's free and requires no API key,
    # but it's rate-limited and explicitly not meant for heavy or
    # production traffic -- point this at a self-hosted OSRM
    # instance if you're generating a lot of trips.
    # --------------------------------------------------

    OSRM_BASE_URL = "https://router.project-osrm.org"

    # OSRM ships "driving", "walking", and "cycling" profiles out of
    # the box -- there's no public rail-routing profile available.
    #
    # "bus" -> "driving": buses run on the road network, so this is
    #     a genuinely accurate stand-in.
    #
    # "train" -> "driving": this is a real approximation, not an
    #     accurate one. Rail corridors *often* roughly parallel major
    #     roads (valleys, city approaches), so this tends to look
    #     more plausible than a straight line, but it is not real
    #     track geometry. Swap this to a dedicated rail/transit
    #     routing provider here if you need accurate train routes.
    OSRM_PROFILES = {
        "walk": "foot",
        "bus": "driving",
        "train": "driving",
    }

    REQUEST_RETRIES = 3
    REQUEST_RETRY_DELAY = 1.5


    def __init__(self, request_timeout=10):

        self.geodesic = Geodesic.WGS84
        self.request_timeout = request_timeout


    def generate(
        self,
        segment,
        points=300
    ):

        mode = segment["mode"]

        start = segment["from"]
        end = segment["to"]

        if mode == "plane":

            return self.plane_route(
                start,
                end,
                points
            )

        elif mode in self.OSRM_PROFILES:

            return self.planned_route(
                start,
                end,
                mode,
                points
            )

        else:

            raise ValueError(
                f"Unknown mode {mode}"
            )


    # --------------------------------------------------
    # Plane route
    # --------------------------------------------------

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
                line.s13 *
                i /
                (points - 1)
            )

            pos = line.Position(
                distance
            )

            lon = pos["lon2"]
            lat = pos["lat2"]

            route.append(
                project(
                    lon,
                    lat
                )
            )

        return route


    # --------------------------------------------------
    # Real, path-following route (walk / bus / train)
    #
    # Queries OSRM for actual road/path geometry between the two
    # endpoints. Falls back to a straight line if the routing
    # request fails or returns nothing usable, so a network hiccup
    # degrades gracefully instead of crashing the whole pipeline.
    # --------------------------------------------------

    def planned_route(
        self,
        start,
        end,
        mode,
        points
    ):

        profile = self.OSRM_PROFILES[mode]

        try:

            waypoints = self._fetch_osrm_route(
                start,
                end,
                profile
            )

        except Exception as exc:

            print(
                f"Route planning failed for {mode} leg "
                f"({start.get('name', '?')} -> {end.get('name', '?')}): {exc}. "
                f"Falling back to a straight-line route."
            )

            return self.linear_route(start, end, points)

        if len(waypoints) < 2:

            print(
                f"Route planning returned no usable path for {mode} leg "
                f"({start.get('name', '?')} -> {end.get('name', '?')}). "
                f"Falling back to a straight-line route."
            )

            return self.linear_route(start, end, points)

        projected = [
            project(lon, lat)
            for lon, lat in waypoints
        ]

        return self._resample(projected, points)


    def _fetch_osrm_route(
        self,
        start,
        end,
        profile
    ):

        url = (
            f"{self.OSRM_BASE_URL}/route/v1/{profile}/"
            f"{start['lon']},{start['lat']};{end['lon']},{end['lat']}"
        )

        params = {
            "overview": "full",
            "geometries": "geojson",
        }

        last_error = None

        for attempt in range(self.REQUEST_RETRIES):

            try:

                response = requests.get(
                    url,
                    params=params,
                    timeout=self.request_timeout,
                    headers={"User-Agent": "trip-animator/1.0"}
                )

                response.raise_for_status()

                data = response.json()

                if data.get("code") != "Ok" or not data.get("routes"):
                    raise RuntimeError(
                        f"OSRM returned no route (code={data.get('code')})"
                    )

                # GeoJSON LineString coordinates are [lon, lat] pairs
                coordinates = data["routes"][0]["geometry"]["coordinates"]

                return [(lon, lat) for lon, lat in coordinates]

            except Exception as exc:

                last_error = exc

                # Only worth retrying on transient issues (timeouts,
                # connection errors, 5xx) -- back off briefly and
                # try again rather than hammering the demo server.
                if attempt < self.REQUEST_RETRIES - 1:
                    time.sleep(self.REQUEST_RETRY_DELAY)

        raise last_error


    # --------------------------------------------------
    # Resample a route into `points` points evenly spaced by arc
    # length.
    #
    # Raw routing-API geometry is NOT evenly spaced -- it's dense on
    # curves and sparse on straightaways. The rest of the pipeline
    # (CameraController, the main frame loop) indexes into the route
    # assuming route[i] for evenly-stepped i corresponds to roughly
    # even progress along the trip, so this step is what makes a
    # planned route animation-ready, not just a cosmetic detail.
    # --------------------------------------------------

    def _resample(
        self,
        waypoints,
        points
    ):

        xs = np.array([p[0] for p in waypoints], dtype=float)
        ys = np.array([p[1] for p in waypoints], dtype=float)

        segment_lengths = np.hypot(np.diff(xs), np.diff(ys))

        cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))

        total_length = cumulative[-1]

        if total_length <= 0:
            # Degenerate route (start basically equals end) --
            # nothing meaningful to interpolate along.
            return [(xs[0], ys[0])] * points

        sample_distances = np.linspace(0.0, total_length, points)

        sampled_x = np.interp(sample_distances, cumulative, xs)
        sampled_y = np.interp(sample_distances, cumulative, ys)

        return list(zip(sampled_x.tolist(), sampled_y.tolist()))

    # --------------------------------------------------
    # Linear fallback -- used when route planning is unavailable
    # or fails for a given leg.
    # --------------------------------------------------

    def linear_route(
        self,
        start,
        end,
        points
    ):

        route = []

        start_xy = project(
            start["lon"],
            start["lat"]
        )

        end_xy = project(
            end["lon"],
            end["lat"]
        )

        for i in range(points):

            t = i / (points - 1)

            x = (
                start_xy[0]
                +
                t *
                (
                    end_xy[0]
                    -
                    start_xy[0]
                )
            )

            y = (
                start_xy[1]
                +
                t *
                (
                    end_xy[1]
                    -
                    start_xy[1]
                )
            )

            route.append(
                (
                    x,
                    y
                )
            )

        return route
