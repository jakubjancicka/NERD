"""
Module for counting number of various events.
"""

from time import gmtime, strftime, mktime
import logging
import json
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

import os
import g

class EventCountLogger():
    """

    """

    def __init__(self):
        # dict in format: { "group1": { "freq": int, "events": { "event_id1": val, ...},
        #                   "group2": { "freq": int, "events": { "event_id1": val, "event_id2": val ... } }
        self.log = logging.getLogger('EventCountLogger')
        self.all_groups = {}
        # old data, while registration, this variable will be checked for some useful data
        self.recovery = None

        self.log_path = g.config.get("log_path")
        if not os.path.exists(self.log_path):
            os.makedirs(self.log_path)

        self.recoverAfterRestart()

        # scheduler
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()

    def registerEvents(self, group, log_frequency, event_ids):
        """
        Use this function before you start logging events.
        :param group: Name of the group, the file with logs will have the same name.
        :param log_frequency: Time interval in seconds, after which,
                              the log for this interval will be appended to the log file.
        :param event_ids: A list of event names you want to collect in this group.
                          e.g.: ["BGP_query", "rank_update" ...]
        :return:
        """
        if group in self.all_groups.keys():
            raise ValueError("Group name " + str(group) + " already exists!")

        # the minimal time interval is 1 second
        if log_frequency < 1:
            log_frequency = 1
            self.log.warning("Log freqency was set to 1 second as it is the minimal time interval.")

        self.all_groups[group] = {"freq": int(log_frequency), "events": {name: 0 for name in event_ids}}
        self.initFile(group)
        self.checkForOldData(group)
        now = int(datetime.now().timestamp())
        # set the first log time the way, that epoch%freq == 0, with this magical expression
        first_log_time = now + log_frequency - now % log_frequency
        self.scheduler.add_job(lambda: self.startLogging(group),
                               'date',
                               run_date=datetime.fromtimestamp(first_log_time))

    def startLogging(self, group):
        self.scheduler.add_job(lambda: self.saveGroup(group),
                               'interval',
                               seconds=self.all_groups[group]["freq"])

    def initFile(self, group):
        filename = self.filename(group)

        # if file does not exist yet, create one
        with open(filename, "w") as fw:
            fw.write("# filename: " + filename + "\n")
            fw.write("# logging frequency: " + str(self.all_groups[group]["freq"]) + " sec\n")
            fw.write("# event ids: \n")
            fw.write("# ")
            for event_id in self.all_groups[group]["events"]:
                fw.write(event_id + " ")
            fw.write("\n\n")
            fw.close()


    def filename(self, group):
        """
        Simple unifying function for creating filenames.
        """
        return os.path.join(self.log_path, group + ".log")

    def logEvent(self, event_id, count=1):
        """
        Simple function for incrementing value of some event.
        :param event_id:
        :param count:
        """
        event_id_exists = False
        # iteration over groups
        for group_name, group in self.all_groups.items():
            if event_id in group["events"]:
                group["events"][event_id] += count
                event_id_exists = True

        if event_id_exists is False:
            raise ValueError("Event ID '" + str(event_id) + "' is not registered in any group!")

    def saveGroup(self, group):
        """
        Function for appending current data to group files in format:
        #YYYY-MM-DDTHH:MM:SS
        eventid count
        eventid count
        :param group: name of group to be saved
        :return:
        """
        filename = self.filename(group)
        if not os.path.isfile(filename):
            raise FileExistsError("File " + filename + " was deleted!")

        with open(filename, "a") as fa:
            fa.write("#" + strftime("%Y-%m-%dT%H:%M:%S\n", gmtime()))
            for event, cnt in self.all_groups[group]["events"].items():
                fa.write(event + ": " + str(cnt) + "\n")
                self.all_groups[group]["events"][event] = 0
            fa.write("\n")

    def stop(self):
        """
        This function needs to be called by nerdd.py before exit.
        :return:
        """
        with open(self.filename("count_logger_recovery_file"), "w") as fw:
            recovery_dict = {
                             "time": int(datetime.now().timestamp()),
                             "allGroups": self.all_groups
                            }
            json.dump(recovery_dict, fw)
            fw.close()

    def checkForOldData(self, group):
        """
        Checks for old data of an group saved in the recovery file.
        :param group: group name
        :return:
        """
        if self.recovery is None:
            return
        timestamp_old = self.recovery["time"]
        all_groups_old = self.recovery["allGroups"]
        timestamp = int(datetime.now().timestamp())
        if group in all_groups_old:
            # check if configuration is the same
            if all_groups_old[group]["freq"] == self.all_groups[group]["freq"] and \
               set(all_groups_old[group]["events"].keys()) == set(self.all_groups[group]["events"].keys()):
                if timestamp - timestamp_old < all_groups_old[group]["freq"]:
                    for event, value in all_groups_old[group]["events"]:
                        self.all_groups[group]["events"][event] = value

    def recoverAfterRestart(self):
        """
        This function will load all_groups_old variable, if old data exist.
        :return:
        """

        if not os.path.isfile(self.filename("count_logger_recovery_file")):
            return

        with open(self.filename("count_logger_recovery_file"), "r") as fr:
            self.recovery = json.load(fr)
            fr.close()

        os.remove(self.filename("count_logger_recovery_file"))