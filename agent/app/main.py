"""Entry point for the Python Agent gRPC service."""

import logging
import signal
import sys

from app.config import config
from app.grpc_server import create_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    port = config.grpc_port
    server = create_server(port)
    server.start()
    logger.info("Agent gRPC server started on port %s", port)

    def shutdown(signum, frame):
        del signum, frame
        logger.info("Shutting down gracefully...")
        event = server.stop(grace=10)
        event.wait()
        logger.info("Server stopped")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, shutdown)

    server.wait_for_termination()


if __name__ == "__main__":
    main()
