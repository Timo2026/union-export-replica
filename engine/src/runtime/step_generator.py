# -*- coding: utf-8 -*-
DENSITY = {"45钢": 7.85, "45#": 7.85, "q235": 7.85, "6061": 2.7, "al6061": 2.7,
           "7075": 2.81, "304": 7.93, "sus304": 7.93, "316l": 7.98, "sus316": 7.98,
           "tc4": 4.43, "钛合金": 4.43, "h59": 8.5, "黄铜": 8.5}

PART_GENERATORS = {"flange": "flange", "sleeve": "sleeve", "shaft": "shaft",
                   "plate": "plate", "box": "box", "bracket": "bracket", "step_block": "box"}

def get_weight(material, volume_cm3):
    try:
        vol = float(volume_cm3 or 0)
    except Exception:
        vol = 0.0
    density = DENSITY.get(material, 2.8)
    return round(vol * density, 2)  # grams
