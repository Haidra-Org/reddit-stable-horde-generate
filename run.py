import praw
import time
import threading
from bot.logger import logger
from bot.listener import StreamListenerExtended
from bot.notifications import MentionHandler
from bot import reddit


@logger.catch(reraise=True)
def check_for_requests():
    for comment in reddit.inbox.all():
        logger.debug([comment.author,comment.body,comment.subreddit,])
    waiting_threads = []
    for comment in reddit.inbox.all():
        notification_handler = MentionHandler(notification)
        thread = threading.Thread(target=notification_handler.handle_notification, args=())
        thread.start()
        waiting_threads.append(thread)    


logger.init("Reddit Stable Horde Bot", status="Starting")
try:
    check_for_requests()
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