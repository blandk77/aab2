# bot/__main__.py
import asyncio
from asyncio import create_subprocess_exec, all_tasks, sleep as asleep
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.filters import command, user
from os import path as ospath, execl, kill
from sys import executable
from signal import SIGKILL
from app import web_server
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import bot, Var, LOGS, ffQueue, ffLock, ffpids_cache, ff_queued
from bot.core.auto_animes import fetch_animes
from bot.core.func_utils import clean_up, new_task, editMessage
from bot.modules.up_posts import upcoming_animes

# event handlers can remain here
@bot.on_message(command('restart') & user(Var.ADMINS))
@new_task
async def restart_handler(client, message):
    rmessage = await message.reply('<i>Restarting...</i>')
    # shutdown scheduler safely if exists
    try:
        if globals().get("sch") and sch.running:
            sch.shutdown(wait=False)
    except Exception:
        LOGS.exception("Error shutting down scheduler during restart")

    await clean_up()
    if ffpids_cache:
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

async def restart_message_edit():
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
    global sch, bot_loop

    # START the client — this creates the event loop used by pyrogram
    await bot.start()
    bot_loop = bot.loop  # safe now

    # create scheduler bound to the running loop
    sch = AsyncIOScheduler(timezone="Asia/Kolkata", event_loop=bot_loop)

    # add job only if configured
    if Var.SEND_SCHEDULE:
        sch.add_job(upcoming_animes, "cron", hour=0, minute=30)

    # start scheduler
    sch.start()
    LOGS.info("Scheduler started successfully!")

    # post-restart message edit if any
    await restart_message_edit()

    LOGS.info('Auto Anime Bot Started! Running in SCHEDULE mode.')

    # start background tasks on the bot's loop
    bot_loop.create_task(queue_loop())
    bot_loop.create_task(fetch_animes())
    bot_loop.create_task(web_server())

    try:
        await idle()
    finally:
        LOGS.info('Auto Anime Bot Stopping...')
        # stop everything cleanly
        if sch:
            sch.shutdown(wait=False)
        await bot.stop()
        # cancel remaining tasks
        for task in list(all_tasks()):
            try:
                task.cancel()
            except Exception:
                pass
        await clean_up()
        LOGS.info('Finished AutoCleanUp !!')

if __name__ == '__main__':
    # Use asyncio.run to create and run the uvloop-compatible loop
    asyncio.run(main())
