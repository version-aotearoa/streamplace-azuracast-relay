# Streaming with OBS — DJ guide

Everything you need to go live from OBS. Copy the block, paste it into OBS,
press Start Streaming.

## The short version

```
OBS → Settings → Stream
  Service:    Custom…
  Server:     rtmps://multistream.versionradio.live:1935/live
  Stream Key: <your key — ask the station>

OBS → Settings → Output
  Output Mode: Advanced → Streaming tab
  Encoder:            x264 (or NVENC if you have an NVIDIA card)
  Rate Control:       CBR
  Bitrate:            6000 Kbps for 1080p60 · 4000 Kbps for 720p60
  Keyframe Interval:  1 second      ← must be 1
  Profile:            high
  B-frames:           0             ← must be 0

OBS → Settings → Audio
  Sample Rate: 48 kHz · Channels: Stereo · Audio Bitrate: 160 Kbps
```

That is the whole configuration. If you change nothing else, you'll sound and
look right.

## Before you start

- **OBS Studio 30 or newer.**
- **Upload speed.** Run a speed test and use about half of it. 20 Mbps up means
  6000 Kbps is safe; 10 Mbps up means use 4000 Kbps.
- **Your stream key.** It's personal to you — don't post it anywhere.

## The two settings that actually matter

**Keyframe Interval: `1` second.**
This is the one that ruins a stream when it's wrong. Some OBS versions show it in
seconds, others in frames — if it's frames, enter `30` for 30 fps or `60` for 60 fps.
Leave it at 2 or higher and viewers get choppy video, and the platform flags your
stream as unreliable.

**B-frames: `0`.**
Found under Output → Advanced. If you can't see it, set **Profile: high** and
leave the rest alone — that's usually enough.

## Do a rehearsal first

You have two keys: your normal one, and **`rehearsal`**.

1. Put `rehearsal` in the Stream Key field.
2. Press **Start Streaming**.
3. OBS should show **connected** and stay green for a minute.

A rehearsal confirms OBS can reach us and your settings are accepted. It is
**not** broadcast — the station keeps playing to listeners while you test, and
nothing appears on Streamplace. When you're ready to be heard, swap in your real
key and start again.

## Going live

1. Check no other DJ is already on air.
2. Put your real key in and press **Start Streaming**.
3. Within about 15 seconds:
   - the station's now-playing shows **live**, with your name as the streamer
   - radio listeners hear you instead of the playlist
   - the video audience sees your feed on Streamplace
4. When you finish, press **Stop Streaming**. The station returns to its normal
   playlist within ~20 seconds — you don't need to do anything else.

## If something's wrong

| What you see | What it usually means | Fix |
|---|---|---|
| "Failed to connect" immediately | wrong server address | it must end in `/live`, and the key goes in the key field — don't put `/live` in both |
| Connected, then drops straight away | the key was pasted with a space or newline | delete the key field and paste it again carefully |
| Connected, but you're not on air | another DJ is already streaming, or you're using the `rehearsal` key | wait for them to finish, and check you swapped the key |
| Video stutters for viewers | keyframe interval isn't 1 s | see the settings above |
| Audio is quiet or distorted | mic gain too high | watch OBS's audio meter — peaks should sit around −6 dB, never touching the top |
| You stopped, but the station seems quiet for a moment | normal handover | wait 20–30 seconds |
| Everything works, but the video page looks frozen while audio plays | not your problem — that's a station-side issue | tell the station, don't change OBS settings |

## Bitrate cheat sheet

| Your upload speed | Use this |
|---|---|
| under 10 Mbps | 720p30 · 2500 Kbps |
| 10–15 Mbps | 720p60 · 4000 Kbps |
| 15 Mbps+ | 1080p60 · 6000 Kbps |

Lower is always safer than higher. A clean 720p stream beats a stuttering 1080p.
