from __future__ import annotations

import uvicorn

from monitor.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "monitor.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
