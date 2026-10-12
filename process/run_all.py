"""Run the whole process for one run: the four notebooks in order, then the dashboard.

    uv run --group process python process/run_all.py

The notebooks in this folder stay free of outputs, because outputs hold store and stockist
names. The executed copies go to data/process/<run>/executed/, which is never committed.
"""

from pathlib import Path

import build_dashboard
import nbformat
import nbutil as nb
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent


def main() -> None:
    executed = nb.process_dir() / "executed"
    executed.mkdir(parents=True, exist_ok=True)
    for path in sorted(HERE.glob("0*.ipynb")):
        notebook = nbformat.read(path, as_version=4)
        NotebookClient(notebook, timeout=900, resources={"metadata": {"path": str(HERE)}}).execute()
        nbformat.write(notebook, executed / path.name)
        print(f"{path.name}: ok")
    print(f"with outputs: {executed.relative_to(nb.ROOT)}")
    build_dashboard.main()


if __name__ == "__main__":
    main()
