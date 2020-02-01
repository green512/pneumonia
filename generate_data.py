# -*- coding: utf-8 -*-
import re
from collections import defaultdict
import json
import requests
import datetime
import schedule
import time


def load_amap_cities():
    return dict([line.strip().split() for line in open('adcodes', encoding='utf8').readlines()])


amap_code_to_city = load_amap_cities()
#print(amap_code_to_city)
amap_city_to_code = {v: k for k, v in amap_code_to_city.items()}
amap_short_city_to_full_city = {k[0:2]: k for k in amap_city_to_code}


def load_dxy_data():
    url = 'https://3g.dxy.cn/newh5/view/pneumonia'
    raw_html = requests.get(url).content.decode('utf8')
    match = re.search('window.getAreaStat = (.*?)}catch', raw_html)
    raw_json = match.group(1)
    result = json.loads(raw_json, encoding='utf8')
    return result


def load_tx_data():
    url = 'https://view.inews.qq.com/g2/getOnsInfo?name=disease_h5'
    data = json.loads(requests.get(url).json()['data'])
    #print(data)
    return data


def normalize_city_name(dxy_province_name, dxy_city_name):
    # 忽略部分内容
    ignore_list = ['外地来京人员', '未知']
    if dxy_city_name in ignore_list:
        return ''

    # 手动映射
    # 高德地图里没有两江新区，姑且算入渝北
    manual_mapping = {'巩义': '郑州市', '满洲里': '呼伦贝尔市', '固始县': '信阳市', '阿拉善': '阿拉善盟','两江新区':'渝北区',
                      '第七师': '塔城地区', '第八师石河子': '石河子市'}
    if manual_mapping.get(dxy_city_name):
        return manual_mapping[dxy_city_name]

    # 名称规则
    # 例如 临高县 其实是市级
    if dxy_city_name[-1] in ['市', '县', '盟']:
        normalized_name = dxy_city_name
    elif dxy_province_name == '重庆市' and dxy_city_name[-1] == '区':
        normalized_name = dxy_city_name
    elif dxy_province_name == '北京市':
        normalized_name = dxy_city_name 
        if dxy_city_name[-1] != '区': normalized_name = dxy_city_name + '区'
        return normalized_name
        #print(normalized_name)
    else:
        normalized_name = dxy_city_name + '市'
    if normalized_name in amap_city_to_code:
        return normalized_name

    # 前缀匹配
    # adcodes 里面的规范市名，出了 张家口市/张家界市，阿拉善盟/阿拉尔市 外，前两个字都是唯一的
    # cat adcodes|cut -d' ' -f2|cut -c1-2|sort|uniq -c |sort -k2n
    # 所以可以用前两个字
    normalized_name = amap_short_city_to_full_city.get(dxy_city_name[0:2], '')
    if normalized_name != dxy_city_name:
      print('fuzz map', dxy_province_name, dxy_city_name, 'to', normalized_name)
    return normalized_name


def get_confirmed_count_dxy():
    confirmed_count = defaultdict(int)
    dead_count = defaultdict(int)
    for p in load_dxy_data():
        dxy_province_name = p['provinceName']
        if dxy_province_name in ['香港', '澳门', '台湾']:
            code = amap_city_to_code[dxy_province_name]
            confirmed_count[code] = p['confirmedCount']
            dead_count[code] = p['deadCount']
            continue
        if dxy_province_name in ['上海市', '天津市']:
            code = amap_city_to_code[dxy_province_name]
            confirmed_count[code] = p['confirmedCount']
            dead_count[code] = p['deadCount']
            #continue
        if dxy_province_name in ['西藏自治区']:
            code = '540100'
            confirmed_count[code] = p['confirmedCount']
            dead_count[code] = p['deadCount']
            continue
        if dxy_province_name in ['北京市']:
            code = amap_city_to_code[dxy_province_name]
            confirmed_count[code] = p['confirmedCount']
            dead_count[code] = p['deadCount']
        for c in p["cities"]:
            dxy_city_name = c["cityName"]
            normalized_name = normalize_city_name(
                dxy_province_name, dxy_city_name)
            if normalized_name != '':
                # 丁香园有重复计算，县级市和地级市重复，如满洲里。因此用累加。TODO 是不是该累加？
                code = amap_city_to_code[normalized_name]
                confirmed_count[code] = c["confirmedCount"]
                dead_count[code] = c['deadCount']
    return confirmed_count, dead_count


def get_confirmed_count_tx():
    confirmed_count = defaultdict(int)
    dead_count = defaultdict(int)
    for item in load_tx_data():
        if item['areaTree']['country'] != '中国':
            continue
        if item['area'] in ['香港', '澳门', '台湾']:
            province_name = item['area']
            code = amap_city_to_code[province_name]
            #province_name = item['area'] + '省'
            confirmed_count[code] += item['confirm']
            dead_count[code] += item['dead']
            continue
        if item['area'] in [ '上海', '天津']:
            province_name = item['area'] + '市'
            code = amap_city_to_code[province_name]
            confirmed_count[code] += item['confirm']
            dead_count[code] += item['dead']
            continue
        if item['area'] in [ '北京']:
            province_name = item['area'] + '市'
            code = amap_city_to_code[province_name]
            confirmed_count[code] += item['confirm']
            dead_count[code] += item['dead']
        normalized_name = normalize_city_name(item['area'], item['city'])
        if normalized_name != '':
            code = amap_city_to_code[normalized_name]
            confirmed_count[code] += item["confirm"]
            dead_count[code] += item["dead"]
    return confirmed_count, dead_count


def count_to_color(confirm, suspect):
    # 颜色含义同丁香园
    if confirm > 1000:
        return '#430c0e'
    if confirm > 100:
        return '#73181B'
    if confirm >= 10:
        return '#E04B49'
    if confirm > 0:
        return '#F08E7E'
    if suspect > 0:
        return '#F2D7A2'
    return '#FFFFFF'


def write_result(result):
    writer = open('confirmed_data.js', 'w', encoding='utf8')
    writer.write('const LAST_UPDATE = "')
    writer.write(datetime.datetime.now(datetime.timezone(
        datetime.timedelta(hours=8))).strftime('%Y.%m.%d-%H:%M:%S'))
    writer.write('"; \r\n')
    writer.write("const DATA = ")
    json.dump(result, writer, indent='  ', ensure_ascii=False)
    writer.close()

def catch_daily():
    """抓取每日确诊和死亡数据"""

    url = 'https://view.inews.qq.com/g2/getOnsInfo?name=wuwei_ww_cn_day_counts&callback=&_=%d'%int(time.time()*1000)
    data = json.loads(requests.get(url=url).json()['data'])
    data.sort(key=lambda x:x['date'])

    date_list = list() # 日期
    confirm_list = list() # 确诊
    suspect_list = list() # 疑似
    dead_list = list() # 死亡
    heal_list = list() # 治愈
    for item in data:
        month, day = item['date'].split('.')
        date_list.append(datetime.datetime.strptime('2020-%s-%s'%(month, day), '%Y-%m-%d'))
        confirm_list.append(int(item['confirm']))
        suspect_list.append(int(item['suspect']))
        dead_list.append(int(item['dead']))
        heal_list.append(int(item['heal']))

    return date_list, confirm_list, suspect_list, dead_list, heal_list

def write_res(date_list, confirm_list, suspect_list, dead_list, heal_list):
    writer = open('2019nCov_data.csv', 'w', encoding='utf8')
    writer.write('date_list, confirm_list, suspect_list, dead_list, heal_list')
    writer.write(' \r\n')
    for i in range(len(date_list)):
        writer.write(date_list[i].strftime("%Y-%m-%d")+', ')
        writer.write('%d,%d,%d,%d \r\n' % (confirm_list[i],suspect_list[i],dead_list[i],heal_list[i]))    
    writer.close()
    writer = open('2019nCov_data.js', 'w', encoding='utf8')
    writer.write('const LAST_UPDATE = "')
    writer.write(datetime.datetime.now(datetime.timezone(
        datetime.timedelta(hours=8))).strftime('%Y.%m.%d-%H:%M:%S'))
    writer.write('"; \r')
    date_str=list()
    confirm_str=list()
    suspect_str=list()
    for x in date_list:
        date_str.append("'"+x.strftime("%m-%d")+"'")
    confirm_str=[u'确诊数']+confirm_list
    suspect_str=[u'疑似数']+suspect_list
    dead_str=[u'死亡数']+dead_list
    heal_str=[u'治愈数']+heal_list

    date_str_=[u'date_list']+date_str[1:len(date_str)-1]
    confirm_str_=[u'新增确诊数']
    suspect_str_=[u'新增疑似数']
    dead_str_=[u'新增死亡数']
    heal_str_=[u'新增治愈数']

    for i in range(len(confirm_list)-2):
        confirm_str_.append(confirm_list[i+1]-confirm_list[i])
        suspect_str_.append(suspect_list[i+1]-suspect_list[i])
        dead_str_.append(dead_list[i+1]-dead_list[i])
        heal_str_.append(heal_list[i+1]-heal_list[i])
    print(str(date_str_)+", \r")

    writer.write("const DATA_2019 = [")
    writer.write("['date_list',"+",".join(tuple(date_str[0:len(date_str)-1]))+"], \r") 
    writer.write(str(confirm_str[0:len(date_str)])+", \r") 
    writer.write(str(suspect_str[0:len(date_str)])+", \r") 
    writer.write(str(dead_str[0:len(date_str)])+", \r") 
    writer.write(str(heal_str[0:len(date_str)])) 
    writer.write("] \r")   
    writer.write("const DATA_2019_ = [")
    writer.write(str(date_str_)+", \r") 
    writer.write(str(confirm_str_)+", \r") 
    writer.write(str(suspect_str_)+", \r") 
    writer.write(str(dead_str_)+", \r") 
    writer.write(str(heal_str_)) 
    writer.write("] \r")   
    writer.close()

def plot_daily():
    """绘制每日确诊和死亡数据"""

    date_list, confirm_list, suspect_list, dead_list, heal_list = catch_daily() # 获取数据
    write_res(date_list, confirm_list, suspect_list, dead_list, heal_list)

def main():
    now = datetime.datetime.now()
    ts = now.strftime('%Y-%m-%d %H:%M:%S')
    
    #confirmed_count, dead_count = get_confirmed_count_tx()
    confirmed_count, dead_count = get_confirmed_count_dxy()
    result = {}
    for code in amap_code_to_city:
        # 现在数据源的疑似都是 0 了
        result[code] = {'confirmedCount': confirmed_count[code],
                        'cityName': amap_code_to_city[code],
                        'deadCount': dead_count[code],
                        'color': count_to_color(confirmed_count[code], dead_count[code])}
    write_result(result)
    print('do func time :',ts)


if __name__ == '__main__':
    main()
    plot_daily()
    #清空任务
    schedule.clear()
    #创建一个按秒间隔执行任务
    schedule.every(15).minutes.do(main)  
    schedule.every(30).minutes.do(plot_daily)   
    while True:
        schedule.run_pending()
    
