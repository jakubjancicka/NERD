"""

"""
import sys
sys.path.append("../")
import redis
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from common import config
import re
import time
import logging

config_file = config.read_config("../etc/nerd/eventcountlogger.yml")
all_groups = config_file.get("groups")
redis_config = config_file.get("redis")
logger = logging.getLogger("EventCountLoggerMaster")


def create_redis_key(group, interval, is_current, event_id):
    """
    :param group: group name
    :param interval: interval in seconds
    :param is_current:
    :param event_id:
    :return:
    """
    type_str = 'cur' if is_current else 'last'

    return ':'.join([str(group), interval, type_str, str(event_id)])


def get_current_time():
    """
    Returns current UTC Unix timestamp.
    :return:
    """
    return int(time.time())


def int2sec(interval_str):
    pattern = re.compile(r'^[-+]?\d*\.\d+|\d+[hHmMsS]$')
    if pattern.match(interval_str):
        number = float(re.search(r'[-+]?\d*\.\d+|\d+', interval_str).group())
        char = str(re.search(r'[hHmMsS]', interval_str).group())
        if char in ["h", "H"]:
            return number * 3600
        if char in ["m", "M"]:
            return number * 60
        else:
            return number
    else:
        logger.error("interval {0} could not be parsed".format(interval_str))


class EventCountLoggerMaster:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.redis_pipe = redis.Redis(**redis_config).pipeline()

    def run(self):
        print("MASTER: Running")
        self.scheduler.start()
        now = get_current_time()
        for group_name, group in all_groups.items():
            for interval in group["intervals"]:
                seconds = int2sec(interval)
                first_log_time = now + seconds - now % seconds
                print("MASTER: Starting group {0} interval {1} in {2}s".format(group_name, interval,
                                                                               seconds - now % seconds))

                self.scheduler.add_job(self.__process, "interval", [group_name, interval], seconds=seconds,
                                       start_date=datetime.fromtimestamp(first_log_time))

        while 1:
            time.sleep(500)

    def __process(self, group_name, interval):
        print("MASTER: processing")
        for event_id in all_groups[group_name]["eventids"]:
            curr_key = create_redis_key(group_name, interval, True, event_id)
            last_key = create_redis_key(group_name, interval, False, event_id)
            time_key = create_redis_key(group_name, interval, True, "@ts")
            print("processing event '{0}', in group '{1}' with interval '{2}'".format(event_id, group_name, interval))

            self.redis_pipe.setnx(curr_key, 0)
            self.redis_pipe.rename(curr_key, last_key)
            self.redis_pipe.set(curr_key, 0)
            self.redis_pipe.set(time_key, get_current_time())

            self.redis_pipe.execute()


ECLMaster = EventCountLoggerMaster()
ECLMaster.run()
