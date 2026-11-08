import logging

import uvicorn

from aidm.config.settings import Settings
from aidm.web.app import create_app


def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level)
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.port)


if __name__ == "__main__":
    main()
