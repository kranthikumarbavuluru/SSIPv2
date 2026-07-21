from pathlib import Path
import ast

path = Path(
    r"D:\WebSite\DASHBOARD\Code\SSIP"
    r"\apps\public_dashboard_app_v2_9.py"
)

tree = ast.parse(
    path.read_text(
        encoding="utf-8-sig"
    )
)

function = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "_published_call_card"
)

returns = [
    node
    for node in ast.walk(function)
    if isinstance(node, ast.Return)
]

print(
    "Published-call renderer return statements:",
    len(returns),
)

if len(returns) < 2:
    raise RuntimeError(
        "The renderer repair is incomplete."
    )

print(
    "Published-call renderer validation: PASS"
)
