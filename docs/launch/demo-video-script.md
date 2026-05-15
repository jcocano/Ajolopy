# Demo video / asciinema cast script

Target length: **75 seconds**. The artefact this repo ships is the
**asciinema cast** at `docs/launch/demo.cast` plus this shot list. The
maintainer can either:

- Embed the cast as-is in the README via `asciinema-player`, or
- Use the shot list as a script for a screen recording (Loom / OBS),
  pasting the same commands and pacing.

The cast is reproducible — re-record any time the API surface
changes; see [Re-recording](#re-recording) below.

## Shot list

| #     | Time (s) | Screen                                               | What's happening                                                                                                                                |
| ----- | -------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | 0–5      | Terminal prompt                                      | Title card overlay: **Ajolopy — a Python framework for AI-native production apps. v0.1.** Held for 3s.                                          |
| 2     | 5–15     | `ajolopy new acme-support` running the wizard       | Four wizard answers fly by (anthropic / agent / yes / yes). End with the printed project tree.                                                  |
| 3     | 15–25    | `cat src/acme_support/agents/support.py`            | The 12-line killer demo lands on screen. Hold long enough to read.                                                                              |
| 4     | 25–35    | `cp .env.example .env` then `ajolopy dev`           | Server banner with the watched paths. Caption overlay: **env validated, reload on, OTel always-on**.                                            |
| 5     | 35–50    | Second pane: `curl -N -X POST .../chat`             | Streaming response landing token by token. Caption: **SSE streaming, fallback wired, one OTel span per call**.                                  |
| 6     | 50–65    | First pane: `ajolopy eval --ci`                     | Eval suite runs against the agent. End with the pass/fail banner. Caption: **`@Eval` blocks PRs that regress**.                                 |
| 7     | 65–75    | Close card                                           | `pip install ajolopy` + `jcocano.github.io/Ajolopy` + tagline **"The axolotl regenerates. So does Ajolopy."**                                   |

## On-screen captions

- Keep captions minimal — three to four lines maximum across the whole
  video.
- Sans-serif, bottom-third placement, no animation. Match the docs
  site's Material indigo for accent color.

## Voice-over

**Skip the voice-over for v0.1.** The cast is silent / captioned. A
voice-over adds production overhead the launch does not need — and
captions are accessible without sound.

If a future release wants narration:

- Script reads ~120 words at 130 wpm = 55 seconds, fits the run-time.
- Suggested script lives in `voice-over-draft.md` (not committed yet —
  add when needed).

## Re-recording

```bash
asciinema rec docs/launch/demo.cast \
  --title "Ajolopy v0.1 killer demo" \
  --idle-time-limit 1.5 \
  --command bash
```

Run the demo flow from the shot list above inside the recording
session. Exit with `Ctrl-D` to stop.

Trim or speed up post-hoc with `asciinema-edit` if needed:

```bash
asciinema-edit speed --factor 1.5 \
  --start 10s --end 45s \
  docs/launch/demo.cast \
  -o docs/launch/demo.cast
```

The committed `demo.cast` is a snapshot; treat it like the
`evals/*.jsonl` snapshots — refresh on intentional API changes, leave
alone otherwise.

## Embedding in the README

Once the cast is recorded, swap the README's "Run it" code block for
an `asciinema-player` embed by uploading the cast to
<https://asciinema.org/> and pasting the player script.

This is **not part of the v0.1 launch PR** — embed-once, after the
recording lands.
