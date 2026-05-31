"""
__main__.py — allows running the package directly:
    python -m service_crawler [args...]

Can be invoked from the crawler/ directory or from anywhere as long as
the crawler/ parent is on sys.path.
"""
import sys
from pathlib import Path

# Ensure the crawler/ directory is on the path so relative imports resolve.
_here = Path(__file__).parent.parent   # crawler/
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from service_crawler.run import main  # noqa: E402

sys.exit(main())

