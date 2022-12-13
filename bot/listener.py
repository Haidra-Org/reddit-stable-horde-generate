import threading
import time
from bot import reddit
from bot.logger import logger
from bot.notifications import MentionHandler

REDDIT_BLACKLIST =  [
    "suicidewatch"
    "depression"
]
class StreamListenerExtended:
    stop_thread = False

    def __init__(self):
        super().__init__()
        self.queue = []
        self.processing_notifications = []
        self.concurrency = 4
        self.queue_thread = threading.Thread(target=self.process_queue, args=())
        self.queue_thread.daemon = True
        self.queue_thread.start()
        for item in reddit.inbox.stream():
            if item.subreddit in REDDIT_BLACKLIST:
                logger.warning(f"Avoiding comment {item} in blacklisted subreddit {item.subreddit}")
                continue
            logger.info(f"Processing comment {item} in subreddit {item.subreddit}")
            self.on_notification(item)

    @logger.catch(reraise=True)
    def on_notification(self,notification):
        if True: #TODO: Check that it's a mention
            self.queue.append(MentionHandler(notification))
    
    def shutdown(self):
        self.stop_thread = True

    @logger.catch(reraise=True)
    def process_queue(self):
        logger.init("Queue processing thread", status="Starting")
        while True:
            if self.stop_thread:
                logger.init_ok("Queue processing thread", status="Stopped")
                return
            processing_notifications = self.processing_notifications.copy()
            for pn in processing_notifications:
                if pn.is_finished():
                    self.processing_notifications.remove(pn)
                    logger.debug(f"removing {pn}")
            if len(self.queue) and len(self.processing_notifications) < self.concurrency:
                notification_handler = self.queue.pop(0)
                self.processing_notifications.append(notification_handler)
                logger.debug(f"starting {notification_handler}")
                thread = threading.Thread(target=notification_handler.handle_notification, args=())
                thread.daemon = True
                thread.start()
            time.sleep(1)
