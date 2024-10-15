import asyncio
import random
from urllib.parse import unquote
import uuid
from time import time

import aiohttp
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from datetime import datetime, timezone, timedelta
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.functions import account
from pyrogram.raw.types import InputBotAppShortName, InputNotifyPeer, InputPeerNotifySettings
from .agents import generate_random_user_agent
from bot.config import settings
from typing import Callable
import functools
from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers
import json


def error_handler(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            await asyncio.sleep(1)
    return wrapper

def get_youtube_answer(title):
    with open('youtube_answers.json', 'r') as file:
        data = json.load(file)
    
    for item in data['youtube_answers']:
        if item['title'].lower() == title.lower():
            return item['answer']
    
    return None

class Tapper:
    def __init__(self, tg_client: Client, proxy: str):
        self.tg_client = tg_client
        self.session_name = tg_client.name
        self.proxy = proxy
        self.tg_web_data = None
        self.tg_client_id = 0

    async def get_tg_web_data(self) -> str:
        
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)
            
            while True:
                try:
                    peer = await self.tg_client.resolve_peer('catsgang_bot')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fls}s")
                    await asyncio.sleep(fls + 3)
            
            ref_id = random.choices([settings.REF_ID, "rfFNTns6NAJuGvXDkG_tv"], weights=[85, 15], k=1)[0]
            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                app=InputBotAppShortName(bot_id=peer, short_name="join"),
                platform='android',
                write_allowed=True,
                start_param=ref_id
            ))

            auth_url = web_view.url
            tg_web_data = unquote(string=auth_url.split('tgWebAppData=', maxsplit=1)[1].split('&tgWebAppVersion', maxsplit=1)[0])

            me = await self.tg_client.get_me()
            self.tg_client_id = me.id
            
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return ref_id, tg_web_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error: {error}")
            await asyncio.sleep(delay=3)

    @error_handler
    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        response = await http_client.request(method, url or f"https://api.catshouse.club{endpoint or ''}", **kwargs)
        response.raise_for_status()
        return await response.json()
    
    @error_handler
    async def login(self, http_client, ref_id):
        user = await self.make_request(http_client, 'GET', endpoint="/user")
        if not user:
            logger.info(f"{self.session_name} | User not found. Registering...")
            await self.make_request(http_client, 'POST', endpoint=f"/user/create?referral_code={ref_id}")
            await asyncio.sleep(5)
            user = await self.make_request(http_client, 'GET', endpoint="/user")
        return user
    
    @error_handler
    async def send_cats(self, http_client):
        avatar_info = await self.make_request(http_client, 'GET', endpoint="/user/avatar")
        if avatar_info:
            attempt_time_str = avatar_info.get('attemptTime', None)
            if not attempt_time_str:
                time_difference = timedelta(hours=25)
            else:
                attempt_time = datetime.fromisoformat(attempt_time_str.replace('Z', '+00:00'))
                current_time = datetime.now(timezone.utc)
                next_day_3am = (attempt_time + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
                
                if current_time >= next_day_3am:
                    time_difference = timedelta(hours=25)
                else:
                    time_difference = next_day_3am - current_time

            if time_difference > timedelta(hours=24):
                response = await http_client.get(f"https://cataas.com/cat?timestamp={int(datetime.now().timestamp() * 1000)}", headers={
                    "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "accept-language": "en-US,en;q=0.9,ru;q=0.8",
                    "sec-ch-ua": "\"Not;A=Brand\";v=\"24\", \"Chromium\";v=\"128\"",
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": "\"macOS\"",
                    "sec-fetch-dest": "image",
                    "sec-fetch-mode": "no-cors",
                    "sec-fetch-site": "cross-site"
                })
                if not response and response.status not in [200, 201]:
                    logger.error(f"{self.session_name} | Failed to fetch image from cataas.com")
                    return None
                
                image_content = await response.read()
                    
                boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
                form_data = (
                    f'--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="photo"; filename="{uuid.uuid4().hex}.jpg"\r\n'
                    f'Content-Type: image/jpeg\r\n\r\n'
                ).encode('utf-8')
                
                form_data += image_content
                form_data += f'\r\n--{boundary}--\r\n'.encode('utf-8')
                
                headers = http_client.headers.copy()
                headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
                response = await self.make_request(http_client, 'POST', endpoint="/user/avatar/upgrade", data=form_data, headers=headers)
                if response:
                    return response.get('rewards', 0)
                else:
                    return None
            else:
                hours, remainder = divmod(time_difference.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.info(f"{self.session_name} | Time until next avatar upload: <y>{hours}</y> hours, <y>{minutes}</y> minutes, and <y>{seconds}</y> seconds")
                return None
    
    @error_handler
    async def get_tasks(self, http_client):
        return await self.make_request(http_client, 'GET', endpoint="/tasks/user", data={'group': 'cats'})
    
    
    @error_handler
    async def check_available(self, http_client):
        return await self.make_request(http_client, 'GET', endpoint="/exchange-claim/check-available")
    
    
    
    
    @error_handler
    async def done_tasks(self, http_client, task_id, type_):
        return await self.make_request(http_client, 'POST', endpoint=f"/tasks/{task_id}/{type_}", json={})
    
    
    @error_handler
    async def check_proxy(self, http_client: aiohttp.ClientSession) -> None:
        response = await self.make_request(http_client, 'GET', url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
        ip = response.get('origin', 'Site is not available')
        logger.info(f"{self.session_name} | Proxy IP: {ip}")
    
    @error_handler
    async def run(self) -> None:
        if settings.USE_RANDOM_DELAY_IN_RUN:
                random_delay = random.randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
                logger.info(f"{self.session_name} | Bot will start in <y>{random_delay}s</y>")
                await asyncio.sleep(random_delay)
                
        proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
        http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
        
        ref_id, init_data = await self.get_tg_web_data()
        if not init_data:
            
            if not http_client.closed:
                await http_client.close()
            if proxy_conn:
                if not proxy_conn.closed:
                    proxy_conn.close()
                    
            logger.error(f"{self.session_name} | Failed to login")
            return

        if self.proxy:
            await self.check_proxy(http_client=http_client)
        
        random_user_agent = generate_random_user_agent(device_type='android', browser_type='chrome')
        if settings.FAKE_USERAGENT:            
            http_client.headers['User-Agent'] = random_user_agent

        token_expiration = 0
        while True:
            try:
                if http_client.closed:
                    if proxy_conn:
                        if not proxy_conn.closed:
                            proxy_conn.close()

                    proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
                    http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
                    if settings.FAKE_USERAGENT:            
                        http_client.headers['User-Agent'] = random_user_agent
                
                current_time = time()
                if current_time >= token_expiration:
                    if (token_expiration != 0): # Чтобы не пугались, скрою от вас когда происходит первый запуск
                        logger.info(f"{self.session_name} | Token expired, refreshing...")
                    ref_id, init_data = await self.get_tg_web_data()
                    http_client.headers['Authorization'] = f"tma {init_data}"
                    user = await self.login(http_client=http_client, ref_id=ref_id)
                
                    if not user:
                        logger.error(f"{self.session_name} | Failed to login")
                        logger.info(f"{self.session_name} | Sleep <y>300s</y>")
                        await asyncio.sleep(delay=300)
                        continue
                    else:
                        logger.info(f"{self.session_name} | <y>Successfully logged in</y>")
                        token_expiration = current_time + 3600
                
                logger.info(f"{self.session_name} | User ID: <y>{user.get('id')}</y> | Telegram Age: <y>{user.get('telegramAge')}</y> | Points: <y>{user.get('totalRewards')}</y>")
                UserHasOgPass = user.get('hasOgPass', False)
                logger.info(f"{self.session_name} | User has OG Pass: <y>{UserHasOgPass}</y>")
                
                data_task = await self.get_tasks(http_client=http_client)
                if data_task is not None and data_task.get('tasks', {}):
                    for task in data_task.get('tasks'):
                        if task['completed'] is True:
                            continue
                        id = task.get('id')
                        type = task.get('type')
                        
                        if type in ['ACTIVITY_CHALLENGE', 'INVITE_FRIENDS', 'NICKNAME_CHANGE', 'TON_TRANSACTION', 'BOOST_CHANNEL']:
                            continue
                        
                        title = task.get('title')
                        reward = task.get('rewardPoints')
                        
                        type_=('check' if type in ['SUBSCRIBE_TO_CHANNEL'] else 'complete')
                        
                        if type == 'YOUTUBE_WATCH':
                            answer = get_youtube_answer(title)
                            if answer:
                                type_ += f'?answer={answer}'
                                logger.info(f"{self.session_name} | Answer found for <y>'{title}'</y>: {answer}")
                            else:
                                logger.info(f"{self.session_name} | Skipping task {id} - No answer available")
                                continue
                        
                        done_task = await self.done_tasks(http_client=http_client, task_id=id, type_=type_)
                        if done_task and (done_task.get('success', False) or done_task.get('completed', False)):
                            logger.info(f"{self.session_name} | Task <y>{title}</y> done! Reward: {reward}")
                            
                        await asyncio.sleep(random.randint(5, 7))
                else:
                    logger.error(f"{self.session_name} | No tasks")
                
                
            
                for _ in range(3 if UserHasOgPass else 1):
                    reward = await self.send_cats(http_client=http_client)
                    if reward:
                        logger.info(f"{self.session_name} | Reward from Avatar quest: <y>{reward}</y>")
                    await asyncio.sleep(random.randint(5, 7))
                   
                available_withdraw = await self.check_available(http_client=http_client)
                if available_withdraw:
                    if available_withdraw.get('isAvailable', False): 
                        logger.info(f"{self.session_name} | Available withdrawal: <y>True</y>")
                    else:
                        logger.info(f"{self.session_name} | Available withdrawal: <r>False</r>")
                
                await http_client.close()
                if proxy_conn:
                    if not proxy_conn.closed:
                        proxy_conn.close()
            
            except InvalidSession as error:
                raise error

            except Exception as error:
                logger.error(f"{self.session_name} | Unknown error: {error}")
                await asyncio.sleep(delay=3)
                
            sleep_time = random.randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
            logger.info(f"{self.session_name} | Sleep <y>{sleep_time}s</y>")
            await asyncio.sleep(delay=sleep_time)
            
            
            
            

async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client, proxy=proxy).run()
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
