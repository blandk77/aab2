from calendar import month_name      
from datetime import datetime      
from random import choice      
from asyncio import sleep as asleep      
from aiohttp import ClientSession      
from anitopy import parse      
import re      
import json  # For error parsing      
      
from bot import Var, bot      
from .ffencoder import ffargs      
from .func_utils import handle_logs      
from .reporter import rep      
      
GENRES_EMOJI = {"Action": "👊", "Adventure": choice(['🪂', '🧗‍♀']), "Comedy": "🤣", "Drama": " 🎭", "Ecchi": choice(['💋', '🥵']), "Fantasy": choice(['🧞', '🧞‍♂', '🧞‍♀','🌗']), "Hentai": "🔞", "Horror": "☠", "Mahou Shoujo": "☯", "Mecha": "🤖", "Music": "🎸", "Mystery": "🔮", "Psychological": "♟", "Romance": "💞", "Sci-Fi": "🛸", "Slice of Life": choice(['☘','🍁']), "Sports": "⚽️", "Supernatural": "🫧", "Thriller": choice(['🥶', '🔪','🤯'])}      

# ====================== ANILIST GRAPHQL ======================
ANIME_GRAPHQL_QUERY = """
query ($id: Int, $search: String, $seasonYear: Int, $perPage: Int) {
  Page(perPage: $perPage) {
    media(search: $search, type: ANIME, seasonYear: $seasonYear, sort: [SEARCH_MATCH, POPULARITY_DESC]) {
      id
      title { romaji english native }
      status(version: 2)
      seasonYear
      nextAiringEpisode { airingAt episode }
      coverImage { large }
      siteUrl
    }
  }
}
"""

def clean_rss_title(raw_title: str) -> str:
    for tag in ["[ToonsHub]", "[VARYG]", "[Erai-raws]", "[SubsPlease]", "[Judas]", "[EMBER]", "[Bili]", "(Multi-Subs)"]:
        raw_title = raw_title.replace(tag, "").strip()
    raw_title = re.sub(r'S\d+E\d+|Ep\.?\s*\d+|1080p|720p|480p|360p|WEB.?DL|AAC\d\.\d|H\.265|H\.264|\d+p|BILI|WEB|DL', '', raw_title, flags=re.IGNORECASE)
    raw_title = re.sub(r'[-–] .*', '', raw_title)
    raw_title = re.sub(r'\s*\(.*\)', '', raw_title)
    raw_title = re.sub(r'[!\?\.]+$', '', raw_title).strip()
    raw_title = re.sub(r'([a-zA-Z])-([a-zA-Z])', r'\1\2', raw_title)
    return raw_title

class AniLister:
    def __init__(self, query: str):
        self.query = query.strip()
        self.api = "https://graphql.anilist.co"

    async def _post(self, variables: dict):
        async with ClientSession() as session:
            async with session.post(self.api, json={'query': ANIME_GRAPHQL_QUERY, 'variables': variables}) as resp:
                try:
                    data = await resp.json()
                except:
                    data = None
                return resp.status, data

    async def search(self):
        # Main search — never send seasonYear if query contains a year number
        variables = {"search": self.query, "perPage": 5}
        if not re.search(r'\b20\d{2}\b', self.query):
            variables["seasonYear"] = datetime.now().year

        status, data = await self._post(variables)
        await rep.report(f"AniList → Query: '{self.query}' | Status: {status}", "info", log=False)

        # SAFE parsing
        if not data or not isinstance(data, dict):
            await rep.report(f"AniList returned bad data: {data}", "warning", log=False)
            media = []
        else:
            media = data.get("data", {}).get("Page", {}).get("media", [])

        if media:
            await rep.report(f"Found {len(media)} results", "info", log=False)
            return media

        # Fallback: force no year
        await rep.report("Primary failed → trying without year", "warning", log=False)
        status, data = await self._post({"search": self.query, "perPage": 5})
        if data and isinstance(data, dict):
            media = data.get("data", {}).get("Page", {}).get("media", [])
            if media:
                return media

        # Final fallback: normalized name
        norm = re.sub(r'([a-zA-Z])-([a-zA-Z])', r'\1\2', self.query)
        if norm != self.query:
            status, data = await self._post({"search": norm, "perPage": 5})
            if data and isinstance(data, dict):
                media = data.get("data", {}).get("Page", {}).get("media", [])
                if media:
                    return media

        await rep.report(f"AniList: ZERO results for '{self.query}'", "error", log=False)
        return []

    async def by_id(self, ani_id: int):
        status, data = await self._post({"id": ani_id, "perPage": 1})
        if data and isinstance(data, dict):
            return data.get("data", {}).get("Page", {}).get("media", [{}])[0] or {}
        return {}

async def search_anilist_multiple(query: str):
    """Returns list of anime dicts"""
    searcher = AniLister(query)
    return await searcher.search()
      
class TextEditor:      
    def __init__(self, name):      
        self.__name = name      
        self.adata = {}      
        self.pdata = parse(name)      
      
    async def load_anilist(self):      
        cache_names = []      
        for option in [(False, False), (False, True), (True, False), (True, True)]:      
            ani_name = await self.parse_name(*option)      
            if ani_name in cache_names:      
                continue      
            cache_names.append(ani_name)      
            self.adata = await AniLister(ani_name).get_anidata()      
            if self.adata:      
                break      
      
    @handle_logs      
    async def parse_name(self, no_s=False, no_y=False):      
        anime_name = self.pdata.get("anime_title")      
        anime_season = self.pdata.get("anime_season")      
        anime_year = self.pdata.get("anime_year")      
        if anime_name:      
            pname = anime_name      
            if not no_s and self.pdata.get("episode_number") and anime_season:      
                pname += f" {anime_season}"      
            if not no_y and anime_year:      
                pname += f" {anime_year}"      
            return pname      
        return anime_name      
              
    @handle_logs      
    async def get_poster(self):      
        if anime_id := self.adata.get('id'):      
            return f"https://img.anili.st/media/{anime_id}"      
        return "https://files.catbox.moe/z69m7i.jpg"      
              
    @handle_logs      
    async def get_upname(self, qual="", custom_title=None, audio_type="Sub"):      
        anime_name = self.pdata.get("anime_title")      
        anime_season = str(ani_s[-1]) if (ani_s := self.pdata.get('anime_season', '01')) and isinstance(ani_s, list) else str(ani_s)      
        if anime_name and self.pdata.get("episode_number"):      
            titles = self.adata.get('title', {})      
            title_use = custom_title or (titles.get('english') or titles.get('romaji') or titles.get('native'))      
            return f"""[S{anime_season}-E{self.pdata.get('episode_number')}] {title_use} [{qual}p] [{audio_type}] {Var.BRAND_UNAME}.mkv"""      
      
    @handle_logs      
    async def get_caption(self, audio_lang="Japanese", sub_type="English"):      
        sd = self.adata.get('startDate', {})      
        startdate = f"{month_name[sd['month']]} {sd['day']}, {sd['year']}" if sd.get('day') and sd.get('year') else ""      
        ed = self.adata.get('endDate', {})      
        enddate = f"{month_name[ed['month']]} {ed['day']}, {ed['year']}" if ed.get('day') and ed.get('year') else ""      
        titles = self.adata.get("title", {})      
        desc = self.adata.get("description") or "N/A"      
        plot = desc[:200] + "..." if len(desc) > 200 else desc      
              
        return f"""      
 <code>{titles.get('english') or titles.get('romaji') or titles.get('native')}</code>      
<b>◇──◇──◇──◇──◇──◇──◇──◇</b>      
<b>✦</b> <i>Genres:</i> <code>{', '.join(self.adata.get('genres', []))}</code>      
<b>✦</b> <i>Episode:</i> <code>{self.pdata.get("episode_number")}</code>      
<b>✦</b> <i>Audio:</i> <code>{audio_lang}</code>      
<b>✦</b> <i>Subtitle:</i> <code>{sub_type}</code>      
<b>◇──◇──◇──◇──◇──◇──◇──◇</b>      
<blockquote><b>Description:</b> {plot}</blockquote>      
<blockquote><b>╭╌═╌═╌═╌══╌═╌═╌═╌═╌╮</b>          <b>✦</b> <b><i>Powered By ~</i></b> <i>{Var.BRAND_UNAME}</i>      
<b>╰╌═╌═╌═╌═╌═╌═╌═╌══╌╯</b></blockquote>      
""".strip()
