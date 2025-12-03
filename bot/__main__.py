from asyncio import create_task, create_subprocess_exec, create_subprocess_shell, run as asyrun, all_tasks, gather, sleep as asleep
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.filters import command, user
from os import path as ospath, execl, kill
from sys import executable
from signal import SIGKILL
from bot import bot, Var, bot_loop, LOGS, ffQueue, ffLock, ffpids_cache, ff_queued, sch
from bot.core.func_utils import clean_up, new_task, editMessage
from bot.modules.up_posts import upcoming_animes
from bot.core.database import db
from bot.core.func_utils import getfeed
from anitopy import parse
from bot.core.auto_animes import get_animes
from bot.core.reporter import rep
import feedparser


@bot.on_message(command('restart') & user(Var.ADMINS))
@new_task
async def restart(client, message):
    rmessage = await message.reply('<i>Restarting...</i>')
    if 'sch' in globals() and sch.running:
        sch.shutdown(wait=False)
    await clean_up()
    if len(ffpids_cache) != 0: 
        for pid in ffpids_cache:
            try:
                LOGS.info(f"Process ID : {pid}")
                kill(pid, SIGKILL)
            except (OSError, ProcessLookupError):
                LOGS.error("Killing Process Failed !!")
                continue
    await (await create_subprocess_exec('python3', 'update.py')).wait()
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{rmessage.chat.id}\n{rmessage.id}\n")
    execl(executable, executable, "-m", "bot")

async def restart_check_missed():
    LOGS.info("Starting restart missed-episode check...")
    schedules = await db.listSchedules()
    checked = 0
    uploaded = 0

    for sch in schedules:
        rss_links = sch.get('rss_links', [])
        ani_id = sch.get('ani_id')
        custom_title = sch.get('custom_title')
        name = sch.get('name', 'Unknown Anime')

        if not rss_links or not ani_id:
            continue

        checked += 1

        for rss in rss_links:
            try:
                feed = feedparser.parse(rss.strip())
                
                if not feed or not hasattr(feed, 'entries') or not feed.entries:
                    LOGS.warning(f"Empty or invalid RSS during restart check: {rss}")
                    continue

                latest_entry = feed.entries[0]
                latest_title = latest_entry.title
                torrent_link = latest_entry.link

                
                parsed = parse(latest_title)
                episode = parsed.get("episode_number")
                if not episode:
                    continue

                if '1080p' not in latest_title.lower():
                    continue

                anime_data = await db.getAnime(ani_id)
                if anime_data and str(episode) in anime_data:
                    continue 

                LOGS.info(f"Restart: Found missed episode → {name} - Episode {episode}")
                await rep.report(f"Restart Recovery: Uploading {name} Episode {episode}", "info")

                
                sch_data = {
                    'custom_title': custom_title,
                    'platform': sch.get('platform'),
                    'audio_pref': sch.get('audio_pref'),
                    'rss_link': rss
                }

                await get_animes(
                    name=latest_title,
                    torrent=torrent_link,
                    force=True,
                    sch_data=sch_data
                )

                uploaded += 1
                await asleep(3)

            except Exception as e:
                LOGS.error(f"Error in restart_check_missed for RSS {rss}: {e}")
                continue

    LOGS.info(f"Restart check complete: {checked} schedules scanned, {uploaded} episodes recovered.")
    if uploaded == 0:
        LOGS.info("No missed episodes found.")


async def restart():
    if ospath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="<i>Restarted !</i>")
        except Exception as e:
            LOGS.error(e)

async def queue_loop():
    LOGS.info("Queue Loop Started !!")
    while True:
        if not ffQueue.empty():
            post_id = await ffQueue.get()
            await asleep(1.5)
            ff_queued[post_id].set()
            await asleep(1.5)
            async with ffLock:
                ffQueue.task_done()
        await asleep(10)

async def main():
    
    await bot.start()
    await restart()
    sch.start()
    LOGS.info('Scheduler started successfully!')

    if Var.SEND_SCHEDULE:
        sch.add_job(upcoming_animes, "cron", hour=0, minute=30)
        
    LOGS.info('Auto Anime Bot Started! Running in SCHEDULE mode.')
    await restart_check_missed()
    bot_loop.create_task(queue_loop())
    await idle()
    LOGS.info('Auto Anime Bot Stopped!')
    await bot.stop()
    sch.shutdown()
    for task in all_tasks:
        task.cancel()
    await clean_up()
    LOGS.info('Finished AutoCleanUp !!')
    
if __name__ == '__main__':
    bot_loop.run_until_complete(main())
