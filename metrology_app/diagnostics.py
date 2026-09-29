"""Shared application diagnostics routed to the shell's terminal-like log."""

import logging


LOGGER_NAME = "metrology_workspace"


def get_logger():
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    return logger


__all__ = ["LOGGER_NAME", "get_logger"]
