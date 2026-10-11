# Mockorola Capcoder: a virtual Motorola Advisor-style pager

Version 0.4 (git tag `v0.4`). Version 0.1 was released under the old name `vpager`. See [CHANGELOG.md](CHANGELOG.md).

Mockorola Capcoder ("Capcoder" for short; the package and command are `capcoder`) is a virtual pager. The name is a nod to the Motorola Advisor it imitates: a mock Motorola that decodes capcodes. It answers to one POCSAG capcode and shows that capcode's pages on a screen drawn to look like a Motorola Advisor alphanumeric pager from the early 1990s. You can change the capcode at any time.

It is the receive side of this repo. `hmew` sends pages through the HME/JTECH iStation transmitter; Capcoder receives them off the air through an RTL-SDR and shows the ones meant for "its" pager.

```
iStation ──RF 457.575 MHz──▶ RTL-SDR ──▶ rtl_fm | nc ──UDP audio :8888──▶ Capcoder ──▶ browser
                                                                    │
                                                                    └─ multimon-ng (decoder)
```

Python 3, standard library only. The pager face is a single local web page, so it runs the same way on Windows, macOS and Linux.

## Usage

### Requirements

- Python 3.9 or newer (developed and tested on 3.13).
- [multimon-ng](https://github.com/EliasOenal/multimon-ng). Capcoder looks for it on PATH, then (on Windows) in `C:\rtl-sdr`; `--mmng` overrides both. Tested with multimon-ng 1.3.0 and 1.6.0 on Windows.
- Something that sends raw demodulated audio over UDP: 16-bit signed mono at 22050 Hz. `rtl_fm` piped into netcat does this; see "Sending audio from an RTL-SDR machine" below.

### Run

From the repo root:

```
python -m capcoder --capcode 870024
python -m capcoder --base 87 --pager 3          # same capcode, from HME base ID + pager number
python -m capcoder --mmng C:\tools\multimon-ng.exe --capcode 870024
```

This opens `http://127.0.0.1:8073/` in its own browser window, separate from your other tabs, so you can size and place it on its own. The page scales the pager to fit the window. Capcoder uses the app mode of Edge, Chrome or Chromium (`--app=URL`, no tabs or address bar), whichever it finds first; with none of them it falls back to a tab in your default browser. Use `--tab` for a normal tab, or `--browser PATH` to pick the browser.

Point the `rtl_fm` command below at UDP port 8888 on this machine. Click the page once so the browser allows sound.

Run one copy per set of ports. A second copy on the same HTTP port exits with "Is Capcoder already running?". If the UDP port is held by another program, such as mmng-ui, Capcoder shows `port 8888 in use, retrying` and takes the port once it is free.

Once set, the capcode is saved. Later runs remember it, and you can also change it from the pager's own menu.

### Sending audio from an RTL-SDR machine

The RTL-SDR dongle doesn't have to be on the machine running Capcoder. On the machine with the dongle, demodulate with `rtl_fm` and send the audio over the network with netcat:

```
rtl_fm -f 457.5755M -s 22050 -g 30 - | nc -u -w1 <capcoder-host> 8888
```

- `<capcoder-host>` is the IP address or name of the machine running Capcoder. Use `127.0.0.1` if the dongle is on the same machine.
- `-f 457.5755M` is the frequency to tune. HMEW's standard US frequency is 457.5750 MHz; this example is 500 Hz higher. Adjust the value, or use `rtl_fm -p <ppm>`, to suit your dongle.
- `-s 22050` sets the output sample rate to 22050 Hz, which is what multimon-ng expects. `rtl_fm` sends FM-demodulated, 16-bit signed mono audio by default, so no other conversion is needed.
- `-g 30` is the tuner gain. Too much gain overloads the front end, especially near the transmitter, so keep the dongle away from it.
- `nc -u` sends over UDP; `-w1` is netcat's timeout. On Windows, Nmap's `ncat -u` does the same job.
- On the Capcoder machine, allow inbound UDP 8888 through the firewall. Windows usually asks the first time Capcoder listens. Capcoder listens for audio on all network interfaces (`--udp-bind`), while the pager page stays on `127.0.0.1` unless you change `--http-host`.

When audio arrives, the status line under the pager shows `receiving from <sender>` and the log records `audio from <sender>`. If the status line stays `idle`, the audio isn't arriving: check the address, the port and the firewall.

### Options

| Option | Default | Meaning |
|---|---|---|
| `--capcode N` | saved value | POCSAG address to answer to |
| `--base B --pager P` | | HME capcode = base ID followed by pager×8 as 4 digits |
| `--udp-port` | 8888 | UDP port for raw audio |
| `--udp-bind` | `::` | listen address for audio (all addresses, IPv4 and IPv6) |
| `--http-host` | 127.0.0.1 | address for the pager page; `0.0.0.0` lets other machines (e.g. a phone) view it |
| `--http-port` | 8073 | port for the pager page |
| `--mmng` | `multimon-ng` | multimon-ng binary; a bare name is looked up on PATH, then in `C:\rtl-sdr` on Windows |
| `--decode-mode` | `alpha` | multimon-ng `-f` mode: `alpha`, `numeric`, `auto`, or `standard` (no `-f`). Keep `alpha` for the iStation; see "Decoder settings" below |
| `--charset` | `US` | multimon-ng `-C` charset |
| `--mmng-args "..."` | | replace all multimon-ng arguments |
| `--dedupe S` | 10 | ignore an identical page (same capcode, function and text) within S seconds; 0 turns it off |
| `--no-receiver` | | don't listen for audio; injected pages only |
| `--data-dir` | see below | where state and logs are kept |
| `--log-file` | `<data-dir>/capcoder.log` | log file |
| `--tab` | | open in a normal browser tab instead of its own window |
| `--browser PATH` | found | Edge/Chrome/Chromium binary for the pager window |
| `--no-browser` | | don't open a browser |
| `-v` | | show DEBUG messages on the console too |

Default data directory: `%USERPROFILE%\.capcoder` on Windows, `~/Library/Application Support/capcoder` on macOS, `~/.local/state/capcoder` on Linux.

On Windows it is deliberately not under `%LOCALAPPDATA%`. The Microsoft Store build of Python silently redirects writes there into its own package folder (`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.*\LocalCache\Local\...`), so the log would not be where Capcoder says it is.

Upgrading from vpager: on the first run without `--data-dir`, an existing vpager data directory (`%USERPROFILE%\.vpager`, or `vpager` on macOS/Linux) is moved to the new location, so the capcode, messages and settings carry over. Old log files keep their `vpager.log` names. Stop any running vpager first, or the move fails and Capcoder starts with empty state.

### Sending test pages without a radio

`inject` sends a line to a running Capcoder in the same format multimon-ng prints. The line then goes through the same parser, filter and alert path as a real decode:

```
python -m capcoder inject "DON'T RUSH FLIGHT CANCELLED-NEW FLIGHT #687 AT 5:25 PM"
python -m capcoder inject --numeric --function 0 "555-1212"
python -m capcoder inject --capcode 874440 "someone else's page"      # ignored by the filter
python -m capcoder inject --line "POCSAG1200: Address:  870024  Function: 1  Alpha:   HI"
```

`inject` is accepted only from the same machine.

To send a real page over the air, use the sender in this repo (`hmew`) and point it at a lab test capcode. Never send test pages to customer pagers.

## Layout

```
 ┌───────────────────────────────────────────────────────────┐
 │  ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀  lamp ▪  │
 │  ┌─────────────────────────────────────────────────────┐  │
 │  │  01: DON'T RUSH                                     │  │
 │  │  FLIGHT CANCELLED-NEW         4 × 20 dot-matrix LCD  │  ▐ On/Reset
 │  │  FLIGHT #687 AT 5:25                                │  ▐
 │  │  PM                                                 │  │
 │  └─────────────────────────────────────────────────────┘  │
 │  [ ▬ Read ]  [ ▬ Function ]       ( ◀ )  [ ▲ ]  ( ▶ )     │
 │  ┌─────────────────────────┐              [ ▼ ]           │
 │  │ (Ø) MOCKOROLA  CAPCODER  │                               │
 │  └─────────────────────────┘                               │
 └───────────────────────────────────────────────────────────┘
   capcode · UDP status · multimon-ng status · last decode · log path
```

- **Case:** drawn with CSS, with no images. The badge reads "MOCKOROLA" with "CAPCODER" underneath, and the round logo holds a slashed zero like the LCD's. It is a parody: no Motorola name or batwing logo.
- **LCD:** a canvas with a 5×7 dot-matrix font and a slashed zero, as on the Advisor. Unlit dots show faintly and lit dots cast a slight shadow, like a reflective LCD. The backlight turns the screen glowing green.
- **Status line under the pager:** shows the capcode (with HME base and pager number), UDP state and sender, multimon-ng state, the last decode for any capcode with what happened to it, and the log file path.

## Functionality

The behavior follows the Motorola Advisor user manual (`refdocs/advisor_inst.pdf`).

| Control | Mouse / touch | Keyboard |
|---|---|---|
| Read | yellow key | Enter or Space |
| Function | red key (hold 1 s = backlight) | F (hold = backlight) |
| Arrows | four-way pad | arrow keys |
| On/Reset | red button on the right edge (hold = power off prompt) | O (hold) |

The manual doesn't say which colored key is Read and which is Function. Yellow = Read and red = Function is a guess.

**Receiving**
- A new page starts the alert: beep or vibrate (the case shakes), the lamp flashes, and the envelope symbol shows for 12 seconds.
- Any button cancels the alert. Read also opens the new message.
- While a message is unread, the ON symbol flashes and the pager beeps once every 2 minutes.

**Reading**
- Read opens the memory-location screen. Locations 1-10 are on the top line and 11-19 on the second. Location 20, at the right end of the second line, is the Personal Message File.
- An arrow marks each message; it flashes while unread and becomes a lock symbol when the message is locked.
- ◀ ▶ choose a location and Read opens it.
- A message starts with its location number (`01:`) and ends with the time and date it arrived.
- Messages auto-scroll a screen every 4 seconds; a one-screen message stays up for 8 seconds.
- Pressing Read again switches to manual: each Read moves one screen, and ▲ ▼ move one line.

**Function menu**
Press Function, choose a symbol with ◀ ▶ (the selected one flashes), and press Function again to run it. From the idle screen the menu has:
- **Speaker:** switches between audible and vibrate.
- **Alerts:** ▲ ▼ choose audible or silent, ◀ ▶ choose the pattern, Function saves. Audible: Escalert, Loud Long, Loud Short, Soft Long, Soft Short, Chirp, None. Silent: Chirp + Vibrate, Vibrate only, None.
- **Clock:** shows the time; the app follows the PC clock.
- **Alarm:** set a time and turn it on or off.
- **Capcode:** sets which capcode this pager answers to. The real pager doesn't have this.

From a message, the menu has:
- **Lock/Unlock:** up to 10 locked messages, which aren't overwritten when memory is full.
- **Delete:** shows `DELETE?`; Function confirms.
- **Personal Message File:** moves the message to location 20 (up to 10). It can't be moved back out; to remove it, delete it.

**Power**
Hold On/Reset to show `PUSH FOR OFF`, then press Function to turn the pager off. While off, the screen is blank and pages are logged but not stored. Press On/Reset to power on, with the 4-second power-up alert. A short press while on returns to the idle screen.

**Memory**
- 19 regular locations. When they're full, the oldest unlocked message is dropped.
- Messages and settings are saved in `state.json` in the data directory, so they survive restarts.

## Design choices

- **The browser draws the face; Python does the receiving.** Standard desktop GUI toolkits tend to look dated, and the pager is mostly timing: flashing symbols, 4 s scroll, 12 s alerts, 1 s holds. That runs smoothly in the browser. Python handles the parts that need the machine: UDP, the multimon-ng subprocess, filtering, storage and logging. Because it's a web page, it also works on any OS and can be viewed from another device with `--http-host 0.0.0.0`.
- **Not Streamlit.** Streamlit reruns the whole script on the server for every click and has no clean way to push an incoming page to the browser. That makes timed button behavior laggy, and the custom drawing would have to live in an HTML component anyway.
- **Standard library only.** `http.server` serves the page and server-sent events, `asyncio` runs UDP and the subprocess, and `logging` writes the log file. The same rule applies to the rest of the repo.
- **Same input as mmng-ui.** Capcoder listens on UDP 8888 for raw demodulated audio, the same input mmng-ui takes. The UDP-to-multimon-ng code is adapted from [mmng-ui](https://github.com/lingfish/mmng-ui), which is GPL-3.0 like this repo; attribution and a list of changes are in the header of `receiver.py`. Only one program can listen on a given port, so to run both, give Capcoder or mmng-ui a different port and send the audio to each.
- **Decoder settings.** Capcoder runs multimon-ng with mmng-ui's POCSAG arguments, minus `-u`:
  `-a POCSAG512 -a POCSAG1200 -a POCSAG2400 -f alpha -t raw -q --timestamp -p -C US -`
  - **`-f alpha` (force text decoding) is needed for the iStation.** POCSAG can encode a message body as numeric digits (4 bits each) or as 7-bit ASCII text, and the function bits conventionally say which (0 = numeric, 3 = alpha). The HMEW protocol document only describes what the PC sends; it doesn't say how the transmitter encodes pages on air, and you can't choose it. On 2026-10-10 a page to pager 1 (capcode 870008) arrived with `Function: 0`, which by convention means numeric, yet decoded cleanly as the text `5551212` under `-f alpha`. The unit therefore sent the body as text despite the numeric function bits. In `standard` mode multimon-ng trusts the function bits and would very likely garble such pages. If a page for your capcode ever shows up garbled, the unit may have sent real numeric encoding; try `--decode-mode auto` then.
  - **`-u` (prune unlikely decodes) is left out.** It was tried with multimon-ng 1.3.0 and 1.6.0 and made the output messier, with stray address-only decodes for random capcodes. Those decodes are ignored by the capcode filter anyway; they only clutter the log. If noise is still a problem, dropping `-p` (show partial messages) is the next thing to try, through `--mmng-args`.
- **The server owns the state; the browser owns the behavior.** Message memory and settings live on the server, so a page reload or a second browser shows the same pager. Screens, timers, sound and the LCD live in `pager.js`.
- **Filter on the server, log everything.** Every decode for every capcode is logged with its verdict, so the log answers "did the radio hear it?" separately from "did the pager accept it?".
- **Duplicate suppression.** An identical page within 10 s is shown only once. It isn't confirmed whether the iStation or the decoder ever repeats pages; this is a precaution.
- **Sounds are generated,** using square-wave beeps from Web Audio, so there are no audio files. Alert lengths come from the manual; the beep pattern within them is a guess.

## Structure

```
capcoder/
  __main__.py   command line: run (default) and inject
  core.py       Core: handles each decode line (log, parse, capcode filter, dedupe, store),
                Hub: pushes server-sent events to browsers
  decode.py     multimon-ng POCSAG line -> Page(capcode, function, kind, text)
  store.py      message memory and settings, Advisor limits, saved as JSON
  receiver.py   UDP audio -> multimon-ng stdin; stdout lines -> Core (adapted from mmng-ui)
  server.py     local HTTP server: static files, /api/state, /api/events, /api/action,
                /api/log, /api/inject
  logsetup.py   rotating log file + console, default data directory per OS
  launch.py     opens the page in its own window (Edge/Chrome/Chromium app mode) or a tab
  web/
    index.html  pager markup
    pager.css   the case, keys, lamp, vibrate animation
    font.js     5x7 glyphs and icons (speaker, lock, envelope, ...)
    pager.js    LCD renderer, screens and button behavior, alerts, sound, connection
tests/test_capcoder.py   unit tests (repo root)
```

### HTTP API (local)

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | full state: capcode, power, settings, messages, receiver status, last decode, log path |
| `GET /api/events` | server-sent events: `state`, `page`, `status`, `decode` |
| `POST /api/action` | `{"action": "read" \| "delete" \| "lock" \| "unlock" \| "file" \| "settings" \| "capcode" \| "power", "id": ..., "value": ...}` |
| `POST /api/log` | `{"level", "msg"}` from the browser, written to the log file |
| `POST /api/inject` | `{"line": "<multimon-ng line>"}`, loopback only |

## Logging

Everything goes to `<data-dir>/capcoder.log` at DEBUG level. The file rotates at 5 MB and keeps 5 old files. The console shows INFO, or DEBUG with `-v`. The log path is printed at startup and shown under the pager. The log includes:

- startup settings, the capcode, and the paths in use
- every raw multimon-ng output line (`capcoder.decode`) and its stderr (`capcoder.multimon`)
- each parsed page with its verdict: `stored`, `ignored: other capcode`, `ignored: duplicate`, `ignored: pager is off`, `ignored: no capcode set`
- the UDP audio sender, audio started/stopped, packet stats every minute, and dropped audio
- multimon-ng start, exit code and restarts
- UI actions (lock, delete, settings, ...) and refusals such as `LOCK FULL`
- from the browser (`capcoder.ui`): key presses, screen changes, alerts, JavaScript errors
- uncaught exceptions in any thread, with traceback

## Testing

**Unit tests** cover the decoder, memory limits, the capcode filter, duplicate suppression and events:

```
python -m unittest tests.test_capcoder -v
```

**Manual, without a radio:**

```
python -m capcoder --capcode 870024 --no-receiver
python -m capcoder inject "TEST 1"
```

**Scripted key presses:** add `?keys=` to the page URL to press buttons after load. This is useful for checking a screen or taking screenshots:

```
http://127.0.0.1:8073/?keys=read,read            # open the newest message
http://127.0.0.1:8073/?keys=read,left,read       # open the one before it
http://127.0.0.1:8073/?keys=func,right&step=0    # global menu, all keys at once
```

`step` is the delay between presses in ms (default 600; 0 = all at once before the first paint). Hold actions use `func-hold` or `power-hold`. Headless screenshots work with Edge or Chrome:

```
msedge --headless=new --window-size=1000,560 --screenshot=shot.png "http://127.0.0.1:8073/?step=0&keys=read,read"
```

**End to end:** run Capcoder with `rtl_fm` sending audio, then page the test capcode with `hmew`. Check that the status line shows `receiving` and that the decode appears in the log.

## Open questions

- Does the iStation ever send a page body with true numeric encoding? So far it has sent text even with `Function: 0` (see "Decoder settings"). If a garbled page for your capcode appears, compare `--decode-mode auto`.
- What sets the function bits: keypad pages have decoded as Function 0, and earlier HTTP pages with `beep=1` as Function 1. It may be the beep setting or how the page was sent.
- Which Advisor key is Read and which is Function (see Functionality).
- Does the iStation repeat pages (affects `--dedupe`)?
- A borderless, pager-shaped desktop window (pywebview) is planned but not built. For now the page opens in its own app-mode browser window.
