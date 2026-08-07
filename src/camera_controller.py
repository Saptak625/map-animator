import numpy as np



class CameraController:


    def __init__(self):

        self.settings = {

            "walk":{

                "zoom":14,

                "look_ahead":0.15,

                "smooth":0.12
            },


            "bus":{

                "zoom":8,

                "look_ahead":0.25,

                "smooth":0.08
            },


            "train":{

                "zoom":6,

                "look_ahead":0.35,

                "smooth":0.06
            },


            "plane":{

                "zoom":3,

                "look_ahead":0.5,

                "smooth":0.04
            }

        }



    def update(

        self,

        camera,

        mode,

        route,

        progress

    ):


        config = self.settings[mode]


        #
        # Look ahead point
        #
        # Instead of following behind,
        # look slightly toward destination
        #

        future = min(
            progress + config["look_ahead"],
            1.0
        )


        index = int(
            future*(len(route)-1)
        )


        target = route[index]


        camera.move_towards(

            target[0],

            target[1],

            config["zoom"],

            position_smoothing=config["smooth"],

            zoom_smoothing=0.03

        )