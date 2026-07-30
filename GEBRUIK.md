# Spelling-bot — gebruik

Bedoeld om te delen met het team. Voor de technische kant, zie [README.md](README.md).

De bot leest mee in het kanaal en zet een ❌ bij je bericht als er een spelfout in
staat. Dat kost een strafpunt. Werkt op Nederlands en Engels; de taal wordt
automatisch herkend.

## Voor iedereen

| Commando | Wat het doet |
|---|---|
| `/score` | Jouw puntenstand, of die van iemand anders |
| `/leaderboard` | De ranglijst. Kies week, maand of aller tijden |
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
| `/whitelist add <woorden>` | Woorden goedkeuren, meerdere met komma's |
| `/whitelist remove <woorden>` | Woorden weer laten meetellen |
| `/whitelist list` | Toon welke woorden goedgekeurd zijn |
| `/say` | De bot iets laten zeggen — niemand ziet dat jij het was |
| `/reminder add\|list\|remove` | Eigen herinneringen beheren |
| `/reminder edit <id>` | Tekst, tijd, kanaal of mention aanpassen |
| `/trigger add\|list\|remove` | Eigen trefwoorden beheren |
| `/trigger edit <id>` | Woorden, antwoord of reacties aanpassen |
| `/summary enable\|uit\|list` | Het dagelijkse overzicht regelen |
| `/backup create` | Nu een back-up van de configuratie maken |
| `/backup list` | Bestaande back-ups tonen |
| `/backup download` | Nieuwste back-up als bestand, alleen naar jou |
| `/whitelist export` | Whitelist als tekstbestand |
| `/flagged` | Welke woorden het vaakst fout gerekend worden |
| `/status` | Wat er draait: versie, woordenboek, opslag |
| `/reset` | Herinneringen, triggers, whitelist of punten wissen |
| `/points adjust` | Punten optellen of aftrekken bij iemand |
| `/points reset` | Iemands puntenstand op nul zetten |
| `/punish mode` | Straffen uit, waarschuwen, of echt dempen |
| `/punish threshold` | Na hoeveel fouten per dag de eerste mute volgt |
| `/punish ladder` | Hoe lang elke mute duurt, in minuten |
| `/punish message` | Zelf schrijven wat de bot zegt bij een mute |
| `/punish status` | Alle instellingen en de hele mute-ladder |

Een trigger kan ook straffen: vul `minutes` in bij `/trigger add` en wie dat
woord zegt krijgt een timeout. In het antwoord mag je `{user}`, `{count}` (hoe
vaak diegene deze trigger al raakte) en `{minutes}` gebruiken. Straffen volgen
altijd `/punish mode` — staat die op waarschuwen, dan wordt er niemand gedempt.

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

## Mutes

Maak je te veel fouten op één dag, dan kan de bot je tijdelijk het zwijgen
opleggen. Dat begint bij 1 minuut en loopt op tot maximaal 30. Elke dag begint
de teller opnieuw.

Dit staat standaard **uit**, en gaat eerst in waarschuwingsmodus draaien: de bot
zegt dan wel wie er gemute zóu worden, maar dempt niemand. Beheerders regelen
alles zelf met `/punish` — de drempel, hoe lang elke mute duurt, en zelfs wat de
bot precies zegt. Daar is geen update van de bot voor nodig.

De teksten mogen `{user}`, `{count}` en `{minutes}` bevatten. Bijvoorbeeld:
`Hup {user}, {count} fouten. Even {minutes} stil.`

## Rustig aan met commando's

Meer dan 5 commando's binnen 15 seconden en de bot vraagt je even te wachten.
Dat merk je bij normaal gebruik niet.

## Onterecht een punt gekregen?

Dat kan, en het ligt niet aan jou. De bot rekent samengestelde woorden als
"zonnebrandcrème" nu nog fout, en namen en straattaal kent hij ook niet allemaal.
Meld het even, dan zet een beheerder het woord op de whitelist met
`/whitelist add`.

## Een opmerking over de taal

De commando's zelf zijn Engels — `add`, `list`, `remove`, `edit` — omdat dat in
Discord de standaard is en overal hetzelfde werkt. Alles wat de bot terugzegt,
en alle uitleg die je ziet tijdens het typen, is Nederlands.
