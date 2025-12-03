#modify get_anime to send post after downloading the file
from asyncio import gather, create_task, sleep as asleep, Event
from os import path as ospath, remove as osremove
from aiofiles.os import remove as aioremove
from time import time
from datetime import datetime
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import BadRequest
from bot import bot, Var, ani_cache, ffQueue, ffLock, ff_queued, sch, bot_loop
from .tordownload import TorDownloader
from .database import db
from json import loads as jloads
from .func_utils import getfeed, mediainfo, editMessage, sendMessage, convertBytes, encode
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep
from traceback import format_exc

btn_formatter = {'1080':'1080p', '720':'720p', '480':'480p', '360':'360p'}

async def process_scheduled_anime(sch_id):
    sch_data = await db.getSchedule(sch_id)
    if not sch_data:
        return

    start_time = time()
    max_duration = 6 * 3600  # 6 hours max
    retry_interval = 120     # 2 min base

    while time() - start_time < max_duration:
        found_valid = False
        for rss_link in sch_data['rss_links']:
            info = await getfeed(rss_link, 0)
            if not info:
                continue

            title = info.title
            torrent = info.link

            # Skip Batch/Movie
            if "[Batch]" in title or "Movie" in title or not TextEditor(title).pdata.get("episode_number"):
                await rep.report(f"Skipped Batch/Movie: {title}", "warning")
                await db.delSchedule(sch_id)
                return

            # Platform filter (optional)
            if sch_data['platform'] and sch_data['platform'] not in title:
                continue

            # Channel duplicate check
            ep_no = TextEditor(title).pdata.get("episode_number")
            search_name = sch_data['custom_title'] or sch_data['name']
            search_query = f'"{search_name}" "Episode: {ep_no}"'
            try:
                msgs = await bot.search_messages(Var.MAIN_CHANNEL, query=search_query, limit=1)
                if msgs:
                    await rep.report(f"Already uploaded: {title}", "info")
                    await db.delSchedule(sch_id)
                    return
            except BadRequest:
                pass

            # Download
            dl_path = await TorDownloader("./downloads").download(torrent, title)
            if not dl_path or not ospath.exists(dl_path):
                continue

            # Mediainfo check
            try:
                minfo_json = (await mediainfo(dl_path, get_json=True))
                tracks = minfo_json['media']['track']
            except:
                await aioremove(dl_path)
                continue

            video_tracks = [t for t in tracks if t['@type'] == 'Video']
            audio_tracks = [t for t in tracks if t['@type'] == 'Audio']
            text_tracks = [t for t in tracks if t['@type'] == 'Text']

            # HEVC skip
            if any('HEVC' in t.get('Format', '') or 'x265' in t.get('CodecID', '') for t in video_tracks):
                await rep.report(f"Skipped HEVC: {title}", "warning")
                await aioremove(dl_path)
                continue

            # English subs REQUIRED
            has_eng_sub = any('eng' in t.get('Language', '').lower() for t in text_tracks)
            if not has_eng_sub:
                await rep.report(f"No English subs: {title} – retrying...", "warning")
                await aioremove(dl_path)
                await asleep(retry_interval + 10)
                continue

            sub_type = "Multi-Sub" if len(text_tracks) > 1 else "English"

            # Audio check
            langs = [t.get('Language', '').lower() for t in audio_tracks]
            original = any(l in ['jpn', 'chi', 'kor'] for l in langs)
            has_eng_audio = 'eng' in langs
            is_sub = len(audio_tracks) == 1 and original
            is_dual = len(audio_tracks) == 2 and original and has_eng_audio

            if len(audio_tracks) > 2 or not (is_sub or is_dual):
                await rep.report(f"Invalid audio tracks: {title}", "warning")
                await aioremove(dl_path)
                continue

            audio_type = "Dual" if is_dual else "Sub"
            audio_lang = next((l.upper() for l in langs if l in ['jpn', 'chi', 'kor']), "Japanese")
            if is_dual:
                audio_lang += " + English"

            # Audio preference logic
            if sch_data['audio_pref'] == 'Dual' and not is_dual:
                await rep.report(f"Dual not found: {title} – waiting...", "info")
                await aioremove(dl_path)
                await asleep(retry_interval + 10)
                continue
            if sch_data['audio_pref'] == 'Sub' and is_dual:
                # Prefer Sub if explicitly asked
                await rep.report(f"Dual found but Sub preferred – skipping", "info")
                await aioremove(dl_path)
                continue

            # VALID RELEASE FOUND
            found_valid = True
            await get_animes(title, torrent, force=True, sch_data=sch_data,
                           dl_path=dl_path, audio_lang=audio_lang, sub_type=sub_type, audio_type=audio_type)
            await db.delSchedule(sch_id)
            return

        if not found_valid:
            await asleep(retry_interval + 10)  # rate limit

    await rep.report(f"TIMEOUT after 6h: {sch_data['name']} – No valid release", "error")
    await db.delSchedule(sch_id)


async def get_animes(name, torrent, force=False, sch_data=None):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id, ep_no = aniInfo.adata.get('id'), aniInfo.pdata.get("episode_number")
        if not ani_id or not ep_no:
            return

        if ani_id in ani_cache['completed'] and not force:
            return
        if ani_id not in ani_cache['ongoing']:
            ani_cache['ongoing'].add(ani_id)

        # FIXED 5: Skip non-1080p
        if '1080p' not in name.lower():
            await rep.report(f"Skipped (not 1080p): {name}", "warning")
            return

        # Check if already uploaded
        anime_data = await db.getAnime(ani_id)
        if anime_data and str(ep_no) in anime_data:
            return

        await rep.report(f"New Episode → {name}", "info")

        # Download first
        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"**Downloading:**\n`{name}`")
        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await editMessage(stat_msg, "**Download Failed!**")
            return

        # NOW detect audio/sub from file
        minfo_json = await mediainfo(dl, get_json=True)
        minfo = jloads(minfo_json)['media']['track']

        audio_tracks = [t for t in minfo if t['@type'] == 'Audio']
        text_tracks = [t for t in minfo if t['@type'] == 'Text']

        audio_langs = [t.get('Language', '').lower() for t in audio_tracks]
        sub_langs = [t.get('Language', '').lower() for t in text_tracks]

        is_dual = len(audio_tracks) >= 2 and 'eng' in audio_langs and any(x in audio_langs for x in ['jpn', 'ja', 'jp'])
        has_eng_sub = any('eng' in l for l in sub_langs)

        if not has_eng_sub:
            await editMessage(stat_msg, "**Skipped: No English Subtitles**")
            await aioremove(dl)
            return

        audio_lang = "Japanese + English" if is_dual else "Japanese"
        sub_type = "Multi-Sub" if len(text_tracks) > 1 else "English"
        audio_type = "Dual" if is_dual else "Sub"

        await editMessage(stat_msg, f"**Detected:**\nAudio: {audio_lang}\nSub: {sub_type}\n\n**Encoding...**")

        # FIXED: Use correct poster for current season
        season_num = aniInfo.pdata.get("anime_season")
        if isinstance(season_num, list):
            season_num = season_num[-1]
        season_year = aniInfo.adata.get("seasonYear")

        # Try to get season-specific poster (Anilist sometimes has different ID per season)
        poster_url = await aniInfo.get_poster()
        if season_num and int(season_num) > 1:
            try:
                from AnilistPython import Anilist
                anilist = Anilist()
                search_name = f"{aniInfo.pdata.get('anime_title')} Season {season_num}"
                alt_id = anilist.get_anime_id(search_name)
                if alt_id and alt_id != ani_id:
                    poster_url = f"https://img.anili.st/media/{alt_id}"
            except:
                pass  # fallback to main poster

        # NOW send post with CORRECT caption + poster
        caption = await aniInfo.get_caption(
            audio_lang=audio_lang,
            sub_type=sub_type
        )

        post_msg = await bot.send_photo(
            Var.MAIN_CHANNEL,
            photo=poster_url,
            caption=caption
        )

        # Encoding & Upload
        post_id = post_msg.id
        ffEvent = Event()
        ff_queued[post_id] = ffEvent
        if ffLock.locked():
            await editMessage(stat_msg, "**Queued for encoding...**")
        await ffQueue.put(post_id)
        await ffEvent.wait()

        await ffLock.acquire()
        btns = []

        for qual in Var.QUALS:
            custom_title = sch_data.get('custom_title') if sch_data else None
            filename = await aniInfo.get_upname(
                qual=qual,
                custom_title=custom_title,
                audio_type=audio_type
            )

            await editMessage(stat_msg, f"**Encoding {qual}p...**")

            out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            if not out_path:
                ffLock.release()
                continue

            await editMessage(stat_msg, f"**Uploading {qual}p...**")
            msg = await TgUploader(stat_msg).upload(out_path, qual)

            link = f"https://t.me/{(await bot.get_me()).username}?start=get-{msg.id * abs(Var.FILE_STORE)}"
            btn_text = f"{btn_formatter[qual]} - {convertBytes(msg.document.file_size)}"

            if len(btns) > 0 and len(btns[-1]) == 1:
                btns[-1].insert(1, InlineKeyboardButton(btn_text, url=link))
            else:
                btns.append([InlineKeyboardButton(btn_text, url=link)])

            await editMessage(post_msg, caption=caption, reply_markup=InlineKeyboardMarkup(btns))
            await db.saveAnime(ani_id, ep_no, qual, post_id)
            bot_loop.create_task(extra_utils(msg.id, out_path))

        ffLock.release()
        await stat_msg.delete()
        await aioremove(dl)
        ani_cache['completed'].add(ani_id)

    except Exception as e:
        await rep.report(f"get_animes error: {e}\n{format_exc()}", "error")
        
async def extra_utils(msg_id, out_path):
    msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)

    if Var.BACKUP_CHANNEL != 0:
        for chat_id in Var.BACKUP_CHANNEL.split():
            await msg.copy(int(chat_id))
            
    # MediaInfo, ScreenShots, Sample Video ( Add-ons Features )
