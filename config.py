import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / 'df_prices.sqlite3'


def load_env(path: Path | None = None) -> None:
    env_path = path or (BASE_DIR / '.env')
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()

DF_BASE_URL = os.environ.get('DF_BASE_URL', 'https://comm.ams.game.qq.com/ide/')
DF_CHART_ID = os.environ.get('DF_CHART_ID', '316969')
DF_SUB_CHART_ID = os.environ.get('DF_SUB_CHART_ID', '316969')
DF_IDE_TOKEN = os.environ.get('DF_IDE_TOKEN', 'NoOapI')
DF_METHOD = os.environ.get('DF_METHOD', 'dfm/object.price.latest')
DF_SOURCE = os.environ.get('DF_SOURCE', '2')
DF_COOKIE = os.environ.get('DF_COOKIE', '')
APP_HOST = os.environ.get('APP_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('APP_PORT', '8000'))
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
DB_BACKEND = 'postgres' if DATABASE_URL else 'sqlite'
