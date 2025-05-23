#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import json
import random
import string
import struct
from argparse import ArgumentParser
from typing import NamedTuple, Optional

import aiohttp
import anyio
from yarl import URL

DEFAULT_TIMEOUT = 20
SEMAPHORE = 64
INFO_HASH = "\x00"*20


class pingResult(NamedTuple):
    url: str
    success: bool = False
    error: Optional[str] = None

    def format(self) -> str:
        if self.success:
            return "SUCCESS"
        else:
            return f"FAILED: {self.error}"


async def ping_udp(url: URL, timeout: int) -> pingResult:
    assert url.host and url.port
    transaction_id = random.getrandbits(32)

    try:
        async with await anyio.create_connected_udp_socket(
            remote_host=url.host, remote_port=url.port
        ) as s:
            with anyio.fail_after(timeout):
                await s.send(struct.pack('!QII', 0x41727101980, 0, transaction_id))
                recv = await s.receive()
    except TimeoutError:
        return pingResult(url=str(url), error="connection timeout")
    except OSError as e:
        return pingResult(url=str(url), error=f"connection error: {e}")

    try:
        resp = struct.unpack('!IIQ', recv)
    except (struct.error):
        return pingResult(url=str(url), error="invalid response")

    if resp[0] != 0 or resp[1] != transaction_id:
        return pingResult(url=str(url), error="invalid response")

    return pingResult(url=str(url), success=True)


def rand_peerid(ua: str) -> str:
    return ua + "".join(
        random.choices(string.ascii_letters+string.digits, k=20-len(ua))
    )


http_headers = {
    'User-Agent': 'qBittorrent/4.2.5',
    'Accept-Encoding': 'gzip',
    'Connection': 'close',
}


http_params = {
    'info_hash': INFO_HASH,
    'peer_id': rand_peerid("-qB4250-"),
    'port': '6881',
    'uploaded': '0',
    'downloaded': '0',
    'left': '0',
    'compact': '1',
    'no_peer_id': '1',
    'event': 'stopped',
}


async def ping_http(url: URL, timeout: int) -> pingResult:
    try:
        async with aiohttp.request(
            "GET", url, params=http_params,
            headers=http_headers, skip_auto_headers=('Accept',),
            allow_redirects=False, raise_for_status=True,
            timeout=aiohttp.ClientTimeout(timeout)
        ) as resp:
            payload = await resp.read()
    except aiohttp.ClientConnectionError as e:
        return pingResult(url=str(url), error=f"connection error: {e}")
    except asyncio.TimeoutError:
        return pingResult(url=str(url), error="connection timeout")
    except aiohttp.ClientResponseError as e:
        return pingResult(
            url=str(url), error=f"invalid response: {e.status} {e.message}"
        )

    if not payload or payload[0] != 100:
        return pingResult(
            url=str(url),
            error=f"invalid response: {str(payload[:16] if len(payload) > 16 else payload)}"
        )
    return pingResult(url=str(url), success=True)


ws_payload = {
    'uploaded': 0,
    'downloaded': 0,
    'left': 0,
    'event': 'stopped',
    'action': 'announce',
    'info_hash': INFO_HASH,
    'peer_id': rand_peerid("-WW0108-"),
}


async def ping_ws(url: URL, timeout: int) -> pingResult:
    try:
        async with aiohttp.ClientSession(
            raise_for_status=True, timeout=aiohttp.ClientTimeout(timeout)
        ) as session, session.ws_connect(url) as ws:
            await ws.send_json(ws_payload)
            recv = await ws.receive(timeout)
    except aiohttp.ClientConnectionError as e:
        return pingResult(url=str(url), error=f"connection error: {e}")
    except asyncio.TimeoutError:
        return pingResult(url=str(url), error="connection timeout")
    except aiohttp.ClientResponseError as e:
        return pingResult(
            url=str(url), error=f"invalid response: {e.status} {e.message}"
        )

    try:
        resp = recv.json()
        if resp['action'] != 'announce':
            return pingResult(url=str(url), error=f"invalid response: {resp}")
    except (json.JSONDecodeError, TypeError, KeyError):
        return pingResult(
            url=str(url),
            error=f"invalid response: {str(recv.data[:16] if len(recv.data) > 16 else recv.data)}"
        )

    return pingResult(url=str(url), success=True)


async def ping(url_str: str, timeout: int) -> pingResult:
    print(f"PING {url_str} ...")
    url = URL(url_str)
    if not url.host or not url.port or url.query_string:
        return pingResult(url=url_str, error="invalid url")

    if url.scheme == 'udp':
        return await ping_udp(url, timeout)
    elif url.scheme in ('http', 'https'):
        return await ping_http(url, timeout)
    elif url.scheme in ('ws', 'wss'):
        return await ping_ws(url, timeout)
    else:
        return pingResult(url=url_str, error="invalid url")


async def ping_list(urls: list[str], timeout: int) -> list[pingResult]:
    semaphore = asyncio.Semaphore(SEMAPHORE)

    async def wrapped_ping(url):
        async with semaphore:
            return await ping(url, timeout)

    results = await asyncio.gather(*[wrapped_ping(url) for url in urls])
    return results


async def ping_single(url: str, timeout: int = DEFAULT_TIMEOUT) -> int:
    result = await ping(url, timeout)
    print("")
    print("[+]" if result.success else "[!]", result.format())
    return not result.success


def write_file(file_path: str, data: list[str]) -> None:
    with open(file_path, 'w') as f:
        f.write("\n\n".join(data))
        f.write("\n")


async def ping_file(
    infile: str, outfile: Optional[str] = None, quiet: bool = False, timeout: int = DEFAULT_TIMEOUT
) -> int:
    try:
        if infile.startswith('http://') or infile.startswith('https://'):
            print(f"Fetching {infile} ...")
            async with aiohttp.request('GET', infile, raise_for_status=True) as resp:
                assert resp.content_type == 'text/plain', \
                    f"invalid content-type: {resp.content_type}, expect text/plain"
                urls = [i.strip() for i in (await resp.text()).split("\n") if i.strip()]
        else:
            with open(infile, 'r') as f:
                urls = [i.strip() for i in f.readlines() if i.strip()]
    except (aiohttp.ClientError, OSError, AssertionError) as e:
        print("[!] ERROR:", e)
        return 2
    print(f"[+] Found {len(urls)} items\n")

    results = await ping_list(urls, timeout)
    succeeded = [i.url for i in results if i.success]
    if outfile is not None:
        write_file(outfile, succeeded)
    print("")
    for i in results:
        if not i.success:
            print(f"[!] {i.url}\n\t{i.format()}\n")
        elif i.success and not quiet:
            print(f"[+] {i.url}\n\t{i.format()}\n")
    print(
        "--- ping statistics ---\n"
        f"{len(urls)} trackers total, {len(succeeded)} available "
        f"({len(succeeded)/len(urls)*100:.2f}%)"
    )
    return not len(succeeded)


if __name__ == '__main__':
    parser = ArgumentParser(prog="trackerping")
    parser.add_argument('target', help="tracker url / trackerslist location")
    parser.add_argument('-l', dest='is_list', action='store_true',
                        help="treat target as a trackerslist")
    parser.add_argument('-q', '--quiet', action='store_true',
                        help="quiet mode (only show failed messages)")
    parser.add_argument('--timeout', '-t', type=int, required=False,
                        help="timeout in seconds", default=DEFAULT_TIMEOUT)
    parser.add_argument('--outfile', '-o', required=False,
                        help="output trackerslist file")
    args = parser.parse_args()

    if args.is_list:
        exit(asyncio.run(ping_file(args.target, args.outfile, args.quiet, args.timeout)))
    else:
        exit(asyncio.run(ping_single(args.target, args.timeout)))
