"""
__main__.py — allows running the package directly:
    python -m degradation_crawler [args...]

Also supports direct invocation of run.py from the command line when the
crawler/ directory is on sys.path.
"""
import sys
from pathlib import Path

# Ensure the crawler/ directory is on the path so relative imports in the
# package resolve correctly when called as `python -m degradation_crawler`
# from outside the crawler directory.
_here = Path(__file__).parent.parent   # crawler/
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from degradation_crawler.run import main  # noqa: E402

sys.exit(main())

