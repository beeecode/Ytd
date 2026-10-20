from redis import Redis
from rq import Queue

from . import config

redis_conn = Redis.from_url(config.REDIS_URL)
download_queue = Queue("downloads", connection=redis_conn)
