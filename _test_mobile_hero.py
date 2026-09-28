#!/usr/bin/env python3
"""The hero's legibility, computed rather than judged.

The hero is dark text on a moving background, seen through two layers of
translucent white. That is a contrast decision disguised as a design decision,
and it is easy to break by nudging one opacity without looking: raising the
panel from 0.32 to 0.6 looks imperceptibly different on screen and can push the
heading below the ratio it needs.

So the composite is computed here from the real values in the real files - the
scene's ground, the scrim, the panel, the text colour - and asserted. If someone
deepens the ground or thins the panel, this fails and says which leg of the
ratio moved.

Three compositions are checked, because the hero has three: the centre of the
panel where the scrim is firmest, the panel's outer area where it is thinnest,
and the bare field at the hero's edges where no panel sits at all. The heading is
large display text, so 3:1 is the WCAG AA floor for it; 7:1 is held as the bar
here because the background is moving and a ratio that is technically adequate
still reads badly in motion.
"""
import io
import re
import sys

fails = []


def check(label, condition, detail=""):
    print(("  PASS  " if condition else "  FAIL  ") + label
          + ("" if condition else "   %s" % (detail,)))
    if not condition:
        fails.append(label)


def read(path):
    return io.open(path, encoding="utf-8").read()


def rgb(value):
    value = value.strip()
    if value.startswith("#"):
        value = value.lstrip("#")
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    match = re.findall(r"[\d.]+", value)
    return tuple(float(x) for x in match[:3])


def over(top, bottom, alpha):
    """Composite `top` at `alpha` over an opaque `bottom`."""
    return tuple(top[i] * alpha + bottom[i] * (1 - alpha) for i in range(3))


def luminance(colour):
    channels = []
    for raw in colour:
        c = raw / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return (0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2])


def ratio(fg, bg):
    a, b = luminance(fg), luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


css = read("docs/styles.css")
scene = read("docs/hero-scene.js")

# --- pull the real values out of the files ----------------------------------
text_colour = rgb(re.search(r"--text:\s*(#[0-9a-fA-F]{3,6})", css).group(1))
ground_top = rgb(re.search(r"groundTop:\s*'(#[0-9a-fA-F]{6})'", scene).group(1))
ground_bottom = rgb(re.search(r"groundBottom:\s*'(#[0-9a-fA-F]{6})'", scene).group(1))

scrim_stops = re.findall(r"rgba\(248, 250, 252, ([\d.]+)\)", css)
scrim_centre = float(scrim_stops[0]) if scrim_stops else 0.0
scrim_edge = float(scrim_stops[-1]) if scrim_stops else 0.0

copy_panel = float(re.search(
    r"\.hero-copy \{[^}]*?background: rgba\(255, 255, 255, ([\d.]+)\)", css, re.S).group(1))
drop_panel = float(re.search(
    r"\.resume-drop-zone \{[^}]*?background: rgba\(255, 255, 255, ([\d.]+)\)",
    css, re.S).group(1))
scrim_rgb = (248.0, 250.0, 252.0)
white = (255.0, 255.0, 255.0)

print("=== values read from the files ===")
print("  text            : %s" % (tuple(int(c) for c in text_colour),))
print("  scene ground    : %s -> %s" % (ground_top, ground_bottom))
print("  scrim           : %s at the centre, %s at the edges"
      % (scrim_centre, scrim_edge))
print("  copy panel      : %s white" % copy_panel)
print("  drop zone panel : %s white" % drop_panel)

print("\n=== the heading against each place it can sit ===")
# Centre: ground -> firmest scrim -> copy panel.
centre = over(white, over(scrim_rgb, ground_top, scrim_centre), copy_panel)
centre_ratio = ratio(text_colour, centre)
check("heading over the centre of the copy panel (>= 7:1)", centre_ratio >= 7.0,
      "%.2f:1 on rgb%s" % (centre_ratio, tuple(int(c) for c in centre)))
print("       %.2f:1 on rgb%s" % (centre_ratio, tuple(int(c) for c in centre)))

# Outer panel: thinner scrim, so more ground shows through.
outer = over(white, over(scrim_rgb, ground_top, scrim_edge), copy_panel)
outer_ratio = ratio(text_colour, outer)
check("heading over the outer part of the copy panel (>= 7:1)", outer_ratio >= 7.0,
      "%.2f:1 on rgb%s" % (outer_ratio, tuple(int(c) for c in outer)))
print("       %.2f:1 on rgb%s" % (outer_ratio, tuple(int(c) for c in outer)))

# The deeper ground at the bottom of the field, with no panel at all.
bare = over(scrim_rgb, ground_bottom, scrim_edge)
bare_ratio = ratio(text_colour, bare)
check("text against the bare field at the hero's edge (>= 7:1)", bare_ratio >= 7.0,
      "%.2f:1 on rgb%s" % (bare_ratio, tuple(int(c) for c in bare)))
print("       %.2f:1 on rgb%s" % (bare_ratio, tuple(int(c) for c in bare)))

print("\n=== the field is actually visible ===")
# A field that ended up the same colour as the page would pass every contrast
# check above while showing nothing - which is precisely how the scene was
# invisible for so long.
page_bg = rgb(re.search(r"--bg:\s*(#[0-9a-fA-F]{3,6})", css).group(1))
delta = sum(abs(ground_top[i] - page_bg[i]) for i in range(3))
check("the scene ground differs from the page background", delta > 24,
      "distance %d, rgb%s vs rgb%s" % (delta, ground_top, page_bg))
print("       distance %d from the page background" % delta)

through = over(white, ground_top, copy_panel)
delta_through = sum(abs(through[i] - page_bg[i]) for i in range(3))
check("it is still distinct after passing through the panel", delta_through > 14,
      "distance %d, rgb%s vs rgb%s" % (delta_through,
                                      tuple(int(c) for c in through), page_bg))
print("       distance %d after 32%% white over it" % delta_through)

print()
if fails:
    print("%d FAILED: %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("hero legibility holds and the field is visible through the glass")
