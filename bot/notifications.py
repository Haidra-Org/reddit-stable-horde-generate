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
from prawcore.exceptions import ServerError
from bot.lemmy import lemmy

imgen_params = {
    "n": 1,
    "karras": True,
    "steps": 10,
    "post_processing": [],
}
generic_submit_dict = {
    "prompt": "a horde of cute stable robots in a sprawling server room repairing a massive mainframe",
    "nsfw": False,
    "censor_nsfw": True,
    "r2": True,
    "shared": True,
    "trusted_workers": True,
    "models": ["stable_diffusion"]
}
pp = pprint.PrettyPrinter(depth=3)
term_regex = re.compile(r'draw for me (.+)', re.IGNORECASE)
modifier_seek_regex = re.compile(r'style:', re.IGNORECASE)
prompt_only_regex = re.compile(r'draw for me (.+)style:', re.IGNORECASE)
style_regex = re.compile(r'style: *([\w+*._ -]+)', re.IGNORECASE)

subreddit = reddit.subreddit("StableHorde")

reply_string = """
Here are {some_images} matching your request\n
{image_markdown_list}\n
Prompt: {unformated_prompt}\n
Style: {requested_style}\n\n
"""
logger.debug(args.redirect)
if args.redirect:
    reply_string += f"*This bot account is obsolete. Please mention `u/{args.redirect}` from now on.*"
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
        logger.info(f"Starting generation from ID '{self.request_id}'. Prompt: {unformated_prompt}. Style: {requested_style}")
        submit_list = []
        for style in styles_array:
            if "###" not in style["prompt"] and negprompt != '' and "###" not in negprompt:
                negprompt = '###' + negprompt
            submit_dict = generic_submit_dict.copy()
            submit_dict["prompt"] = style["prompt"].format(p=unformated_prompt, np=negprompt)
            submit_dict["params"] = imgen_params.copy()
            if style["model"] == "SDXL_beta::stability.ai#6901":
                submit_dict["params"]["n"] = 2
            submit_dict["models"] = [style["model"]]
            submit_dict["params"]["width"] = style.get("width", 512)
            submit_dict["params"]["height"] = style.get("height", 512)
            submit_dict["params"]["sampler_name"] = style.get("sampler", "k_euler_a")
            submit_dict["params"]["steps"] = style.get("steps", 45)
            submit_dict["params"]["cfg_scale"] = style.get("cfg_scale", 7.5)
            submit_dict["params"]["hires_fix"] = style.get("hires_fix", False)
            if "loras" in style:
                submit_dict["params"]["loras"] = style["loras"]
            if "tis" in style:
                submit_dict["params"]["tis"] = style["tis"]
            submit_list.append(submit_dict)
        # logger.debug(submit_list)
        # self.reply_faulted("This is a test reply")
        # return
        gen = HordeMultiGen(submit_list, self.request_id)
        while not gen.all_gens_done():
            time.sleep(1)
        if gen.is_faulted():
            if not gen.is_possible():
                self.reply_faulted("It is not possible to fulfil this request using this style at the moment. Please select a different style and try again.")
            else:
                self.reply_faulted("Something went wrong when trying to fulfil your request. Please try again later")
            return
        if gen.is_censored():
            self.reply_faulted("Unfortunately all images from this request were censored by the automatic safety filter. Please tweak your prompt to avoid nsfw terms and try again.")
            return
        if args.r2:
            self.upload_to_r2(gen, requested_style, unformated_prompt)
        else:
            self.upload_to_subreddit(gen, requested_style, unformated_prompt)
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
            for iter_fn in range(len(job.filenames)):
                image_dict = {
                    "image_path": job.filenames[iter_fn], 
                    "caption": f"Seed {job.seeds[iter_fn]}. Prompt: {job.prompt}"[0:179]
                }
                images_payload.append(image_dict)
        logger.info(f"replying to {self.request_id}: {self.mention_content}")
        logger.debug(f"{requested_style}: {unformated_prompt}")
        logger.debug(f"{images_payload}")
        for iter in range(4):
            try:
                if len(images_payload) > 1:
                    submission = subreddit.submit_gallery(f"{requested_style}: {unformated_prompt}"[0:298], images_payload)
                else:
                    submission = subreddit.submit_image(f"{requested_style}: {unformated_prompt}"[0:298], images_payload[0]["image_path"])
                break
            except (ClientException) as e:
                self.set_faulted()
                logger.error(f"Bad filename. Aborting!")
                return
            except (RedditAPIException, ServerError) as e:
                if iter >= 3:
                    self.set_faulted()
                    logger.error(f"Reddit Exception: {e}. Aborting!")
                    return
        image_markdowns = []
        image_urls = []
        if len(images_payload) > 1:
            submission_images = submission.media_metadata
            iter = 0
            for image_item in submission_images.values():
                iter += 1
                for proc_iter in range(120):
                    if image_item.get("status") == "unprocessed":
                        time.sleep(1)
                        logger.debug(f"Image still processing. Sleeping ({proc_iter}/120)")
                        continue
                if image_item.get("status") == "unprocessed":
                    self.set_faulted()
                    logger.error(f"Images taking unreasonably long to process. Aborting!")
                    return
                largest_image = image_item['s']
                image_url = largest_image['u']
                image_urls.append(image_url)
                image_markdowns.append(
                    f'[[Gen{iter}]]({image_url})'
                )
        else:
            image_markdowns.append(
                f'[[Generation]]({submission.url})'
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
        logger.info("Crossposting to Lemmy")
        community_id = lemmy.discover_community("botart")
        image_body = ''
        for img_url in image_urls:
            image_body += f"![]({img_url})"
        post_result = lemmy.post(
            community_id=community_id,
            name=f"{requested_style}: {unformated_prompt}"[0:298],
            url=image_urls[0],
            body=f"Prompt: {unformated_prompt}\n\nStyle: {requested_style}\n\n{image_body}"
        )
        if not post_result:
            logger.warning("Failed to crosspost to Bot Art")


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
        # Horde models
        {
            "url": "https://aihorde.net/api/v2/status/models",
            "default": []
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
    return jsons

def parse_style(mention_content):
    '''retrieves the styles requested and returns a list of unformated style prompts and the models to use'''
    global style_regex
    jsons = get_styles()
    styles = jsons[0]
    categories = jsons[1]
    horde_models = jsons[2]
    style_array = []
    requested_style = "featured"
    sr = style_regex.search(mention_content)
    if sr:
        requested_style = sr.group(1).lower()
    if requested_style in styles:
        if not get_model_worker_count(styles[requested_style]["model"], horde_models):
            logger.error(f"Style '{requested_style}' appear to have no workers. Aborting.")
            return None, None
        n = 4
        if requested_style == "sdxl":
            n = 1
        for iter in range(n):
            style_array.append(styles[requested_style])
    elif requested_style in categories:
        category_styles = expand_category(categories,requested_style)
        category_styles_running = category_styles.copy()
        n = 4
        if "sdxl" in category_styles:
            n = 1
        for iter in range(n):
            if len(category_styles_running) == 0:
                category_styles_running = category_styles.copy()
            random_style = category_styles_running.pop(random.randrange(len(category_styles_running)))    
            if random_style not in styles:
                logger.error(f"Category has style {random_style} which cannot be found in styles json. Skipping.")
                continue
            if not get_model_worker_count(styles[random_style]["model"], horde_models):
                logger.warning(f"Category style {random_style} has no workers available. Skipping.")
                if not len(category_styles_running) and not len(style_array):
                    logger.error(f"All styles in category {requested_style} appear to have no workers. Aborting.")
                    return None, None
                continue
            style_array.append(styles[random_style])
    return style_array, requested_style


def expand_category(categories, category_name):
    styles = []
    for item in categories[category_name]:
        if item in categories:
            styles += expand_category(categories,item)
        else:
            styles.append(item)
    return styles


def get_model_worker_count(model_name, models_json):
    for model_details in models_json:
        if model_name == model_details["name"]:
            return model_details["count"]
    return 0
