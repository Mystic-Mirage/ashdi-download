import asyncio
import re
from contextlib import suppress
from functools import wraps

import asyncclick as click
from aiohttp import ClientError, ClientSession
from asyncclick_option_group import RequiredMutuallyExclusiveOptionGroup, optgroup
from bs4 import BeautifulSoup
from ffmpeg.asyncio import FFmpeg


@click.command()
@optgroup.group(cls=RequiredMutuallyExclusiveOptionGroup)
@optgroup.option("-e", "--episode", metavar="URL", multiple=True)
@optgroup.option("-s", "--season", metavar="URL", multiple=True)
@click.option("-q", "--quality", type=int)
@click.option("-o", "--output-format", default="mp4")
async def cli(episode, season, quality, output_format):
    if episode:
        await download_multiple(download_episode, episode, quality, output_format)
    elif season:
        await download_multiple(download_season, season, quality, output_format)


def aiohttp_session(coro):
    @wraps(coro)
    async def wrapper(*args, session=None, **kwargs):
        if session:
            return await coro(*args, session=session, **kwargs)

        async with ClientSession() as session:
            return await coro(*args, session=session, **kwargs)

    return wrapper


@aiohttp_session
async def download_multiple(
    coro, urls, quality, output_format, *, session: ClientSession
):
    await asyncio.gather(
        *[coro(url, quality, output_format, session=session) for url in urls]
    )


async def get_player_url(url, *, session: ClientSession):
    async with session.get(url) as response:
        text = await response.text()

    bs = BeautifulSoup(text, "html.parser")
    if tag := bs.find("iframe", src=re.compile(r".*ashdi\.vip.*")):
        return tag["src"]


async def get_quality_url(url, *, session: ClientSession):
    async with session.get(url) as response:
        text = await response.text()

    bs = BeautifulSoup(text, "html.parser")
    pattern = re.compile(r'file:.*"(.*ashdi\.vip.*)"')
    tag = bs.find("script", string=pattern)
    return re.search(pattern, tag.text).group(1)


async def get_episode_url(url, quality, *, session: ClientSession):
    async with session.get(url) as response:
        text = await response.text()

    url = next(line for line in text.splitlines() if not line.startswith("#"))

    if quality:
        begin, _, end = url.rsplit("/", 2)
        url = "/".join([begin, str(quality), end])

    return url


async def download_playlist(url, output_format):
    _, name, _, _, _ = url.rsplit("/", 4)
    output = f"{name}.{output_format}"
    ffmpeg = FFmpeg().option("y").input(url).output(output, c="copy")
    await ffmpeg.execute()


async def download_episode(url, quality, output_format, *, session: ClientSession):
    with suppress(ClientError):
        if player_url := await get_player_url(url, session=session):
            quality_url = await get_quality_url(player_url, session=session)
            episode_url = await get_episode_url(quality_url, quality, session=session)
            await download_playlist(episode_url, output_format)


async def get_sub_urls(url, *, session: ClientSession):
    async with session.get(url) as response:
        text = await response.text()

    bs = BeautifulSoup(text, "html.parser")
    urls = [
        tag["href"]
        for tag in bs.find_all("a", href=lambda value: value.startswith(url))
    ]
    return urls


async def download_season(url, quality, output_format, *, session: ClientSession):
    urls = await get_sub_urls(url, session=session)
    await download_multiple(
        download_episode, urls, quality, output_format, session=session
    )


if __name__ == "__main__":
    cli()
