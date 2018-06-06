
import sys
sys.path.insert(0, "../NERDd/core")

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from core import event_count_logger as ECL
from datetime import datetime

redis_config = ECL.redis_config


class EventCountLoggerMaster:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.redis_pipe = redis.Redis(redis_config).pipeline()

    def run(self):
        self.scheduler.start()
        now = ECL.get_current_time()
        for group_name, group in ECL.all_groups:
            for interval in group["intervals"]:
                seconds = ECL.int2sec(interval)
                first_log_time = now + seconds - now % seconds
                self.scheduler.add_job(lambda: self.__start_interval(group_name, interval, seconds),
                                       'date',
                                       run_date=datetime.fromtimestamp(first_log_time))

    def __start_interval(self, group_name, interval, seconds):
        self.scheduler.add_job(lambda: self.__process(group_name, interval), "interval", seconds=seconds)

    def __process(self, group_name, interval):
        for event_id in ECL.all_groups[group_name]["eventids"]:
            curr_key = ECL.create_redis_key(group_name, interval, True, event_id)
            last_key = ECL.create_redis_key(group_name, interval, False, event_id)
            time_key = ECL.create_redis_key(group_name, interval, True, "@ts")

            self.redis_pipe.multi()
            self.redis_pipe.setnx(curr_key, 0)
            self.redis_pipe.rename(curr_key, last_key)
            self.redis_pipe.set(curr_key, 0)
            self.redis_pipe.set(time_key, ECL.get_current_time())
            self.redis_pipe.execute()


ECLMaster = EventCountLoggerMaster()
ECLMaster.run()
