"""
Simple module for testing Event count logger
"""

from core.basemodule import NERDModule
import g

from core import event_count_logger
from multiprocessing import Process
from time import sleep


def separateProcess(num):
    event_count_logger.test_var[0] += 1

    print("process " + str(num) + " exits. var val: " + str(event_count_logger.test_var[0]))
    exit(0)


class ECLTest(NERDModule):
    def __init__(self):
        event_count_logger.test()




