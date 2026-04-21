import logging
import os

from django.conf import settings

from .cid import NO_CID_DISPLAY


class ConsoleFormatter(logging.Formatter):
    """
    Cleaner formatter that handles missing CIDs and shortens paths
    without destroying the original log record.
    """

    DEFAULT_FORMAT = (
        "[%(levelname)-8s - %(name)-20s] - [cid: %(cid)s] - [%(asctime)s] - [%(clean_path)s:%(lineno)s]: %(message)s"
    )

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt or self.DEFAULT_FORMAT, datefmt)

    def format(self, record):
        if not hasattr(record, "cid"):
            record.cid = NO_CID_DISPLAY

        try:
            rel_path = os.path.relpath(record.pathname, settings.BASE_DIR)
            record.clean_path = rel_path.replace("app/", "", 1) if rel_path.startswith("app/") else rel_path
        except Exception:
            record.clean_path = record.pathname

        return super().format(record)
