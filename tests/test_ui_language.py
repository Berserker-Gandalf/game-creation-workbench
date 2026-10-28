"""Keep owned validation messages readable in the English interface."""
import ast
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_owned_literal_validation_messages_have_english():
    catalog = {}
    for path in (ROOT / 'src/locales').glob('*.json'):
        catalog.update(json.loads(path.read_text(encoding='utf-8')))
    missing = []
    for path in (ROOT / 'backend').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call): continue
            call = node.exc
            if not isinstance(call.func, ast.Name) or call.func.id not in ('ValueError', 'HTTPException'): continue
            for arg in call.args:
                text = None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str): text = arg.value
                elif isinstance(arg, ast.JoinedStr):
                    parts, index = [], 0
                    for part in arg.values:
                        if isinstance(part, ast.Constant): parts.append(str(part.value))
                        elif isinstance(part, ast.FormattedValue): parts.append('{' + str(index) + '}'); index += 1
                    text = ''.join(parts)
                if text and re.search('[\u3400-\u9fff]', text):
                    if text not in catalog or re.search('[\u3400-\u9fff]', catalog[text]): missing.append((path.name, node.lineno, text))
    assert not missing, missing
