"""The retailer map: where brands like ours are sold, read from the process output.

`process/build_dashboard.py` writes one `retailer_map.json` per run. This view serves the
newest one as it is. Nothing is computed here, and the pipeline is not involved.
"""

from pathlib import Path

from pydantic import ValidationError

from .schemas import RetailerMapOut

FILE = "retailer_map.json"


class RetailerMapError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


def retailer_map(process_dir: Path) -> RetailerMapOut:
    """The map of the newest run that has one. Run ids start with their time, so they sort."""
    found = sorted(process_dir.glob(f"*/{FILE}"))
    if not found:
        raise RetailerMapError(
            "no_process_output",
            "No run has been processed yet. Run: uv run --group process python process/run_all.py",
        )
    try:
        return RetailerMapOut.model_validate_json(found[-1].read_text())
    except ValidationError as exc:
        raise RetailerMapError(
            "process_output_invalid",
            f"{found[-1]} does not match what this page reads; run the process again.",
        ) from exc
