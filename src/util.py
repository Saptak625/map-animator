import os
import numpy as np
from dotenv import load_dotenv

load_dotenv()

root_dir = os.path.dirname(os.path.dirname(__file__))
data_dir = os.path.join(root_dir, "data")
output_dir = os.path.join(root_dir, "output")
assets_dir = os.path.join(root_dir, "assets")
icons_dir = os.path.join(assets_dir, "icons")

# map_source_api_key = os.environ.get("MAP_SOURCE_API_KEY")
# map_source = f"https://tiles.stadiamaps.com/tiles/stamen_terrain/{{z}}/{{x}}/{{y}}{{r}}.png?api_key={map_source_api_key}"

import contextily as ctx

map_source = ctx.providers.OpenStreetMap.HOT

def saturate_ends(x, power=3.0):
    """
    Saturates the input x (0 to 1) near 0 and 1, transitioning in the middle.
    Higher power increases flatness at the edges.
    """
    # Clamp input to safety range [0, 1]
    x = max(0.0, min(1.0, float(x)))
    
    # Map [0, 1] to [-1, 1] for central symmetry
    t = 2.0 * x - 1.0
    
    # Apply polynomial or algebraic shaping
    # This creates a steep middle and flat ends
    if t >= 0:
        y = 0.5 + 0.5 * (t ** (1.0 / power))
    else:
        y = 0.5 - 0.5 * ((-t) ** (1.0 / power))
        
    return y