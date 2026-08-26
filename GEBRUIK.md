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
| `/backup restore` | Een gedownloade back-up terugzetten |
| `/update enable\|disable` | Melden zodra er een nieuwe versie klaarstaat |
| `/update now` | Een update aanvragen. De bot meldt daarna zelf of het lukte |
| `/settings show` | Hoe streng de spellingcheck nu staat |
| `/settings points\|reply\|minwords\|capitals` | Die strengheid bijstellen |
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

## AI-antwoorden op triggers

De bot kan zijn antwoord op een trigger zelf laten schrijven, in plaats van altijd
dezelfde vaste tekst. Dit staat **standaard uit** en werkt alleen als er een
Anthropic API-sleutel op de host staat.

| Commando | Wat het doet |
|---|---|
| `/ai replies enabled:True` | Laat de AI trigger-antwoorden schrijven |
| `/ai evasion enabled:True` | Laat de AI omzeilingen herkennen |
| `/ai off` | Zet alle AI-functies in een keer uit |
| `/ai verdicts` | Toon welke woorden als omzeiling zijn beoordeeld |
| `/ai forget word:...` | Draai een oordeel terug. Een `-` wist alles |
| `/ai persona tekst:...` | Beschrijf hoe de bot moet klinken. Een `-` zet de standaard terug |
| `/ai budget aantal:50` | Maximaal aantal AI-antwoorden per dag. `0` = uit |
| `/ai context send_message:True` | Laat het model ook het bericht zelf zien |
| `/ai test woord:thuiswerken` | Genereer nu één voorbeeldantwoord om je persona te testen |
| `/ai status` | Staat het aan, hoeveel is er vandaag gebruikt, en welke persona geldt |

**Voorbeeld.** Persona instellen en testen:

```
/ai persona tekst: Je bent een droge collega. Kort, nuchter, nooit meer dan twee zinnen.
/ai test woord: thuiswerken
🤖 Weer thuis? De koffie hier is anders ook niet slechter geworden.
/ai replies enabled: True
✅ AI-antwoorden aan, maximaal 50 per dag.
```

**Uitzetten kan altijd,** met `/ai replies enabled:False` of `/ai off`. De vaste tekst van elke trigger blijft
gewoon staan en wordt dan meteen weer gebruikt — je raakt niets kwijt. Datzelfde
gebeurt vanzelf als het dagbudget op is, als het te lang duurt, of als er iets
misgaat. De bot valt dan stil terug op de tekst die je zelf hebt ingevuld; je merkt
er in het kanaal niets van.

**Wat gaat er naar buiten?** Standaard alleen het trefwoord waar de trigger op let
en hoeveel keer die persoon het gezegd heeft. De berichten van collega's blijven op
de server. Zet je `/ai context send_message:True` aan, dan wordt het bericht zelf
meegestuurd naar Anthropic — betere antwoorden, maar berichten verlaten dan wel de
server. Die keuze is bewust een aparte handeling.

## Trigger-omzeiling

Een trigger op `brent` reageert niet op `br3nt`, `brenttt`, `b r e n t` of `brentify` —
dat zijn andere woorden. Daar zijn twee losse schakelaars voor.

**Gratis, zonder AI:** `/trigger obfuscation enabled:True`

Vangt alles wat na omrekenen letterlijk hetzelfde woord is:

| Geschreven | Gevangen |
|---|---|
| `br3nt`, `br€nt` | ja — cijfers en tekens voor letters |
| `brenttt`, `brenttttt` | ja — herhaalde letters |
| `b r e n t`, `b-r-e-n-t`, `b.r.e.n.t` | ja — letters uit elkaar |
| `brentify`, `brentje` | nee — dat zijn andere woorden |
| `brand`, `bren` | nee |

Dit is een vaste rekenregel, geen oordeel. Er gaat niets naar buiten en het kost niets.

**Met AI:** `/ai evasion enabled:True`

Woorden die op een trigger *lijken* maar er niet gelijk aan zijn — `brentify`,
`brentje`, `superbrent` — worden aan de AI voorgelegd met één vraag: is dit een
omzeiling, ja of nee. Bij twijfel altijd nee.

Wat er nooit wordt voorgelegd: woorden die in het woordenboek staan, woorden die jij
gewhitelist hebt, en woorden waar al eerder een oordeel over gegeven is. Per bericht
worden er maximaal 3 woorden voorgelegd.

**Een oordeel telt als een gewone treffer.** Dus reageert de bot, telt de teller, en
loopt een eventuele straf via `/punish` — precies zoals bij een gewone treffer. Staat
`/punish mode` op waarschuwen, dan wordt er niemand gedempt.

```
brentify weer hoor
Bot: @jij dat is 3 keer nu.
     (`brentify` gelezen als omzeiling van `brent`)
```

**Oordelen corrigeren.** De AI heeft het niet altijd bij het rechte eind. Elk oordeel
wordt onthouden, dus je kunt het terugkijken en terugdraaien:

| Commando | Wat het doet |
|---|---|
| `/ai verdicts` | Alle beoordeelde woorden, met 🚫 of ✅ |
| `/ai forget word:brentje` | Vergeet dit oordeel, opnieuw beoordelen |
| `/ai forget word:-` | Vergeet alles |
| `/whitelist add woorden:brentje` | Voorgoed met rust laten, ook door de AI |

**Zet `/punish mode` eerst op waarschuwen** als je dit aanzet. Dan zie je een paar dagen
wie er gedempt *zou* worden, zonder dat er iemand stilvalt.

## Testkanaal

Wil je een nieuwe trigger, een andere persona of een strengere drempel uitproberen
zonder dat je collega's er last van hebben? Wijs een testkanaal aan.

| Commando | Wat het doet |
|---|---|
| `/test channel channel:#bot-test` | Maakt dit kanaal het testkanaal |
| `/test isolate enabled:True` | De bot reageert tijdelijk **alleen** nog daar |
| `/test off` | Testmodus helemaal uit |
| `/test status` | Toont welk kanaal het is en of isolate aanstaat |

In het testkanaal doet de bot **precies wat hij anders ook zou doen** — kruisje,
antwoord, triggers, emoji, AI — maar er wordt niets van opgeslagen. Geen punten,
geen trigger-teller, geen mute. Onder elk antwoord staat een regel die dat zegt.

**Voorbeeld.**

```
/test channel channel: #bot-test
🧪 Testkanaal staat op #bot-test.

(in #bot-test) dit is een berichtt met een fout
🔤 1 fout(en) [nl]: `berichtt` · zou +1 punt(en) zijn
🧪 Testkanaal — niets hiervan is opgeslagen.
```

Draagt de trigger die je test een straf, dan zegt de bot erbij hoe lang hij zou
dempen — zonder iemand te dempen.

**Isolate** is er voor als je even rustig wilt sleutelen: de bot laat alle andere
kanalen met rust tot je hem uitzet. Let op dat je dat ook doet — zolang isolate
aanstaat worden er nergens fouten geteld. `/status` zegt het er nadrukkelijk bij,
en `/test isolate enabled:False` zet het terug.

Reminders blijven gewoon versturen, ook tijdens isolate. Die staan er los van.

## Rustig aan met commando's

Meer dan 5 commando's binnen 15 seconden en de bot vraagt je even te wachten.
Dat merk je bij normaal gebruik niet.

## Gaat er iets mis met een commando?

De bot zegt zelf wat er aan de hand is — of hij het commando niet kent, of je
de rechten mist, of er iets stuk is. Krijg je alsnog Discord's eigen melding
"de applicatie heeft niet gereageerd", dan draait de bot niet of is hij
onbereikbaar.

## Onterecht een punt gekregen?

Dat kan, en het ligt niet aan jou. De bot rekent samengestelde woorden als
"zonnebrandcrème" nu nog fout, en namen en straattaal kent hij ook niet allemaal.
Meld het even, dan zet een beheerder het woord op de whitelist met
`/whitelist add`.

## Een opmerking over de taal

De commando's zelf zijn Engels — `add`, `list`, `remove`, `edit` — omdat dat in
Discord de standaard is en overal hetzelfde werkt. Alles wat de bot terugzegt,
en alle uitleg die je ziet tijdens het typen, is Nederlands.
