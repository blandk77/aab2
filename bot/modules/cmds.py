from asyncio import sleep as asleep, gather    
from datetime import datetime    
from pyrogram.filters import command, private, user, regex    
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup,CallbackQuery    
from pyrogram.errors import FloodWait, MessageNotModified    
    
from bot import bot, bot_loop, Var, ani_cache    
from bot.core.database import db    
from bot.core.func_utils import decode, is_fsubbed, get_fsubs, editMessage, sendMessage, new_task, convertTime, getfeed    
from bot.core.auto_animes import process_scheduled_anime    
from bot.core.reporter import rep    
from bot.core.text_utils import AniLister, search_anilist_multiple    
    
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
    if len(args := message.text.split(maxsplit=1)) <= 1:    
        return await sendMessage(message,     
            "<b>Usage:</b> /addschedule rss1,rss2|platform|audio|rename_title|anilist_search_title\n"    
            "<i>Example: https://nyaa.si/?page=rss&q=Blue+Lock|CR|Dual|Blue Lock S2|Sawaranaide Kotesashi-kun</i>\n"    
            "<i>Use 'None' for optional fields. If no anilist_search_title, auto-parses RSS.</i>")    
    
    parts = args[1].split('|', 4)  # Up to 5 parts now    
    rss_raw = parts[0].strip()    
    platform = parts[1].strip() if len(parts) > 1 and parts[1].lower() != 'none' else None    
    audio_pref = parts[2].strip() if len(parts) > 2 and parts[2].lower() != 'none' else None    
    rename_title = parts[3].strip() if len(parts) > 3 and parts[3].lower() != 'none' else None    
    anilist_search = parts[4].strip() if len(parts) > 4 and parts[4].lower() != 'none' else None    
    
    rss_links = [link.strip() for link in rss_raw.split(',') if link.strip()]    
    if not rss_links:    
        return await sendMessage(message, "<b>No valid RSS links!</b>")    
    
    # Determine search query    
    if anilist_search:    
        search_query = anilist_search    
    else:    
        # Auto-parse RSS title cleanly    
        feed = await getfeed(rss_links[0])    
        if not feed:    
            return await sendMessage(message, "<b>First RSS invalid!</b>")    
        search_query = clean_rss_title(feed.title) or rename_title or "Unknown Anime"    
        
    # Log the query for debugging    
    await rep.report(f"AniList search query: '{search_query}' for RSS: {rss_raw[:50]}...", "info")    
    
    # Search AniList    
    results = await search_anilist_multiple(search_query)    
    if not results:    
        await rep.report(f"AniList empty for '{search_query}'", "warning")  # Now logs!    
        return await sendMessage(message,     
            f"<b>No AniList results for '{search_query}'</b>\n"    
            f"<i>Try providing exact anilist_search_title like 'Sawaranaide Kotesashi-kun'</i>")    
    
    # Build buttons    
    buttons = []    
    for res in results[:5]:    
        title = res.get('title', {}).get('english') or res.get('title', {}).get('romaji') or "Unknown"    
        year = res.get('seasonYear', 'N/A')    
        status = res.get('status', 'Unknown')    
        next_ep = res.get('nextAiringEpisode', {}).get('episode', 'N/A')    
        btn_text = f"{title} ({year}) – {status}"    
        if next_ep != 'N/A':    
            btn_text += f" | Ep {next_ep}"    
        buttons.append([InlineKeyboardButton(btn_text[:60], callback_data=f"ani_{res['id']}")])    
    
    markup = InlineKeyboardMarkup(buttons)    
    picker_text = f"<b>Found {len(results)} results for '{search_query}':</b>\n\n<i>Click to schedule. Logs: {len(results)} hits.</i>"    
    msg = await sendMessage(message, picker_text, markup)    
    
    # Store temp data    
    temp_schedule_data[msg.id] = {    
        'rss_links': rss_links,    
        'platform': platform,    
        'audio_pref': audio_pref,    
        'rename_title': rename_title,  # For filename    
        'search_query': search_query    
}    
        
# ============ CALLBACK HANDLER FOR PICKER ============    
@bot.on_callback_query(regex(r'^ani_'))    
@new_task    
async def handle_anilist_pick(client: CallbackQuery):    
    data = client.data    
    ani_id = int(data.split('_')[1])    
    
    # Get full data by ID    
    anilister = AniLister(f"id:{ani_id}")    
    ani_data = await anilister.get_anidata_by_id()  # New method below    
    if not ani_data:    
        return await client.answer("Failed to fetch details — try again!", show_alert=True)    
    
    # Get message & temp data    
    msg = client.message    
    temp_data = temp_schedule_data.get(msg.id)    
    if not temp_data:    
        return await client.answer("Session expired — restart /addschedule!", show_alert=True)    
    
    # Schedule it    
    next_air = ani_data.get('nextAiringEpisode')    
    if not next_air:    
        return await client.answer("No upcoming episode — pick another!", show_alert=True)    
    
    airing_time = datetime.fromtimestamp(next_air['airingAt'] + 300)  # +5min    
    sch_id = await db.saveSchedule(    
        name=ani_data['title']['english'] or ani_data['title']['romaji'],    
        rss_links=temp_data['rss_links'],    
        platform=temp_data['platform'],    
        audio_pref=temp_data['audio_pref'],    
        custom_title=temp_data['custom_title'],    
        timestamp=airing_time.timestamp()    
    )    
    
    sch.add_job(process_scheduled_anime, 'date', run_date=airing_time, args=(sch_id,), id=f"sch_{sch_id}")    
    
    # Edit picker to success    
    success_text = f"<b>✅ Scheduled Successfully!</b>\n\n<b>Anime:</b> {ani_data['title']['english'] or ani_data['title']['romaji']}\n<b>Next Ep:</b> {airing_time.strftime('%Y-%m-%d %I:%M %p')} IST\n<b>ID:</b> <code>{sch_id}</code>"    
    await editMessage(msg, success_text)    
    
    # Send new message with poster    
    poster_url = f"https://img.anili.st/media/{ani_id}"    
    caption = f"<b>Added to Schedule:</b>\n{ani_data.get('title', {}).get('english', 'N/A')}\n\n<i>RSS: {len(temp_data['rss_links'])} | Platform: {temp_data['platform'] or 'Any'} | Audio: {temp_data['audio_pref'] or 'Any'} | Rename: {temp_data['custom_title'] or 'Auto'}</i>"    
    await client.message.reply_photo(photo=poster_url, caption=caption)    
    
    # Cleanup temp    
    del temp_schedule_data[msg.id]    
    await client.answer("Scheduled! Check /listschedule.", show_alert=False)
