import requests, json, os, time, base64, random, re, pprint
import threading
from bs4 import BeautifulSoup
from datetime import timedelta
from bot.logger import logger
from bot.horde import HordeMultiGen
from bot.enums import JobStatus
from bot.redisctrl import db_r
from bot import reddit
from bot.r2 import upload_image
from bot.argparser import args
from praw.exceptions import ClientException, RedditAPIException

imgen_params = {
    "n": 1,
    "karras": True,
    "steps": 10,
    "post_processing": ['GFPGAN'],
}
generic_submit_dict = {
    "prompt": "a horde of cute stable robots in a sprawling server room repairing a massive mainframe",
    "nsfw": False,
    "censor_nsfw": True,
    "r2": True,
    "trusted_workers": True,
    "models": ["stable_diffusion"]
}
pp = pprint.PrettyPrinter(depth=3)
term_regex = re.compile(r'draw for me (.+)', re.IGNORECASE)
modifier_seek_regex = re.compile(r'style:', re.IGNORECASE)
prompt_only_regex = re.compile(r'draw for me (.+)style:', re.IGNORECASE)
style_regex = re.compile(r'style: *([\w ]+)', re.IGNORECASE)

blacklist = re.compile(os.getenv("BLACKLIST"), re.IGNORECASE)

subreddit = reddit.subreddit("StableHorde")

reply_string = """
Here are {some_images} matching your request\n
{image_markdown_list}\n
Prompt: {unformated_prompt}\n
Style: {requested_style}\n\n
*I am [a bot](https://www.reddit.com/user/StableHorde/comments/znhtaw/faq/)*
"""
if args.redirect:
    reply_string += f"*This account is obsolete. Please mention `u/{args.redirect}` from now on."
else:
    reply_string += "*I am [a bot](https://www.reddit.com/user/StableHorde/comments/znhtaw/faq/)*"

class MentionHandler:

    def __init__(self, notification):
        self.status = JobStatus.INIT
        self.notification = notification
        self.request_id = self.notification.id
        self.mention_content = BeautifulSoup(self.notification.body_html,features="html.parser").get_text()

    def is_finished(self):
        return self.status in [JobStatus.DONE, JobStatus.FAULTED]
        
    @logger.catch(reraise=True)
    def handle_notification(self):
        if db_r.get(str(self.request_id)):
            self.status = JobStatus.FAULTED
            return
        if db_r.get(str(self.notification.author)):
            logger.warning(f"Too frequent requests from {self.notification.author}")
            return
        if self.notification.author != 'dbzer0' and db_r.get(f"horny_jail_{self.notification.author}"):
            logger.warning(f"{self.notification.author} currently in Horny Jail")
            return
        if False: #TODO Ensure it's a comment mention
            self.handle_dm()
        else:
            self.handle_mention()
        
    def handle_mention(self):
        # pp.pprint(notification)
        self.status = JobStatus.WORKING
        logger.debug(f"Handling notification {self.request_id} as a mention")
        # logger.debug([self.request_id, last_parsed_notification, self.request_id < last_parsed_notification])
        reg_res = term_regex.search(self.mention_content)
        if not reg_res:
            logger.info(f"{self.request_id} is not a generation request, skipping")
            db_r.setex(str(self.request_id), timedelta(days=120), 1)
            self.status = JobStatus.DONE
            return
        styles_array, requested_style = parse_style(self.mention_content)
        if len(styles_array) == 0:
            self.reply_faulted("We could not discover this style in our database. Please pick one from [styles](https://github.com/db0/Stable-Horde-Styles/blob/main/styles.json) or [categories](https://github.com/db0/Stable-Horde-Styles/blob/main/categories.json)")
            return
        db_r.setex(str(self.notification.author), timedelta(seconds=20), 1)
        unformated_prompt = reg_res.group(1)[0:500]
        negprompt = ''
        if modifier_seek_regex.search(unformated_prompt):
            por = prompt_only_regex.search(self.mention_content)
            unformated_prompt = por.group(1)
        if "###" in unformated_prompt:
            unformated_prompt, negprompt = unformated_prompt.split("###", 1)
        if self.notification.author != 'dbzer0' and blacklist.search(unformated_prompt):
            logger.warning(f"Detected Blacklist item from {self.notification.author}")
            db_r.setex(f"horny_jail_{self.notification.author}", timedelta(seconds=20), 1)
            self.set_faulted()
            return
        logger.info(f"Starting generation from ID '{self.request_id}'. Prompt: {unformated_prompt}. Style: {requested_style}")
        submit_list = []
        for style in styles_array:
            if "###" not in style["prompt"] and negprompt != '' and "###" not in negprompt:
                negprompt = '###' + negprompt
            submit_dict = generic_submit_dict.copy()
            submit_dict["prompt"] = style["prompt"].format(p=unformated_prompt, np=negprompt)
            submit_dict["params"] = imgen_params.copy()
            submit_dict["models"] = [style["model"]]
            submit_dict["params"]["width"] = style.get("width", 512)
            submit_dict["params"]["height"] = style.get("height", 512)
            submit_dict["params"]["sampler_name"] = style.get("sampler", "k_euler_a")
            submit_dict["params"]["steps"] = style.get("steps", 45)
            submit_dict["params"]["cfg_scale"] = style.get("cfg_scale", 7.5)
            submit_list.append(submit_dict)
        # logger.debug(submit_list)
        # self.reply_faulted("This is a test reply")
        # return
        gen = HordeMultiGen(submit_list, self.request_id)
        while not gen.all_gens_done():
            if gen.is_faulted():
                if not gen.is_possible():
                    self.reply_faulted("It is not possible to fulfil this request using this style at the moment. Please select a different style and try again.")
                else:
                    self.reply_faulted("Something went wrong when trying to fulfil your request. Please try again later")
                return
            time.sleep(1)
        if args.subreddit:
            self.upload_to_subreddit(gen, requested_style, unformated_prompt)
        else:
            self.upload_to_r2(gen, requested_style, unformated_prompt)
        for fn in gen.get_all_filenames():
            os.remove(fn)
        db_r.setex(str(self.request_id), timedelta(days=120), 1)
        self.status = JobStatus.DONE

    def upload_to_r2(self, gen, requested_style, unformated_prompt):
        image_urls = []
        for job in gen.get_all_done_jobs():
            download_link = upload_image(job.filename)
            if download_link:
                image_urls.append(download_link)
        logger.info(f"replying to {self.request_id}: {self.mention_content}")
        # logger.debug(f"{requested_style}: {unformated_prompt}")
        image_markdowns = []
        iter = 0
        for image_url in image_urls:
            iter += 1
            image_markdowns.append(
                f'[[Gen{iter}]]({image_url})'
            )
        try:
            self.notification.reply(
                reply_string.format(
                    some_images = "some images",
                    image_markdown_list = " ".join(image_markdowns),
                    unformated_prompt = unformated_prompt,
                    requested_style = requested_style,
                )
            )
        except RedditAPIException as e:
            self.set_faulted()
            logger.error(f"Reddit Exception: {e}. Aborting!")
            return

    def upload_to_subreddit(self, gen, requested_style, unformated_prompt):
        images_payload = []
        for job in gen.get_all_done_jobs():
            image_dict = {
                "image_path": job.filename, 
                "caption": f"Seed {job.seed}. Prompt: {job.prompt}"[0:179]
            }
            images_payload.append(image_dict)
        logger.info(f"replying to {self.request_id}: {self.mention_content}")
        logger.debug(f"{requested_style}: {unformated_prompt}")
        logger.debug(f"{images_payload}")
        for iter in range(4):
            try:
                submission = subreddit.submit_gallery(f"{requested_style}: {unformated_prompt}"[0:298], images_payload)
                break
            except (ClientException) as e:
                self.set_faulted()
                logger.error(f"Bad filename. Aborting!")
                return
            except (RedditAPIException) as e:
                if iter >= 3:
                    self.set_faulted()
                    logger.error(f"Reddit Exception: {e}. Aborting!")
                    return
        submission_images = submission.media_metadata
        image_markdowns = []
        iter = 0
        for image_item in submission_images.values():
            iter += 1
            for proc_iter in range(120):
                if image_item.get("status") == "unprocessed":
                    time.sleep(1)
                    logger.debug(f"Image still processing. Sleeping ({proc_iter}/10)")
                    continue
            if image_item.get("status") == "unprocessed":
                self.set_faulted()
                logger.error(f"Images taking unreasonably long to process. Aborting!")
                return
            largest_image = image_item['s']
            image_url = largest_image['u']
            image_markdowns.append(
                f'[[Gen{iter}]]({image_url})'
            )
        try:
            self.notification.reply(
                reply_string.format(
                    some_images = f"[some images]({submission.permalink})",
                    image_markdown_list = " ".join(image_markdowns),
                    unformated_prompt = unformated_prompt,
                    requested_style = requested_style,
                )
            )
        except RedditAPIException as e:
            self.set_faulted()
            logger.error(f"Reddit Exception: {e}. Aborting!")
            return

    def handle_dm(self):
        # pp.pprint(notification)
        logger.debug(f"Handling notification {self.request_id} as a DM")
        db_r.setex(str(self.request_id), timedelta(days=120), 1)
        self.status = JobStatus.DONE

    def set_faulted(self):
        self.status = JobStatus.FAULTED
        db_r.setex(str(self.request_id), timedelta(days=120), 1)

    def reply_faulted(self,message):
        self.set_faulted()
        try:
            self.notification.reply(
                message
            )
        except RedditAPIException as e:
            logger.error(f"Reddit Exception: {e}. Aborting!")
            return

def get_styles():
    # styles = db_r.get("styles")
    # logger.info([styles, type(styles)])
    downloads = [
        # Styles
        {
            "url": "https://raw.githubusercontent.com/db0/Stable-Horde-Styles/main/styles.json",
            "default": {"raw": "{p}"}
        },
        # Categories
        {
            "url": "https://raw.githubusercontent.com/db0/Stable-Horde-Styles/main/categories.json",
            "default": {}
        },
    ]
    logger.debug("Downloading styles")
    jsons = []
    for download in downloads:
        for iter in range(5):
            try:
                r = requests.get(download["url"],timeout=5)
                jsons.append(r.json())
                break
            except Exception as e:
                if iter >= 3: 
                    jsons.append(download["default"])
                    break
                logger.warning(f"Error during file download. Retrying ({iter+1}/3)")
                time.sleep(1)
    return(jsons)

def parse_style(mention_content):
    '''retrieves the styles requested and returns a list of unformated style prompts and the models to use'''
    global style_regex
    jsons = get_styles()
    styles = jsons[0]
    categories = jsons[1]
    style_array = []
    requested_style = "raw"
    sr = style_regex.search(mention_content)
    if sr:
        requested_style = sr.group(1).lower()
    if requested_style in styles:
        for iter in range(4):
            style_array.append(styles[requested_style])
    elif requested_style in categories:
        category_copy = []
        for iter in range(4):
            if len(category_copy) == 0:
                category_copy = categories[requested_style].copy()
            random_style = category_copy.pop(random.randrange(len(category_copy)))    
            if random_style not in styles:
                logger.error(f"Category has style {random_style} which cannot be found in styles json:")
                continue
            style_array.append(styles[random_style])
    logger.debug(style_array)
    return(style_array, requested_style)