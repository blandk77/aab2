from calendar import month_name
from datetime import datetime
from random import choice
from asyncio import sleep as asleep
from aiohttp import ClientSession
from anitopy import parse
import re
from anilist import Client as AniClient
from anilist.types import Anime

_anilist_client = None

async def get_anilist_client():
    global _anilist_client
    if _anilist_client is None:
        _anilist_client = AniClient()
    return _anilist_client

async def search_anilist_multiple(query: str, max_results: int = 5):
    """Used ONLY for /addschedule picker — 100% reliable"""
    client = await get_anilist_client()
    
    try:
        results: list[Anime] = await client.search_anime(query, limit=max_results)
    except Exception as e:
        from bot.core.reporter import rep
        await rep.report(f"AniList.py error: {e}", "warning")
        return []

    if not results:
        from bot.core.reporter import rep
        await rep.report(f"AniList.py: No results for '{query}'", "warning")
        return []

    formatted = []
    for anime in results:
        formatted.append({
            "id": anime.id,
            "title": {
                "english": anime.title_english or anime.title_romaji,
                "romaji": anime.title_romaji,
                "native": anime.title_native
            },
            "status": (anime.status.value.upper() if anime.status else "UNKNOWN"),
            "seasonYear": anime.start_date.year if anime.start_date else None,
            "nextAiringEpisode": {
                "episode": anime.next_episode,
                "airingAt": int(anime.next_airing_time.timestamp()) if anime.next_airing_time else None
            } if anime.next_episode else None,
            "coverImage": {"large": anime.cover_image or "https://via.placeholder.com/300x450"}
        })

    from bot.core.reporter import rep
    await rep.report(f"AniList.py: Found {len(results)} results for '{query}'", "info")
    return formatted

class AniLister:
    def __init__(self, anime_name: str, year: int = None) -> None:
        self.__api = "https://graphql.anilist.co"
        self.__ani_name = anime_name.strip()
        self.__original_year = year or datetime.now().year

    async def post_data(self):
        query = """
        query ($search: String, $perPage: Int) {
          Page(perPage: $perPage) {
            media(search: $search, type: ANIME) {
              id
              title { romaji english native }
              description(asHtml: false)
              status(version: 2)
              seasonYear
              episodes
              nextAiringEpisode { airingAt episode }
              coverImage { large }
              genres
              averageScore
              studios { nodes { name } }
              startDate { year month day }
            }
          }
        }
        """
        async with ClientSession() as sess:
            async with sess.post(self.__api, json={
                "query": query,
                "variables": {"search": self.__ani_name, "perPage": 1}
            }) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return data.get("data", {}).get("Page", {}).get("media", [{}])[0] or {}

    async def get_anidata(self):
        return await self.post_data()

class TextEditor:
    def __init__(self, name):
        self.__name = name
        self.adata = {}
        self.pdata = parse(name)

    async def load_anilist(self):
        cache_names = []
        for option in [(False, False), (False, True), (True, False), (True, True)]:
            ani_name = await self.parse_name(*option)
            if ani_name in cache_names or not ani_name:
                continue
            cache_names.append(ani_name)
            self.adata = await AniLister(ani_name).get_anidata()
            if self.adata:
                break

    async def parse_name(self, no_s=False, no_y=False):
        anime_name = self.pdata.get("anime_title")
        if not anime_name:
            return ""
        pname = anime_name
        if not no_s and self.pdata.get("episode_number") and self.pdata.get("anime_season"):
            pname += f" Season {self.pdata.get('anime_season')}"
        if not no_y and self.pdata.get("anime_year"):
            pname += f" {self.pdata.get('anime_year')}"
        return pname

    async def get_poster(self):
        if anime_id := self.adata.get('id'):
            return f"https://img.anili.st/media/{anime_id}"
        return "https://files.catbox.moe/z69m7i.jpg"

    async def get_upname(self, qual="", custom_title=None, audio_type="Sub"):
        if not self.pdata.get("anime_title") or not self.pdata.get("episode_number"):
            return None
        title_use = custom_title or (
            self.adata.get("title", {}).get("english") or
            self.adata.get("title", {}).get("romaji") or
            self.adata.get("title", {}).get("native")
        )
        season = self.pdata.get("anime_season", "01")
        if isinstance(season, list):
            season = season[-1]
        return f"[S{season}-E{self.pdata.get('episode_number')}] {title_use} [{qual}p] [{audio_type}] @{Var.BRAND_UNAME}.mkv"

    async def get_caption(self, audio_lang="Japanese", sub_type="English"):
        if not self.adata:
            return "<code>No AniList data</code>"
        titles = self.adata.get("title", {})
        title = titles.get("english") or titles.get("romaji") or titles.get("native")
        desc = (self.adata.get("description") or "No description").replace("<br>", "\n")
        plot = desc[:200] + "..." if len(desc) > 200 else desc
        genres = ", ".join(self.adata.get("genres", []))
        ep = self.pdata.get("episode_number", "??")
        return f"""
<code>{title}</code>
<b>◇ Episode:</b> <code>{ep}</code> │ <b>Audio:</b> <code>{audio_lang}</code> │ <b>Subs:</b> <code>{sub_type}</code>
<b>◇ Genres:</b> <code>{genres or "N/A"}</code>
<blockquote>{plot}</blockquote>
<i>Powered by @{Var.BRAND_UNAME}</i>
""".strip()
