"""scrapebot: bulk store links in, raw store data out."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("scrapebot")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"
