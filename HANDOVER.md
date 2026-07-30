# Overdrachtsdocument — MB spelling-bot

Samenvatting van een werksessie op 29–30 juli 2026. Bedoeld om in een nieuw
gesprek te plakken zodat je niet opnieuw hoeft uit te leggen wat er speelt.

---

## 1. Wat het project is

Discord-bot die elk bericht spellingcontroleert (Nederlands + Engels) en
strafpunten bijhoudt per gebruiker per server. Draait in Docker op de NAS van een
collega. Python 3.12, discord.py, SQLite.

- **Repo:** `Woefies/spelling-points-bot`, default branch `master`
- **Server-ID (guild):** `1518714200342659245`
- **Container op de NAS:** `discord_bot-spellbot-1` (let op: níet `spellbot`)
- **Projectmap op de NAS:** `/volume1/docker/discord-bot`
- **Docker vereist `sudo`** op die machine

---

## 2. Stand van zaken bij het afsluiten

| | Versie |
|---|---|
| Lokale branch `task/trigger-edit` | `0.3.0` |
| `master` | `0.2.17` |
| Draaiende bot op de NAS | **veel ouder** — zie hieronder |

**PR #18 wacht** op `task/trigger-edit` op `task/trigger-edit`: `9aa36d4`
(checker-kolom in het foutenrapport), `791b50a` (`/flagged`, `/status`,
`/backup download`, `/whitelist export`) en `ba27c6b` (`tzdata` vastgezet, WAL
op beide SQLite-verbindingen). Die moet eerst gemerged worden — zie de
volgorde-waarschuwing in §6.

PR's #13, #15, #16 en #17 zijn allemaal gemerged. #14 was van de collega (alleen
een `flagged.csv` toegevoegd, geen code).

### ⚠️ Het belangrijkste openstaande punt

**De draaiende bot loopt ver achter.** Bij aanvang van de sessie bleek het
Docker-image gebouwd te zijn uit de állereerste commit van 14 juli — het bevatte
alleen `admin.py`, `scores.py` en `spelling.py`. Er is sindsdien wel een keer
herbouwd (de reminders werken inmiddels), maar alles vanaf `0.2.10` staat nog
niet live.

De collega moet dus: `git pull` + `sudo docker compose up -d --build`. Die eerste
build duurt langer dan normaal omdat er Hunspell-woordenboeken bij komen.

Controleren of het gelukt is: `/version` in Discord, of
`sudo docker exec discord_bot-spellbot-1 cat /app/VERSION`.

---

## 3. Wat er in deze sessie is gebouwd

### Opstart en diagnose
- Cogs laden nu los van elkaar; één kapotte cog sloopt niet meer de hele bot
- Command-sync kan niet meer fataal zijn, en logt welke commands geaccepteerd zijn
- `DEV_GUILD_ID` in `.env` → commands verschijnen direct in plaats van na een uur
- `bot.run(root_logger=True)` zodat eigen logregels ook zichtbaar zijn

### Versiebeheer
- De pre-commit hook die `VERSION` ophoogt was nooit geactiveerd; `run.sh` zet
  `core.hooksPath` nu bij de eerste run
- `VERSION` stond maanden op `0.1.0`, waardoor `/version` altijd "up to date" zei

### Reminders
- Nieuwe frequentie `weekdays` (ma-vr)
- **Meerdere tijden per herinnering** in één regel: `09:00,11:00,13:00`
- `last_fired` slaat daarom datum **én** tijdslot op (`YYYY-MM-DD HH:MM`)
- `/reminder edit` met autocomplete op het ID
- Tekstvarianten met `|` — de bot kiest er willekeurig één per keer

### Triggers
- Nieuwe cog: trefwoord → antwoord en/of emoji-reactie, per server in de database
- `/trigger add|edit|list|remove`, met `-` om een veld leeg te maken
- Woordgrenzen (`\b`) zodat `kanker` niet afgaat op `kankeren` of `borstkanker`

### Dagoverzicht
- Elke werkdag om 16:30 een ranglijst van de fouten van die dag, mét de woorden
- Leest `issues_log` met een **UTC-venster**, niet `DATE(ts)` — anders belandt
  alles tussen middernacht en 02:00 in de verkeerde dag

### Straffen (mutes)
- Escalerende timeouts: standaard 20 fouten per dag → 1 min, dan 2, 5, 10, 20, 30
- **Staat standaard uit.** Drie modi: uit / waarschuwen / echt dempen
- Drempel, ladder én de meldingsteksten zijn allemaal instelbaar via `/punish`
- Teksten gebruiken `{user}`, `{count}`, `{minutes}`

### Woordenboek (de grootste inhoudelijke verbetering)
- **Hunspell via `spylls`** in plaats van pyspellchecker voor Nederlands
- Dockerfile installeert `hunspell-nl` (Debian bouwt dat uit OpenTaal) en `hunspell-en-us`
- Valt terug op pyspellchecker als de woordenboeken ontbreken
- `services/lexicon.py` uitgebreid met `ABBREVIATIONS` (`enz`, `bijv`, `ipv`…) en
  `TECH_TERMS` — die staan in géén woordenboek

### Back-ups
- Elke nacht 04:00 een JSON-snapshot van reminders, triggers, whitelist,
  instellingen en punten, 14 dagen bewaard
- `/backup create|list|download` en `scripts/export_config.py` / `import_config.py`
- `/reset` maakt altijd eerst een back-up en breekt af als dat mislukt

### Zelfbediening (zodat de collega niet nodig is)
- `/flagged` — het foutenrapport in Discord, te filteren op checker en periode
- `/status` — versie, geladen onderdelen, actief woordenboek, databasegrootte
- `/whitelist export` en `/backup download` sturen bestanden privé

### Overig
- `/say` — bot laten praten zonder dat iemand ziet wie
- Rate limit: 5 commando's per 15 seconden per persoon, over alles heen
- Whitelist accepteert meerdere woorden tegelijk met komma's
- `repeats`-checker respecteert nu de whitelist (deed dat niet)
- Alle beheercommando's antwoorden privé (ephemeral)

---

## 4. Conventies die zijn vastgelegd

- **Engels typen, Nederlands lezen.** Commando's, subcommando's en parameters in
  het Engels (`add`, `list`, `remove`, `edit`, `message`, `time`, `channel`);
  alle omschrijvingen, keuzelijsten en antwoorden in het Nederlands.
- **Discord kapt omschrijvingen af op 100 tekens.** Gaat er één overheen, dan
  weigert Discord de héle sync en verdwijnen álle commands.
- **Geen berichtteksten in de code.** Reminders en triggers staan volledig in de
  database. De presets zijn bewust verwijderd — een tekst aanpassen mag nooit
  een rebuild vereisen.
- **Overzichten tonen namen, alleen persoonlijke berichten taggen.**
- Meer staat in `CLAUDE.md`; die is deze sessie volledig bijgewerkt.

---

## 5. Bekende problemen

**Valse positieven in `dutch_dt`.** De regel `als→dan` gaat af op het correcte
"het is **beter als** je nu gaat". Die checker is grammatica, terwijl de wens is
om alleen op spelling te controleren. Voorstel om die regel te verwijderen staat
open.

**`kanker` in een echt gesprek.** Woordgrenzen houden `kankeren` en
`borstkanker` tegen, maar "mijn opa heeft kanker" triggert wel. Niet op te
lossen zonder context te begrijpen.

**Python 3.10+ vereist.** De code gebruikt `int | None` in geëvalueerde
annotaties. `run.sh` controleert dat niet. Docker gebruikt 3.12, dus daar gaat
het goed; lokaal draaien op een Mac met 3.9 lukt niet.

**`issues_log` groeit oneindig.** Geen opschoning.

---

## 6. Nog te doen door mensen

**Jij, in Discord (na de rebuild):**
- `/trigger preset` bestaat niet meer — triggers met `/trigger add` aanmaken
- Reminders met `/reminder add` (de teksten staan hieronder in §7)
- `/summary enable channel:#kanaal` voor het dagoverzicht
- `/punish mode mode:waarschuwen` — een week laten draaien vóór je 'm scherp zet
- Serverinstellingen → Integraties → per commando de rol MB-bot instellen voor
  `/say`, `/punish`, `/reset`, `/backup`, `/reminder`, `/trigger`, `/summary`

**Volgorde is belangrijk.** De zelfbedieningscommando's (`/status`, `/flagged`,
`/backup download`, `/whitelist export`) zitten in de laatste commits. Merge die
eerst — anders rebuildt je collega naar een versie waarin je niet kunt
controleren of het gelukt is, en moet hij een tweede keer aan de bak.

**De collega, op de NAS (pas ná de merge):**
- `git pull` + `sudo docker compose up -d --build`
- In `.env`: `DEV_GUILD_ID=1518714200342659245` toevoegen, en controleren of er
  een lege regel `PREFIX=` staat (dat brak de `!`-commando's)
- De bot de permissie **Moderate Members** geven en zijn rol boven de anderen
  zetten, anders kan hij niemand dempen
- `scripts/auto_update.sh --check` draaien, en werkt dat, hem als dagelijkse taak
  zetten (DSM: Configuratiescherm → Taakplanner → Maken → **Geplande taak** →
  Door gebruiker gedefinieerd script, als **root**)
- Controleren of `hunspell-nl` goed geïnstalleerd is: `/status` in Discord toont
  welk woordenboek actief is

---

## 7. De PK-teksten (stonden eerst hardcoded, nu handmatig aan te maken)

```
/reminder add
  message: Goede….MORGEN..Team...Minigames!
  time: 09:00
  frequency: elke werkdag (ma-vr)
```
```
/reminder add
  message: Jongens allemaal naar paars!
  time: 09:30
  frequency: elke werkdag (ma-vr)
```
```
/reminder add
  message: Het is de eerste van de maand jongens, checkt iedereen de uurtjes weer? | Denkt iedereen aan de uurtjes? 1ste van de maand!
  time: 09:00, 11:00, 13:00, 15:00, 17:00
  frequency: maandelijks
  day: 1
  mention: @everyone
```
```
/reminder add
  message: 💰 Salaris komt er aan!
  time: 09:00
  frequency: maandelijks
  day: 24
  mention: @everyone
```
```
/trigger add
  words: thuiswerken|thuis werken|thuis aan het werk
  response: Jongens...vergeet niet dat we een kantoormentaliteit hebben bij PK! | Maximaal 1 dag in de week thuiswerken! | Thuiswerken? Bij PK is de koffie beter. ☕ | Ik hoor 'thuiswerken'. Ik hoor ook 'maximaal 1 dag per week'. 👀 | De bureaustoel mist je.
```
```
/trigger add
  words: kanker|kkr|kanher|kenker
  reactions: 👎,❌
```

---

## 8. Waar het gesprek eindigde: de bot laten praten als "Fleur"

Wens: de bot moet klinken als een collega (Fleur), het liefst met een AI-koppeling.

Drie niveaus besproken:

1. **Vaste persona, geen AI** — alle teksten in haar stem herschrijven, met veel
   varianten via `|`. Kost niets, volledig voorspelbaar.
2. **AI-antwoorden op triggers** — een model schrijft de reactie. Bij ~50 reacties
   per dag: ongeveer €1/maand met Haiku, €2,50 met Sonnet 5, €5 met Opus 5. De
   modelkeuze maakt financieel dus nauwelijks uit.
3. **Echt gesprek** — bot taggen en antwoord krijgen. Niet verder uitgewerkt.

**Waar het stond:** voorkeur voor niveau 2 met **Sonnet 5** als middenweg. Nog
niet gebouwd. Aandachtspunten die genoemd zijn:

- Als Fleur een echte collega is: even checken of ze het leuk vindt, zeker in
  combinatie met `/say`
- Er is een Anthropic-account met betaalmethode nodig en een API-sleutel in de
  `.env` op de NAS
- Bouw een harde daglimiet in, en laat de bot terugvallen op de vaste teksten als
  de API onbereikbaar is of de limiet bereikt
- **Het echte werk is beschrijven hóe Fleur praat** — dat is nodig bij alle drie
  de opties, en die beschrijving is meteen de instructie voor het model

Ontbrekend om verder te kunnen: voorbeelden van hoe ze schrijft.

---

## 9. Handige commando's

```bash
# Op de NAS (alles met sudo)
sudo docker exec discord_bot-spellbot-1 cat /app/VERSION
sudo docker exec discord_bot-spellbot-1 ls /app/cogs/
sudo docker compose logs --tail 80 spellbot
sudo docker exec discord_bot-spellbot-1 python scripts/report_flagged.py --kind repeat
sudo docker exec discord_bot-spellbot-1 python scripts/export_config.py

# Whitelist uitlezen zonder nieuwe code
sudo docker exec discord_bot-spellbot-1 python -c "
import sqlite3
for (w,) in sqlite3.connect('data/points.db').execute('SELECT word FROM whitelist ORDER BY word'): print(w)
"
```

GitHub-toegang: het account `yannicknijssen` heeft schrijfrechten,
`yannickpageking` alleen lezen. In deze repo staat een credential-helper lokaal
ingesteld zodat `git push` het juiste account gebruikt.
