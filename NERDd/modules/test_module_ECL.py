"""
Simple module for testing Event count logger
"""

from core.basemodule import NERDModule
import g

from core import event_count_logger

class ECLTest(NERDModule):
    def __init__(self):
        event_count_logger.test()
