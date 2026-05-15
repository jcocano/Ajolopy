# Launch

This section holds the **paste-ready drafts** the maintainer publishes
on the day v0.1.0 ships:

- [Show HN post](hn-post.md) — title + body.
- [X / Bluesky thread](x-thread.md) — 12 numbered posts.
- [Demo video script](demo-video-script.md) — 75-second shot list.

They are committed alongside the code so future releases can fork the
format and iterate on the voice in PR review instead of in a shared
doc.

## Cadence

| Step                                  | Owner       | Trigger                                |
| ------------------------------------- | ----------- | -------------------------------------- |
| Edit the drafts in this folder        | maintainer  | Once the launch date is set.           |
| Tag `v0.1.0` and push                 | maintainer  | After PyPI trusted-publisher is wired (see [release guide](../contributing/release.md)). |
| Record `demo.cast`                    | maintainer  | After v0.1.0 is on PyPI so the demo's `pip install ajolopy` step works.  |
| Post the X thread                     | maintainer  | Within an hour of the PyPI release.    |
| Submit Show HN                        | maintainer  | Same day, off-peak US morning (Tue–Thu, 9–11 a.m. PT typically). |
| Reply to comments                     | maintainer  | First two hours decide HN ranking.    |

## Out of scope for v0.1

- Logo / press kit / brand assets.
- Post-launch analytics dashboards.
- Comparison-with-LangChain matrix (one-off blog post, not part of
  the framework repo).

## Future enhancements

- Reusable launch template for v0.2 — fork these four pages, redo the
  X thread, refresh the video.
- Translations (Spanish, Portuguese) — the wedge user is global; a
  translated thread can double reach.
