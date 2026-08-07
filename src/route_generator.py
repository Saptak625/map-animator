import numpy as np

from geographiclib.geodesic import Geodesic

from geometry import project


class RouteGenerator:


    def __init__(self):

        self.geodesic = Geodesic.WGS84



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


        elif mode in ["train", "bus"]:

            return self.linear_route(
                start,
                end,
                points
            )


        elif mode == "walk":

            return self.linear_route(
                start,
                end,
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


        route=[]


        for i in range(points):


            distance = (
                line.s13 *
                i /
                (points-1)
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
    # Linear fallback
    # --------------------------------------------------

    def linear_route(
        self,
        start,
        end,
        points
    ):


        route=[]


        start_xy = project(
            start["lon"],
            start["lat"]
        )


        end_xy = project(
            end["lon"],
            end["lat"]
        )



        for i in range(points):


            t = i/(points-1)


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