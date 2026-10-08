from __future__ import annotations
from inventory.equipment import load_all

def printers():
    return [x for x in load_all().get("items",[]) if x.get("category")=="3d_printer"]

def default_printer():
    ps=printers()
    return ps[0] if ps else None

def build_volume(printer):
    if not printer: return None
    s=printer.get("specs",{}) or {}
    keys=("build_x_mm","build_y_mm","build_z_mm")
    if not all(k in s for k in keys): return None
    return tuple(float(s[k]) for k in keys)
