#modify addschedule and it's callback
from asyncio import sleep as asleep, gather    
from datetime import datetime, timedelta, timezone
from pyrogram.filters import command, private, user, regex    
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup,CallbackQuery    
from pyrogram.errors import FloodWait, MessageNotModified    
import feedparser
import re, time, os
from anitopy import parse
from bot.core.tordownload import TorDownloader
from bot import bot, bot_loop, Var, ani_cache, sch  
from bot.core.database import db    
from bot.core.func_utils import decode, is_fsubbed, get_fsubs, editMessage, sendMessage, new_task, convertTime, getfeed, download_via_torrent    
from bot.core.auto_animes import process_scheduled_anime, get_animes
from bot.core.reporter import rep    
from bot.core.text_utils import AniLister, TextEditor, search_anilist_multiple    
    
temp_schedule_data = {}    
    
@bot.on_message(command('start') & private)    
@new_task    
async def start_msg(client, message):    
    uid = message.from_user.id    
    from_user = message.from_user    
    txtargs = message.text.split()    
    temp = await sendMessage(message, "<i>Connecting..</i>")    
    if not await is_fsubbed(uid):    
        txt, btns = await get_fsubs(uid, txtargs)    
        return await editMessage(temp, txt, InlineKeyboardMarkup(btns))    
    if len(txtargs) <= 1:    
        await temp.delete()    
        btns = []    
        for elem in Var.START_BUTTONS.split():    
            try:    
                bt, link = elem.split('|', maxsplit=1)    
            except:    
                continue    
            if len(btns) != 0 and len(btns[-1]) == 1:    
                btns[-1].insert(1, InlineKeyboardButton(bt, url=link))    
            else:    
                btns.append([InlineKeyboardButton(bt, url=link)])    
        smsg = Var.START_MSG.format(first_name=from_user.first_name,    
                                    last_name=from_user.first_name,    
                                    mention=from_user.mention,     
                                    user_id=from_user.id)    
        if Var.START_PHOTO:    
            await message.reply_photo(    
                photo=Var.START_PHOTO,     
                caption=smsg,    
                reply_markup=InlineKeyboardMarkup(btns) if len(btns) != 0 else None    
            )    
        else:    
            await sendMessage(message, smsg, InlineKeyboardMarkup(btns) if len(btns) != 0 else None)    
        return    
    try:    
        arg = (await decode(txtargs[1])).split('-')    
    except Exception as e:    
        await rep.report(f"User : {uid} | Error : {str(e)}", "error")    
        await editMessage(temp, "<b>Input Link Code Decode Failed !</b>")    
        return    
    if len(arg) == 2 and arg[0] == 'get':    
        try:    
            fid = int(int(arg[1]) / abs(int(Var.FILE_STORE)))    
        except Exception as e:    
            await rep.report(f"User : {uid} | Error : {str(e)}", "error")    
            await editMessage(temp, "<b>Input Link Code is Invalid !</b>")    
            return    
        try:    
            msg = await client.get_messages(Var.FILE_STORE, message_ids=fid)    
            if msg.empty:    
                return await editMessage(temp, "<b>File Not Found !</b>")    
            nmsg = await msg.copy(message.chat.id, reply_markup=None)    
            await temp.delete()    
            if Var.AUTO_DEL:    
                async def auto_del(msg, timer):    
                    await asleep(timer)    
                    await msg.delete()    
                await sendMessage(message, f'<i>File will be Auto Deleted in {convertTime(Var.DEL_TIMER)}, Forward to Saved Messages Now..</i>')    
                bot_loop.create_task(auto_del(nmsg, Var.DEL_TIMER))    
        except Exception as e:    
            await rep.report(f"User : {uid} | Error : {str(e)}", "error")    
            await editMessage(temp, "<b>File Not Found !</b>")    
    else:    
        await editMessage(temp, "<b>Input Link is Invalid for Usage !</b>")    
    
    
@bot.on_message(command('pause') & private & user(Var.ADMINS))    
async def pause_fetch(client, message):    
    ani_cache['fetch_animes'] = False    
    await sendMessage(message, "`Successfully Paused Fetching Animes...`")    
    
@bot.on_message(command('resume') & private & user(Var.ADMINS))    
async def resume_fetch(client, message):    
    ani_cache['fetch_animes'] = True    
    await sendMessage(message, "`Successfully Resumed Fetching Animes...`")    
    
@bot.on_message(command('log') & private & user(Var.ADMINS))    
@new_task    
async def _log(client, message):    
    await message.reply_document("log.txt", quote=True)    
    
# ============ NEW SCHEDULE COMMANDS ============    
    
        
@bot.on_message(command('listschedule') & private & user(Var.ADMINS))    
@new_task    
async def list_schedules(client, message):    
    schedules = await db.listSchedules()    
    if not schedules:    
        return await sendMessage(message, "<b>No active schedules!</b>")    
    txt = "<b>Active Schedules:</b>\n\n"    
    for s in schedules:    
        dt = datetime.fromtimestamp(s['timestamp'])    
        txt += f"<b>ID:</b> <code>{s['_id']}</code>\n"    
        txt += f"<b>Name:</b> {s['name']}\n"    
        txt += f"<b>Time:</b> {dt.strftime('%Y-%m-%d %I:%M %p')} IST\n"    
        txt += f"<b>Audio:</b> {s.get('audio_pref') or 'Any'}\n"    
        txt += "────────────\n"    
    await sendMessage(message, txt)    
    
@bot.on_message(command('delschedule') & private & user(Var.ADMINS))    
@new_task    
async def del_schedule(client, message):    
    if len(args := message.text.split()) < 2:    
        return await sendMessage(message, "<b>Usage: /delschedule &lt;id&gt;</b>")    
    if await db.delSchedule(args[1]):    
        await sendMessage(message, "<b>Schedule deleted!</b>")    
    else:    
        await sendMessage(message, "<b>ID not found!</b>")    
    
@bot.on_message(command('editschedule') & private & user(Var.ADMINS))    
@new_task    
async def edit_schedule(client, message):    
    if len(args := message.text.split()) < 3:    
        return await sendMessage(message, "<b>Usage: /editschedule &lt;id&gt; &lt;Sub/Dual/None&gt;</b>")    
    sch_id, pref = args[1], args[2]    
    if pref not in ['Sub', 'Dual', 'None']:    
        return await sendMessage(message, "<b>Invalid preference!</b>")    
    new_pref = None if pref == 'None' else pref    
    if await db.editScheduleAudio(sch_id, new_pref):    
        await sendMessage(message, f"<b>Updated {sch_id} → {pref}</b>")    
    else:    
        await sendMessage(message, "<b>ID not found!</b>")    
    

@bot.on_message(command('addschedule') & private & user(Var.ADMINS))
@new_task
async def add_schedule(client, message):
    if len(message.command) < 2:
        return await message.reply(
            "<b>Usage:</b> <code>/addschedule &lt;rss_links&gt; | &lt;platform&gt; | &lt;audio&gt; | &lt;rename_title&gt; | &lt;anilist_search_title&gt;</code>\n\n"
            "<i>Example:</i>\n"
            "<code>/addschedule https://nyaa.si/?page=rss&q=[Erai-Raws]+One+Punch+Man|CR|Dual|One Punch Man S3|Sawaranaide Kotesashi-kun</code>\n\n"
            "<b>Bot will:</b> Catch up latest episode + schedule future ones"
        )

    parts = message.text.split(maxsplit=1)[1].split('|', 4)
    rss_raw = parts[0].strip()
    platform = parts[1].strip() if len(parts) > 1 and parts[1].lower() != 'none' else None
    audio_pref = parts[2].strip() if len(parts) > 2 and parts[2].lower() != 'none' else None
    rename_title = parts[3].strip() if len(parts) > 3 and parts[3].lower() != 'none' else None
    anilist_search = parts[4].strip() if len(parts) > 4 and parts[4].lower() != 'none' else None

    rss_links = [link.strip() for link in rss_raw.split(',') if link.strip()]
    if not rss_links:
        return await message.reply("<b>No valid RSS links!</b>")

    # Search AniList for picker (same as before)
    search_query = anilist_search or clean_rss_title((await getfeed(rss_links[0])).title) or rename_title or "Unknown Anime"
    results = await search_anilist_multiple(search_query)
    if not results:
        return await message.reply(f"<b>No AniList results for '{search_query}'</b>\n<i>Try exact title in last part.</i>")

    # Picker (same as before)
    buttons = []
    for res in results[:5]:
        title = res.get('title', {}).get('english') or res.get('title', {}).get('romaji') or "Unknown"
        year = res.get('seasonYear') or "N/A"
        status = res.get('status', 'Unknown').title()
        next_ep = res.get('nextAiringEpisode', {}).get('episode') or "N/A"
        btn_text = f"{title} ({year}) – {status}"
        if next_ep != "N/A":
            btn_text += f" | Ep {next_ep}"
        buttons.append([InlineKeyboardButton(btn_text[:64], callback_data=f"ani_{res['id']}")])

    markup = InlineKeyboardMarkup(buttons)
    picker_msg = await message.reply(
        f"<b>Found {len(results)} result(s) for '{search_query}':</b>\n\n<i>Click to schedule (catches latest + future episodes).</i>",
        reply_markup=markup
    )

    # Store temp data
    temp_schedule_data[picker_msg.id] = {
        'rss_links': rss_links,
        'platform': platform,
        'audio_pref': audio_pref,
        'rename_title': rename_title,
        'search_query': search_query,
        'user_id': message.from_user.id
    }

@bot.on_callback_query(filters.regex(r'^ani_'))
@new_task
async def handle_anilist_pick(client, query):
    ani_id = int(query.data.split('_')[1])

    temp_data = temp_schedule_data.get(query.message.id)
    if not temp_data:
        return await query.answer("Session expired! Run /addschedule again.", show_alert=True)

    # Fetch full data
    anilister = AniLister(f"id:{ani_id}")
    ani_data = await anilister.get_anidata()
    if not ani_data:
        return await query.answer("Failed to fetch details.", show_alert=True)

    next_air = ani_data.get('nextAiringEpisode')
    if not next_air:
        return await query.answer("No upcoming episodes.", show_alert=True)

    airing_time = datetime.fromtimestamp(next_air['airingAt'] + 300)  # +5 min buffer

    title = ani_data['title'].get('english') or ani_data['title'].get('romaji') or "Unknown"

    # Step 1: Schedule for NEXT episode
    sch_id = await db.saveSchedule(
        name=title,
        rss_links=temp_data['rss_links'],
        platform=temp_data['platform'],
        audio_pref=temp_data['audio_pref'],
        custom_title=temp_data['rename_title'],
        timestamp=airing_time.timestamp()
    )

    sch.add_job(
        process_scheduled_anime,
        'date',
        run_date=airing_time,
        args=(sch_id,),
        id=f"sch_{sch_id}"
    )

    # Step 2: CATCH-UP LATEST FROM RSS (if available)
    catch_up_msg = await query.message.reply("<b>Catching up latest episode...</b>")

    for rss in temp_data['rss_links']:
        feed = await getfeed(rss, 0)
        if feed:
            latest_entry = feed.entries[0] if feed.entries else None
            if latest_entry:
                latest_title = latest_entry.title
                parsed = parse(latest_title)
                latest_episode = parsed.get("episode_number")
                if latest_episode and int(latest_episode) < int(next_air['episode']):  # Latest < next → missed
                    # Check DB for latest episode
                    if not await db.getAnime(ani_id) or not ani_data.get(latest_episode):
                        # Upload latest (use your upload logic)
                        await catch_up_msg.edit(f"<b>Uploading missed Episode {latest_episode}...</b>")
                        await get_animes(
                            name=latest_title,
                            torrent=latest_entry.link,
                            force=True,
                            sch_data=temp_data
                        )
                        await catch_up_msg.edit(f"<b>Uploaded Episode {latest_episode}!</b>")
                    else:
                        await catch_up_msg.edit(f"<b>Episode {latest_episode} already uploaded.</b>")

    # Success message
    success_text = (
        f"<b>✅ Scheduled Successfully!</b>\n\n"
        f"<b>Anime:</b> <code>{title}</code>\n"
        f"<b>Next Episode:</b> {airing_time.strftime('%d %b %Y • %I:%M %p')} IST\n"
        f"<b>ID:</b> <code>{sch_id}</code>\n\n"
        "<i>Latest episode checked — ready for auto-upload!</i>"
    )

    await query.edit_message_text(success_text)

    poster_url = f"https://img.anili.st/media/{ani_id}"
    caption = (
        f"<b>Added to Schedule:</b>\n"
        f"<b>Title:</b> <code>{title}</code>\n\n"
        f"<i>RSS: {len(temp_data['rss_links'])} | Platform: {temp_data['platform'] or 'Any'} | "
        f"Audio: {temp_data['audio_pref'] or 'Any'} | Rename: {temp_data['rename_title'] or 'Auto'}</i>"
    )
    await query.message.reply_photo(photo=poster_url, caption=caption)

    # Cleanup
    temp_schedule_data.pop(query.message.id, None)
    await query.answer("Scheduled! Latest checked — use /listschedule.", show_alert=False)

@bot.on_message(command('addtask') & private & user(Var.ADMINS))
@new_task
async def add_task(client, message):
    if len(message.command) < 2:
        return await message.reply(
            "<b>Usage:</b> <code>/addtask &lt;link&gt; | &lt;optional_title&gt;</code>\n\n"
            "<i>Supported: RSS, Nyaa view, magnet, .torrent</i>\n"
            "<b>Runs immediately — full encode + poster + buttons</b>"
        )

    args = message.text.split(maxsplit=1)[1]
    parts = args.split('|', 1)
    link = parts[0].strip()
    custom_title = parts[1].strip() if len(parts) > 1 else None

    status = await message.reply("<b>Preparing upload...</b>")

    if "nyaa.si/?page=rss" in link:
        feed = feedparser.parse(link)
        if not feed.entries:
            return await status.edit("<b>Empty RSS!</b>")
        entry = feed.entries[0]
        torrent_link = entry.link
        filename = entry.title
    else:
        torrent_link = link
        filename = link.split("/")[-1].split("?")[0].replace(".torrent", "")

    await status.edit("<b>Parsing episode...</b>")

    parsed = parse(filename)
    anime_name = parsed.get("anime_title")
    episode = parsed.get("episode_number")
    if not anime_name or not episode:
        return await status.edit(f"<b>Failed to parse:</b>\n<code>{filename}</code>")

    episode = int(episode)

    await status.edit("<b>Loading AniList...</b>")
    editor = TextEditor(filename)
    await editor.load_anilist()
    ani_data = editor.adata

    if not ani_data:
        return await status.edit("<b>AniList not found!</b>")

    final_title = custom_title or (
        ani_data.get("title", {}).get("english") or
        ani_data.get("title", {}).get("romaji") or
        anime_name
    )

    await status.edit(f"<b>Downloading Episode {episode}...</b>")

    downloader = TorDownloader(path="/tmp/addtask")
    file_path = await downloader.download(torrent_link)

    if not file_path or not os.path.exists(file_path):
        return await status.edit("<b>Download failed!</b>")

    await status.edit(f"<b>Encoding & Uploading:</b> <code>{final_title} - E{episode:02d}</code>")
    
    await get_animes(
        name=filename,
        torrent=torrent_link,
        force=True,
        sch_data={
            'rss_link': link,
            'platform': "Manual Task",
            'audio_pref': None,
            'custom_title': final_title
        }
    )

    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
    except:
        pass

    await status.edit(f"<b>Uploaded Successfully!</b>\n<code>{final_title} - Episode {episode}</code>")
