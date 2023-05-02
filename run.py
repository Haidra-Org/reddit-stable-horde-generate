import praw
import time
import threading
from bot.logger import logger
from bot.listener import StreamListenerExtended
from bot.notifications import MentionHandler
from bot import reddit
from loguru import logger


@logger.catch(reraise=True)
def check_for_requests():
    waiting_threads = []
    for notification in reddit.inbox.all():
        # Avoid parsing comments older than 3 days
        if notification.created_utc < time.time() - (86400 * 3):
            logger.debug([notification.created_utc,time.time() - (86400 * 3),notification.created_utc < time.time() - (86400 * 3)])
            continue
        notification_handler = MentionHandler(notification)
        thread = threading.Thread(target=notification_handler.handle_notification, args=())
        thread.start()
        waiting_threads.append(thread)    


logger.init("Reddit Stable Horde Bot", status="Starting")
try:
    # Normally this shouldn't be needed, as the initial stream gets the last 100
    # check_for_requests()
    while True:
        try:
            logger.debug(f"Starting Reddit Inbox Stream")
            listener = StreamListenerExtended()
            time.sleep(1)
        except Exception as e:
            raise e
            logger.warning(f"{e} continuing")
            listener.shutdown()
            time.sleep(2)
except KeyboardInterrupt:
    logger.init_ok("Reddit Stable Horde Bot", status="Exited")