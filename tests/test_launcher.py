import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_launcher_dispatches_frozen_doctor_before_main():
    tree = ast.parse((ROOT / "launcher.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "main"
    ]
    names = {call.func.attr for call in calls}
    assert "run_doctor" in names
    assert "main" in names
