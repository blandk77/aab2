from calendar import month_name
from datetime import datetime
from random import choice
from asyncio import sleep as asleep
from aiohttp import ClientSession
from anitopy import parse
import re
from AnilistPython import Anilist


GENRES_EMOJI = {"Action": "👊", "Adventure": choice(['🪂', '🧗‍♀']), "Comedy": "🤣", "Drama": " 🎭", "Ecchi": choice(['💋', '🥵']), "Fantasy": choice(['🧞', '🧞‍♂', '🧞‍♀','🌗']), "Hentai": "🔞", "Horror": "☠", "Mahou Shoujo": "☯", "Mecha": "🤖", "Music": "🎸", "Mystery": "🔮", "Psychological": "♟", "Romance": "💞", "Sci-Fi": "🛸", "Slice of Life": choice(['☘','🍁']), "Sports": "⚽️", "Supernatural": "🫧", "Thriller": choice(['🥶', '🔪','🤯'])}


CAPTION_FORMAT = """
 <code>{title}</code>
<b>◇──◇──◇──◇──◇──◇──◇──◇</b>
<b>✦</b> <i>Genres:</i> <code>{genres}</code>
<b>✦</b> <i>Episode:</i> <code>{ep_no}</code>
<b>✦</b> <i>Audio:</i> <code>{audio_lang}</code>
<b>✦</b> <i>Subtitle:</i> <code>{sub_type}</code>
<b>◇──◇──◇──◇──◇──◇──◇──◇</b>
<blockquote expandable><b>Description:</b> {plot}</blockquote>
<blockquote><b>╭╌═╌═╌═╌══╌═╌═╌═╌═╌╮</b>          <b>✦</b> <b><i>Powered By ~</i></b> <i>{cred}</i>
<b>╰╌═╌═╌═╌═╌═╌═╌═╌══╌╯</b></blockquote>
"""



async def search_anilist_multiple(query: str, max_results: int = 5):
    """Used ONLY for /addschedule picker — searches AniList via AnilistPython"""
    try:
        anilist = Anilist()
        # Search anime (fuzzy, handles English/Romaji/Native)
        results = anilist.searchAnime(query, amount=max_results)
        
        if not results or len(results) == 0:
            from bot.core.reporter import rep
            await rep.report(f"AnilistPython: No results for '{query}'", "warning")
            return []

        formatted = []
        for res in results:
            formatted.append({
                "id": res.id,
                "title": {
                    "english": res.english_title or res.romaji_title,
                    "romaji": res.romaji_title,
                    "native": res.native_title
                },
                "status": res.status or "UNKNOWN",
                "seasonYear": res.release_date.year if res.release_date else None,
                "nextAiringEpisode": {
                    "episode": res.episodes or None,
                    "airingAt": None  # AnilistPython doesn't have next airing; use old method if needed
                },
                "coverImage": {"large": res.image_url or "https://via.placeholder.com/300x450"}
            })
        
        from bot.core.reporter import rep
        await rep.report(f"AnilistPython: Found {len(formatted)} results for '{query}'", "info")
        return formatted
        
    except Exception as e:
        from bot.core.reporter import rep
        await rep.report(f"AnilistPython error: {str(e)}", "error")
        return []

ANIME_GRAPHQL_QUERY = """
query ($id: Int, $search: String, $seasonYear: Int) {
  Media(id: $id, type: ANIME, format_not_in: [MOVIE, MUSIC, MANGA, NOVEL, ONE_SHOT], search: $search, seasonYear: $seasonYear) {
    id
    idMal
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
    endDate {
      year
      month
      day
    }
    season
    seasonYear
    episodes
    duration
    chapters
    volumes
    countryOfOrigin
    source
    hashtag
    trailer {
      id
      site
      thumbnail
    }
    updatedAt
    coverImage {
      large
    }
    bannerImage
    genres
    synonyms
    averageScore
    meanScore
    popularity
    trending
    favourites
    studios {
      nodes {
         name
         siteUrl
      }
    }
    isAdult
    nextAiringEpisode {
      airingAt
      timeUntilAiring
      episode
    }
    airingSchedule {
      edges {
        node {
          airingAt
          timeUntilAiring
          episode
        }
      }
    }
    externalLinks {
      url
      site
    }
    siteUrl
  }
}
"""

class AniLister:
    def __init__(self, anime_name: str, year: int = None) -> None:
        self.__api = "https://graphql.anilist.co"
        self.__ani_name = anime_name
        self.__ani_year = year
        self.__vars = {'search' : self.__ani_name, 'seasonYear': self.__ani_year}
    
    def __update_vars(self, year=True) -> None:
        if year:
            self.__ani_year -= 1
            self.__vars['seasonYear'] = self.__ani_year
        else:
            self.__vars = {'search' : self.__ani_name}
    
    async def post_data(self):
        async with ClientSession() as sess:
            async with sess.post(self.__api, json={'query': ANIME_GRAPHQL_QUERY, 'variables': self.__vars}) as resp:
                return (resp.status, await resp.json(), resp.headers)
        
    async def get_anidata(self):
        res_code, resp_json, res_heads = await self.post_data()
        while res_code == 404 and self.__ani_year > 2020:
            self.__update_vars()
            await rep.report(f"AniList Query Name: {self.__ani_name}, Retrying with {self.__ani_year}", "warning", log=False)
            res_code, resp_json, res_heads = await self.post_data()
        
        if res_code == 404:
            self.__update_vars(year=False)
            res_code, resp_json, res_heads = await self.post_data()
        
        if res_code == 200:
            return resp_json.get('data', {}).get('Media', {}) or {}
        elif res_code == 429:
            f_timer = int(res_heads['Retry-After'])
            await rep.report(f"AniList API FloodWait: {res_code}, Sleeping for {f_timer} !!", "error")
            await asleep(f_timer)
            return await self.get_anidata()
        elif res_code in [500, 501, 502]:
            await rep.report(f"AniList Server API Error: {res_code}, Waiting 5s to Try Again !!", "error")
            await asleep(5)
            return await self.get_anidata()
        else:
            await rep.report(f"AniList API Error: {res_code}", "error", log=False)
            return {}
    
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
            self.adata = await AniLister(ani_name, datetime.now().year).get_anidata()
            if self.adata:
                break

    @handle_logs
    async def get_id(self):
        if (ani_id := self.adata.get('id')) and str(ani_id).isdigit():
            return ani_id
            
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
        if anime_id := await self.get_id():
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
        
        return CAPTION_FORMAT.format(
            title=titles.get('english') or titles.get('romaji') or titles.get('native'),
            genres=", ".join(f"{GENRES_EMOJI.get(x, '')} {x}" for x in (self.adata.get('genres') or [])),
            ep_no=self.pdata.get("episode_number"),
            audio_lang=audio_lang,
            sub_type=sub_type,
            plot=plot,
            cred=Var.BRAND_UNAME
        )
