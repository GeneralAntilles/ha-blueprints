# Controller Guide

A generated "what does this button do?" reference for every remote and
smart switch in the house: a small website plus printable sheets.

The button bindings come straight from Home Assistant, so the guide can't
drift from what the buttons really do. The wording, physical locations,
and anything HA can't know (buttons programmed in the Hue app) live in
`data/overlay.yaml`.

## Use it

```sh
python3 fetch.py          # read-only: HA automations, blueprints, registries, LED settings, Hue bridge
python3 build.py --pdf    # writes dist/, dist/pdf/*.pdf and dist/build-report.txt
python3 deploy.py         # publishes into Home Assistant (config share must be mounted)
```

`deploy.py` copies `dist/` to `www/controller-guide/` on the HA config share
and keeps a **Controllers** entry in the HA sidebar (a Webpage dashboard
showing `/local/controller-guide/index.html`). Re-running it is safe. Pages
under `/local/` need no login, so the QR codes on printed cards open straight
on a phone on the home network. Home Assistant caches `/local/` for 31 days;
every link carries the build version, and each page checks `version.txt` and
reloads itself when a newer build is deployed, so nobody sees a stale page.
Run `build.py --pdf` before deploying, or the PDFs won't be published.

`fetch.py` reads `HA_URL`, `HA_TOKEN` and `HA_IP` from the repo's `.env`
and needs no SMB mount. It writes `data/snapshot.json`, which is committed
so git diffs show when a button's binding changes.

`build.py --strict` exits non-zero while anything in the report is
unresolved: unlabeled actions, broken bindings, Hue switches with no entry.

### Hue switches

Hue dimmers and taps are programmed in the Hue app, not in Home Assistant.
`fetch.py` reads their setup straight from the Hue bridge (read-only GETs of
the CLIP v2 `behavior_instance`, `button`, `room`/`zone` and scene resources)
and the cards are generated from that. Credentials, first match wins:

1. `HUE_BRIDGE_HOST` and `HUE_APP_KEY` in the repo `.env`
2. Home Assistant's own Hue integration, when the config share is mounted

With neither, `fetch.py` keeps the previous Hue data and the build report
says it may be stale. A `manual:` entry in the overlay overrides the bridge
for that switch. Hue Tap buttons are numbered by the dots printed on them
(the big face is 1, then left 2, bottom 3, right 4).

## What's in dist/

| Page | For |
|---|---|
| `index.html` | Every controller by floor and room, with search |
| `controllers/<slug>.html` | One controller: every button and gesture, notes, technical details |
| `cheatsheet.html` | The whole house on a few landscape Letter pages |
| `print/letter.html` | One controller per Letter page, with the drawing and every gesture |
| `print/card.html` | 6 x 4 in landscape laminated cards: drawing, everyday gestures and holds, what the lights mean |
| `print/mini.html` | 3.5 x 2 in labels (business-card size): everyday gesture per button only |

| `print/card-2up.html` | Two 6 x 4 cards per Letter page with crop marks |
| `print/mini-10up.html` | Ten labels per Letter page in the standard business-card layout (Avery 8371 / 5371 and similar); optional cut lines |
| `pdf/*.pdf` | All of the above as ready-to-print PDFs (`build.py --pdf`) |

Add `?only=<slug>` (or `?only=slug1,slug2`) to any print page to print just
those controllers; the multi-up sheets repack so there are no gaps. Print at 100%
scale with margins set to "Default". Type size on cards and labels steps
down automatically for busy controllers such as the cube.

## Keeping printed cards current

Every card and sheet carries a revision code (bottom left), and the website
shows the same code under Technical details. After printing, record it:

```sh
python3 build.py --mark-printed all                  # or list slugs
```

That writes `data/printed.json`. From then on `build-report.txt` has a
**REPRINT** list of cards whose printed copy no longer matches what the
buttons do, and each controller's page says "Out of date: reprint". Then
print just those, for example
`print/card-2up.html?only=kitchen-remote,office-cube`.

## Editing the wording

Run `build.py` and read `dist/build-report.txt`. Every unlabeled action is
listed with its signature, for example `script.common_light_toggle`. Add
it under `labels:` in `data/overlay.yaml` with a `short` phrase for cards
(about four words, written for a guest) and a `long` phrase for the
website and Letter sheet.

Per-controller overrides such as title, location, notes, button names, or
hiding a gesture go under `controllers:`, keyed by the slug the report
shows. Identical twin remotes are merged with `groups:`, and the build
warns if the twins ever stop matching.

Buttons programmed in the Hue app go under `manual:` (see the example in
the overlay).

## When a blueprint changes

`guide/layouts.py` pins a hash of each controller blueprint's inputs. If
a blueprint gains, loses or re-defaults an input, the build warns until
you review the layout and update `PINNED_SCHEMAS`.

The wall-dimmer paddle grammar (tap up, double tap, lamps only...) is
written out in `guide/extract.py`. **If you change what the paddle does
in `wall-dimmer-natural-light-controller.yaml`, update that text too.**
The hash only notices input changes, not changed behavior.

## What the lights mean

`fetch.py` also reads each switch's LED settings: Z-Wave configuration
parameters (read-only `zwave_js/get_config_parameters`) and the Inovelli
light-bar entities. `guide/leds.py` turns them into plain sentences with
colour swatches, for example the ZEN37's per-button blink colours. Change an
LED setting in Home Assistant, re-run fetch and build, and the cards follow.

When you set up LED notifications (an Inovelli bar effect, a HomeSeer status
light), describe them in the overlay and they appear first in that
controller's lights section:

```yaml
controllers:
  office-fan:
    led_notifications:
      - {color: red, effect: blinking, means: "Garage door is open"}
      - {color: "#ffb000", effect: pulsing, means: "Dryer finished"}
```

`color` takes a name (red, green, blue, yellow, purple, orange, cyan, pink,
white) or a CSS colour.

## Colour

Colour carries information only: the LED swatches show the colours the
devices really light up, amber flags a binding that isn't working, and each
floor has an accent (teal for the main floor, indigo for the 2nd floor) on
card headers and index headings, so a stack of printed cards sorts by floor.
Everything still reads in black and white, because gestures always pair a
glyph with a word.

## Drawings

`templates/devices/<name>.svg.j2` holds one line drawing per model, each
traced from a manufacturer or retailer product photo (the source is noted
in the comment at the top of each file). The
model-to-drawing map is `DRAWINGS` in `guide/layouts.py`, plus
`HUE_MODEL_DRAWING` in `guide/hue.py`. A badge is drawn only where the
controller has that control, so unused buttons stay plain outlines.


