import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_generated_docs_are_fresh():
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_api_doc.py"), "--check"], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_doc_index_links_exist():
    index = (ROOT / "doc" / "plugins" / "README.md").read_text(encoding="utf-8")
    import re
    for name in re.findall(r"\]\(([A-Z_]+\.md)\)", index):
        assert (ROOT / "doc" / "plugins" / name).is_file(), name
