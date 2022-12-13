from bot.argparser import args
from bot.logger import logger, set_logger_verbosity, quiesce_logger
import praw
import os
from dotenv import load_dotenv

load_dotenv()

reddit = praw.Reddit(
    client_id=os.environ["CLIENT_ID"],
    client_secret=os.environ["CLIENT_SECRET"],
    username=os.environ["BOT_USERNAME"],
    password=os.environ["BOT_PASSWORD"],
    user_agent=os.environ["USER_AGENT"],
)

    