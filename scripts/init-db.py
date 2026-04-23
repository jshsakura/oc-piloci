from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure src/ is on the path when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from piloci.config import get_settings
from piloci.db.session import init_db


async def main() -> None:
    settings = get_settings()
    await init_db()

    # Extract the file path from the SQLite URL for display
    db_url = settings.database_url
    # sqlite+aiosqlite:////data/piloci.db  → /data/piloci.db
    if ":///" in db_url:
        db_path = db_url.split("///", 1)[1]
        if not db_path.startswith("/"):
            db_path = "/" + db_path
    else:
        db_path = db_url

    print(f"Database initialized at {db_path}")


if __name__ == "__main__":
    asyncio.run(main())
