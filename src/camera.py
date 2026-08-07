class Camera:


    def __init__(self):

        self.x = 0
        self.y = 0
        self.zoom = 1



    def set_position(
        self,
        x,
        y,
        zoom
    ):

        self.x = x
        self.y = y
        self.zoom = zoom



    def move_towards(
        self,
        x,
        y,
        zoom,
        position_smoothing=0.08,
        zoom_smoothing=0.05
    ):

        self.x += (
            x-self.x
        )*position_smoothing


        self.y += (
            y-self.y
        )*position_smoothing


        self.zoom += (
            zoom-self.zoom
        )*zoom_smoothing



    def bounds(
        self,
        aspect=9/16
    ):

        height = 1000000/self.zoom

        width = height*aspect


        return (
            self.x-width,
            self.x+width,

            self.y-height,
            self.y+height
        )