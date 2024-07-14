from .setup import *
from .model import ModelItem
import requests
import re
import time
import cloudscraper
from pywebpush import webpush, WebPushException
import html
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
        regex = None
        items = ModelItem.get_non_shopping_mall_lsit()
        for item in items:
            mall_url = ''
            if item.site_name == 'ppomppu':
                regex = r'div class=wordfix>링크: \<a .+\>(?P<mall_url>.+)\</a\>'
            elif item.site_name == 'clien':
                regex = r'구매링크</span>.+>(?P<mall_url>.+)</a>'
            elif item.site_name == 'ruriweb':
                regex = r'<div class=\"source_url\">원본출처.+<a href=\".+\">(?P<mall_url>.+)</a>'
            elif item.site_name == 'coolenjoy':
                regex = r'alt=\"관련링크\">\s+<strong>(?P<mall_url>.+)</strong>'
            elif item.site_name == 'quasarzone':
                regex = r'<th>링크</th>\s+<td><a href=\".+\"\s+>(?P<mall_url>.+)</a>'
            if regex:
                if item.site_name == 'quasarzone':
                    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'desktop': False})
                    getdata = scraper.get(get_url_prefix(item.site_name) + item.url)
                else:
                    sess = requests.session()
                    getdata = sess.get(get_url_prefix(item.site_name) + item.url)

                find_result = re.compile(regex).search(getdata.text)
                if find_result:
                    mall_url = find_result.groupdict().get('mall_url', '')
            item.mall_url = html.unescape(mall_url)
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
            regex = r'title\" href=\"(?P<url>.+?)\"\s?>.+>(?P<title>.+)</span></a>'
            for board in boards:
                if P.ModelSetting.get(f'use_board_ppomppu_{board}') == 'True':

                    getdata = sess.get(
                        f'https://www.ppomppu.co.kr/zboard/zboard.php?id={board}')
                    matches = re.finditer(regex, getdata.text, re.MULTILINE)
                    for matchNum, match in enumerate(matches, start=1):
                        new_obj = match.groupdict()
                        new_obj['site'] = 'ppomppu'
                        new_obj['board'] = board
                        ret['data'].append(new_obj)

        if P.ModelSetting.get('use_site_clien') == 'True':
            boards = ['allsell', 'jirum']

            for board in boards:
                if board == 'allsell':
                    regex = r' class=\"list_subject\" href=\"(?P<url>.+?)\" .+\s+.+\s+.+?data-role=\"list-title-text\"\stitle=\"(?P<title>.+)\"\>'
                    url = f'https://www.clien.net/service/group/{board}'
                elif board == 'jirum':
                    regex = r'<span class=\"list_subject\" data-role=\"cut-string\" title=\"(?P<title>.+)\">\s+<a href=\"(?P<url>.+?)\"\s'
                    url = f'https://www.clien.net/service/board/{board}'

                if P.ModelSetting.get(f'use_board_clien_{board}') == 'True':
                    getdata = sess.get(url)
                    matches = re.finditer(regex, getdata.text, re.MULTILINE)
                    for matchNum, match in enumerate(matches, start=1):
                        new_obj = match.groupdict()
                        new_obj['site'] = 'clien'
                        new_obj['board'] = board
                        ret['data'].append(new_obj)

        if P.ModelSetting.get('use_site_ruriweb') == 'True':
            boards = ['1020', '600004']
            for board in boards:
                regex = r'<a class=\"deco\" href=\"(?P<url>.+)\"\>(?P<title>.+)</a>'
                url = f'https://bbs.ruliweb.com/market/board/{board}'
                if P.ModelSetting.get(f'use_board_ruriweb_{board}') == 'True':
                    getdata = sess.get(url)
                    matches = re.finditer(regex, getdata.text, re.MULTILINE)
                    for matchNum, match in enumerate(matches, start=1):
                        new_obj = match.groupdict()
                        new_obj['site'] = 'ruriweb'
                        new_obj['board'] = board
                        ret['data'].append(new_obj)

        if P.ModelSetting.get('use_site_coolenjoy') == 'True':
            boards = ['jirum']
            for board in boards:
                regex = r'<td class=\"td_subject\">\s+<a href=\"(?P<url>.+)\">\s+(?:<font color=.+?>)?(?P<title>.+?)(?:</font>)?\s+<span class=\"sound_only\"'
                url = f'https://coolenjoy.net/bbs/{board}'
                if P.ModelSetting.get(f'use_board_coolenjoy_{board}') == 'True':
                    getdata = sess.get(url)
                    matches = re.finditer(regex, getdata.text, re.MULTILINE)
                    for matchNum, match in enumerate(matches, start=1):
                        new_obj = match.groupdict()
                        new_obj['site'] = 'coolenjoy'
                        new_obj['board'] = board
                        ret['data'].append(new_obj)

        if P.ModelSetting.get('use_site_quasarzone') == 'True':
            boards = ['qb_saleinfo']
            scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'desktop': False})
            for board in boards:
                regex = r'<p class=\"tit\">\s+<a href=\"(?P<url>.+)\"\s+class=.+>\s+.+\s+(?:<span class=\"ellipsis-with-reply-cnt\">)?(?P<title>.+?)(?:</span>)'
                url = f'https://quasarzone.com/bbs/{board}'
                if P.ModelSetting.get(f'use_board_quasarzone_{board}') == 'True':
                    getdata = scraper.get(url)
                    matches = re.finditer(regex, getdata.text, re.MULTILINE)
                    for matchNum, match in enumerate(matches, start=1):
                        new_obj = match.groupdict()
                        new_obj['site'] = 'quasarzone'
                        new_obj['board'] = board
                        new_obj['url'] = 'https://quasarzone.com' + new_obj['url'] if new_obj['url'].startswith('/') else new_obj['url']
                        ret['data'].append(new_obj)

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