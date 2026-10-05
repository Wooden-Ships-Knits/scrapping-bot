"""Print the API's OpenAPI schema. The web app generates its TypeScript types from it:

uv run python -m scrapebot.api.openapi > web/openapi.json
"""

import json

from .app import create_app


def main() -> None:
    print(json.dumps(create_app().openapi(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
