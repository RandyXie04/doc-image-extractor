import os
import json

def get_app_name():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return data["app_name"]