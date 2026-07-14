from core.config import load_settings
from core.bot import SpellBot


def main():
    settings = load_settings()
    bot = SpellBot(settings)
    bot.run(settings.token)


if __name__ == "__main__":
    main()
