from core.config import load_settings
from core.bot import SpellBot


def main():
    settings = load_settings()
    bot = SpellBot(settings)
    # root_logger=True so our own log lines (cog loading, command sync) reach the
    # console too, not just discord.py's — otherwise startup failures stay silent.
    bot.run(settings.token, root_logger=True)


if __name__ == "__main__":
    main()
