"""Read public release metadata; never execute downloaded code."""
import json,re,urllib.request,urllib.error
from app_version import VERSION,REPOSITORY

def version_tuple(value):
    if not re.fullmatch(r'v?\d+\.\d+\.\d+',value):raise ValueError('不支持的版本号')
    return tuple(map(int,value.lstrip('v').split('.')))

def check_update():
    url='https://api.github.com/repos/'+REPOSITORY+'/releases/latest'
    request=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'WechatReplyAssistant/'+VERSION})
    try:
        with urllib.request.urlopen(request,timeout=12) as response:release=json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code==404:raise ValueError('尚无公开正式版本，或仓库尚未公开') from None
        raise ValueError('检查更新失败：GitHub HTTP '+str(exc.code)) from None
    except (OSError,ValueError):raise ValueError('无法连接 GitHub，请稍后重试') from None
    tag=release.get('tag_name','');newer=version_tuple(tag)>version_tuple(VERSION)
    return {'current':VERSION,'latest':tag,'available':newer,
            'url':'https://github.com/'+REPOSITORY+'/releases/tag/'+tag,
            'notes':str(release.get('body',''))[:10000]}
