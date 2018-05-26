"""
Module for counting number of various events.
"""

from common import config
import redis
from datetime import datetime

config_file = config.read_config("../etc/nerd/eventcountlogger.yml")
# module variables
redis_config = config_file.get("redis")
redis_pool = redis.ConnectionPool(**redis_config)
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
        self.sync_interval = None if "sync_interval" not in this_group.keys() else this_group["sync_interval"]
        self.sync_limit = None if "sync_limit" not in this_group.keys() else this_group["sync_limit"]

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
            else:
                server = redis.Redis(connection_pool=redis_pool)
                for interval in self.intervals:
                    key = self.__create_redis_key(self.group_name, interval, True, event_id)
                    current_value = server.get(key, event_id)
                    current_value = 0 if current_value is None else int(current_value)
                    server.set(key, current_value)
        else:
            # some error
            pass

    def get_count(self, event_id):
        """
        Return current sate of counter event_id (local one is used when local counters are enabled).
        :param event_id:
        :return:
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
            server = redis.Redis(connection_pool=redis_pool)
            for interval, value in self.counters:
                for event_key, event_val in value:
                    key = self.__create_redis_key(self.group_name, interval, True, event_key)
                    server.set(key, event_val)

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
