from pyproj import Transformer


transformer = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:3857",
    always_xy=True
)


def project(lon,lat):

    x,y = transformer.transform(
        lon,
        lat
    )

    return x,y



def interpolate(start,end,t):

    x = start[0] + (end[0]-start[0])*t
    y = start[1] + (end[1]-start[1])*t

    return x,y