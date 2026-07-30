# Spelling-bot — gebruik

Bedoeld om te delen met het team. Voor de technische kant, zie [README.md](README.md).

De bot leest mee in het kanaal en zet een ❌ bij je bericht als er een spelfout in
staat. Dat kost een strafpunt. Werkt op Nederlands en Engels; de taal wordt
automatisch herkend.

## Voor iedereen

| Commando | Wat het doet |
|---|---|
| `/score` | Jouw puntenstand, of die van iemand anders |
| `/leaderboard` | De ranglijst aller tijden |
| `/version` | Welke versie er draait |

## Wat de bot uit zichzelf doet

- Elke werkdag om **09:00** en **09:30** een berichtje
- **1e van de maand** — herinnering om je uren in te vullen (meerdere keren die dag)
- **24e** — salaris komt eraan
- Zeg **"thuiswerken"** en je hoort er wat van
- **16:30** op werkdagen — dagoverzicht met de fouten van die dag

## Voor beheerders

Vereist *Manage Server*. Zonder die rechten zijn deze commando's niet eens zichtbaar.

| Commando | Wat het doet |
|---|---|
| `/whitelist add <woord>` | Woord voortaan goedkeuren in deze server |
| `/whitelist remove <woord>` | Woord weer meetellen |
| `/whitelist list` | Toon welke woorden goedgekeurd zijn |
| `/say` | De bot iets laten zeggen — niemand ziet dat jij het was |
| `/reminder add\|list\|remove` | Eigen herinneringen beheren |
| `/reminder edit <id>` | Tekst, tijd, kanaal of mention aanpassen |
| `/trigger add\|list\|remove` | Eigen trefwoorden beheren |
| `/trigger edit <id>` | Woorden, antwoord of reacties aanpassen |
| `/dagoverzicht aan\|uit\|nu` | Het dagelijkse overzicht regelen |
| `/backup nu` | Nu een back-up van de configuratie maken |
| `/backup lijst` | Bestaande back-ups tonen |
| `/reset` | Herinneringen, triggers, whitelist of punten wissen |

Bij `/reminder add` en `/trigger add` kun je meerdere teksten scheiden met een
`|`. De bot kiest er elke keer willekeurig één, zodat een dagelijks bericht niet
gaat vervelen.

Bij `/reminder edit`, `/reminder remove`, `/trigger edit` en `/trigger remove` hoef je geen
nummer te onthouden — je kiest uit een lijst zodra je begint te typen.

`/reset` maakt altijd eerst een back-up voordat er iets weggegooid wordt, en
vraagt om een expliciete bevestiging.

Moet een herinnering meerdere keren per dag afgaan, vul dan meerdere tijden in
gescheiden door komma's: `09:00, 11:00, 13:00, 15:00, 17:00`. Dat is één
herinnering met één ID, dus je past de tekst ook maar op één plek aan.

## Onterecht een punt gekregen?

Dat kan, en het ligt niet aan jou. De bot rekent samengestelde woorden als
"zonnebrandcrème" nu nog fout, en namen en straattaal kent hij ook niet allemaal.
Meld het even, dan zet een beheerder het woord op de whitelist met
`/whitelist add`.
