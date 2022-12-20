import  argparse

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('-v', '--verbosity', action='count', default=0, help="The default logging level is ERROR or higher. This value increases the amount of logging seen in your screen")
arg_parser.add_argument('-q', '--quiet', action='count', default=0, help="The default logging level is ERROR or higher. This value decreases the amount of logging seen in your screen")
arg_parser.add_argument('--r2', action='store_true', default=False, help="If true, will try to store images in a r2 instead of a subreddit")
arg_parser.add_argument('--redirect', action='store', default=False, help="If specified, will add a message which will redirect to a different username.")
args = arg_parser.parse_args()
