import os
from legacy_loader import load_legacy_config

def get_legacy_app_name():
    abs_path = os.path.join(os.path.dirname(__file__), "config.json")
    rel_path = os.path.relpath(abs_path, os.getcwd())
    return load_legacy_config(rel_path)["app_name"]