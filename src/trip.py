import json


class Trip:

    def __init__(self, filename):

        with open(filename, "r") as f:
            self.data = json.load(f)

        self.fps = self.data["fps"]
        self.dpi = self.data["dpi"]
        self.segments = self.data["segments"]


    def get_points(self):

        points = []

        for segment in self.segments:

            points.append(
                (
                    segment["from"]["lon"],
                    segment["from"]["lat"]
                )
            )

            points.append(
                (
                    segment["to"]["lon"],
                    segment["to"]["lat"]
                )
            )

        return points