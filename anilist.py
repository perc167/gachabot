"""A very small AniList client, for looking a series up at runtime.

The tools in tools/ do their own bulk fetching; this exists so the bot can
add one series on request without shelling out to a script.

Blocking on purpose - callers run it through asyncio.to_thread so the bot
keeps answering while it waits.
"""
import json
import urllib.error
import urllib.request

API = "https://graphql.anilist.co"

SERIES_QUERY = """
query ($search: String, $castSize: Int) {
  Page(page: 1, perPage: 8) {
    media(search: $search, sort: POPULARITY_DESC) {
      type format isAdult popularity
      title { romaji english }
      characters(sort: FAVOURITES_DESC, perPage: $castSize) {
        nodes {
          id
          name { full }
          favourites
          image { large }
        }
      }
    }
  }
}
"""


class AniListError(RuntimeError):
    pass


def _post(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        API,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "gachabot/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise AniListError(f"AniList returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise AniListError(f"could not reach AniList: {error}") from error
    if "errors" in payload and not payload.get("data"):
        raise AniListError(str(payload["errors"])[:200])
    return payload["data"]


def find_series(search: str, cast_size: int = 30, allow_adult: bool = False):
    """Return (title, [character dicts]) for the best match, or (None, []).

    A franchise often has several entries sharing one cast - MILGRAM has one
    per trial - so the most popular is taken and its title used, rather than
    importing the same people three times under different names.
    """
    data = _post(SERIES_QUERY, {"search": search, "castSize": cast_size})
    best = None
    for entry in data["Page"]["media"]:
        if entry.get("isAdult") and not allow_adult:
            continue
        if not ((entry.get("characters") or {}).get("nodes") or []):
            continue
        if best is None or (entry.get("popularity") or 0) > (
            best.get("popularity") or 0
        ):
            best = entry
    if best is None:
        return None, []

    title = best["title"].get("english") or best["title"].get("romaji")
    cast = []
    for node in (best.get("characters") or {}).get("nodes") or []:
        name = (node.get("name") or {}).get("full")
        image = (node.get("image") or {}).get("large") or ""
        if not name or not image or "default.jpg" in image:
            continue  # a character with no portrait is a worse roll
        cast.append(
            {
                "name": name,
                "series": title,
                "image_url": image,
                "likes": 0,
                "favourites": node.get("favourites") or 0,
                "anilist_id": node["id"],
                "source": "AniList",
            }
        )
    return title, cast
