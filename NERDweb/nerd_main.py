#!/usr/bin/env python
from __future__ import print_function
import sys
import random
import json
import time
import os
import subprocess
import re
import pytz

from flask import Flask, request, render_template, make_response, g, jsonify, json, flash, redirect, session
from flask_pymongo import pymongo, PyMongo, ASCENDING, DESCENDING
from flask_wtf import Form
from flask_mail import Mail, Message
from wtforms import validators, TextField, IntegerField, BooleanField, HiddenField, SelectField, SelectMultipleField, PasswordField

# Add to path the "one directory above the current file location"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')))
import common.eventdb
import common.config

#import db
import ctrydata
import userdb
from userdb import get_user_info

# ***** Load configuration *****

BASE_URL = '/nerd' # without trailing slash   TODO: get automatically (or from config)
#BASE_URL = ''

DEFAULT_CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../etc/nerdweb.cfg"))

# TODO parse arguments using ArgParse
if len(sys.argv) >= 2:
    cfg_file = sys.argv[1]
else:
    cfg_file = DEFAULT_CONFIG_FILE
cfg_dir = os.path.dirname(os.path.abspath(cfg_file))

# Read web-specific config (nerdweb.cfg)
config = common.config.read_config(cfg_file)
# Read common config (nerd.cfg) and combine them together
common_cfg_file = os.path.join(cfg_dir, config.get('common_config'))
config.update(common.config.read_config(common_cfg_file))

WARDEN_DROP_PATH = os.path.join(config.get("warden_filer_path", "/data/warden_filer/warden_receiver"), "incoming")

config.testing = False

userdb.init(config, cfg_dir)

# **** Create and initialize Flask application *****

app = Flask(__name__)

app.secret_key = config.get('secret_key')

app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True

# Configuration of PyMongo
app.config['MONGO_HOST'] = config.get('mongodb.host', 'localhost')
app.config['MONGO_PORT'] = config.get('mongodb.port', 27017)
app.config['MONGO_DBNAME'] = config.get('mongodb.dbname', 'nerd')

mongo = PyMongo(app)

# Configuration of MAIL extension
app.config['MAIL_SERVER'] = config.get('mail.server', 'localhost')
app.config['MAIL_PORT'] = config.get('mail.port', '25')
app.config['MAIL_USE_TLS'] = config.get('mail.tls', False)
app.config['MAIL_USE_SSL'] = config.get('mail.ssl', False)
app.config['MAIL_USERNAME'] = config.get('mail.username', None)
app.config['MAIL_PASSWORD'] = config.get('mail.password', None)
app.config['MAIL_DEFAULT_SENDER'] = config.get('mail.sender', 'NERD <noreply@nerd.example.com>')

mailer = Mail(app)


eventdb = common.eventdb.FileEventDatabase({'eventdb_path': config.get("eventdb_path")})


# ***** Jinja2 filters *****

# Datetime filters
def format_datetime(val, format="%Y-%m-%d %H:%M:%S"):
    return val.strftime(format)

app.jinja_env.filters['datetime'] = format_datetime

    

# ***** Login handlers *****
# A handler function is created for each configured login method
# (config.login.<method>) with URL path set to config.login.<method>.loc.
# 
# Each of these paths should have a login mechanism configured in web server.
# (e.g. HTTP basic authentication or Shibboleth).
# The handler expect a valid user information in environent variables set by 
# the server.
# The user info (id and optionally name and email) is taken from environment 
# variables specified in config.login.<method>.{id_field,user_field,email_field}. 

def create_login_handler(method_id, id_field, name_field, email_field, return_path):
    def login_handler():
        # Check presence of the only mandatory field (id)
        if id_field not in request.environ:
            flash("ERROR: Login failed - '"+id_field+"' not defined (either your IdP is not providing this field or there is a problem with server configuration).", "error")
            return redirect(return_path)
        session['user'] = {
            'login_type': method_id,
            'id': request.environ[id_field].decode('utf-8'),
        }
        # Name may be present in various fields, try all specified in the config and use the first present
        for field in (name_field if isinstance(name_field, list) else ([name_field] if name_field else [])):
            # Name may be a combination of more fields, specified using "+" symbol (e.g. )
            if "+" in field and all(f in request.environ for f in field.split('+')):
                session['user']['name'] = " ".join(map(lambda f: request.environ[f].decode('utf-8'), field.split('+')))
                break
            elif field in request.environ:
                session['user']['name'] = request.environ[field].decode('utf-8')
                break
        # Email
        if email_field and email_field in request.environ:
            session['user']['email'] = request.environ[email_field]
        flash("Login successful", "success")
        return redirect(return_path)
    return login_handler

# Register the login handlers
for method_id, method_cfg in config.get('login.methods', {}).items():
    app.add_url_rule(
        method_cfg['loc'],
        'login_'+method_id,
        create_login_handler(method_id,
                             method_cfg.get('id_field', 'REMOTE_USER'),
                             method_cfg.get('name_field', None),
                             method_cfg.get('email_field', None),
                             config['login']['return-path']
        )
    )


@app.route('/logout')
def logout():
    redir_path = config['login']['return-path']
    if 'user' in session:
        # If there is logout-path defined for the login_type, redirect to this instead of the default
        login_type = session['user']['login_type']
        if 'logout_path' in config['login']['methods'][login_type]:
            redir_path = config['login']['methods'][login_type]['logout_path']
        # Cancel local NERD session
        del session['user']
        flash("You have been logged out", "info")
    return redirect(redir_path)



# ***** Main page *****
@app.route('/')
def main():
    user, ac = get_user_info(session)
    
    # User is authenticated but has no account
    if user and ac('notregistered'):
        return redirect(BASE_URL+'/noaccount')
    
    return redirect(BASE_URL+'/ips/')


# ***** Request for new account *****
class AccountRequestForm(Form):
    email = TextField('Contact email', [validators.Required()], description='Used to send information about your request and in case admins need to contact you.')

@app.route('/noaccount', methods=['GET','POST'])
def noaccount():
    user, ac = get_user_info(session)
    if not user:
        return make_response("ERROR: no user is authenticated")
    if not ac('notregistered'):
        return redirect(BASE_URL+'/ips/')
    if user['login_type'] != 'shibboleth':
        return make_response("ERROR: You've successfully authenticated to web server but there is no matching user account. This is probably a configuration error. Contact NERD administrator.")
    
    form = AccountRequestForm(request.values)
    # Prefill user's default email from his/her account info (we expect a list of emails separated by ';')
    if not form.email.data and 'email' in user:
        form.email.data = user['email'].split(';')[0]
    
    request_sent = False
    if form.validate():
        # TODO check presence of config login.request-email
        # if not config.get()
        # Send email
        name = user.get('name', '[name not available]').encode('ascii', 'replace')
        id = user['id']
        email = form.email.data.decode('utf-8')
        msg = Message(subject="[NERD] New account request from {} ({})".format(name,id),
                      #recipients=[email],
                      recipients=[config.get('login.request-email')],
                      reply_to=email,
                      body="A user with the following ID has requested creation of a new account in NERD.\n\nid: {}\nname: {}\nemail: {}".format(id,name,email),
                     )
        mailer.send(msg)
        request_sent = True
        
    return render_template('noaccount.html', config=config, **locals())


# ***** Account info & password change *****

class PasswordChangeForm(Form):
    old_passwd = PasswordField('Old password', [validators.InputRequired()])
    new_passwd = PasswordField('New password', [validators.InputRequired(), validators.length(8, -1, 'Password must have at least 8 characters')])
    new_passwd2 = PasswordField('Repeat password', [validators.InputRequired(), validators.EqualTo('new_passwd', message='Passwords must match')])


@app.route('/account')
@app.route('/account/set_password', endpoint='set_password', methods=['POST'])
def account_info():
    user, ac = get_user_info(session)
    if not user:
        return make_response("ERROR: no user is authenticated")
    if user and ac('notregistered'):
        return redirect(BASE_URL+'/noaccount')
    
    # Handler for /account/set_password
    if request.endpoint == 'set_password':
        if user['login_type'] != 'local':
            return make_response("ERROR: Password can be changed for local accounts only")
        passwd_form = PasswordChangeForm(request.form)
        if passwd_form.validate():
            htpasswd_file = os.path.join(cfg_dir, config.get('login.methods.local.htpasswd_file', '.htpasswd'))
            try:
                # Verify old password
                cmd = ['htpasswd', '-v', '-i', htpasswd_file, user['id']]
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE)#, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                p.communicate(passwd_form.old_passwd.data.encode('utf-8'))
                if p.returncode != 0:
                    if p.returncode == 3: # Bad password
                        flash('ERROR: Bad password', 'error')
                        return render_template('account_info.html', config=config, **locals())
                    else:
                        print("ERROR: htpasswd check error '{}': retcode: {}".format(' '.join(cmd), p.returncode), file=sys.stderr)
                        return make_response('ERROR: Cannot change password: error '+str(p.returncode),  'error')
                
                # Set new password
                # (-i: read password from stdin, -B: use bcrypt, -C: bcrypt cost factor (12 should be quite secure and takes approx. 0.3s on my server)
                cmd = ['htpasswd', '-i', '-B', '-C', '12', htpasswd_file, user['id']]
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE)#, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                p.communicate(passwd_form.new_passwd.data.encode('utf-8'))
                if p.returncode != 0:
                    print("ERROR: htpasswd set error '{}': retcode: {}".format(' '.join(cmd), p.returncode), file=sys.stderr)
                    return make_response('ERROR: Cannot change password: error '+str(p.returncode),  'error')
            except OSError as e:
                p.kill()
                print("ERROR: htpasswd OSError '{}': {}".format(' '.join(cmd), str(e)), file=sys.stderr)
                return make_response('ERROR: Cannot change password: OSError.', 'error')
            
            # If we got there, passward was successfully changed
            flash('Password changed. Please, <b><a href="'+BASE_URL+'/logout">log out</a></b> and then log back in using the new password.', 'safe success')
            return redirect(BASE_URL+'/account')
        else:
            flash('ERROR: Password not changed.', 'error')

    # Handler for /account
    else:
        if user['login_type'] == 'local':
            passwd_form = PasswordChangeForm()
    
    return render_template('account_info.html', config=config, **locals())


# def set_password():
#     form = PasswordChangeForm(request.form)
#     if form.validate():
#         
#     return redirect(BASE_URL+'/account')


# ***** List of IP addresses *****

def get_blacklists():
    # Get the list of all configured blacklists
    # DNSBL
    blacklists = [bl_name for bl_group in config.get('dnsbl.blacklists', []) for bl_name in bl_group[2].values()]
    # Locally downloaded blacklists
    blacklists += [bl[0] for bl in config.get('local_bl.lists', [])]
    blacklists.sort()
    return blacklists

class IPFilterForm(Form):
    subnet = TextField('IP prefix', [validators.Optional()])
    hostname = TextField('Hostname suffix', [validators.Optional()])
    country = TextField('Country code', [validators.Optional(), validators.length(2, 2)])
    asn = TextField('ASN', [validators.Optional(),
        validators.Regexp('^((AS)?\d+|\?)+$', re.IGNORECASE,
        message='Must be a number, optionally preceded by "AS", or "?".')])
    blacklist = SelectMultipleField('Blacklist', [validators.Optional()],
        choices=[(bl,bl) for bl in get_blacklists()])
    bl_op = HiddenField('', default="or")
    sortby = SelectField('Sort by', choices=[
                ('events','Events'),
                ('ts_update','Last update'),
                ('ts_added','Time added'),
                ('ip','IP address'),
             ], default='events')
    asc = BooleanField('Ascending', default=False)
    limit = IntegerField('Max number of addresses', [validators.NumberRange(1, 1000)], default=20)

sort_mapping = {
    'events': 'events.total',
    'ts_update': 'ts_last_update',
    'ts_added': 'ts_added',
    'ip': '_id',
}

def create_query(form):
    # Prepare 'find' part of the query
    queries = []
    if form.subnet.data:
        subnet = form.subnet.data
        subnet_end = subnet[:-1] + chr(ord(subnet[-1])+1)
        queries.append( {'$and': [{'_id': {'$gte': subnet}}, {'_id': {'$lt': subnet_end}}]} )
    if form.hostname.data:
        hn = form.hostname.data[::-1] # Hostnames are stored reversed in DB to allow search by suffix as a range search
        hn_end = hn[:-1] + chr(ord(hn[-1])+1)
        queries.append( {'$and': [{'hostname': {'$gte': hn}}, {'hostname': {'$lt': hn_end}}]} )
    if form.country.data:
        queries.append( {'geo.ctry': form.country.data.upper() } )
    if form.asn.data:
        if form.asn.data[0] == '?':
            queries.append( {'$and': [{'as_maxmind.num': {'$exists': True}},
                                      {'as_rv.num': {'$exists': True}},
                                      {'$where': 'this.as_maxmind.num != this.as_rv.num'} # This will be probably very slow
                                     ]} )
        else:
            asn = int(form.asn.data.lstrip("ASas"))
            queries.append( {'$or': [{'as_maxmind.num': asn}, {'as_rv.num': asn}]} )
    if form.blacklist.data:
        op = '$and' if (form.bl_op.data == "and") else '$or'
        queries.append( {op: [{'bl.'+blname: {'$exists': True}} for blname in form.blacklist.data]} )
    
    query = {'$and': queries} if queries else None
    return query

@app.route('/ips')
@app.route('/ips/')
def ips():
    title = "IP search"
    user, ac = get_user_info(session)

    form = IPFilterForm(request.args, csrf_enabled=False)

    if ac('ipsearch') and form.validate():
        timezone = pytz.timezone('Europe/Prague') # TODO autodetect (probably better in javascript)
        sortby = sort_mapping[form.sortby.data]
        
        query = create_query(form)
        
        # Query parameters to be used in AJAX requests
        query_params = json.dumps(form.data)
        
        # Perform DB query
        #print("Query: "+str(query))
        try:
            results = mongo.db.ip.find(query).limit(form.limit.data).sort(sortby, 1 if form.asc.data else -1)
            results = list(results) # Load all data now, so we are able to get number of results in template
        except pymongo.errors.ServerSelectionTimeoutError:
            results = []
            error = 'mongo_error'
        
        # Add metainfo about evetns for easier creation of event table in the template
        date_regex = re.compile('^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
        for ip in results:
            events = ip.get('events', {})
            dates = set()
            cats = set()
            nodes = set()
            for key,val in events.items():
                if date_regex.match(key):
                    dates.add(key)
                    for cat,val in val.items():
                        if cat == 'nodes':
                            nodes.update(val)
                        else:
                            cats.add(cat)
            dates = sorted(dates)
            cats = sorted(cats)
            nodes = sorted(nodes)
            date_cat_table = [ [ events.get(d, {}).get(c, 0) for c in cats ] for d in dates ]
            
            MAX_DAYS = 5
            if len(dates) > MAX_DAYS:
                dates = dates[-MAX_DAYS:]
                dates.insert(0, '...')
                date_cat_table = date_cat_table[-MAX_DAYS:]
                date_cat_table.insert(0, ['...' for c in cats])
            
            events['_dates'] = ','.join(dates)
            events['_cats'] = ','.join(cats)
            events['_nodes'] = ','.join(nodes)
            events['_date_cat_table'] = ';'.join( [','.join(map(str,c)) for c in date_cat_table] )
            events['_n_cats'] = len(cats)
            events['_n_nodes'] = len(nodes)
    else:
        results = None
        if user and not ac('ipsearch'):
            flash('Only registered users may search IPs.', 'error')

    return render_template('ips.html', config=config, ctrydata=ctrydata, **locals())


@app.route('/_ips_count', methods=['POST'])
def ips_count():
    user, ac = get_user_info(session)
    #Excepts query as JSON encoded POST data.
    form_values = request.get_json()
    form = IPFilterForm(obj=form_values, csrf_enabled=False)
    if ac('ipsearch') and form.validate():
        query = create_query(form)
        print("query: " + str(query))
        return make_response(str(mongo.db.ip.find(query).count()))
    else:
        return make_response("ERROR")


# ***** List of alerts *****

# class AlertFilterForm(Form):
#     limit = IntegerField('Max number of results', [])
# 
# @app.route('/events')
# def events():
#     title = "Events"
#     limit = get_int_arg('limit', 10, min=1, max=1000)
#     skip = get_int_arg('skip', 0, min=0)
#     num_alerts = mongo.db.alerts.count()
#     num_ips = mongo.db.ips.count()
#     alerts = mongo.db.alerts.find().sort("$natural", DESCENDING).skip(skip).limit(limit)
#     form = AlertFilterForm(limit=limit)
#     return render_template('events.html', **locals())


# ***** Detailed info about individual IP *****

class SingleIPForm(Form):
    ip = TextField('IP address', [validators.IPAddress(message="Invalid IPv4 address")])


@app.route('/ip/')
@app.route('/ip/<ipaddr>')
def ip(ipaddr=None):
    user, ac = get_user_info(session)
    
    form = SingleIPForm(ip=ipaddr)
    #if form.validate():
    if ipaddr:
        if ac('ipsearch'):
            title = ipaddr
            ipinfo = mongo.db.ip.find_one({'_id':form.ip.data})
            events = eventdb.get('ip', form.ip.data, limit=100) # Load events (IDEA messages as strings)
            events = list(map(json.loads, events)) # Decode IDEA messages
            num_events = str(len(events))
            if len(events) >= 100:
                num_events = "&ge;100, only first 100 shown"
        else:
            flash('Only registered users may search IPs.', 'error')
    else:
        title = 'IP detail search'
        ipinfo = {}
    return render_template('ip.html', config=config, ctrydata=ctrydata, ip=form.ip.data, **locals())


# ***** NERD status information *****

@app.route('/status')
def get_status():
    ips = mongo.db.ip.count()
    idea_queue_len = len(os.listdir(WARDEN_DROP_PATH))
    try:
        if "data_disk_path" in config:
            disk_usage = subprocess.check_output(["df", config.get("data_disk_path"), "-P"]).decode('ascii').splitlines()[1].split()[4]
        else:
            disk_usage = "(N/A)"
    except Exception as e:
        disk_usage = "(error) " + str(e);
    return jsonify(
        ips=ips,
        idea_queue=idea_queue_len,
        disk_usage=disk_usage
    )


# **********

if __name__ == "__main__":
    config.testing = True
    app.run(host="0.0.0.0", debug=True)

