"""Friendly error messages for learners. The raw error is kept alongside as ``detail``."""

from __future__ import annotations

import re


def friendly(kind: str, message: str, target: str) -> str:
    m = re.search(r"name '(\w+)' is not defined", message)
    if kind == "NameError" and m:
        return (f"{m.group(1)} is used before it has a value. Add a Set var block above it, "
                f"or pick a column instead.")
    m = re.search(r"object '(\w+)' not found", message)
    if m:
        return (f"{m.group(1)} is used before it has a value. Add a Set var block above it, "
                f"or pick a column instead.")
    m = re.search(r"no such column: ([\w.\"]+)", message)
    if m:
        return f"There is no column called {m.group(1).strip(chr(34))} at this point."
    m = re.search(r"no such table: ([\w.\"]+)", message)
    if m:
        return f"There is no table called {m.group(1)}. Drop a CSV to add it."
    if kind == "KeyError":
        col = message.strip("'\"")
        return f"There is no column called {col} at this point."
    if kind == "ZeroDivisionError":
        return "Something is divided by zero."
    if kind == "AttributeError" and "has no attribute" in message:
        m = re.search(r"has no attribute '(\w+)'", message)
        if m:
            return f"There is no column or field called {m.group(1)} on that row."
    if kind == "TypeError" and ("unsupported operand" in message or "can only concatenate" in message):
        return "These values can't be combined: check you aren't mixing text and numbers."
    if kind == "Timeout" and target == "sql":
        return ("This query took too long, so it was stopped. A join on a column with many "
                "repeated values can make a huge number of rows: check the JOIN key, or add a "
                "WHERE block before it.")
    if kind == "Timeout":
        return "Your program took too long. Is there a loop that never stops?"
    if kind == "SyntaxError":
        return f"The code has a typo: {message}"
    return message
