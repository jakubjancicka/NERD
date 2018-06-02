"""
Module for counting number of various events.
"""

from common import config
import redis
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

config_file = config.read_config("../etc/nerd/eventcountlogger.yml")
# module variables
redis_config = config_file.get("redis")
redis_db = redis.Redis(**redis_config)
all_groups = config_file.get("groups")
instantiated_groups = {}


def test():
    print("ECL Test:")
    print(redis_config)
    print()


def get_group(name):
    """
    Create EventGroup representing given event group,
    loading its parameters from configuration file, or return reference to the existing one.
    :param name:
    :return:
    """
    if name in instantiated_groups.keys():
        return instantiated_groups[name]
    else:
        if name not in all_groups.keys():
            # TODO some error
            return None

        instantiated_groups[name] = EventGroup(name)
        return instantiated_groups[name]


class EventGroup:
    """
    Singleton class representing an event group and its configuration
    """

    def __init__(self, group_name):
        self.group_name = group_name
        this_group = all_groups[group_name]
        self.event_ids = this_group["eventids"]
        self.intervals = this_group["intervals"]
        self.use_local_counters = True
        self.sync_interval = None if "sync_interval" not in this_group.keys() else float(this_group["sync_interval"])
        self.sync_limit = None if "sync_limit" not in this_group.keys() else this_group["sync_limit"]

        if self.sync_interval is not None:
            self.scheduler = BackgroundScheduler()
            self.scheduler.start()
            self.scheduler.add_job(self.sync, 'interval', seconds=self.sync_interval)

        if self.sync_interval is None and self.sync_limit is None:
            self.use_local_counters = False
        # local counters structure:
        # {
        #  "5m": {
        #           "eventX": <count>,
        #           "eventY": <count>
        #        },
        #  "1h": {
        #           "eventX": <count>,
        #           "eventY": <count>
        #        }
        # }
        if self.use_local_counters:
            self.counters = {interval: {x: 0 for x in self.event_ids} for interval in self.intervals}
        else:
            self.counters = None

        self.redis_pipe = redis_db.pipeline()

    def log_event(self, event_id, count=1):
        """
        Increment counter event_id in given group by count.
        :param event_id:
        :param count:
        """

        if event_id in self.event_ids:
            if self.use_local_counters:
                for interval in self.counters:
                    interval[event_id] += count
                    if self.sync_limit is not None and interval[event_id] > self.sync_limit:
                        self.sync()
            else:
                for interval in self.intervals:
                    key = self.__create_redis_key(self.group_name, interval, True, event_id)
                    self.__increment_redis_value(key, count)
        else:
            # some error
            pass

    def get_count(self, event_id):
        """
        Return current sate of counter event_id (local one is used when local counters are enabled).
        :param event_id:
        :return: Dictionary { "time_interval": counter_val, "next_interval" : ...}
        """
        if event_id in self.event_ids:
            ret_dict = {}
            if self.use_local_counters:
                for key, value in self.counters:
                    ret_dict[key] = value[event_id]
            else:
                pass

            return ret_dict
        else:
            # some error
            pass

    def sync(self):
        """
        Force synchronization of counters in this group
        (do nothing when local counters are not enabled).
        :return:
        """
        if self.use_local_counters:
            for interval, value in self.counters:
                for event_key, event_val in value:
                    key = self.__create_redis_key(self.group_name, interval, True, event_key)
                    self.__increment_redis_value(key, value)

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

    def __create_redis_key(self, group, interval, is_current, event_id):
        """
        :param group: group name
        :param interval: interval in seconds
        :param is_current:
        :param event_id:
        :return:
        """
        type_str = 'cur' if is_current else 'last'

        return ':'.join([str(group), interval, type_str, str(event_id)])

    def __update_redis_value(self, event_id, server):
        pass

    def __get_current_time(self):
        """
        Returns current UTC Unix timestamp.
        :return:
        """
        return int(datetime.now().timestamp())

    def __increment_redis_value(self, key, value):
        while 1:
            try:
                self.redis_pipe.watch(key)
                current_val = self.redis_pipe.get(key)
                current_val = value if current_val is None else current_val + value
                self.redis_pipe.multi()
                self.redis_pipe.set(key, current_val)
                self.redis_pipe.execute()
            except redis.WatchError:
                continue
            finally:
                self.redis_pipe.reset()


class EventCountLoggerMaster:
    def __init__(self):
        pass