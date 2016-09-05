# -*- coding: utf-8 -*-
#
# -----------------------------------------------------------------------------------
# Copyright (c) Microsoft Open Technologies (Shanghai) Co. Ltd.  All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
# -----------------------------------------------------------------------------------

import sys
from client.enum import LoginProvider

sys.path.append("..")
reload(sys)
sys.setdefaultencoding('utf-8')

import time
from datetime import datetime, timedelta
import re

import json
import requests
import markdown
from flask_login import login_required, login_user, LoginManager, current_user
from flask import Response, render_template, request, g, redirect, make_response, session, url_for, abort

from client import app, Context
from client.constants import LOGIN_PROVIDER
from client.user.login_manager import login_manager_helper
from client.functions import get_config, safe_get_config, get_now
from client.log import log

API_HACKATHON = "/api/hackathon"
API_HACKATHON_LIST = "/api/hackathon/list"
API_HACKATHON_TEMPLATE = "/api/hackathon/template"
API_HACKATHON_REGISTRATION = "/api/user/registration"
API_TEAM_MEMBER_LIST = "/api/team/member/list"
API_TEAM_USER = "/api/user/team/list"
API_TEAM = "/api/team"
API_MY_TEAM = "/api/team/my"

login_manager = LoginManager()
login_manager.init_app(app)


def __oauth_meta_content():
    return {
        LOGIN_PROVIDER.WEIBO: get_config('login.weibo.meta_content'),
        LOGIN_PROVIDER.QQ: get_config('login.qq.meta_content')
    }


def __oauth_api_key():
    return {
        LOGIN_PROVIDER.WEIBO: get_config('login.weibo.client_id'),
        LOGIN_PROVIDER.QQ: get_config('login.qq.client_id'),
        LOGIN_PROVIDER.LIVE: get_config('login.live.client_id'),
        LOGIN_PROVIDER.WECHAT: get_config("login.wechat.client_id"),
        LOGIN_PROVIDER.GITHUB: get_config('login.github.client_id')
    }


def render(template_name_or_list, **context):
    ui = ""
    if current_user and current_user.is_authenticated():
        ui = " for user '%s'" % current_user.name
    log.debug("rendering template '%s' %s" % (template_name_or_list, ui))
    return render_template(template_name_or_list,
                           meta_content=__oauth_meta_content(),
                           oauth_api_key=__oauth_api_key(),
                           **context)


def __login_failed(provider):
    if provider == "mysql":
        error = "Login failed. username or password invalid."
        return render("/superadmin.html", error=error)
    return redirect("/")


def __login(provider):
    try:
        user_with_token = login_manager_helper.login(provider)

        if user_with_token is None:
            return __login_failed(provider)

        log.info("login successfully:" + repr(user_with_token))

        token = user_with_token["token"]
        login_user(user_with_token["user"])
        session["token"] = token
        if session.get("return_url") is not None:
            resp = make_response(redirect(session["return_url"]))
            session["return_url"] = None
        else:
            resp = make_response(redirect(url_for("index")))
        resp.set_cookie('token', token)
        return resp
    except Exception as ex:
        log.error(ex)
        return __login_failed(provider)


def __date_serializer(date):
    return long((date - datetime(1970, 1, 1)).total_seconds() * 1000)


def __get_api(url, headers=None, **kwargs):
    default_headers = {"content-type": "application/json"}
    if headers is not None and isinstance(headers, dict):
        default_headers.update(headers)
    try:
        req = requests.get(get_config("hackathon-api.endpoint") + url, headers=default_headers, **kwargs)
        resp = req.content
        return json.loads(resp)
    except Exception as e:
        abort(500, 'API Service is not yet open')


@app.context_processor
def utility_processor():
    def get_now_serialized():
        return __date_serializer(get_now())

    def activity_progress(starttime, endtime):
        return ((int(time.time() * 1e3) - starttime) * 1.0 / (endtime - starttime + 0.0001) * 1.0) * 100

    def get_provides(value):
        prs = []
        if value is None:
            return ""
        else:
            value = int(value)
            if value == 255:
                return ""
            else:
                if value & LoginProvider.live == LoginProvider.live:
                    prs.append("live")
                if value & LoginProvider.github == LoginProvider.github:
                    prs.append("github")
                if value & LoginProvider.weibo == LoginProvider.weibo:
                    prs.append("weibo")
                if value & LoginProvider.qq == LoginProvider.qq:
                    prs.append("qq")
                if value & LoginProvider.wechat == LoginProvider.wechat:
                    prs.append("wechat")
                if value & LoginProvider.alauda == LoginProvider.alauda:
                    prs.append("alauda")
        return ",".join(prs)

    return dict(get_now=get_now_serialized, activity_progress=activity_progress, get_provides=get_provides)


@app.template_filter('mkHTML')
def to_markdown_html(text):
    if text is None:
        text = ""
    return markdown.markdown(text)


@app.template_filter('stripTags')
def strip_tags(html):
    if html is None:
        html = ""
    return re.sub(r"</?\w+[^>]*>", "", html)


@app.template_filter('limitTo')
def limit_to(text, limit=100):
    if text is None:
        text = ""
    text = unicode(text)
    return text[0:limit]


@app.template_filter('deadline')
def deadline(endtime):
    end_date = datetime.fromtimestamp(endtime / 1e3)
    if end_date > datetime.now():
        return (end_date - datetime.now()).days
    else:
        return "--"


week = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


@app.template_filter('date')
def to_datetime(datelong, fmt=''):
    if fmt:
        date = datetime.fromtimestamp(datelong / 1e3)
        fmt = re.compile('%a', re.I).sub(week[date.weekday()], fmt)
        return date.strftime(fmt)
    else:
        return datetime.fromtimestamp(datelong / 1e3).strftime("%y/%m/%d")


@login_manager.user_loader
def load_user(id):
    return login_manager_helper.load_user(id)


@login_manager.unauthorized_handler
def unauthorized_log():
    return render("/login.html",
                  error=None,
                  providers=safe_get_config("login.provider_enabled",
                                            ["github", "qq", "wechat", "weibo", "live", "alauda"]))


@app.before_request
def make_session_permanent():
    g.user = current_user
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=safe_get_config("login.session_valid_time_minutes", 60))


@app.errorhandler(401)
def custom_401(e):
    return render("/login.html", error=None)


@app.errorhandler(404)
def page_not_found(e):
    return render('/404.html'), 404


@app.errorhandler(500)
def server_error(e):
    return render('error.html', error=e), 500


# js config
@app.route('/config.js')
def js_config():
    resp = Response(response="var CONFIG=%s" % json.dumps(get_config("javascript")),
                    status=200,
                    mimetype="application/javascript")
    return resp


@app.route('/github')
def github_login():
    return __login(LOGIN_PROVIDER.GITHUB)


@app.route('/weibo')
def weibo_login():
    return __login(LOGIN_PROVIDER.WEIBO)


@app.route('/wechat')
def wechat_login():
    return __login(LOGIN_PROVIDER.WECHAT)


@app.route('/qq')
def qq_login():
    return __login(LOGIN_PROVIDER.QQ)


@app.route('/live')
def live_login():
    return __login(LOGIN_PROVIDER.LIVE)


@app.route('/alauda')
def alauda_login():
    return __login(LOGIN_PROVIDER.ALAUDA)


@app.route('/')
@app.route('/index')
def index():
    landing_page_visited = request.cookies.get('ohplpv')
    if not landing_page_visited:
        return redirect("/landing")

    empty_items = {
        "items": []
    }
    newest_hackathons = __get_api(API_HACKATHON_LIST, {"token": session.get("token")},
                                  params={"page": 1, "per_page": 6, "order_by": "create_time", "status": 1})
    hot_hackathons = __get_api(API_HACKATHON_LIST, {"token": session.get("token")},
                               params={"page": 1, "per_page": 6, "order_by": "registered_users_num", "status": 1})
    soon_hackathon = __get_api(API_HACKATHON_LIST, {"token": session.get("token")},
                               params={"page": 1, "per_page": 6, "order_by": "event_start_time", "status": 1})

    newest_hackathons = empty_items if "error" in newest_hackathons else newest_hackathons
    hot_hackathons = empty_items if "error" in hot_hackathons else hot_hackathons
    soon_hackathon = empty_items if "error" in soon_hackathon else soon_hackathon

    return render('/home.html', newest_hackathons=newest_hackathons, hot_hackathons=hot_hackathons,
                  soon_hackathon=soon_hackathon, sc=False)


@app.route('/shuangchuang')
def shuangchuang():
    empty_items = {
        "items": []
    }
    newest_hackathons = __get_api(API_HACKATHON_LIST, {"token": session.get("token")},
                                  params={"page": 1, "per_page": 3, "order_by": "create_time", "status": 1})
    hot_hackathons = __get_api(API_HACKATHON_LIST, {"token": session.get("token")},
                               params={"page": 1, "per_page": 3, "order_by": "registered_users_num", "status": 1})
    soon_hackathon = __get_api(API_HACKATHON_LIST, {"token": session.get("token")},
                               params={"page": 1, "per_page": 3, "order_by": "event_start_time", "status": 1})

    newest_hackathons = empty_items if "error" in newest_hackathons else newest_hackathons
    hot_hackathons = empty_items if "error" in hot_hackathons else hot_hackathons
    soon_hackathon = empty_items if "error" in soon_hackathon else soon_hackathon

    return render('/home.html', newest_hackathons=newest_hackathons, hot_hackathons=hot_hackathons,
                  soon_hackathon=soon_hackathon, sc=True)


@app.route('/help')
def help():
    return render('/help.html')


@app.route('/about')
def about():
    return render('/about.html')


@app.route("/logout")
@login_required
def logout():
    login_manager_helper.logout(session.get("token"))
    return_url = request.args.get("return_url", "/")
    if "manage/" in return_url:
        return_url = "/"
    resp = redirect(return_url)
    resp.set_cookie('token', '', expires=0)
    return resp


@app.route("/login")
def login():
    session["return_url"] = request.args.get("return_url")
    provider = request.args.get("provides")
    prs = ["github", "qq", "wechat", "weibo", "live", "alauda"]
    if provider is None:
        provider = safe_get_config("login.provider_enabled", prs)
    else:
        provider = provider.split(',')
    return render("/login.html",
                  error=None,
                  providers=provider)


@app.route("/site/<hackathon_name>")
def hackathon(hackathon_name):
    headers = {"hackathon_name": hackathon_name, "token": session.get("token")}
    data = __get_api(API_HACKATHON, headers)
    data = Context.from_object(data)
    reg = Context.from_object(__get_api(API_HACKATHON_REGISTRATION, headers))
    if data.get('error') is not None:
        return render("/404.html")
    else:
        hackathon = data.get("hackathon", data)
        if len(hackathon.banners) == 0:
            hackathon.banners = ['/static/pic/homepage.jpg']
        return render("/site/hackathon.html",
                      hackathon_name=hackathon_name,
                      hackathon=hackathon,
                      user=data.get("user"),
                      registration=data.get("registration"),
                      team=data.get("team"),
                      experiment=reg.get("experiment"))


@app.route("/site/<hackathon_name>/workspace")
@login_required
def workspace(hackathon_name):
    headers = {"hackathon_name": hackathon_name, "token": session.get("token")}
    reg = Context.from_object(__get_api(API_HACKATHON_REGISTRATION, headers))

    if reg.get('registration') is not None:
        if reg.registration.status == 1 or reg.registration.status == 3:
            return render("/site/workspace.html", hackathon_name=hackathon_name,
                          workspace=True,
                          asset=reg.get("asset"),
                          hackathon=reg.get("hackathon"),
                          experiment=reg.get('experiment', {id: 0}))
        else:
            return redirect(url_for('hackathon', hackathon_name=hackathon_name))
    else:
        return redirect(url_for('hackathon', hackathon_name=hackathon_name))


@app.route("/site/<hackathon_name>/settings")
@login_required
def temp_settings(hackathon_name):
    headers = {"hackathon_name": hackathon_name, "token": session.get("token")}
    reg = Context.from_object(
        __get_api(API_HACKATHON, {"hackathon_name": hackathon_name, "token": session.get("token")}))

    if reg.get('registration') is not None:
        if reg.get('experiment') is not None:
            return redirect(url_for('workspace', hackathon_name=hackathon_name))
        elif reg.registration.status == 1 or reg.registration.status == 3:
            templates = Context.from_object(__get_api(API_HACKATHON_TEMPLATE, headers))
            return render("/site/settings.html", hackathon_name=hackathon_name, templates=templates)
        else:
            return redirect(url_for('hackathon', hackathon_name=hackathon_name))
    else:
        return redirect(url_for('hackathon', hackathon_name=hackathon_name))


@app.route("/site/<hackathon_name>/team")
@login_required
def my_team(hackathon_name):
    headers = {"hackathon_name": hackathon_name, "token": session.get("token")}
    team = Context.from_object(__get_api(API_MY_TEAM, headers))
    return render_team_page(hackathon_name, team)


@app.route("/site/<hackathon_name>/team/<tid>")
def create_join_team(hackathon_name, tid):
    headers = {"hackathon_name": hackathon_name, "token": session.get("token")}
    team = Context.from_object(__get_api(API_TEAM, headers, params={"id": tid}))
    return render_team_page(hackathon_name, team)


def render_team_page(hackathon_name, team):
    if team.get('error') is not None:
        return redirect(url_for('hackathon', hackathon_name=hackathon_name))
    else:
        role = team.get('is_admin') and 4 or 0
        role += team.get('is_leader') and 2 or 0
        role += team.get('is_member') and 1 or 0
        return render("/site/team.html", hackathon_name=hackathon_name, team=team, role=role)


@app.route("/signin", methods=['GET', 'POST'])
@app.route("/admin", methods=['GET', 'POST'])
def superadmin():
    if request.method == 'POST':
        return __login(LOGIN_PROVIDER.DB)

    return render("/superadmin.html")


@app.route("/landing")
def landing():
    return render("/landing.html")


@app.route("/events")
def events():
    return render("/events.html")


from route_manage import *
from route_template import *
from route_user import *
from route_team import *
