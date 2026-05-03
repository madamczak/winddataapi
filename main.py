import sys
import uvicorn
from app.api import app


if __name__ == '__main__':
    # allow `python main.py` to run the API for development
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except Exception:
            pass
    uvicorn.run(app, host='0.0.0.0', port=port)

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
