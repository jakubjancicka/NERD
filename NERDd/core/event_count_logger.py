"""
Module for counting number of various events.
"""

from common import config
import redis
from datetime import datetime
import time
from apscheduler.schedulers.background import BackgroundScheduler
from multiprocessing import Process
import re
import logging

config_file = config.read_config("../etc/nerd/eventcountlogger.yml")
# module variables
redis_config = config_file.get("redis")
redis_pool = redis.ConnectionPool(**redis_config)
all_groups = config_file.get("groups")
instantiated_groups = {}
logger = logging.getLogger("event_count_logger")


def test():
    print("ECL Test:\nconfig:")
    print(redis_config)
    print("all_groups: ")
    import json
    print(json.dumps(all_groups, indent=2))


def get_group(name):
    """
    Create EventGroup representing given event group,
    loading its parameters from configuration file, or return reference to the existing one.
    :param name:
    :return:
    """
    if name in instantiated_groups:
        return instantiated_groups[name]
    else:
        if name not in all_groups:
            # TODO some error
            return None

        instantiated_groups[name] = EventGroup(name)
        return instantiated_groups[name]


class EventGroup:
    """
    Singleton class representing an event group and its configuration
    """

    def __init__(self, group_name):
        self.log = logging.getLogger("EventGroup_" + group_name)
        self.log.info("__init__")
        self.group_name = group_name
        this_group = all_groups[group_name]
        self.event_ids = this_group["eventids"]
        self.intervals = this_group["intervals"]
        self.use_local_counters = True
        self.sync_interval = None if "sync_interval" not in this_group else float(this_group["sync_interval"])
        self.sync_limit = None if "sync_limit" not in this_group else this_group["sync_limit"]

        if self.sync_interval is None and self.sync_limit is None:
            self.use_local_counters = False
        # local counters structure: { "5m": { "eventX": <count>, "eventY": <count> }, "1h": { "eventX": <count> ..} ..}
        if self.use_local_counters:
            self.log.info("This groupt is using local counters")
            self.counters = {interval: {x: 0 for x in self.event_ids} for interval in self.intervals}
        else:
            self.counters = None

        if self.sync_interval is not None:
            self.log.info("Starting background scheduler")
            self.scheduler = BackgroundScheduler()
            self.scheduler.start()
            self.scheduler.add_job(self.sync, 'interval', seconds=self.sync_interval)

    def log_event(self, event_id, count=1):
        """
        Increment counter event_id in given group by count.
        :param event_id:
        :param count:
        """
        self.log.info("logging event {0}: by {1}".format(event_id, count))
        if event_id in self.event_ids:
            if self.use_local_counters:
                for interval in self.counters.values():
                    interval[event_id] += count
                    if self.sync_limit is not None and interval[event_id] >= self.sync_limit:
                        self.sync()
            else:
                for interval in self.intervals:
                    key = create_redis_key(self.group_name, interval, True, event_id)
                    self.__increment_redis_value(key, count)
        else:
            self.log.warning("Event {0} is not declared!".format(event_id))

    def get_count(self, event_id):
        """
        Return current sate of counter event_id (local one is used when local counters are enabled).
        :param event_id:
        :return: Dictionary { "time_interval": counter_val, "next_interval" : ...}
        """
        if event_id in self.event_ids:
            ret_dict = {}
            # get counts from redis
            for interval in self.intervals:
                key = create_redis_key(self.group_name, interval, True, event_id)
                ret_dict[interval] = self.__get_redis_value(key)

            # add local counts
            if self.use_local_counters:
                for key, value in self.counters.items():
                    ret_dict[key] += value[event_id]

            return ret_dict
        else:
            self.log.warning("Event {0} is not declared!".format(event_id))

    def sync(self):
        """
        Force synchronization of counters in this group
        (do nothing when local counters are not enabled).
        :return:
        """
        if self.use_local_counters:
            for interval, value in self.counters.items():
                for event_key, event_val in value.items():
                    key = create_redis_key(self.group_name, interval, True, event_key)
                    self.__increment_redis_value(key, event_val)
                    value[event_key] = 0

    def declare_event_id(self, event_id):
        """
        Create counter for event_id if it doesn't exist yet.
        Should be equivalent to listing the event ID in configuration file.
        """
        if event_id not in self.event_ids:
            self.event_ids.append(event_id)
            for val in self.counters:
                val[event_id] = 0

    def declare_event_ids(self, event_ids):
        """
        The same as declare_event_id but for more values.
        """
        for event_id in event_ids:
            self.declare_event_id(event_id)

    def __get_redis_value(self, key):
        redis_server = redis.Redis(connection_pool=redis_pool)
        val = redis_server.get(key)
        return int(val) if val else 0

    def __increment_redis_value(self, key, value):
        redis_server = redis.Redis(connection_pool=redis_pool)
        redis_server.incr(key, amount=value)


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
        logger.warning("Interval string {0} does not match pattern '^[-+]?\d*\.\d+|\d+[hHmMsS]$'".format(interval_str))
