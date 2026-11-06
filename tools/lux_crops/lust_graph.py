"""LuST road network as a networkx graph, and window cropping that matches build_lux_crop.py.

Graph model (primal, directed):
    nodes = SUMO junctions            attributes: x, y, junction_type (SUMO), tls (True if signalised)
    arcs  = drivable SUMO edges       attributes: id, length [m], speed [m/s], time [s] = length / speed,
                                                  type (OSM highway class), shape, lane_shape (for drawing)
A two-way street is two opposite arcs. Parallel arcs can exist, so G is a MultiDiGraph.

Cropping rule (checked against networks/luxembourg_south_bonnevoie: same 275 edges):
    keep every arc whose shape touches the bounding box, then keep the largest weakly connected component.
"""
import os
import urllib.request

import networkx as nx
import sumolib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
LUST_NET_URL = "https://raw.githubusercontent.com/lcodeca/LuSTScenario/master/scenario/lust.net.xml"

# The existing crop, used as the reference in the selection and the drawings.
BONNEVOIE = ("luxembourg_south_bonnevoie", (7700.0, 8600.0, 4600.0, 5500.0))

# Approximate centres of Luxembourg-City quarters in LuST coordinates. LuST has no street names,
# so a window is labelled with the nearest quarter. Labels are approximate.
PLACES = {
    "Ville Haute": (7250, 7000), "Gare": (7400, 5700), "Bonnevoie-Nord": (8050, 6150),
    "Bonnevoie-Sud": (8250, 5250), "Grund": (7700, 6550), "Clausen": (8300, 7200),
    "Pfaffenthal": (7450, 7600), "Limpertsberg": (6700, 7950), "Belair": (6000, 6900),
    "Hollerich": (6300, 5650), "Merl": (5150, 6000), "Rollingergrund": (5450, 7700),
    "Muhlenbach": (6450, 8750), "Eich": (7650, 9050), "Dommeldange": (8050, 9900),
    "Beggen": (7350, 10600), "Weimerskirch": (8750, 8900), "Kirchberg": (9600, 8750),
    "Neudorf": (9650, 7650), "Cents": (10100, 7050), "Hamm": (10850, 6450),
    "Pulvermuhl": (9100, 6300), "Cessange": (5200, 4450), "Gasperich": (6600, 4050),
    "Cloche d'Or": (6000, 3550), "Howald": (8250, 3650), "Hesperange": (8850, 2200),
    "Alzingen": (9550, 1750), "Itzig": (10250, 4250), "Sandweiler": (13600, 7250),
    "Findel": (12750, 8850), "Strassen": (3150, 8100), "Bertrange": (1450, 7150),
    "Leudelange": (2450, 4800), "Kockelscheuer": (5600, 2450), "Bridel": (3800, 12100),
    "Heisdorf": (8100, 11250), "Fentange": (8600, 1750), "Contern": (14000, 3800),
    "Howald-Ceinture": (7850, 4600), "Senningerberg": (13900, 10800),
}


def place_name(x, y):
    """Nearest quarter to a point (LuST coordinates)."""
    return min(PLACES, key=lambda p: (PLACES[p][0] - x) ** 2 + (PLACES[p][1] - y) ** 2)


def lust_net_path():
    """Path to lust.net.xml, downloaded from the public LuST repository on first use."""
    path = os.path.join(DATA_DIR, "lust.net.xml")
    if not os.path.exists(path):
        os.makedirs(DATA_DIR, exist_ok=True)
        print(f"Downloading {LUST_NET_URL} ...")
        urllib.request.urlretrieve(LUST_NET_URL, path)
    return path


def load_lust():
    """Return the LuST network as a networkx MultiDiGraph (see module docstring)."""
    net = sumolib.net.readNet(lust_net_path())
    G = nx.MultiDiGraph()
    for node in net.getNodes():
        x, y = node.getCoord()
        G.add_node(node.getID(), x=x, y=y, junction_type=node.getType(),
                   tls=node.getType().startswith("traffic_light"))
    for e in net.getEdges():
        if e.getFunction() not in ("", "normal") or not e.allows("passenger"):
            continue
        G.add_edge(e.getFromNode().getID(), e.getToNode().getID(), key=e.getID(),
                   id=e.getID(), length=e.getLength(), speed=e.getSpeed(),
                   time=e.getLength() / e.getSpeed(), type=e.getType(), lanes=e.getLaneNumber(),
                   shape=e.getShape(), lane_shape=e.getLane(0).getShape())
    G.graph["bounds"] = net.getBoundary()  # xmin, ymin, xmax, ymax
    return G


def _segment_touches_box(p, q, box):
    """Liang-Barsky clipping: does the segment p-q intersect box = (x0, x1, y0, y1)?"""
    x0, x1, y0, y1 = box
    dx, dy = q[0] - p[0], q[1] - p[1]
    t_in, t_out = 0.0, 1.0
    for a, b in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if a == 0:
            if b < 0:
                return False
        elif a < 0:
            t_in = max(t_in, b / a)
        else:
            t_out = min(t_out, b / a)
        if t_in > t_out:
            return False
    return True


def shape_touches_box(shape, box):
    xs, ys = [p[0] for p in shape], [p[1] for p in shape]
    if max(xs) < box[0] or min(xs) > box[1] or max(ys) < box[2] or min(ys) > box[3]:
        return False
    return any(_segment_touches_box(shape[i], shape[i + 1], box) for i in range(len(shape) - 1))


def crop(G, box):
    """Sub-network for box = (x0, x1, y0, y1), with the build_lux_crop.py rule. Returns a MultiDiGraph.

    Nodes and arcs keep the order of G (networkx subgraph views can iterate in set order, which changes between
    Python processes and would make results depend on the hash seed).
    """
    H = nx.MultiDiGraph(**G.graph)
    H.add_edges_from((u, v, k, a) for u, v, k, a in G.edges(keys=True, data=True) if shape_touches_box(a["shape"], box))
    if H.number_of_nodes() == 0:
        return H
    largest = max(nx.weakly_connected_components(H), key=len)
    H.remove_nodes_from([v for v in list(H) if v not in largest])
    for v in H:
        H.nodes[v].update(G.nodes[v])
    return H


def inside(G, v, box):
    return box[0] <= G.nodes[v]["x"] <= box[1] and box[2] <= G.nodes[v]["y"] <= box[3]
