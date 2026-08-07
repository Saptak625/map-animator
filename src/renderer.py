import matplotlib.pyplot as plt
import contextily as ctx

class Renderer:
    def __init__(self):
        self.dpi = 50 # TODO: INCREASE AND MAKE THIS A PARAMETER
        self.fig, self.ax = plt.subplots(
            figsize=(6,10),
            dpi=self.dpi
        )

        self.fig.subplots_adjust(
            left=0,
            right=1,
            top=1,
            bottom=0
        )

    def draw(
            self,
            camera,
            full_route,
            traveled_route,
            position,
            cities,
            arrived=False
        ):

        self.ax.clear()


        xmin,xmax,ymin,ymax = camera.bounds(
            # aspect=9/16
        )


        self.ax.set_xlim(
            xmin,
            xmax
        )

        self.ax.set_ylim(
            ymin,
            ymax
        )


        #
        # Layer 1:
        # complete route (faint background)
        #

        xs = [
            p[0]
            for p in full_route
        ]

        ys = [
            p[1]
            for p in full_route
        ]


        self.ax.plot(
            xs,
            ys,
            linewidth=3,
            alpha=0.15,
            zorder=1
        )


        #
        # Layer 2:
        # traveled route
        #

        if len(traveled_route) > 1:

            xs = [
                p[0]
                for p in traveled_route
            ]

            ys = [
                p[1]
                for p in traveled_route
            ]


            self.ax.plot(
                xs,
                ys,
                linewidth=5,
                alpha=0.8,
                zorder=2
            )


        #
        # Layer 3:
        # origin marker
        #

        origin = full_route[0]


        self.ax.scatter(
            origin[0],
            origin[1],
            s=150,
            zorder=5
        )


        #
        # Layer 4:
        # destination marker
        #

        if arrived:

            destination = full_route[-1]

            self.ax.scatter(
                destination[0],
                destination[1],
                s=150,
                zorder=6
            )


        #
        # Layer 5:
        # moving cursor
        #

        self.ax.scatter(
            position[0],
            position[1],
            s=220,
            zorder=10
        )


        #
        # Labels
        #

        for name,x,y in cities:

            self.ax.text(
                x,
                y,
                name,
                fontsize=12,
                zorder=20
            )


        ctx.add_basemap(
            self.ax,
            source=ctx.providers.OpenStreetMap.Mapnik,
            zorder=0
        )


        self.ax.axis("off")



    def save(self, filename):
        self.fig.savefig(
            filename,
            dpi=self.dpi,
            pad_inches=0,
            facecolor="black"
        )