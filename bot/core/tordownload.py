from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, remove as aioremove, mkdir

from aiohttp import ClientSession
from torrentp import TorrentDownloader
from bot import LOGS
from bot.core.func_utils import handle_logs

class TorDownloader:
    def __init__(self, path="."):
        self.__downdir = path
        self.__torpath = "torrents/"
    
    @handle_logs
    async def download(self, torrent, name=None):
        # Support magnet
        if torrent.startswith("magnet:"):
            torp = TorrentDownloader(torrent, self.__downdir)
            await torp.start_download()
            return ospath.join(self.__downdir, name or torp._torrent_info._info.name())

        # Support direct .torrent file
        if torrent.endswith(".torrent"):
            torfile = await self.get_torfile(torrent)
            if not torfile:
                return None
            torp = TorrentDownloader(torfile, self.__downdir)
            await torp.start_download()
            await aioremove(torfile)
            return ospath.join(self.__downdir, torp._torrent_info._info.name())

        # Support Nyaa view link → convert to download
        if "nyaa.si/view/" in torrent:
            tor_id = torrent.split("/view/")[-1].split("#")[0].split("?")[0]
            torrent = f"https://nyaa.si/download/{tor_id}.torrent"
            torfile = await self.get_torfile(torrent)
            if not torfile:
                return None
            torp = TorrentDownloader(torfile, self.__downdir)
            await torp.start_download()
            await aioremove(torfile)
            return ospath.join(self.__downdir, torp._torrent_info._info.name())

        LOGS.error(f"Unsupported torrent link: {torrent}")
        return None

    @handle_logs
    async def get_torfile(self, url):
        if not await aiopath.isdir(self.__torpath):
            await mkdir(self.__torpath)
        
        tor_name = url.split('/')[-1]
        des_dir = ospath.join(self.__torpath, tor_name)
        
        async with ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    async with aiopen(des_dir, 'wb') as file:
                        async for chunk in response.content.iter_chunked(1024*1024):
                            await file.write(chunk)
                    return des_dir
        return None
