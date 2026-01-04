import logging


def get_logger() -> logging.Logger:

    logger = logging.getLogger(__name__)

    if not logger.handlers:  # Prevent adding multiple handlers in interactive use
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
    return logger
