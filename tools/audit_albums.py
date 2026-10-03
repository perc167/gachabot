"""Checks the albums of everyone who gained episode frames.

    python tools/audit_albums.py --dry-run
    python tools/audit_albums.py

Three questions, asked of every picture in those albums:

  Is there a face in it? A frame can be the right character, alone, and
  still be a shoulder against a curtain or a single eye filling the screen.
  Nothing about identity catches that, so the face detector does.

  Is it still them, alone? The frames were checked before they were cropped,
  and a crop can ruin that - the attention crop keeps what is visually
  interesting, which is not always the character, so a frame that passed can
  come out as scenery with an elbow in it.

  Is it already in the album? Twice over: the same file twice, which the
  merge now prevents, and two different files that are the same picture,
  which nothing has looked for. Near-duplicates are compared by an 8x8
  average hash, so a crop and its original, or two frames a second apart,
  count as one.

  Can you see them? A frame can be the right character, alone, face in
  shot, and still be a silhouette in an unlit room or one eye filling the
  card. That is what Emilia's album was complained about for, twice.

Anything failing a question is dropped. A character whose every picture
fails loses their album and falls back to the portrait on the roster, which
is the same place everyone who was never swept gets theirs.
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "character_art.json")
FRAMES = os.path.join(ROOT, "data", "character_frames.json")
TAGS = os.path.join(ROOT, "data", "character_art_tags.json")
# Fingerprints of the linked pictures, so a second audit does not download
# them all again only to hash them.
MARKS = os.path.join(ROOT, "data", "art_marks.json")
ART_DIR = os.path.join(ROOT, "assets", "characters")

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

# Two pictures whose 8x8 thumbnails differ in fewer bits than this are the
# same picture as far as a player flipping through them is concerned.
SAME_BITS = 8


def load(path: str) -> dict:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_marks(marks: dict):
    with io.open(MARKS, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(marks, handle, ensure_ascii=False)


def open_image(url: str, fetch):
    """The picture behind an album entry, local file or link."""
    from PIL import Image

    if url.startswith("local:"):
        path = os.path.join(ART_DIR, url[len("local:"):])
        if not os.path.exists(path):
            return None
        try:
            image = Image.open(path)
            image.load()
            return image
        except Exception:  # noqa: BLE001 - a broken file is a dropped entry
            return None
    # A linked picture that is slow is not worth a minute of the clock;
    # there are hundreds of them and the audit has to finish.
    data = fetch(url, tries=2, timeout=20)
    if not data:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image
    except Exception:  # noqa: BLE001
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    import fetch_episode_frames as frames_tool

    art = load(ART)
    frames = load(FRAMES)
    tags = load(TAGS)
    panel = frames_tool.Panel()

    marks_seen = {}
    if os.path.exists(MARKS):
        marks_seen = load(MARKS)
    had_marks = len(marks_seen)

    # Every linked picture that still needs a fingerprint, fetched several at
    # a time. One at a time it was ten seconds each and two hours in total,
    # because most of that was sitting waiting on a server rather than doing
    # anything. A dead link is remembered as dead, so it costs its forty
    # seconds once rather than on every run.
    wanted = [url for key in frames for url in (art.get(key) or [])
              if not url.startswith("local:") and url not in marks_seen]
    if wanted:
        print(f"fetching {len(wanted):,} linked pictures to fingerprint"
              f" (of {sum(len(art.get(k) or []) for k in frames):,})",
              flush=True)
        from concurrent.futures import ThreadPoolExecutor
        from PIL import Image

        def mark_of(url):
            data = frames_tool.fetch(url, tries=1, timeout=15)
            if not data:
                return url, ""
            try:
                image = Image.open(io.BytesIO(data))
                image.load()
            except Exception:  # noqa: BLE001 - a broken link is a dead link
                return url, ""
            return url, frames_tool.fingerprint(image)

        with ThreadPoolExecutor(max_workers=8) as pool:
            for number, (url, mark) in enumerate(pool.map(mark_of, wanted), 1):
                marks_seen[url] = mark
                if number % 100 == 0:
                    save_marks(marks_seen)
                    print(f"  {number:,}/{len(wanted):,}", flush=True)
        save_marks(marks_seen)

    checked = not_alone = duplicate = broken = faceless = unlit = 0
    emptied = []
    for key in sorted(frames):
        album = art.get(key) or []
        if not album:
            continue
        tag = tags.get(key, "")
        kept, marks = [], []

        for url in album:
            checked += 1
            # A linked picture is never re-judged - only the frames are - so
            # the single thing it is fetched for is its fingerprint, to catch
            # the same picture appearing twice. Remembering that between runs
            # turns seven hundred downloads into none, which is the whole
            # difference between an audit you can run after every sweep and
            # one that takes two hours.
            remembered = None if url.startswith("local:") else marks_seen.get(url)
            if remembered is not None:
                # "" means the link would not load. That is not grounds for
                # deleting somebody's art - the server may simply have been
                # down - so it stays, and it is not compared against anything.
                if not remembered:
                    kept.append(url)
                    continue
                mark = remembered
            else:
                image = open_image(url, frames_tool.fetch)
                if image is None:
                    # A bundled file that is not there is really gone.
                    if url.startswith("local:"):
                        broken += 1
                        continue
                    kept.append(url)
                    continue
                mark = frames_tool.fingerprint(image)

            if any(frames_tool.alike(mark, seen) for seen in marks):
                duplicate += 1
                continue

            # Only the frames are re-judged. The official art was chosen by
            # its own rules and is not a frame of anything.
            if url.startswith("local:frame-"):
                ok, scene = panel.judge(image, tag)
                if not ok:
                    not_alone += 1
                    continue
                # A frame with no face is a torso, a shoulder, or a speck in
                # a landscape. It passes every identity check and is still
                # not a picture of anybody.
                if not frames_tool.shows_face(scene):
                    faceless += 1
                    continue
                # The one the album was complained about twice: her, alone,
                # face in shot, and too dark or too close to make out.
                if not frames_tool.visible(image, scene):
                    unlit += 1
                    continue

            marks.append(mark)
            kept.append(url)

        if kept:
            art[key] = kept
        else:
            emptied.append(key.split("\x1f")[0])
            art.pop(key, None)

    print(f"checked {checked:,} pictures across {len(frames):,} albums")
    print(f"  dropped {not_alone:,} where the crop no longer shows them alone")
    print(f"  dropped {faceless:,} with no face in them at all")
    print(f"  dropped {unlit:,} too dark, or too close, to see who it is")
    print(f"  dropped {duplicate:,} that repeat a picture already there")
    print(f"  dropped {broken:,} that would not open")
    if emptied:
        print(f"  {len(emptied)} left with nothing: {', '.join(emptied[:6])}")

    # And the frames file, so a later merge does not put them back.
    kept_local = {url for urls in art.values() for url in urls}
    trimmed = {}
    for key, urls in frames.items():
        alive = [url for url in urls if url in kept_local]
        if alive:
            trimmed[key] = alive

    total = sum(len(v) for v in art.values())
    print(f"\nthe art file holds {sum(1 for v in art.values() if v):,}"
          f" characters and {total:,} pictures")

    if args.dry_run:
        print("\nDry run, nothing written.")
        return 0

    if len(marks_seen) != had_marks:
        save_marks(marks_seen)
        print(f"remembered {len(marks_seen) - had_marks:,} more fingerprints")

    with io.open(ART, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(art, handle, ensure_ascii=False)
    with io.open(FRAMES, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(trimmed, handle, ensure_ascii=False)
    print(f"\nWrote {ART} and {FRAMES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
