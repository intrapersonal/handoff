(preview of connector site) 
<img width="1161" height="649" alt="image" src="https://github.com/user-attachments/assets/d9da49b9-f9ec-4b03-87a3-f27a808f314e" />
# handoff

no webcam? use your phone. handoff turns your phone into a camera for touchdesigner over wifi, and sends its tilt, motion and touches along with it.

nothing to install on the phone. you scan a qr code, hit start, and it shows up in td as a spout texture plus an osc chop.

## run it

needs windows 10/11 and python 3.10 or newer. your phone and pc have to be on the same wifi.

1. download this repo
2. double click `start.bat`. first time it makes its own venv and installs what it needs
3. scan the qr code with your phone (it's in the window and on the page that opens)
4. your phone warns you about the certificate. that's expected, the pc made its own. tap through it (**show details → visit this website** on iphone, **advanced → proceed** on android)
5. hit **start**, allow the camera

windows firewall asks about python the first time. allow it on private networks or the phone can't reach your pc.

or from a terminal:

```
pip install -r requirements.txt
python -m handoff
```

## in touchdesigner

| what | how |
| --- | --- |
| video | **Syphon Spout In TOP**, sender `handoff` |
| phone sensors | **OSC In CHOP**, port `7410` |
| anything else | `http://127.0.0.1:7421/stream.mjpg` |

channels come in flat, same style as wintd:

```
ph_connected  ph_fps  ph_rtt  ph_width  ph_height  ph_front
ph_yaw  ph_pitch  ph_roll  ph_tilt_x  ph_tilt_y
ph_acc_x  ph_acc_y  ph_acc_z  ph_motion  ph_shake
ph_touches  ph_tap  ph_pinch  ph_pinch_amt
ph_t0_x  ph_t0_y  ph_t0_down  ph_t1_x ...  ph_t2_down
```

- `tilt_x` `tilt_y` are -1 to 1, flat on a table is 0 0
- `yaw` `pitch` `roll` are degrees straight from the phone
- `acc_*` is movement without gravity in m/s², `motion` is a smoothed 0 to 1 of how much you're moving it
- `shake` and `tap` pulse to 1 for a moment
- touches are 0 to 1 across the screen with y going up, so the whole phone screen is a touchpad. `pinch_amt` starts at 1 when two fingers go down and grows or shrinks as you spread them
- when the phone drops off everything goes to 0 and `ph_connected` goes to 0

## hand tracking

if you've installed wintd in touchdesigner before, handoff runs its hand tracking on the phone by itself. nothing to set up. once the phone is live the `h0_index_tip_x` style channels show up on port 7400 like normal, and they stop when the phone does.

turn **Active** off on the wintd component while you use handoff so the two don't fight over the port.

want face or pose too? `python -m handoff --track hands,face,pose`. don't want it at all? `--no-hands`.

## on the phone

- **flip** switches front and back camera
- **720p** cycles 360p / 480p / 720p / 1080p
- **light** turns on the flashlight, only shows up if your phone lets the browser do that
- **dim** blacks out the screen so it doesn't cook your battery, it keeps sending. tap to wake
- open it on a second phone and that one takes over

the screen stays awake while it's running.

## options

```
python -m handoff --res 1080 --fps 60
python -m handoff --quality 0.6
python -m handoff --mirror --rotate 90
python -m handoff --osc-host 192.168.1.20 --osc-port 9000
python -m handoff --spout-name phone2 --port 7430 --local-port 7431 --osc-port 7411
python -m handoff --ip 192.168.1.42
```

`--ip` is for when the qr code shows the wrong address (vpn, hotspot, two network cards). `--help` for the rest.

## how it works

```
phone camera ─► jpeg ─► wss :7420 ─► handoff ─► spout "handoff"
phone sensors ─► json ─┘                     ├─► osc :7410
                                             └─► mjpeg :7421
```

the phone encodes the jpegs itself and only keeps two frames in flight, so if the wifi gets slow it drops frames instead of getting laggy. the pc side doesn't re-encode anything, it just hands the jpeg to spout and the mjpeg stream. https is needed because phones only give the camera to secure pages, so handoff makes a certificate for your pc the first time and keeps it in `%LOCALAPPDATA%\handoff`.

## troubleshooting

- **phone can't load the page**: same wifi? firewall allowed? guest networks and school wifi often block devices from seeing each other, use your phone's hotspot instead
- **qr code has a weird address**: use `--ip` with your pc's address from `ipconfig`
- **no video in td but the phone says live**: spout needs `SpoutGL` (`pip install SpoutGL`). the status page says if spout is off
- **laggy**: drop to 480p or `--quality 0.6`, or get closer to the router

## license

MIT
