#!/usr/bin/env python3
"""Style cycler: dark <-> light Solarized palette for stage6 profiles."""
import argparse, json, copy, sys

def make_palette(mode):
    if mode == "light":
        return {
            "palette_id": "solarized_light",
            "background_color": "#fdf6e3",
            "panel_color": "#eee8d5",
            "grid_color": "#93a1a1",
            "text_color": "#002b36",
            "accent_sequence": ["blue","cyan","green","yellow","orange","magenta","violet","red"],
            "colors": {
                "base03":"#002b36","base02":"#073642","base01":"#586e75","base00":"#657b83",
                "base0":"#839496","base1":"#93a1a1","yellow":"#b58900","orange":"#cb4b16",
                "red":"#dc322f","magenta":"#d33682","violet":"#6c71c4","blue":"#268bd2",
                "cyan":"#2aa198","green":"#859900"
            }
        }
    else:
        return {
            "palette_id": "solarized_dark",
            "background_color": "#002b36",
            "panel_color": "#073642",
            "grid_color": "#586e75",
            "text_color": "#93a1a1",
            "accent_sequence": ["blue","cyan","green","yellow","orange","magenta","violet","red"],
            "colors": {
                "base03":"#002b36","base02":"#073642","base01":"#586e75","base00":"#657b83",
                "base0":"#839496","base1":"#93a1a1","yellow":"#b58900","orange":"#cb4b16",
                "red":"#dc322f","magenta":"#d33682","violet":"#6c71c4","blue":"#268bd2",
                "cyan":"#2aa198","green":"#859900"
            }
        }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dark-config", default="config/stage6_default_scene_profile.json")
    parser.add_argument("--light-config", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--transition-frames", type=int, default=0)
    args = parser.parse_args()
    
    cfg_path = args.dark_config if args.light_config is None else args.light_config
    with open(cfg_path) as f: data = json.load(f)
    data["palette"] = make_palette("light" if args.light_config else "dark")
    with open(args.output, "w") as f: json.dump(data, f, indent=2)
    print("DONE: wrote", args.output)

if __name__ == "__main__": main()
