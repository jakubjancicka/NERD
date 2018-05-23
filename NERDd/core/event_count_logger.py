"""
Module for counting number of various events.
"""

import g

# module variables
redis_config = g.config.get("redis")
all_groups = g.config.get("groups")
instantiated_groups = {}


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
        self.sync_interval = this_group["sync_interval"]
        self.sync_limit = this_group["sync_limit"]

        self.counters = {x: 0 for x in self.event_ids}

    def log_event(self, event_id, count=1):
        """
        Increment counter event_id in given group by count.
        :param event_id:
        :param count:
        """
        if event_id in self.event_ids:
            self.counters[event_id] += count
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
            return self.counters[event_id]
        else:
            # some error
            pass

    def sync(self):
        """
        Force synchronization of counters in this group
        (do nothing when local counters are not enabled).
        :return:
        """
        pass

    def declare_event_id(self, event_id):
        """
        Create counter for event_id if it doesn't exist yet.
        Should be equivalent to listing the event ID in configuration file.
        """
        pass

    def declare_event_ids(self, event_ids):
        """
        The same as declare_event_id but for more values.
        """
        for event_id in event_ids:
            self.declare_event_id(event_id)
