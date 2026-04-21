import logging

from .cid import NO_CID_DISPLAY, get_cid


class CidFilter(logging.Filter):
    """
    Enriches log records with the Correlation ID (CID).
    """

    def filter(self, record):
        if not hasattr(record, "cid"):
            record.cid = get_cid() or NO_CID_DISPLAY

        return True
