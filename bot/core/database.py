from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]
        self.__schedules = self.__db.schedules[Var.BOT_TOKEN.split(':')[0]]

    async def getAnime(self, ani_id):
        botset = await self.__animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        quals = (await self.getAnime(ani_id)).get(ep, {q: False for q in Var.QUALS})
        quals[qual] = True
        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': {ep: quals}},
            upsert=True
        )
        if post_id:
            await self.__animes.update_one(
                {'_id': ani_id},
                {'$set': {"msg_id": post_id}},
                upsert=True
            )
        # CLEANUP OLD EPISODES (keep only latest + current)
        existing = await self.getAnime(ani_id)
        for old_ep in list(existing.keys()):
            if old_ep.isdigit() and int(old_ep) < int(ep) - 1:  # keep previous one as buffer
                await self.__animes.update_one(
                    {'_id': ani_id},
                    {'$unset': {old_ep: ""}}
                )
  
    # === NEW SCHEDULE SYSTEM ===
    async def saveSchedule(self, name, rss_links, platform, audio_pref, custom_title, timestamp, file_path=None, episode_num=None, ani_data=None):
        doc = {
            '_id': str(hash(name + ''.join(rss_links))),  # unique
            'name': name,
            'rss_links': rss_links,
            'platform': platform,
            'audio_pref': audio_pref,   # Sub / Dual / None
            'custom_title': custom_title,
            'timestamp': timestamp,
            'file_path': file_path or None,
            'episode_num': episode or None,
            'ani_data': ani_data or {}
        }
        await self.__schedules.replace_one({'_id': doc['_id']}, doc, upsert=True)
        return doc['_id']

    async def getSchedule(self, sch_id):
        return await self.__schedules.find_one({'_id': sch_id})

    async def delSchedule(self, sch_id):
        result = await self.__schedules.delete_one({'_id': sch_id})
        return result.deleted_count > 0

    async def editScheduleAudio(self, sch_id, new_pref):
        result = await self.__schedules.update_one(
            {'_id': sch_id},
            {'$set': {'audio_pref': new_pref}}
        )
        return result.modified_count > 0

    async def listSchedules(self):
        return await self.__schedules.find().to_list(100)

    async def reboot(self):
        await self.__animes.drop()

db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
