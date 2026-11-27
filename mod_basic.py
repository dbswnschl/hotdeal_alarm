from .setup import *
from .model import ModelItem
from urllib.parse import parse_qs, urljoin, urlsplit
from lxml import html as lxml_html
import requests
from lxml.etree import ParserError
import time
from threading import Lock
from urllib3.util.retry import Retry
from urllib3.exceptions import InvalidHeader
from pywebpush import webpush, WebPushException
import os
import json
from tool import ToolNotify
import traceback

site_map = {
    'ppomppu': '뽐뿌',
    'clien': '클리앙',
    'ruriweb': '루리웹',
    'coolenjoy' : '쿨엔조이',
    'quasarzone' : '퀘이사존'
}
board_map = {
    'ppomppu': '뽐뿌게시판',
    'ppomppu4': '해외뽐뿌',
    'ppomppu8': '알리뽐뿌',
    'money': '재태크포럼',
    'allsell': '사고팔고',
    'jirum': '알뜰구매',
    '1020': '핫딜/예판 유저',
    '600004': '핫딜/예판 업체',
    'qb_saleinfo': '지름/할인정보'
}
site_board_map = {
    'ppomppu': ['ppomppu', 'ppomppu4', 'ppomppu8', 'money'],
    'clien': ['allsell', 'jirum'],
    'ruriweb': ['1020', '600004'],
    'coolenjoy' : ['jirum'],
    'quasarzone': ['qb_saleinfo']
}


PPOMPPU_INTERVAL = 5
PPOMPPU_DETAIL_LIMIT = 4
_ppomppu_lock = Lock()
_ppomppu_next_request = 0
_ppomppu_retry_at = 0


class PpomppuCooldown(Exception):
    pass


def ppomppu_page(session, path):
    global _ppomppu_next_request, _ppomppu_retry_at
    with _ppomppu_lock:
        now = time.monotonic()
        if now < _ppomppu_retry_at:
            raise PpomppuCooldown('server cooldown active')
        time.sleep(max(0, _ppomppu_next_request - now))
        _ppomppu_next_request = time.monotonic() + PPOMPPU_INTERVAL
        response = session.get(get_url_prefix('ppomppu') + path,
                               headers={'User-Agent': 'hotdeal-alarm/1.0'}, timeout=15)
        if response.status_code == 429:
            try:
                delay = Retry().get_retry_after(response)
            except InvalidHeader:
                delay = None
            delay = max(60, delay or 300)
            _ppomppu_retry_at = time.monotonic() + delay
            P.logger.warning('ppomppu HTTP 429: pausing requests for %s seconds', delay)
            raise PpomppuCooldown('server rate limit')
    response.raise_for_status()
    return lxml_html.fromstring(response.text)


def ppomppu_rows(page, board):
    rows = []
    for anchor in page.find_class('baseList-title'):
        link = urlsplit(anchor.get('href', ''))
        query = parse_qs(link.query)
        number = query.get('no', [''])[0]
        if (link.path in ('view.php', '/zboard/view.php') and query.get('id') == [board]
                and number.isdecimal()):
            rows.append(dict(site='ppomppu', board=board, title=anchor.text_content().strip(),
                             url=f'view.php?id={board}&no={number}'))
    return rows


def get_url_prefix(site_name):
    url_prefix = ''
    if site_name == 'ppomppu':
        url_prefix = 'https://www.ppomppu.co.kr/zboard/'
    elif site_name == 'clien':
        url_prefix = 'https://www.clien.net'
    elif site_name == 'ruriweb':
        url_prefix = ''
    elif site_name == 'coolenjoy':
        url_prefix = ''
    elif site_name == 'quasarzone':
        url_prefix = ''

    return url_prefix


BOARD_URLS = {
    'clien': {'allsell': 'https://www.clien.net/service/group/allsell',
              'jirum': 'https://www.clien.net/service/board/jirum'},
    'ruriweb': {board: f'https://bbs.ruliweb.com/market/board/{board}' for board in ('1020', '600004')},
    'coolenjoy': {'jirum': 'https://coolenjoy.net/bbs/jirum'},
    'quasarzone': {'qb_saleinfo': 'https://quasarzone.com/bbs/qb_saleinfo'},
}

TITLE_SELECTORS = {
    'clien': '//*[@data-role="list-title-text"]',
    'ruriweb': '//a[contains(@class,"subject_link") and not(ancestor::tr[contains(@class,"notice")])]',
    'coolenjoy': '//a[contains(@class,"na-subject")]',
    'quasarzone': '//p[contains(@class,"tit")]/a[@href]',
}

LINK_SELECTORS = {
    'clien': '//span[normalize-space()="구매링크"]/following-sibling::a | //article//div[@class="content"]//a[@class="url"]',
    'ruriweb': '//div[contains(@class,"source_url")]//a[@href]',
    'coolenjoy': '//a[contains(@href,"/bbs/link2.php") or contains(@href,"/bbs/link.php")]',
    'quasarzone': '//th[starts-with(normalize-space(),"링크")]/following-sibling::td//a[@href]',
}


def community_page(session, url):
    response = session.get(url, headers={'User-Agent': 'hotdeal-alarm/1.0'}, timeout=15)
    response.raise_for_status()
    return lxml_html.fromstring(response.content.decode('utf-8', errors='replace'))


def community_rows(page, site, board):
    base = BOARD_URLS[site][board]
    rows = {}
    for node in page.xpath(TITLE_SELECTORS[site]):
        anchor = node if node.tag == 'a' else node.getparent()
        href = anchor.get('href', '')
        parsed = urlsplit(urljoin(base, href))
        if parsed.hostname != urlsplit(base).hostname or not parsed.path.rsplit('/', 1)[-1].isdecimal():
            continue
        if site == 'quasarzone' and not parsed.path.startswith(f'/bbs/{board}/views/'):
            continue
        for count in node.find_class('num_reply'):
            count.drop_tree()
        label = node.find_class('ellipsis-with-reply-cnt')
        title = ' '.join((label[0] if label else node).text_content().split())
        url = href if site == 'clien' else urljoin(base, href)
        if title:
            rows[url] = dict(site=site, board=board, title=title, url=url)
    return list(rows.values())


def community_mall_url(page, site, url):
    for anchor in page.xpath(LINK_SELECTORS[site]):
        target = urljoin(url, anchor.get('href', ''))
        if site in ('coolenjoy', 'ruriweb'):
            label = (anchor.text or '').strip()
            if label.startswith(('https://', 'http://')) and not label.endswith(('...', '…')):
                target = label
        if target != url and urlsplit(target).scheme in ('https', 'http'):
            return target
    return ''


class ModuleBasic(PluginModuleBase):
    def __init__(self, P):
        super(ModuleBasic, self).__init__(P, name='basic',
                                          first_menu='setting', scheduler_desc="핫딜 알람")
        self.db_default = {
            f'db_version': '2.0',
            f'{self.name}_auto_start': 'False',
            f'{self.name}_interval': '1',
            f'{self.name}_db_delete_day': '7',
            f'{self.name}_db_auto_delete': 'False',
            f'{P.package_name}_item_last_list_option': '',
            f'notify_mode': 'always',
            'use_site_ppomppu': 'False',
            'use_site_clien': 'False',
            'use_board_ppomppu_ppomppu': 'False',
            'use_board_ppomppu_ppomppu4': 'False',
            'use_board_ppomppu_ppomppu8': 'False',
            'use_board_ppomppu_money': 'False',
            'use_board_clien_allsell': 'False',
            'use_board_clien_jirum': 'False',
            'use_site_ruriweb': 'False',
            'use_board_ruriweb_1020': 'False',
            'use_board_ruriweb_600004': 'False',
            'use_site_coolenjoy': 'False',
            'use_board_coolenjoy_jirum': 'False',
            'use_site_quasarzone': 'False',
            'use_board_quasarzone_qb_saleinfo': 'False',
            'use_hotdeal_alarm': 'False',
            'use_hotdeal_keyword_alarm': 'False',
            'use_hotdeal_keyword_alarm_dist' : 'False',
            'hotdeal_alarm_keyword': '',
            'alarm_message_template': '`{title}`\n{url}\n{mall_url}',
            'selenium_remote_address': '',
            'use_hotdeal_web_push' : 'True',
            'web_push_public_key' : '',
            'web_push_subscription' : '[]'
        }
        self.web_list_model = ModelItem

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        if sub == 'setting':
            arg['is_include'] = F.scheduler.is_include(
                self.get_scheduler_name())
            arg['is_running'] = F.scheduler.is_running(
                self.get_scheduler_name())
        if sub == 'list':
            arg = self.web_list_model.get_list()
        return render_template(f'{P.package_name}_{self.name}_{sub}.html', arg=arg, site_map=site_map, board_map=board_map, site_board_map=site_board_map)

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret': 'success'}
        if command == 'test':
            ret['status'] = 'warn'
            ret['title'] = '테스트'
            ret['data'] = '테스트 내용'
        return jsonify(ret)

    def scheduler_function(self):
        self.scrap_items()

    def scrap_detail(self):
        ret = {
            'status': 'success'
        }
        P.logger.info("scrap_details")
        budgets = {site: 2 for site in BOARD_URLS}
        items = ModelItem.get_non_shopping_mall_lsit()
        detail_budget = PPOMPPU_DETAIL_LIMIT
        for item in items:
            mall_url = ''
            if item.site_name == 'ppomppu':
                if detail_budget == 0:
                    continue
                detail_budget -= 1
                try:
                    page = ppomppu_page(requests, item.url)
                except PpomppuCooldown:
                    detail_budget = 0
                    continue
                except requests.RequestException as error:
                    P.logger.warning('ppomppu detail %s: %s', item.url, error)
                    continue
                links = page.xpath('//li[contains(@class, "topTitle-link")]/a[@href]')
                if links:
                    label = links[0].text_content().strip()
                    mall_url = label if label.startswith(('http://', 'https://')) and '...' not in label else links[0].get('href')
                item.mall_url = mall_url
                ModelItem.save(item)
                continue
            site = item.site_name
            if site not in BOARD_URLS or budgets[site] == 0:
                continue
            budgets[site] -= 1
            url = get_url_prefix(site) + item.url
            try:
                page = community_page(requests, url)
                item.mall_url = community_mall_url(page, site, url)
            except (requests.RequestException, ParserError, ValueError) as error:
                P.logger.warning('%s detail %s: %s', site, item.url, error)
                response = getattr(error, 'response', None)
                if response is not None and response.status_code in (404, 410):
                    item.mall_url = ''
                    ModelItem.save(item)
                elif response is None or response.status_code in (403, 429):
                    budgets[site] = 0
                continue
            ModelItem.save(item)
        return ret

    def scrap_items(self):
        ret = {
            'status': 'success',
            'data': []
        }
        P.logger.info("scrap_items")
        sess = requests.session()
        # get model settings.
        if P.ModelSetting.get('use_site_ppomppu') == 'True':
            boards = ['ppomppu', 'ppomppu4', 'ppomppu8', 'money']
            for board in boards:
                if P.ModelSetting.get(f'use_board_ppomppu_{board}') != 'True':
                    continue
                try:
                    page = ppomppu_page(sess, f'zboard.php?id={board}')
                    rows = ppomppu_rows(page, board)
                    if not rows:
                        raise ValueError('no board posts found')
                    ret['data'].extend(rows)
                except PpomppuCooldown:
                    ret['status'] = 'warning'
                    break
                except (requests.RequestException, ValueError) as error:
                    P.logger.warning('ppomppu list %s: %s', board, error)
                    ret['status'] = 'warning'

        for site, boards in BOARD_URLS.items():
            if P.ModelSetting.get(f'use_site_{site}') != 'True':
                continue
            for board, url in boards.items():
                if P.ModelSetting.get(f'use_board_{site}_{board}') != 'True':
                    continue
                try:
                    page = community_page(sess, url)
                    rows = community_rows(page, site, board)
                    if not rows:
                        raise ValueError('no board posts found')
                    ret['data'].extend(rows)
                except (requests.RequestException, ParserError, ValueError) as error:
                    P.logger.warning('%s list %s: %s', site, board, error)
                    ret['status'] = 'warning'

        for row in ret['data']:
            ModelItem.update({
                'site_name': row['site'],
                'board_name': row['board'],
                'title': row['title'].replace('</span>',''),
                'url':  row['url']
            })
        self.process_discord_data()
        return ret

    def process_discord_data(self):
        try:
            self.scrap_detail()
        except Exception as e:
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
        items = ModelItem.get_alarm_target_list()
        if items is None or len(items) == 0:
            return
        msg_template = P.ModelSetting.get('alarm_message_template')
        if msg_template is None or len(msg_template) == 0:
            return
        for item in items:
            if P.ModelSetting.get_bool('use_hotdeal_alarm') or P.ModelSetting.get_bool('use_hotdeal_keyword_alarm'):
                title = item.title.replace('&gt;', '>').replace('&lt;', '<')
                site = site_map[item.site_name]
                board = board_map[item.board_name]
                url = get_url_prefix(site_name=item.site_name)+item.url
                mall_url = item.mall_url if item.mall_url and len(
                    item.mall_url) > 0 else ''
                is_send = False
                is_dist_send = False
                is_web_push = P.ModelSetting.get_bool('use_hotdeal_web_push')

                keywords = P.ModelSetting.get('hotdeal_alarm_keyword').split(',')
                if P.ModelSetting.get_bool('use_hotdeal_alarm'):
                    is_send = True
                else:
                    is_send = False
                    is_dist_send = False
                for keyword in keywords:
                    if P.ModelSetting.get_bool('use_hotdeal_keyword_alarm'):
                        if len(keyword) > 0 and keyword.lower() in title.lower():
                            is_send = True
                    if P.ModelSetting.get_bool('use_hotdeal_keyword_alarm_dist'):
                        if len(keyword) > 0 and keyword.lower() in title.lower():
                            is_dist_send = True
                        

                if is_send is True:
                    msg = msg_template
                    msg = msg.replace('{title}', title).replace('{site}', site).replace(
                        '{board}', board).replace('{mall_url}', mall_url).replace('{url}', url)
                    ToolNotify.send_message(
                        msg, message_id=f"bot_{P.package_name}")
                    if is_web_push:
                        self.web_push({'message' : title, 'url':mall_url if len(mall_url) > 0 else url})
                if is_dist_send is True:
                    msg = msg_template
                    msg = msg.replace('{title}', title).replace('{site}', site).replace(
                        '{board}', board).replace('{mall_url}', mall_url).replace('{url}', url)
                    ToolNotify.send_message(
                        msg, message_id=f"bot_{P.package_name}_keyword")
                    if is_web_push:
                        self.web_push({'message' : title, 'url':mall_url if len(mall_url) > 0 else url})
            item.alarm_status = True
            ModelItem.save(item)
    def process_api(self, sub, req):
        result = ''
        if sub == 'web_push_init':
            if not os.path.exists('/data/web_push'):
                os.mkdir('/data/web_push')
            gen_key_result = os.popen("cd /data/web_push ; /usr/local/bin/vapid --applicationServerKey --gen").read()
            key = gen_key_result.split(' = ')[1].strip()
            P.logger.info(key)
            with open('/data/web_push/key.txt','w') as file:
                file.write(key)
            P.ModelSetting.set('web_push_public_key', key)
            result = json.dumps({'key' : key})

        elif sub =='web_push_subscribe':
            P.logger.info(req.get_json())
            subscription_info = req.get_json()
            web_push_subscription = json.loads(P.ModelSetting.get('web_push_subscription'))
            if type(web_push_subscription) != list:
                web_push_subscription = []
            if subscription_info not in  web_push_subscription:
                web_push_subscription.append(subscription_info)
            P.ModelSetting.set('web_push_subscription', json.dumps(web_push_subscription))
            return subscription_info

        elif sub == 'web_push' : 
            self.web_push(req.get_json())
            result = json.dumps({'status' : 'success'})
        elif sub == 'web_push_reset' :
            P.ModelSetting.set('web_push_subscription', '[]')
        return result
    def web_push(self, data):
        P.logger.info(data)
        infos = json.loads(P.ModelSetting.get('web_push_subscription'))
        result = []
        for info in infos:
            try:
                result.append(webpush(
                    subscription_info = info,
                    data = json.dumps(data),
                    vapid_private_key='/data/web_push/private_key.pem',
                    vapid_claims = {
                        'sub' : 'mailto:dbswnschl@gmail.com'
                    }
                ))
            except:
                P.logger.error(traceback.format_exc())
                continue