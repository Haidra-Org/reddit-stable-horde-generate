import  argparse

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('-v', '--verbosity', action='count', default=0, help="The default logging level is ERROR or higher. This value increases the amount of logging seen in your screen")
arg_parser.add_argument('-q', '--quiet', action='count', default=0, help="The default logging level is ERROR or higher. This value decreases the amount of logging seen in your screen")
arg_parser.add_argument('--subreddit', action='store_true', default=False, help="If true, will try to store images in a subreddit instead of r2")
args = arg_parser.parse_args()
