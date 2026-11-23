"""Generate the static floor plan and the 30× SVG replay from the checked-in DaRA log."""

import csv
import json
import textwrap
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = "session02_order2904_execution03"
FPS = 2997 / 100
SPEED = 30
INK = "#203438"
SUBTLE = "#445b5c"
ROUTE = "#9b294c"
PAPER = "#ffffff"
COLORS = {
    155: "#dbe4f3", 156: "#e4e3d8", 157: "#efddd0", 158: "#d2e5dd",
    159: "#cde5e3", 160: "#e8deec", 161: "#f8eacb", 162: "#dae8d3", 163: "#d8e8f1",
}
# Positions inside zones for the illustrative first walk; observations give zone visits.
WALK_POINTS = {
    "z155": (7.13, 9.48), "z164": (7.13, 7.13), "z170": (4.82, 7.13),
    "z169": (4.82, 5.75), "z168": (4.82, 3.28), "z172-177": (3.24, 3.28),
}
MILESTONES = (1, 4, 74, 85, 95, 97)


def element(parent, tag, **attrs):
    props = {k.replace("_", "-"): str(v) for k, v in attrs.items()}
    return ET.SubElement(parent, tag, props)


def text(parent, x, y, value, size=16, weight=400, color=INK, anchor="start", **attrs):
    node = element(parent, "text", x=x, y=y, font_size=size, font_weight=weight,
                   fill=color, text_anchor=anchor, **attrs)
    node.text = value
    return node


def lines(parent, x, y, value, chars, size=20, line_height=24, **attrs):
    for n, line in enumerate(textwrap.wrap(value, width=chars)):
        text(parent, x, y + n * line_height, line, size, **attrs)


def xy(x, y):
    """Use a common scale with the positive y direction upwards on the floor plan."""
    return round(40 + 40*x, 2), round(647 - 40*y, 2)


def polygon(parent, coords, **attrs):
    points = " ".join(f"{x:g},{y:g}" for x, y in (xy(*p) for p in coords))
    return element(parent, "polygon", points=points, **attrs)


def label(parent, coord, captions, size=17, weight=600, rotation=0):
    x, y = xy(*coord)
    node = element(parent, "g", transform=f"translate({x:g} {y:g}) rotate({rotation})")
    for i, caption in enumerate(captions):
        text(node, 0, 5 + (i - (len(captions)-1)/2) * (size+1), caption, size, weight,
             anchor="middle")


def clock(frames):
    seconds = int(frames/FPS + 0.5)
    return f"{seconds // 60}:{seconds % 60:02}"


def observations():
    with (HERE.parent / "logs/dara_retrieval_gt.csv").open(newline="") as source:
        rows = [r for r in csv.DictReader(source) if r["case:concept:name"] == CASE]
    rows.sort(key=lambda r: int(r["dara:event_index"]))
    first = int(rows[0]["dara:start_frame"])
    events = []
    for idx, row in enumerate(rows, 1):
        start = int(row["dara:start_frame"]) - first
        end = int(row["dara:end_frame"]) - first
        visits = []
        for entry in row["dara:zone_path"].split():
            zone, offset = entry.split("@")
            visits.append((start + int(offset), zone))
        assert visits[0][0] == start
        assert idx == int(row["dara:event_index"]) and (idx == 1 or start == events[-1]["end"])
        events.append(dict(start=start, end=end, visits=visits, activity=row["concept:name"],
                           area=row["dara:area_end"], zone=row["dara:zone_end_id"]))
    return events


def floor(parent, layout):
    polygon(parent, layout["outline"], fill="#f3f3ef")
    for area in layout["zones"].values():
        for shape in area["polygons"]:
            # The rear halves also include small connecting strips behind the rack ends.
            edge = COLORS[area["source"]] if area["source"] == 163 else PAPER
            polygon(parent, shape, fill=COLORS[area["source"]], stroke=edge, stroke_width=1.5)
    for x0, y0, x1, y1 in layout["rack_bounds"]:
        polygon(parent, [(x0,y0),(x1,y0),(x1,y1),(x0,y1)], fill="#b4bcb7",
                stroke="#89968f", stroke_width=1)
        for j in (1, 2, 3):
            x, top = xy(x0 + j * (x1-x0)/4, y1)
            _, bottom = xy(x0, y0)
            element(parent, "path", d=f"M{x} {top} V{bottom}", stroke="#e3e7e1")
    for zone_id, area in layout["zones"].items():
        if zone_id.endswith("-177"):
            p = area["polygons"][0]
            x, top = xy(*p[3])
            _, bottom = xy(*p[0])
            element(parent, "path", d=f"M{x} {top} V{bottom}", stroke=PAPER, stroke_width=2)
    polygon(parent, layout["outline"], fill="none", stroke="#738984", stroke_width=1.6)


def floor_labels(parent, layout):
    for n in range(1,6):
        for side, suffix in [("back",178),("front",177)]:
            area = layout["zones"][f"z{171+n}-{suffix}"]
            label(parent, area["anchor"], [f"{n} {side}"], size=15)
    for n in range(1,5):
        area = layout["zones"][f"z{167+n}"]
        label(parent, [area["anchor"][0]+0.19, area["anchor"][1]], [f"{n}–{n+1}"], 15)
    for point, names, size, rot in [
        ((9.1, 10.55), ["Office"], 20, 0), ((15.49, 3.52), ["Cart area"], 18, 0),
        ((15.50, 7.00), ["Cardboard", "box area"], 17, 0), ((6.65, 4.53), ["Base"], 16, -90),
        ((9.60, 4.52), ["Packing /", "sorting area"], 18, 0),
        ((15.49, 10.45), ["Issuing /", "receiving area"], 16, 0),
        ((8.21, 7.94), ["To office"], 15, 0), ((12.03, 7.60), ["To boxes"], 15, 0),
        ((12.90, 4.52), ["To carts"], 15, -90), ((12.90, 10.06), ["To issuing"], 15, -90),
    ]:
        label(parent, point, names, size, rotation=rot)


def source_key(parent):
    text(parent, 40, 621, "Nine source areas  ·  three contain finer zones", 18, 700)
    items = [(40, 163, "Aisle path", "5 aisles, front and back"),
             (286, 162, "Cross-aisle path", "4 aisle-pair zones"),
             (504, 161, "Connecting path", "4 destination zones")]
    for x, source, title, desc in items:
        element(parent, "rect", x=x, y=639, width=17, height=17, rx=2,
                fill=COLORS[source], stroke="#6d8282", stroke_width=1)
        text(parent, x+25, 653, title, 16, 700)
        text(parent, x+25, 675, desc, 14, color=SUBTLE)


def static_walk(parent, rows):
    visits = []
    for row in rows[:4]:
        for _, zone in row["visits"]:
            if not visits or visits[-1] != zone:
                visits.append(zone)
    coords = [xy(*WALK_POINTS[zone]) for zone in visits]
    points = " ".join(f"{x},{y}" for x, y in coords)
    for stroke, width in [(PAPER, 6), (ROUTE, 2.9)]:
        element(parent, "polyline", points=points, fill="none", stroke=stroke,
                stroke_width=width, stroke_linejoin="round")
    x, y = coords[0]
    element(parent, "circle", cx=x, cy=y, r=5, fill=PAPER, stroke=ROUTE, stroke_width=3)
    x, y = coords[-1]
    element(parent, "path", d=f"M{x} {y} l10 -6 v12 z", fill=ROUTE)
    text(parent, 40, 132, "First walk  ·  office to aisle 1", 22, 700)
    text(parent, 40, 155, "The arrow follows the recorded order of zone visits in observations 1–4.", 15, color=SUBTLE)


def milestones(parent, rows, layout):
    text(parent, 773, 132, "Activities during the order", 22, 700)
    text(parent, 773, 155, "Start time · source at observation end", 15, color=SUBTLE)
    for i, event_index in enumerate(MILESTONES):
        y = 193 + 81*i
        row = rows[event_index-1]
        area_id=layout["zones"][row["zone"]]["source"]
        element(parent, "line", x1=773, x2=1122, y1=y-13, y2=y-13,
                stroke="#d6dfdd", stroke_width=1)
        element(parent, "rect", x=773, y=y-2, width=12, height=12, rx=2,
                fill=COLORS[area_id], stroke="#758582", stroke_width=0.8)
        text(parent, 793, y+9, f'{clock(row["start"])}   ·   {row["area"]}', 15, color=SUBTLE)
        text(parent, 1122, y+9, f'#{event_index}', 15, color=SUBTLE, anchor="end")
        lines(parent, 773, y+36, row["activity"], chars=32, size=19,
              line_height=21, weight=600)


def visibility(node, ranges, total, seconds):
    """Repeat each set of half-open active ranges on a shared SMIL time axis."""
    changes = {0: 0, total: 0}
    for start, end in ranges:
        changes[start] = 1
        changes[end] = 0
    times = sorted(changes)
    node.set("opacity", str(changes[0]))
    element(node, "animate", attributeName="opacity", calcMode="discrete",
            values=";".join(str(changes[t]) for t in times),
            keyTimes=";".join(f"{t/total:.9f}" for t in times),
            dur=f"{seconds:.6f}s", repeatCount="indefinite")


def replay(parent, rows, layout):
    total = rows[-1]["end"]
    seconds = total/FPS/SPEED
    visits = [(t, z) for row in rows for t, z in row["visits"]]
    ranges = defaultdict(list)
    for n, (start, zone) in enumerate(visits):
        end = visits[n+1][0] if n+1 < len(visits) else total
        if ranges[zone] and ranges[zone][-1][1] == start:
            ranges[zone][-1] = (ranges[zone][-1][0], end)
        else:
            ranges[zone].append((start, end))
    text(parent, 40, 132, "Recorded zone visits", 22, 700)
    text(parent, 40, 155, "The outline follows the active zone at 30× recording speed.", 15, color=SUBTLE)
    text(parent, 773, 132, "Worker S04", 22, 700)
    text(parent, 773, 155, "One full retrieval order in about 41 seconds", 15, color=SUBTLE)
    text(parent, 773, 229, "Ground truth activity", 16, 700, SUBTLE)
    text(parent, 773, 405, "Current zone", 16, 700, SUBTLE)
    text(parent, 773, 492, "Source at observation end", 16, 700, SUBTLE)
    for i, row in enumerate(rows, 1):
        node = element(parent, "g", id=f"observation-{i}")
        visibility(node, [(row["start"],row["end"])], total, seconds)
        lines(node, 773, 269, row["activity"], 22, 27, 33, weight=600)
        text(node, 773, 363, f'Observation {i} of {len(rows)}  ·  starts at {clock(row["start"])}',
             15, color=SUBTLE)
        text(node, 773, 530, row["area"], 23, 600)
    for zone, active in ranges.items():
        node = element(parent, "g", id=f"zone-{zone}")
        visibility(node, active, total, seconds)
        area = layout["zones"][zone]
        for shape in area["polygons"]:
            polygon(node, shape, stroke=ROUTE, stroke_width=3, fill=ROUTE, fill_opacity=.12)
        lines(node, 773, 442, area["name"], 26, 24, 28, weight=600)
    text(parent, 773, 597, "Elapsed recording time", 15, 700, SUBTLE)
    element(parent, "rect", x=773, y=611, width=349, height=6, fill="#dce6e3", rx=3)
    progress = element(parent, "rect", x=773, y=611, width=0, height=6, fill=ROUTE, rx=3)
    element(progress, "animate", attributeName="width", values="0;349", dur=f"{seconds:.6f}s",
            repeatCount="indefinite")
    text(parent, 773, 640, "0:00", 14, color=SUBTLE)
    text(parent, 1122, 640, clock(total), 14, color=SUBTLE, anchor="end")


def render(layout, rows, animated):
    svg = ET.Element("svg", {"xmlns":"http://www.w3.org/2000/svg", "viewBox":"0 0 1160 742",
                            "width":"1160", "height":"742", "role":"img",
                            "aria-labelledby":"title desc", "font-family":"Arial, Helvetica, sans-serif"})
    title = "A retrieval order through the DaRA warehouse"
    element(svg, "title", id="title").text = title
    element(svg, "desc", id="desc").text = (
        "Worker S04 retrieves order 2904. Nine colored areas act as sources and contain 24 location zones. "
        + ("The active zone and current ground truth activity change at recorded video frame boundaries."
           if animated else "The first walk goes from the office along the connecting path and cross-aisle to aisle 1 front. "
           "Selected activities follow picking, packing, handover and the return to the office.")
    )
    element(svg, "rect", width=1160, height=742, fill=PAPER)
    text(svg, 40, 57, title, 36, 700)
    prefix = f"Worker S04   ·   Session 2   ·   Order 2904, execution 3   ·   {len(rows)} observations"
    text(svg, 40, 88, prefix + f'   ·   {clock(rows[-1]["end"])} elapsed', 17, color=SUBTLE)
    element(svg, "line", x1=744, x2=744, y1=113, y2=678, stroke="#d6dfdd")
    floor(svg, layout)
    if animated:
        replay(svg, rows, layout)
        floor_labels(svg, layout)
    else:
        floor_labels(svg, layout)
        static_walk(svg, rows)
        milestones(svg, rows, layout)
    source_key(svg)
    element(svg, "line", x1=40, x2=1122, y1=693, y2=693, stroke="#d6dfdd")
    text(svg, 40, 720, "Layout adapted from Niemann & Moya Rueda, DaRA Documentation, Fig. 2.42 (CC BY-NC 4.0).",
         14, color=SUBTLE)
    text(svg, 1122, 720, "Movement follows annotated zones.", 14, color=SUBTLE, anchor="end")
    ET.indent(svg, space="  ")
    name = "warehouse_route_replay.svg" if animated else "warehouse_route.svg"
    (HERE/name).write_text(ET.tostring(svg, encoding="unicode")+"\n", encoding="utf-8")


if __name__ == "__main__":
    geometry = json.loads((HERE/"warehouse_zones.json").read_text())
    events = observations()
    for animated in (False, True):
        render(geometry, events, animated)
