# -*- coding: utf-8 -*-
import os
from datetime import datetime

_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_path = os.path.join(_log_dir, "operations.log")


def write_log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(_log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")
