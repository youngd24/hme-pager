# TODO

## Troubleshooting: spurious decodes in the Capcoder log

**Symptom.** Every so often the decoder log shows junk between real pages:

```
capcoder.decode multimon-ng: POCSAG1200: Address:  945964  Function: 3
capcoder.decode page capcode=945964 function=3 kind=tone text='' -> ignored: other capcode
capcoder.decode multimon-ng: POCSAG1200: Address:       -  Function: -  Alpha:   <DEL>9
```

- Random capcodes with no text: likely false decodes from noise. Between transmissions `rtl_fm` passes FM noise, and multimon-ng's error correction sometimes turns it into a valid-looking address.
- `Address: -` lines with garbage text: fragments without an address, printed because of the `-p` flag (show partially received messages).
- Real pages still display correctly. Capcoder ignores both kinds of line; neither reaches the pager.
- It seemed to stop after restarting the netcat forwarder, or after the next real page. That may be coincidence, since noise decodes come and go. Restarting netcat doesn't restart multimon-ng, so if the link is real, the UDP stream (gaps or bunching) is a better suspect than the decoder. Unconfirmed.

**Things to try, one at a time** (no code change needed; use `--mmng-args`):

1. Drop `-p`. This should remove the `Address: -` fragment lines.
2. Decode 1200 baud only. The iStation sends at 1200, but Capcoder also runs the 512 and 2400 decoders, and each one adds false decodes.

   ```
   python -m capcoder --capcode 870008 --mmng C:\rtl-sdr\multimon-ng_1.61.exe --mmng-args "-a POCSAG1200 -f alpha -t raw -q --timestamp -C US -"
   ```
3. Lower error correction: add `-b 1` before the final `-`. Per multimon-ng's help, lower levels mean fewer false positives, at the cost of possibly missing a weak real page.
4. Squelch in `rtl_fm` (`-l <level>`) so it sends silence instead of noise between pages. This could clip the start of a page if set too high, so test it with real pages.

**Done when** the log is noticeably quieter over a comparable stretch of time and real test pages to the lab pager still decode and display. If 1-3 help, make them Capcoder's default multimon-ng arguments (`capcoder/receiver.py`, `multimon_args`) and note it in `capcoder/CHANGELOG.md` and the README's "Decoder settings" section.
