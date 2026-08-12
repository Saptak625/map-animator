import math
import os
import numpy as np
import matplotlib.pyplot as plt
import contextily as ctx
from svg_pltmarker import get_marker_from_svg

from util import icons_dir, map_source


# Make custom markers for matplotlib scatter() and plot() calls from svg images.
# PIN_MARKER = Path.load(icons_dir, "map_pinpoint.svg")
PIN_MARKER = get_marker_from_svg(
	filepath=os.path.join(icons_dir, "map_pinpoint.svg")
)

# Default cursor marker is just a circle.
DEFAULT_CURSOR_MARKER = get_marker_from_svg(
	filepath=os.path.join(icons_dir, "circle_icon.svg")
)
MODE_CURSOR_MARKERS = {
	"plane_left": get_marker_from_svg(
		filepath=os.path.join(icons_dir, "airplane_left.svg")
	),
	"plane_right": get_marker_from_svg(
		filepath=os.path.join(icons_dir, "airplane_right.svg")
	),
	"bus": get_marker_from_svg(
		filepath=os.path.join(icons_dir, "bus_train_icon.svg")
	),
	"train": get_marker_from_svg(
		filepath=os.path.join(icons_dir, "bus_train_icon.svg")
	),
	"walk": get_marker_from_svg(
		filepath=os.path.join(icons_dir, "walk_icon.svg")
	),
}


class Renderer:

	def __init__(self, dpi=300):

		self.dpi = dpi

		self.fig, self.ax = plt.subplots(
			figsize=(6, 10),
			dpi=self.dpi,
		)

		self.fig.subplots_adjust(
			left=0,
			right=1,
			top=1,
			bottom=0,
		)

		self.ax.axis("off")

		# --------------------------------------------------
		# Persistent artists.
		#
		# These are created once (lazily, on first draw()) and
		# updated in place on every later call instead of
		# ax.clear()-ing and rebuilding the whole scene each
		# frame. Clearing and re-adding the basemap + every line/
		# marker/label every frame is the dominant per-frame cost;
		# reusing artists and calling set_data()/set_offsets()/
		# set_extent() instead avoids redoing that work.
		#
		# Because frames are rendered across multiple worker
		# processes (see frame_worker.py) in whatever order the
		# pool happens to hand them out -- NOT necessarily
		# chronological order within one worker's lifetime -- every
		# update below is written to be correct from an arbitrary
		# frame's data, not just "append what's new". Lists of
		# reusable artists (background route lines, waypoint
		# labels) explicitly hide any leftover entries from a
		# previous, longer-history frame instead of assuming
		# history only grows.
		# --------------------------------------------------

		self._basemap_artist = None
		self._basemap_fast_path_supported = None  # unknown until first attempt

		self._background_route_lines = []  # one per completed segment
		self._preview_route_line = None  # current segment, not-yet-traveled
		self._traveled_route_line = None  # current segment, traveled-so-far

		self._waypoint_pins = None  # one PathCollection, offsets updated
		self._waypoint_labels = []  # one Text per waypoint

		self._cursor_marker = None  # one Line2D, marker swapped per mode


	# ======================================================
	# Basemap
	# ======================================================

	def _update_basemap(self, xmin, xmax, ymin, ymax):

		if self._basemap_fast_path_supported is not False:

			try:

				img, ext = ctx.bounds2img(
					xmin,
					ymin,
					xmax,
					ymax,
					source=map_source,
					ll=False,
				)

				if self._basemap_artist is None:

					self._basemap_artist = self.ax.imshow(
						img,
						extent=ext,
						zorder=0,
						interpolation="bilinear",
					)

				else:

					self._basemap_artist.set_data(img)
					self._basemap_artist.set_extent(ext)

				self._basemap_fast_path_supported = True

				return

			except Exception as exc:

				if self._basemap_fast_path_supported is None:

					print(
						f"Fast basemap updates aren't available with this "
						f"contextily version ({exc}); falling back to "
						f"re-adding the basemap each frame (slower, but "
						f"always works)."
					)

				self._basemap_fast_path_supported = False

		# --------------------------------------------------
		# Fallback: contextily's high-level add_basemap(), which
		# always works but re-fetches/composites a brand new image
		# every call. Remove the previous one first so they don't
		# stack up.
		# --------------------------------------------------

		if self._basemap_artist is not None:
			self._basemap_artist.remove()
			self._basemap_artist = None

		ctx.add_basemap(
			self.ax,
			source=map_source,
			zorder=0,
		)

		self._basemap_artist = self.ax.images[-1]


	# ======================================================
	# Draw
	# ======================================================

	def draw(
		self,
		camera,
		full_route,
		traveled_route,
		position,
		cities,
		mode,
		completed_routes=None,
		arrived=False,
		marker_color="darkorange",
		animated_marker_color="orange",
		marker_size=300,
		cursor_size=500,
		show_labels=True,
		show_cursor=True,
		show_current_route=True,
	):

		completed_routes = completed_routes or []

		xmin, xmax, ymin, ymax = camera.bounds()

		self._update_basemap(xmin, xmax, ymin, ymax)

		self.ax.set_xlim(xmin, xmax)
		self.ax.set_ylim(ymin, ymax)

		#
		# Layer 1a:
		# previously completed segments' routes -- very
		# transparent, stay visible for the rest of the video.
		#

		for i, route in enumerate(completed_routes):

			xs = [p[0] for p in route]
			ys = [p[1] for p in route]

			if i < len(self._background_route_lines):

				line = self._background_route_lines[i]
				line.set_data(xs, ys)
				line.set_visible(True)

			else:

				line, = self.ax.plot(
					xs,
					ys,
					linewidth=1,
					alpha=0.06,
					zorder=1,
					color="k",
				)

				self._background_route_lines.append(line)

		# Hide any lines left over from a previous frame that had
		# more completed-segment history than this one (can happen
		# when frames from different segments land on the same
		# worker out of chronological order).
		for j in range(len(completed_routes), len(self._background_route_lines)):
			self._background_route_lines[j].set_visible(False)

		#
		# Layer 1b:
		# complete route of the CURRENT segment (faint preview)
		#
		# Can be disabled for the outro.
		#

		if show_current_route and full_route:

			xs = [p[0] for p in full_route]
			ys = [p[1] for p in full_route]

			if self._preview_route_line is None:

				self._preview_route_line, = self.ax.plot(
					xs,
					ys,
					linewidth=1,
					alpha=0.15,
					zorder=1,
					color="k",
				)

			else:

				self._preview_route_line.set_data(xs, ys)
				self._preview_route_line.set_visible(True)

		else:

			if self._preview_route_line is not None:
				self._preview_route_line.set_visible(False)

		#
		# Layer 2:
		# traveled route of the CURRENT segment
		#
		# Can be disabled for the outro.
		#

		if show_current_route and len(traveled_route) > 1:

			txs = [p[0] for p in traveled_route]
			tys = [p[1] for p in traveled_route]

		else:

			txs, tys = [], []

		if self._traveled_route_line is None:

			self._traveled_route_line, = self.ax.plot(
				txs,
				tys,
				linewidth=5,
				alpha=0.4,
				zorder=2,
				color=animated_marker_color,
			)

		else:

			self._traveled_route_line.set_data(txs, tys)

		self._traveled_route_line.set_visible(
			show_current_route and len(traveled_route) > 1
		)

		#
		# Layer 3:
		# waypoint pins + labels for every stop reached so far
		# (grows as the trip progresses; stays visible afterward)
		#

		offsets = [(x, y) for _, x, y in cities]

		if self._waypoint_pins is None:
			self._waypoint_pins = self.ax.scatter(
				[p[0] for p in offsets],
				[p[1] for p in offsets],
				s=marker_size,
				marker=PIN_MARKER,
				color=marker_color,
				edgecolors="black",
				linewidths=0.6,
				zorder=5,
			)

		else:
			self._waypoint_pins.set_offsets(offsets if offsets else np.empty((0, 2)))

		#
		# Labels
		#
		# Labels are optional. The outro disables them while keeping
		# all waypoint pins visible.
		#

		for label in self._waypoint_labels:
			label.set_visible(False)

		self._waypoint_labels = []

		if show_labels:

			for name, x, y in cities:

				label = self.ax.annotate(
					name,
					xy=(x, y),
					xytext=(0, 10),
					textcoords="offset points",
					fontsize=14,
					ha="center",
					zorder=20,
				)

				self._waypoint_labels.append(label)

		#
		# Layer 4:
		# moving cursor
		#
		# Can be disabled for the outro.
		#

		if not show_cursor:

			if self._cursor_marker is not None:
				self._cursor_marker.set_visible(False)

		else:

			cursor_marker_key = mode

			if mode == "plane":

				if len(traveled_route) >= 2:

					if traveled_route[-1][0] < traveled_route[-2][0]:
						cursor_marker_key = "plane_left"

					else:
						cursor_marker_key = "plane_right"

				else:

					cursor_marker_key = "plane_right"

			cursor_marker = MODE_CURSOR_MARKERS.get(
				cursor_marker_key,
				DEFAULT_CURSOR_MARKER
			)

			if self._cursor_marker is None:

				self._cursor_marker, = self.ax.plot(
					[position[0]],
					[position[1]],
					marker=cursor_marker,
					markersize=math.sqrt(cursor_size),
					markerfacecolor=animated_marker_color,
					markeredgecolor="black",
					markeredgewidth=0.8,
					linestyle="None",
					zorder=10,
				)

			else:

				self._cursor_marker.set_data(
					[position[0]],
					[position[1]]
				)

				self._cursor_marker.set_marker(cursor_marker)
				self._cursor_marker.set_visible(True)

		self.ax.axis("off")


	def save(self, filename):

		self.fig.savefig(
			filename,
			dpi=self.dpi,
			pad_inches=0,
			facecolor="black",
		)