import socket
import redis
from bot.logger import logger

hostname = "localhost"
port = 6379
address = f"redis://{hostname}:{port}"

bot_db = 14

def is_redis_up() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((hostname, port)) == 0

def get_bot_db():
    rdb = redis.Redis(
        host=hostname,
        port=port,
        db = bot_db)
    return(rdb)

db_r = None
logger.init("Database", status="Connecting")
if is_redis_up():
    db_r = get_bot_db()
    logger.init_ok("Database", status="Connected")
else:
    logger.init_err("Database", status="Failed")
    # raise Exception("No redis DB found")
