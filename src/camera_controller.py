import math

from util import saturate_ends

class CameraController:

    def __init__(self):

        # ==================================================
        # GROUND TRAVEL
        # ==================================================
        #
        # These values intentionally produce a MUCH closer
        # camera than the previous version.
        #
        # Higher zoom = closer.
        #
        # The route length is used to dynamically adjust
        # the zoom.
        # ==================================================

        self.settings = {

            "walk": {

                "base_zoom": 40.0,
                "reference_length": 1_000.0,

                # Raised — walking segments no longer drift
                # into a wide, distant shot on longer routes.
                "min_zoom": 35.0,

                "max_zoom": 500.0,

                "look_ahead": 0.06,
                "position_smoothing": 0.6,
                "zoom_smoothing": 0.4
            },

            "bike": {

                "base_zoom": 20.0,
                "reference_length": 5_000.0,

                "min_zoom": 15.0,

                "max_zoom": 200.0,

                "look_ahead": 0.08,
                "position_smoothing": 0.6,
                "zoom_smoothing": 0.4
            },

            "car": {
                "base_zoom": 20.0,
                "reference_length": 5_000.0,

                "min_zoom": 15.0,

                "max_zoom": 200.0,

                "look_ahead": 0.08,
                "position_smoothing": 0.6,
                "zoom_smoothing": 0.4
            },

            "bus": {

                "base_zoom": 20.0,
                "reference_length": 5_000.0,

                "min_zoom": 15.0,

                "max_zoom": 200.0,

                "look_ahead": 0.08,
                "position_smoothing": 0.6,
                "zoom_smoothing": 0.4
            },

            "train": {

                "base_zoom": 20.0,
                "reference_length": 5_000.0,

                "min_zoom": 15.0,

                "max_zoom": 100.0,

                "look_ahead": 0.10,
                "position_smoothing": 0.6,
                "zoom_smoothing": 0.3
            }
        }


        # ==================================================
        # FLIGHT
        # ==================================================

        self.flight = {

            "start_zoom": 20.0,

            "end_zoom": 20.0,

            "min_cruise_zoom": 0.4,

            "max_cruise_zoom": 20.0,

            # ----------------------------------------------
            # Cruise padding now scales with route length
            # instead of one flat constant. Short domestic
            # hops get a tighter, closer frame; long-haul /
            # transatlantic flights keep the wide cinematic
            # pull-back. (Replaces the old unused
            # "route_padding" key, which the code never
            # actually applied.)
            # ----------------------------------------------

            "cruise_padding_short": 0.7,

            "cruise_padding_long": 3.0,

            "cruise_padding_reference_km": 8000.0,

            "zoom_out_end": 0.12,

            "zoom_in_start": 0.93,

            "look_ahead": 0.07,

            "position_smoothing": 0.6,

            "zoom_smoothing": 0.6

        }


    # ======================================================
    # EASING
    # ======================================================

    @staticmethod
    def smoothstep(t):

        t = max(
            0.0,
            min(1.0, t)
        )

        return (
            t *
            t *
            (3.0 - 2.0 * t)
        )


    @staticmethod
    def interpolate(
        start,
        end,
        t
    ):

        t = CameraController.smoothstep(t)

        return (
            start +
            (end - start) * t
        )


    # ======================================================
    # ROUTE UTILITIES
    # ======================================================

    @staticmethod
    def route_point(
        route,
        progress
    ):

        progress = max(
            0.0,
            min(1.0, progress)
        )

        index = int(
            progress *
            (len(route) - 1)
        )

        return route[index]


    @staticmethod
    def distance(
        p1,
        p2
    ):

        dx = p2[0] - p1[0]

        dy = p2[1] - p1[1]

        return math.sqrt(
            dx * dx +
            dy * dy
        )


    @classmethod
    def route_length(
        cls,
        route
    ):

        if len(route) < 2:

            return 0.0


        length = 0.0


        for i in range(
            1,
            len(route)
        ):

            length += cls.distance(
                route[i - 1],
                route[i]
            )


        return length


    # ======================================================
    # GROUND ZOOM
    # ======================================================

    def ground_zoom(
        self,
        mode,
        route
    ):

        config = self.settings[mode]


        length = self.route_length(
            route
        )


        if length <= 0:

            return config["base_zoom"]


        # --------------------------------------------------
        # Desired amount of route visible vertically.
        #
        # Walking:
        #     show ~2x route length
        #
        # Bus:
        #     show ~3x route length
        #
        # Train:
        #     show ~5x route length
        #
        # --------------------------------------------------

        # Show less of the total route at once = closer camera
        visible_multiplier = {
            "walk": 0.75,
            "bike": 1.0,
            "car": 1.0,
            "bus": 1.0,
            "train": 1.0
        }[mode]


        desired_height = (
            length *
            visible_multiplier
        )


        zoom = (
            1000000 /
            desired_height
        )


        return max(

            config["min_zoom"],

            min(

                config["max_zoom"],

                zoom

            )

        )

    # ======================================================
    # FLIGHT ROUTE EXTENT
    # ======================================================

    def route_extent(
        self,
        route
    ):

        if len(route) < 2:

            return 0.0, 0.0


        min_x = min(
            p[0]
            for p in route
        )

        max_x = max(
            p[0]
            for p in route
        )

        min_y = min(
            p[1]
            for p in route
        )

        max_y = max(
            p[1]
            for p in route
        )


        return (
            max_x - min_x,
            max_y - min_y
        )


    # ======================================================
    # FLIGHT CRUISE ZOOM
    # ======================================================

    def route_fit_zoom(
        self,
        route
    ):

        min_x = min(p[0] for p in route)
        max_x = max(p[0] for p in route)
        min_y = min(p[1] for p in route)
        max_y = max(p[1] for p in route)

        width = max_x - min_x
        height = max_y - min_y

        # Portrait frame
        aspect = 9/16

        required_height = max(
            height,
            width/aspect
        )

        # --------------------------------------------------
        # Padding scales with route length: short hops get a
        # tighter frame, long-haul flights get the full
        # cinematic pull-back. `blend` is 0 for a very short
        # hop, 1 once the route reaches the reference length.
        # --------------------------------------------------

        route_km = self.distance(route[0], route[-1]) / 1000.0

        reference_km = self.flight["cruise_padding_reference_km"]

        blend = min(1.0, route_km / reference_km)

        padding = self.interpolate(
            self.flight["cruise_padding_short"],
            self.flight["cruise_padding_long"],
            blend
        )

        required_height *= padding

        zoom = (
            1000000 /
            required_height
        )

        return max(

            self.flight["min_cruise_zoom"],

            min(

                self.flight["max_cruise_zoom"],

                zoom

            )

        )


    # ======================================================
    # GROUND TRAVEL
    # ======================================================

    def update_ground(
        self,
        camera,
        mode,
        route,
        progress
    ):

        config = self.settings[mode]


        # --------------------------------------------------
        # Dynamic zoom
        # --------------------------------------------------

        zoom = self.ground_zoom(
            mode,
            route
        )


        # --------------------------------------------------
        # Follow slightly ahead
        # --------------------------------------------------

        future = min(

            progress +
            config["look_ahead"],

            1.0

        )


        target = self.route_point(
            route,
            future
        )


        camera.move_towards(

            target[0],
            target[1],

            zoom,

            position_smoothing=
                config[
                    "position_smoothing"
                ],

            zoom_smoothing=
                config[
                    "zoom_smoothing"
                ]

        )


    # ======================================================
    # FLIGHT CAMERA
    # ======================================================

    def update_flight(
        self,
        camera,
        route,
        progress,
        total_frames=None
    ):
        
        progress = min(max(1.2 * (saturate_ends(progress, power=1.1) - 0.5), -0.5), 0.5) + 0.5

        config = self.flight

        # Capture the real entry zoom once, at the start of this segment
        if progress <= 0.0:
            self._flight_entry_zoom = camera.zoom

        entry_zoom = getattr(self, "_flight_entry_zoom", config["start_zoom"])

        cruise_zoom = self.route_fit_zoom(route)

        destination = route[-1]

        # --------------------------------------------------
        # Target position
        # --------------------------------------------------

        if progress < config["zoom_out_end"]:
            # During zoom-out phase, zoom out while focused on the origin point.\
            target = route[0]

        elif progress < config["zoom_in_start"]:

            look_ahead = (
                config["look_ahead"]
                *
                (1.0 - progress)
            )

            future = min(
                progress + look_ahead,
                1.0
            )

            target = self.route_point(route, future)

        else:

            # Inside the settle window: lock onto the literal
            # destination point instead of a route-index
            # approximation, which otherwise only equals the
            # destination on the exact last frame.
            target = destination


        # --------------------------------------------------
        # Target zoom
        # --------------------------------------------------

        if progress < config["zoom_out_end"]:

            phase = progress / config["zoom_out_end"]

            zoom = self.interpolate(entry_zoom, cruise_zoom, phase)

        elif progress < config["zoom_in_start"]:

            zoom = cruise_zoom

        else:

            phase = (
                (progress - config["zoom_in_start"])
                /
                (0.98 - config["zoom_in_start"])
            )

            zoom = self.interpolate(cruise_zoom, config["end_zoom"], phase)


        camera.move_towards(
            target[0], target[1], zoom,
            position_smoothing=config["position_smoothing"],
            zoom_smoothing=config["zoom_smoothing"]
        )


    # ======================================================
    # PUBLIC UPDATE
    # ======================================================

    def update(
        self,
        camera,
        mode,
        route,
        progress,
        total_frames=None
    ):

        if mode == "plane":

            self.update_flight(
                camera,
                route,
                progress,
                total_frames=total_frames
            )

        elif mode in self.settings:

            self.update_ground(
                camera,
                mode,
                route,
                progress
            )

        else:

            raise ValueError(
                f"Unknown travel mode: {mode}"
            )