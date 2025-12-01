from calendar import month_name
from datetime import datetime
from random import choice
from asyncio import sleep as asleep
from aiohttp import ClientSession
from anitopy import parse
import re

from bot import Var, bot
from .ffencoder import ffargs
from .func_utils import handle_logs
from .reporter import rep

GENRES_EMOJI = {"Action": "👊", "Adventure": choice(['🪂', '🧗‍♀']), "Comedy": "🤣", "Drama": " 🎭", "Ecchi": choice(['💋', '🥵']), "Fantasy": choice(['🧞', '🧞‍♂', '🧞‍♀','🌗']), "Hentai": "🔞", "Horror": "☠", "Mahou Shoujo": "☯", "Mecha": "🤖", "Music": "🎸", "Mystery": "🔮", "Psychological": "♟", "Romance": "💞", "Sci-Fi": "🛸", "Slice of Life": choice(['☘','🍁']), "Sports": "⚽️", "Supernatural": "🫧", "Thriller": choice(['🥶', '🔪','🤯'])}

ANIME_GRAPHQL_QUERY = """
query ($id: Int, $search: String, $seasonYear: Int, $perPage: Int) {
  Page(perPage: $perPage) {
    media(search: $search, type: ANIME, seasonYear: $seasonYear, sort: [SEARCH_MATCH, POPULARITY_DESC]) {
      id
      title {
        romaji
        english
        native
      }
      type
      format
      status(version: 2)
      description(asHtml: false)
      startDate {
        year
        month
        day
      }
      season
      seasonYear
      episodes
      nextAiringEpisode {
        airingAt
        timeUntilAiring
        episode
      }
      coverImage {
        large
      }
      genres
      averageScore
      studios {
        nodes { name }
      }
      isAdult
      siteUrl
    }
  }
}
"""

def clean_rss_title(raw_title: str) -> str:
    """Clean RSS title for AniList search: remove uploader, ep, quality, junk."""
    # Remove common uploader tags
    for tag in ["[ToonsHub]", "[VARYG]", "[Erai-raws]", "[SubsPlease]", "[Judas]", "[EMBER]", "[Bili]", "(Multi-Subs)"]:
        raw_title = raw_title.replace(tag, "").strip()
    
    # Remove episode/quality/source patterns (enhanced)
    raw_title = re.sub(r'S\d+E\d+|Ep\.?\s*\d+|1080p|720p|480p|360p|WEB-DL|AAC\d\.\d|H\.265|H\.264|\d+p|BILI|WEB|DL', '', raw_title, flags=re.IGNORECASE)
    raw_title = re.sub(r'[-–] .*', '', raw_title)  # Everything after " - "
    raw_title = re.sub(r'\s*\(.*\)', '', raw_title)  # Parentheticals
    raw_title = re.sub(r'[!\?\.]+$', '', raw_title)  # Trailing punctuation
    # Normalize romaji (remove hyphens/spaces in names like "Kotesashi-kun" → "Kotesashikun")
    raw_title = re.sub(r'([a-zA-Z])-([a-zA-Z])', r'\1\2', raw_title)  # Kotesashi-kun → Kotesashikun
    return raw_title.strip()

class AniLister:
    def __init__(self, anime_name: str, year: int = None) -> None:
        self.__api = "https://graphql.anilist.co"
        self.__ani_name = anime_name.strip()
        self.__original_year = year or datetime.now().year
        self.__current_year = self.__original_year

    def __update_vars(self):
        self.__current_year -= 1
        self.__vars['seasonYear'] = self.__current_year

    async def post_data(self):
        async with ClientSession() as sess:
            async with sess.post(self.__api, json={'query': ANIME_GRAPHQL_QUERY, 'variables': self.__vars}) as resp:
                json_data = await resp.json() if resp.status == 200 else None
                return (resp.status, json_data)

    async def get_anidata(self):
        # Primary query with year
        self.__vars = {'search': self.__ani_name, 'seasonYear': self.__original_year, 'perPage': 5}
        await rep.report(f"Trying AniList query: '{self.__ani_name}' (year {self.__original_year})", "info", log=False)
        status, data = await self.post_data()

        # FIXED: Guard against None data
        if data is None or not isinstance(data, dict):
            await rep.report(f"Bad API response for '{self.__ani_name}': status {status}, data {data}", "warning", log=False)
            media_list = []
        else:
            media_list = data.get('data', {}).get('Page', {}).get('media', [])
        
        if media_list:
            await rep.report(f"Found {len(media_list)} results for '{self.__ani_name}'", "info", log=False)
            return media_list

        # Fallback 1: Older years
        while status == 404 and self.__current_year > self.__original_year - 5:
            self.__update_vars()
            await asleep(1)
            await rep.report(f"404 → retrying '{self.__ani_name}' with year {self.__current_year}", "warning", log=False)
            status, data = await self.post_data()
            if data is None or not isinstance(data, dict):
                await rep.report(f"Bad fallback response: status {status}", "warning", log=False)
                media_list = []
            else:
                media_list = data.get('data', {}).get('Page', {}).get('media', [])
            if media_list:
                await rep.report(f"Found {len(media_list)} in fallback year {self.__current_year}", "info", log=False)
                return media_list

        # Fallback 2: No year, original query
        self.__vars = {'search': self.__ani_name, 'perPage': 5}
        await rep.report(f"Year fallback failed → no-year search for '{self.__ani_name}'", "warning", log=False)
        status, data = await self.post_data()
        if data is None or not isinstance(data, dict):
            await rep.report(f"Bad no-year response: status {status}", "warning", log=False)
            media_list = []
        else:
            media_list = data.get('data', {}).get('Page', {}).get('media', [])
        if media_list:
            await rep.report(f"No-year search success: {len(media_list)} results", "info", log=False)
            return media_list

        # Fallback 3: Normalized romaji (remove hyphens/spaces)
        normalized = re.sub(r'([a-zA-Z])-([a-zA-Z])', r'\1\2', self.__ani_name)  # Kotesashi-kun → Kotesashikun
        if normalized != self.__ani_name:
            self.__vars = {'search': normalized, 'perPage': 5}
            await rep.report(f"Trying normalized: '{normalized}'", "warning", log=False)
            status, data = await self.post_data()
            if data is None or not isinstance(data, dict):
                await rep.report(f"Bad normalized response: status {status}", "warning", log=False)
                media_list = []
            else:
                media_list = data.get('data', {}).get('Page', {}).get('media', [])
            if media_list:
                await rep.report(f"Normalized success: {len(media_list)} results", "info", log=False)
                return media_list

        await rep.report(f"Total failure for '{self.__ani_name}' → 0 results after all fallbacks", "error", log=False)
        return []

    async def get_anidata_by_id(self):
        self.__vars = {'id': int(self.__ani_name.split(':')[1]), 'perPage': 1}
        status, data = await self.post_data()
        if data is None or not isinstance(data, dict) or status != 200:
            return {}
        return data.get('data', {}).get('Page', {}).get('media', [{}])[0] or {}

async def search_anilist_multiple(query: str, max_results: int = 5):
    """Search AniList for multiple results (returns list)"""
    anilister = AniLister(query)
    media_list = await anilister.get_anidata()
    return media_list[:max_results]



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
