"""
Simple module for testing Event count logger
"""

from core.basemodule import NERDModule
import g

from core import event_count_logger
from multiprocessing import Process
from time import sleep


class ECLTest(NERDModule):
    def __init__(self):
        event_count_logger.test()
        self.log_some_events()
        self.start_master()

    def start_master(self):
        Process(target=self.start_master2())

    def start_master2(self):
        master = event_count_logger.EventCountLoggerMaster()
        master.run()

    def log_some_events(self):
        group1 = event_count_logger.get_group("test_group")
        group1.log_event("event1", 2)
        group2 = event_count_logger.get_group("test_group1")
        group2.log_event("event1", 2)
        group2.log_event("event3", 2)
        group2.log_event("event2", 2)
        group3 = event_count_logger.get_group("test_group2")
        group3.log_event("event1", 2)




