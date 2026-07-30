"""Words that should never count as a spelling mistake, on any server.

Three groups, all merged into the whitelist on every check. Anything specific to
one company or one Discord (client names, colleagues, in-jokes) belongs in the
per-guild whitelist via /whitelist add instead — this file is for things that are
simply Dutch or simply the internet.
"""

CHAT_SLANG = frozenset({
    # English
    "idk", "tbh", "imo", "imho", "btw", "ngl", "fr", "ez", "gg", "pog", "based",
    "nvm", "rn", "wyd", "wdym", "hmu", "ftw", "istg", "afaik", "lmao", "lmfao",
    "lmfaoo", "lol",
    "rofl", "smh", "irl", "tldr", "dm", "gtg", "brb", "bruh", "meh", "ugh",
    "pff", "oof", "yikes", "yep", "nope", "yup", "nah", "huh", "eh", "oi", "xd",
    "lowkey", "highkey", "sus", "sussy", "goated", "bussin", "rizz", "yap",
    # Dutch
    "idd", "gwn", "wrm", "ff", "effe", "mss", "egt", "ofzo", "ofz", "tog", "kzn",
    "ofc", "iig", "sws", "hoezo", "joh", "nou", "mkay", "oke", "aub", "svp",
    "wss", "vgm", "eig", "eigl", "zometeen", "gefixt", "fixen", "flexen",
    "appen", "adden", "chillen", "chille", "bro", "ey", "jonko",
    # Dutch contractions (apostrophe forms preserved by tokenizer)
    "m'n", "z'n", "d'r", "'t",
})

# Written abbreviations. Hunspell does not carry these — they are punctuation
# conventions rather than words — and they are extremely common in chat, which
# made "enz" and "bijv" a steady source of false mistakes.
ABBREVIATIONS = frozenset({
    # Dutch
    "enz", "bijv", "bv", "etc", "ivm", "ipv", "evt", "incl", "excl", "excl",
    "mbt", "mbv", "tav", "nav", "dwz", "oa", "ed", "resp", "zgn", "tbv", "ihkv",
    "mn", "ca", "nr", "jl", "blz", "pag", "tel", "max", "min", "div", "excl",
    "mvg", "vr", "gr", "dhr", "mevr", "nvt", "wo", "incl", "excl", "afk",
    # English
    "fyi", "asap", "aka", "eg", "ie", "vs", "faq", "diy", "tba", "tbd", "wip",
    "eod", "ooo", "pto", "eta", "rsvp", "approx", "misc", "temp", "info",
})

# Everyday technical vocabulary. Generic tools and concepts only — anything
# company-specific (a client, a supplier, an internal system) goes in the
# per-guild whitelist, not here.
TECH_TERMS = frozenset({
    "app", "apps", "api", "url", "urls", "css", "html", "php", "js", "json",
    "sql", "cms", "seo", "ssl", "dns", "vps", "ftp", "sftp", "cli", "ide",
    "repo", "repos", "git", "npm", "cdn", "dns", "http", "https", "ssh", "ip",
    "ui", "ux", "db", "backend", "frontend", "fullstack", "devops", "dev",
    "devs", "deploy", "deployen", "deployment", "commit", "commits", "committen",
    "merge", "mergen", "branch", "branches", "bug", "bugs", "bugfix", "debug",
    "debuggen", "config", "configs", "server", "servers", "hosting", "domein",
    "plugin", "plugins", "theme", "themes", "template", "templates", "cache",
    "browser", "cookie", "cookies", "login", "logs", "usb", "wifi", "zzp",
    "webshop", "webhook", "webhooks", "framework", "cronjob", "endpoint",
    "responsive", "screenshot", "screenshots", "update", "updaten", "upgraden",
    "downloaden", "uploaden", "inloggen", "uitloggen", "resetten", "rebuild",
    "rebuilden", "init", "npm", "docker", "container", "containers",
})

# What the spelling checker actually consults.
SKIP_WORDS = CHAT_SLANG | ABBREVIATIONS | TECH_TERMS
