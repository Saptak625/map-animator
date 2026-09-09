import os
import numpy as np
import contextily as ctx

root_dir = os.path.dirname(os.path.dirname(__file__))
data_dir = os.path.join(root_dir, "data")
output_dir = os.path.join(root_dir, "output")
assets_dir = os.path.join(root_dir, "assets")
icons_dir = os.path.join(assets_dir, "icons")

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

def darken_hex_color(hex_color: str, percentage: float = 5.0) -> str:
    """Takes a hex color string and darkens it by the given percentage."""
    # Remove the '#' character if present
    hex_color = hex_color.lstrip('#')
    
    # Parse RGB components from the hex string
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    
    # Calculate the reduction factor (e.g., 5% darker means multiplying by 0.95)
    factor = 1.0 - (percentage / 100.0)
    
    # Apply factor and clamp to a minimum of 0
    new_r = max(0, int(r * factor))
    new_g = max(0, int(g * factor))
    new_b = max(0, int(b * factor))
    
    # Format back into a standard hex string
    return f"#{new_r:02X}{new_g:02X}{new_b:02X}"