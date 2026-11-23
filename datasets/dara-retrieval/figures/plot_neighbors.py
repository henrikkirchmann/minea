"""Draw the two observed DaRA neighbor votes as an SVG using the standard library."""

import csv
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
K = 15
STYLE = {
    "CL124": ("#087767", "circle"),
    "CL133": ("#a94718", "square"),
    "CL135": ("#345f9b", "triangle"),
    "CL137": ("#916221", "diamond"),
    "CL139": ("#794e89", "circle"),
}
INK = "#1b3037"
MUTED = "#4c6067"
WIDTH = 1060


def text(parent, x, y, label, *, size=16, fill=INK, bold=False, anchor="start"):
    element = ET.SubElement(parent, "text", {
        "x": str(x), "y": str(y), "font-size": str(size), "fill": fill,
        "font-weight": "700" if bold else "400", "text-anchor": anchor,
    })
    element.text = str(label)


def marker(parent, x, y, activity):
    color, shape = STYLE[activity]
    if shape == "circle":
        ET.SubElement(parent, "circle", {"cx": str(x), "cy": str(y), "r": "8", "fill": color})
    elif shape == "square":
        ET.SubElement(parent, "rect", {
            "x": str(x - 7.5), "y": str(y - 7.5), "width": "15", "height": "15",
            "rx": "1.7", "fill": color,
        })
    else:
        if shape == "triangle":
            points = [(x, y - 9), (x + 9, y + 7), (x - 9, y + 7)]
        else:
            points = [(x, y - 9), (x + 9, y), (x, y + 9), (x - 9, y)]
        ET.SubElement(parent, "polygon", {
            "points": " ".join(f"{px},{py}" for px, py in points), "fill": color,
        })


def draw_panel(svg, top, query, neighbors):
    votes = Counter(row["ground_truth_activity_id"] for row in neighbors)
    activities = sorted(votes, key=lambda code: (-votes[code], code))
    names = {row["ground_truth_activity_id"]: row["ground_truth_activity"] for row in neighbors}
    panel = ET.SubElement(svg, "g")
    text(panel, 30, top, f"Observation {query['dara:event_index']}  ·  {query['dara:area_end']}",
         size=23, bold=True)
    text(panel, 30, top + 25, f"Ground truth for S04  ·  {query['concept:name']}", fill=MUTED)

    header_y = top + 66
    row_y = header_y + 29
    pitch = 33
    rank_x = [356 + 35 * i for i in range(K)]
    text(panel, 30, header_y, "Ground truth activity of neighbor", size=15, fill=MUTED, bold=True)
    text(panel, 898, header_y, "Votes", size=15, fill=MUTED, bold=True, anchor="middle")
    for rank, x in enumerate(rank_x, start=1):
        text(panel, x, header_y, rank, size=15, fill=MUTED, anchor="middle")
    for index, act in enumerate(activities):
        y = row_y + index * pitch
        ET.SubElement(panel, "rect", {
            "x": "20", "y": str(y - 15), "width": str(WIDTH - 40), "height": "30",
            "fill": "#f1f5f5" if index % 2 == 0 else "#fafbfb",
        })
        text(panel, 30, y + 5, names[act], size=16)
        text(panel, 898, y + 5, votes[act], size=18, bold=True, anchor="middle")
        if index == 0:
            text(panel, 933, y + 5, "First choice", size=15, bold=True)
    for x in rank_x:
        ET.SubElement(panel, "line", {
            "x1": str(x), "x2": str(x), "y1": str(header_y + 12),
            "y2": str(row_y + (len(activities) - 1) * pitch + 13),
            "stroke": "#d5ddde", "stroke-width": "1",
        })
    for row in neighbors:
        rank = int(row["rank"])
        activity = row["ground_truth_activity_id"]
        group = ET.SubElement(panel, "g")
        distance = float(row["distance"])
        ET.SubElement(group, "title").text = (
            f"Rank {rank} · {names[activity]} · Distance {distance:.3f} · "
            f"{row['neighbor_observation_id']}"
        )
        marker(group, rank_x[rank - 1], row_y + activities.index(activity) * pitch, activity)
    return row_y + (len(activities) - 1) * pitch + 15


def main():
    with (HERE / "s04_neighbors.csv").open(newline="") as f:
        panels = {}
        for row in csv.DictReader(f):
            if int(row["rank"]) <= K:
                panels.setdefault(row["query_observation_id"], []).append(row)
    with (HERE.parent / "logs/dara_retrieval_gt.csv").open(newline="") as f:
        queries = {row["dara:observation_id"]: row for row in csv.DictReader(f)
                   if row["dara:observation_id"] in panels}

    svg = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg", "role": "img",
        "aria-labelledby": "figure-title figure-description",
        "font-family": "Inter, Arial, sans-serif",
    })
    ET.SubElement(svg, "title", {"id": "figure-title"}).text = "How S04’s 15 nearest neighbors voted"
    ET.SubElement(svg, "desc", {"id": "figure-description"}).text = (
        "Each column is one training observation, ranked by its classifier distance to S04’s "
        "observation. Each mark casts one vote for its row’s ground truth activity."
    )
    ET.SubElement(svg, "rect", {"width": "100%", "height": "100%", "fill": "white"})
    text(svg, 30, 43, "How the 15 nearest neighbors voted", size=30, bold=True)
    text(svg, 30, 71, "Worker S04  ·  Session 2  ·  Order 2904  ·  Execution 3", fill=MUTED, size=17)
    text(svg, 30, 101, "Read from left to right. Each column is one neighbor, from closest (1) to farthest (15).", size=17)

    next_top = 150
    for query_id in sorted(panels):
        voters = sorted(panels[query_id], key=lambda row: int(row["rank"]))
        if [int(row["rank"]) for row in voters] != list(range(1, K + 1)):
            raise ValueError(f"Expected ranks 1 through {K} for {query_id}")
        panel_bottom = draw_panel(svg, next_top, queries[query_id], voters)
        next_top = panel_bottom + 48

    height = panel_bottom + 22
    svg.set("width", str(WIDTH))
    svg.set("height", str(height))
    svg.set("viewBox", f"0 0 {WIDTH} {height}")
    ET.indent(svg, space="  ")
    ET.ElementTree(svg).write(HERE / "s04_neighbors.svg", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
