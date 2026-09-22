#!/usr/bin/env python3
"""Matplotlib vector figures for the verified IKEA sweep.

All plotting is expressed with Python/Matplotlib. The PGF PDF backend typesets
labels with the same Libertine/newtx fonts as the manuscript. No bitmap layers,
smoothed fits, inferred measurements or solver calls are introduced.

Run analyze_sweep.py to verify the saved experiment and regenerate the figures.
"""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile

# These settings are local to this plotting process, not the user's environment.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "minea-mpl"))
if shutil.which("pdflatex") is None and Path("/Library/TeX/texbin/pdflatex").exists():
    os.environ["PATH"] = "/Library/TeX/texbin" + os.pathsep + os.environ.get("PATH", "")

import matplotlib
matplotlib.use("pgf")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import NullLocator

BLUE = "#0072B2"
ORANGE = "#D55E00"
PAPER_WIDTH = 430 / 72.27
PREAMBLE = (r"\usepackage[T1]{fontenc}" r"\usepackage{libertine}"
            r"\usepackage[libertine]{newtxmath}")


def configure_style():
    """Use the manuscript's actual font family, not a similarly named fallback."""
    if shutil.which("pdflatex") is None:
        raise RuntimeError("Figure generation needs pdflatex on PATH (TeX Live).")
    plt.rcParams.update({
        "pgf.texsystem": "pdflatex", "pgf.rcfonts": False, "pgf.preamble": PREAMBLE,
        "font.family": "serif", "font.serif": [], "font.size": 8.5,
        "axes.labelsize": 8.5, "axes.titlesize": 9,
        "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": .55, "axes.edgecolor": "#555555",
        "text.color": "#171717", "axes.labelcolor": "#171717",
        "xtick.color": "#333333", "ytick.color": "#333333",
        "xtick.direction": "out", "ytick.direction": "out",
        "xtick.major.width": .5, "ytick.major.width": .5,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "axes.axisbelow": True, "grid.color": "#DEDEDE", "grid.linewidth": .4,
        "legend.frameon": False, "lines.linewidth": 1.1,
        "figure.facecolor": "white", "savefig.facecolor": "white",
        "savefig.transparent": False, "text.usetex": True,
    })


def source_label(members):
    numbers = [m.removeprefix("distributed_K") for m in members if m != "central"]
    label = "Central" if "central" in members else ""
    if label and numbers:
        label += " and "
    label += ", ".join(numbers)
    if numbers:
        label += " source" if numbers == ["1"] else " sources"
    return label


def overview_figure(data):
    """Draw the paper figure from recorded interface sizes and case coverage."""
    fig = plt.figure(figsize=(PAPER_WIDTH, 164 / 72.27))
    left = fig.add_axes((.085, .24, .355, .61))
    right = fig.add_axes((.61, .24, .37, .61))
    fig.text(.535, .965, r"\textbf{(b)} Matching within 300 s", va="top", fontsize=9)
    fig.text(.01, .965, r"\textbf{(a)} Largest component interface", va="top", fontsize=9)
    panel = {r["sources"]: r["points"] for r in data["component_interface_panel"]}
    cs = [p["components"] for p in panel[1]]
    single = [p["maximum_component_interface"] for p in panel[1]]
    multi = [[p["maximum_component_interface"] for p in panel[k]] for k in (2, 4, 8)]
    # Arithmetic mean across source counts, not repeated experimental trials.
    mean = [sum(values) / len(values) for values in zip(*multi)]
    left.plot(cs, mean, color=ORANGE, linestyle="-", marker="o", markersize=3.5,
              label="2, 4, 8 sources (mean)")
    # The centralized solver has no inter-source matching interface after
    # collecting all inputs. This is a reference, not another construction.
    if any(single):
        raise ValueError("Central/one-source reference requires an empty interface")
    left.plot(cs, single, color=BLUE, marker="s", markersize=3.5,
              label="Central and 1 source", zorder=4)
    left.set_xscale("log", base=2)
    left.set(xlim=(135, .83), ylim=(-100, 2700), xlabel=r"Components $C$ (log scale)",
             ylabel="Interface variables")
    left.set_xticks(cs, [str(c) for c in cs])
    left.xaxis.set_minor_locator(NullLocator())
    left.set_yticks([0, 1000, 2000], ["0", "1,000", "2,000"])
    left.grid(axis="y")
    left.legend(loc="upper left", bbox_to_anchor=(.015, .91), fontsize=7.2,
                handlelength=1.2, labelspacing=.45, borderaxespad=0)
    left.annotate(f"{mean[0]:g}", (cs[0], mean[0]), xytext=(5, 9),
                  textcoords="offset points", ha="left", color=ORANGE, fontsize=8)
    left.annotate(f"{mean[-1]:,.1f}", (cs[-1], mean[-1]),
                  xytext=(-2, 8), textcoords="offset points", ha="right",
                  color=ORANGE, fontsize=7.8)
    left.text(.5, -.32, r"More coupling $\longrightarrow$", transform=left.transAxes,
              ha="center", fontsize=7.5, color="#444444")

    groups = data["coverage_groups"]
    colors = [BLUE, ORANGE, "#009E73", "#CC79A7", "#555555"]
    markers = ["s", "o", "^", "D", "v"]
    handles = []
    for i, group in enumerate(groups):
        points = group["points"]
        cx = [r["components"] for r in points]
        cy = [r["cases_in_optimal_components"] for r in points]
        color, marker = colors[i], markers[i]
        linestyle = "-"
        right.plot(cx, cy, color=color, linestyle=linestyle, zorder=2 + i)
        # A larger square behind a smaller circle preserves coincident data,
        # without moving any observation away from its true x/y position.
        size = 5.2 if marker == "s" else 3.8
        right.plot(cx, cy, linestyle="none", marker=marker, markersize=size,
                   markeredgewidth=.8, markeredgecolor=color,
                   markerfacecolor=color, zorder=4 + i)
        handles.append(Line2D([], [], color=color, linestyle=linestyle,
                              marker=marker, markersize=3.8, label=source_label(group["members"])))
    right.set_xscale("log", base=2)
    right.set(xlim=(135, .83), ylim=(-5, 128),
              xlabel=r"Components $C$ (log scale)", ylabel="Cases in solved components")
    cs = [p["components"] for p in groups[0]["points"]]
    right.set_xticks(cs, [str(c) for c in cs])
    right.xaxis.set_minor_locator(NullLocator())
    right.set_yticks([0, 58, 116])
    right.grid(axis="y")
    right.legend(handles=handles, loc="center right", bbox_to_anchor=(1.02, .60),
                 borderaxespad=0, handlelength=1.6, labelspacing=.45, fontsize=7.8)
    right.text(.5, -.32, r"More coupling $\longrightarrow$", transform=right.transAxes,
               ha="center", fontsize=7.5, color="#444444")
    return fig


def export_figures(overview, destination):
    """Save only Figure 3, as a vector PDF and editable Matplotlib PGF source."""
    configure_style()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    fig = overview_figure(overview)
    try:
        fig.savefig(destination / "ikea-overview.pdf", backend="pgf", metadata={
            "Title": "ikea-overview", "Author": "MINEA IKEA evaluation",
            "Subject": "Verified controlled source/component sweep; exact plotted observations",
            "CreationDate": None, "ModDate": None,
        })
        fig.savefig(destination / "ikea-overview.pgf", backend="pgf")
    finally:
        plt.close(fig)
    return {"renderer": "Python/Matplotlib with the PGF PDF backend",
            "matplotlib_version": matplotlib.__version__, "font_preamble": PREAMBLE,
            "font_family": "Linux Libertine (same family as the ACM manuscript)",
            "vector_only": True,
            "figure_files": ["figures/ikea-overview.pdf", "figures/ikea-overview.pgf"],
            "plot_source_sha256": {Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            "documentation": "https://matplotlib.org/stable/users/explain/text/pgf.html"}
