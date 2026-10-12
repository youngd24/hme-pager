# FreePBX/Asterisk Paging IVR

Use this to create an IVR on FreePBX/Asterisk, I'm on Debian/17, that's where this was tested. Calls are routed to it via a Cisco 3845, other configurations, needs and requirements may vary based on your installation and environment.

# Generate TTS Audio Files

I do this on another Ubuntu machine or under WSL on Windows, not the FreePBX one.

## Install prerequisite packages:
```
sudo apt install sox
```

## Install Piper
```
python3 -m venv ~/piper && . ~/piper/bin/activate
pip install piper-tts
python3 -m piper.download_voices en_US-lessac-medium
```

## Create input file

Add to `prompts.txt`:

```
pagerivr-enter-pager|Paging system. Enter the pager number, followed by the pound key.
pagerivr-enter-message|Enter your numeric message, followed by the pound key.
pagerivr-pager|Pager
pagerivr-message|Message
pagerivr-confirm|Press 1 to send, or 2 to start over.
pagerivr-invalid|That entry was not valid.
pagerivr-sent|Your page has been sent.
pagerivr-failed|Sorry, your page could not be sent. Please try again later.
```

## Create prompt files

Create `make_prompts.sh` and run it.

```
#!/bin/bash
set -euo pipefail
OUT=sounds/en/custom
mkdir -p "$OUT"
while IFS='|' read -r name text; do
  [[ -z "$name" || "$name" == \#* ]] && continue
  tmp=$(mktemp --suffix=.wav)
  piper -m en_US-lessac-medium -f "$tmp" -- "$text"
  # Asterisk-friendly: 8 kHz, mono, 16-bit PCM
  sox "$tmp" -r 8000 -c 1 -b 16 "$OUT/$name.wav" gain -n -3
  rm -f "$tmp"
  echo "built $name.wav"
done < prompts.txt
```

You should now have these files in `sounds/en/custom`:
```
pagerivr-confirm.wav
pagerivr-enter-message.wav
pagerivr-enter-pager.wav
pagerivr-failed.wav
pagerivr-invalid.wav
pagerivr-message.wav
pagerivr-pager.wav
pagerivr-sent.wav
```

# Create the IVR

## Install the hme pager cli

I install into /usr/local, you can do it elsewhere, as the asterisk user:

```
sudo git clone https://github.com/youngd24/hme-pager.git
chown -R asterisk:asterisk /usr/local/hme-pager
sudo chmod +x /usr/local/hme-pager/hmepager
```

## Create a config file

```
sudo mkdir ~askterisk/.hme-pager
sudo cp /usr/local/hme-pager/config.example ~asterisk/.hme-pager/config
```

## Example config

```
# Defaults for pager.py. Copy to ~/.hme-pager/config and edit.
# Every setting is optional; command-line options override them.

[pager]
# How to send: network (the transmitter's HTTP interface) or serial (RS-232).
mode = network

# For network: the transmitter's address, host or host:port (port 80 if not given).
host = 192.168.x.x

# For serial: the port the transmitter's cable is on.
serial_port = /dev/ttyS0

# The transmitter's 3-digit base ID. Serial needs it to page by pager number
# (capcode = base ID followed by pager x 8 as 4 digits; base 087, pager 1 -> 0870008).
base = 087

# What to send when neither -a nor -n is given: alpha or numeric.
type = alpha

# Show what is sent and the transmitter's reply on every page: true or false.
verbose = false
```

## Test the pager

```
/usr/local/hme-pager/hmepager -p <pagerid> 5551234; echo "exit=$?"
```

## Install audio files

SCP/SFTP the wav files you created up to the machine then copy them into place:

```
sudo cp pagerivr-*.wav /var/lib/asterisk/sounds/en/custom/
sudo chown asterisk:asterisk /var/lib/asterisk/sounds/en/custom/pagerivr-*.wav
```

## Create the dialplan

For my example it's using the extension 3682

Append this to `/etc/asterisk/extensions_custom.conf`:

```
[from-internal-custom]
exten => 3682,1,Goto(app-pagerivr,s,1)

[app-pagerivr]
exten => s,1,Answer()
 same => n,Wait(1)
 same => n,Set(TRIES=0)

 same => n(getpager),Set(TRIES=$[${TRIES}+1])
 same => n,GotoIf($[${TRIES} > 3]?bye)
 same => n,Read(PAGERID,custom/pagerivr-enter-pager,10,,1,10)
 same => n,GotoIf($[${REGEX("^[0-9]+$" ${PAGERID})}]?getmsg)
 same => n,Playback(custom/pagerivr-invalid)
 same => n,Goto(getpager)

 same => n(getmsg),Set(TRIES=0)
 same => n(msgloop),Set(TRIES=$[${TRIES}+1])
 same => n,GotoIf($[${TRIES} > 3]?bye)
 same => n,Read(PAGEMSG,custom/pagerivr-enter-message,20,,1,15)
 same => n,GotoIf($[${REGEX("^[0-9]+$" ${PAGEMSG})}]?confirm)
 same => n,Playback(custom/pagerivr-invalid)
 same => n,Goto(msgloop)

 same => n(confirm),Playback(custom/pagerivr-pager)
 same => n,SayDigits(${PAGERID})
 same => n,Playback(custom/pagerivr-message)
 same => n,SayDigits(${PAGEMSG})
 same => n,Read(CONFIRM,custom/pagerivr-confirm,1,,1,5)
 same => n,GotoIf($["${CONFIRM}" = "1"]?send)
 same => n,GotoIf($["${CONFIRM}" = "2"]?restart)
 same => n,Goto(bye)
 same => n(restart),Set(TRIES=0)
 same => n,Goto(getpager)

 same => n(send),System(timeout 10 /usr/local/hme-pager/hmepager ${PAGERID} ${PAGEMSG})
 same => n,NoOp(pagerivr pager=${PAGERID} msg=${PAGEMSG} status=${SYSTEMSTATUS})
 same => n,GotoIf($["${SYSTEMSTATUS}" = "SUCCESS"]?sent)
 same => n,Playback(custom/pagerivr-failed)
 same => n,Goto(bye)
 same => n(sent),Playback(custom/pagerivr-sent)

 same => n(bye),Playback(goodbye)
 same => n,Hangup()
 ```

 ## Reload and verify

 ```
 sudo fwconsole reload
sudo asterisk -rx "dialplan show 3682@from-internal-custom"
sudo asterisk -rx "dialplan show app-pagerivr"
```

## Cisco Config

Here's an example of my configuration that sends calls there:

```
conf t
dial-peer voice 3682 voip
 description Outbound to FreePBX - PAGER IVR
 destination-pattern 3682
 session protocol sipv2
 session target ipv4:192.168.x.x
 dtmf-relay rtp-nte
 codec g711ulaw
 no vad
```