from calendar import month_name    
from datetime import datetime    
from random import choice    
from asyncio import sleep as asleep    
from aiohttp import ClientSession    
from anitopy import parse    
import re    
import json    
    
from bot import Var, bot    
from .ffencoder import ffargs    
from .func_utils import handle_logs    
from .reporter import rep    
    
GENRES_EMOJI = {
    "Action": "👊", "Adventure": choice(['🪂', '🧗‍♀']), "Comedy": "🤣",
    "Drama": " 🎭", "Ecchi": choice(['💋', '🥵']), "Fantasy": choice(['🧞', '🧞‍♂', '🧞‍♀','🌗']),
    "Hentai": "🔞", "Horror": "☠", "Mahou Shoujo": "☯", "Mecha": "🤖", "Music": "🎸",
    "Mystery": "🔮", "Psychological": "♟", "Romance": "💞", "Sci-Fi": "🛸",
    "Slice of Life": choice(['☘','🍁']), "Sports": "⚽️", "Supernatural": "🫧",
    "Thriller": choice(['🥶', '🔪','🤯'])
}    
    
ANIME_GRAPHQL_QUERY = """    
query ($id: Int, $search: String, $seasonYear: Int, $perPage: Int) {    
  Page(perPage: $perPage) {    
    media(search: $search, type: ANIME, seasonYear: $seasonYear, sort: [SEARCH_MATCH, POPULARITY_DESC]) {    
      id    
      title { romaji english native }    
      type    
      format    
      status(version: 2)    
      description(asHtml: false)    
      startDate { year month day }    
      season    
      seasonYear    
      episodes    
      nextAiringEpisode { airingAt timeUntilAiring episode }    
      coverImage { large }    
      genres    
      averageScore    
      studios { nodes { name } }    
      isAdult    
      siteUrl    
    }    
  }    
}    
"""    

def clean_rss_title(raw_title: str) -> str:    
    """Robustly clean any filename for AniList search."""    
    # Remove common uploader tags
    raw_title = re.sub(r'[\[\(].*?[\]\)]', '', raw_title)  # Remove brackets
    for tag in ["ToonsHub", "VARYG", "Erai-raws", "SubsPlease", "Judas", "EMBER", "Bili", "Multi-Subs"]:
        raw_title = raw_title.replace(tag, "")    
    # Remove episode/quality patterns
    raw_title = re.sub(r'(S\d+E\d+|Ep\.?\s*\d+|\d+p|WEB-DL|AAC\d\.\d|H\.265|H\.264|DL|BILI|WEB|AVC|CR|DUAL|MSubs)', '', raw_title, flags=re.IGNORECASE)    
    # Remove extra characters
    raw_title = re.sub(r'[-–_]+', ' ', raw_title)    
    raw_title = re.sub(r'\s+', ' ', raw_title)    
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
                try:    
                    json_data = await resp.json()    
                except Exception as e:    
                    await rep.report(f"JSON parse error: {str(e)}", "warning", log=False)    
                    json_data = None    
                if resp.status != 200:    
                    await rep.report(f"AniList HTTP {resp.status}: {json_data.get('errors', [{}])[0].get('message', 'Unknown') if json_data else 'No body'}", "warning", log=False)    
                return resp.status, json_data    
    
    async def get_anidata(self):    
        has_year_in_query = re.search(r'\b(20\d{2})\b', self.__ani_name)    
        season_var = None if has_year_in_query else self.__original_year    
        self.__vars = {'search': self.__ani_name, 'perPage': 5}    
        if season_var:    
            self.__vars['seasonYear'] = season_var    
        status, data = await self.post_data()    
        media_list = data.get('data', {}).get('Page', {}).get('media', []) if data else []    
        return media_list or []    
    
    async def get_anidata_by_id(self):    
        self.__vars = {'id': int(self.__ani_name.split(':')[1]), 'perPage': 1}    
        status, data = await self.post_data()    
        if not data or not isinstance(data, dict) or status != 200:    
            return {}    
        return data.get('data', {}).get('Page', {}).get('media', [{}])[0] or {}    

async def search_anilist_multiple(query: str, max_results: int = 5):    
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
