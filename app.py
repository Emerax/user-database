import uuid
import json
import datetime
import sqlite3

from os import environ

from threading import Thread

from functools import wraps

from flask import Flask
from flask import jsonify
from flask import request
from flask import render_template
from flask import url_for

from google.oauth2 import id_token as token_auth
from google.auth.transport import requests

from emailer import send_mail

from queries import *
from config import *
from util import *

app = Flask(__name__)

from db import *

def admin_only(f):
    """
    Wraps endpoint so that it will require authorization.
    Authorization is done using either a SECRET_KEY with basic
    authorization, where the username is empty. Or, using a
    bearer token received from the /login/ endpoint.
    """
    @wraps(f)
    def decorated_fn(*args, **kwargs):

        if SECRET_KEY == "dev":
            return f(*args, **kwargs)

        now = datetime.datetime.now().timestamp()
        auth = request.headers["Authorization"].split(" ")

        if len(auth) != 2:
            return "Invalid authorization. Try reloading.", 401

        auth_type, token = auth
        if auth_type == "Bearer":
            tok = query_db(SELECT_TOKEN_WITH_ID, (token,), one=True)

            if tok is None:
                return "Unauthorized", 401

            token_id, email, issued = tok

            #FIXME: use datetime.datetime.fromisoformat when 3.8 is available
            fmt = "%Y-%m-%d %H:%M:%S"
            issued = datetime.datetime.strptime(issued, fmt).timestamp()

            if issued + 21600 < now:
                return "Unauthorized", 401

        elif auth_type == "Basic":
            if request.authorization["password"] != SECRET_KEY:
                return "Unauthorized token", 401
        else:
            return "Unknown auth type", 401

        return f(*args, **kwargs)

    return decorated_fn


@app.route("/login/", methods=["POST"])
def login():
    """
    Log in a specific user. To log in, POST a json with a google oauth2_token.
    The token must have been received from logging in to the LiTHe kod database
    app and the user must have logged in with a @lithekod.se email.

    This endpoint returns a bearer token that is active for 6 hours after
    being issued.
    """
    token = request.get_json()["token"]

    CLIENT_ID = "235722913299-vs78qd2rm2gpmp39gls54uii3ma8irp0.apps.googleusercontent.com"

    try:
        idinfo = token_auth.verify_oauth2_token(token, requests.Request(), CLIENT_ID)
        now = datetime.datetime.now().timestamp()

        if int(idinfo["exp"]) < now:
            return "Token expired", 401

        if idinfo["hd"] != "lithekod.se":
            return "Only members of the LiTHe kod board are allowed", 401

        if idinfo["iss"] not in ["accounts.google.com", "https://accounts.google.com"]:
            return "Wrong issuer", 401

        roles = ["webb", "ordf", "vordf", "pr", "verks", "kassor", "gamejam"]
        valid_emails = [role + "@lithekod.se" for role in roles]

        if idinfo["email"] not in valid_emails:
            return "Invalid user", 401

        expiration = now + datetime.timedelta(hours=6).seconds
        session_token = random_string(32)

        modify_db(INSERT_NEW_TOKEN, (session_token, idinfo["email"]))

        return session_token, 200

    except Exception as e:
        return "Login failed: {}".format(e), 401


@app.route("/authorized/")
@admin_only
def is_authorized():
    """
    Return 200 if the authentication succeeded.
    Otherwise 401 (in admin_only).
    """
    return "Authorized", 200


def add_member(liuid, name, email, joined, receive_email):
    """
    Add a member to the database.
    All arguments has to be provided and properly formatted.
    Return a tuple with a boolean and a string (success, message).
    """
    def err_msg(msg):
        """ Return a informative error message. """
        return False, f"Failed to add user with id: {liuid} - {msg}."

    liuid = liuid.lower()

    if not is_id(liuid):
        return err_msg("Invalid id")

    if not is_email(email):
        return err_msg("Invalid email")

    if not is_date(joined):
        return err_msg("Invalid date (%Y-%m-%d required)")

    joined = datetime.datetime.strptime(joined, "%Y-%m-%d")

    if not is_bool(receive_email):
        return err_msg("Invalid receive_email (0 or 1 required)")

    try:
        modify_db(INSERT_NEW_MEMBER, (liuid, name, email, joined, receive_email))
    except sqlite3.Error as e:
        return err_msg(e.args[0])

    return True, f"Successfully added user with id: {liuid}."


def add_link(member_id, action):
    """
    Add a link to the database that when accessed,
    performs action on the member with corresponding member_id.

    :param member_id str: id which the link should be linked with.
    :param action str: The action the link should perform.
    """
    if action not in ACTIONS:
        return "Invalid action"

    url = "{}_{}".format(action, random_string(32 - len(action) - 1))
    modify_db(INSERT_NEW_LINK, (member_id, action, url))

    return f"Successfully added {action} link to id: {member_id}"


def get_links():
    """
    Get a dict with all of the links currently in the database.
    The dict is formatted in the following way:
    {
        "liuid123": {
            "ACTION": "ACTION_tehxrkAOEuhrc9238"
                .
                .
        }
        .
        .
    }
    """
    table = {}
    for liuid, link in query_db(SELECT_LINK_MEMBERID_LINK):
        if liuid not in table:
            table[liuid] = {}
        table[liuid][link[:link.find("_")]] = link

    return table


def regenerate_links():
    """
    Remove old links and generate new links for all users.
    Every user gets one link for each ACTION.
    """
    modify_db(DELETE_LINK, [])

    for (liuid,) in query_db(SELECT_MEMBER_ID):
        for action in ACTIONS:
            add_link(liuid, action)

    return get_links()


@app.route("/<link>")
def handle_link(link):
    """
    Handle a link and perform action related to the link.
    Possible actions can be found in ACTIONS.
    """
    link = query_db(SELECT_LINK_WITH_URL, (link,), True)

    if link is None:
        return "Invalid link. It might have been used up..", 404

    member_id, action_id, url, created  = link

    member = query_db(SELECT_MEMBER_WITH_ID, (member_id,), True)
    liuid, name, email, joined, renewed, receive_email = member

    resp = render_template("gui/message.html", message="Unknown link")

    if action_id == "SHOW":
        json_data = json.dumps(member_to_dict(member))
        resp = render_template("gui/member_data.html", json_data=json_data)

    elif action_id == "RENEW":
        modify_db(UPDATE_MEMBER_RENEW, (liuid,))
        modify_db(DELETE_LINK_WITH_IDS, (liuid, action_id))
        message = "Your membership has been renewed!"
        resp = render_template("gui/message.html", message=message)

    elif action_id == "DELETE":
        if "confirm" not in request.args:
            message = "<a href=\"/" + url + "?confirm=true\">Confirm</a>"
        else:
            modify_db(DELETE_LINK_WITH_MEMBER_ID, (liuid,))
            modify_db(DELETE_MEMBER_WITH_ID, (liuid,))
            message = "You have now left LiTHe kod. We hope you enjoyed your stay!"
        resp = render_template("gui/message.html", message=message)

    elif action_id == "UNSUBSCRIBE":
        modify_db(UPDATE_MEMBER_UNSUBSCRIBE, (liuid,))
        message = "You are no longer subscribed to emails from LiTHe kod."
        resp = render_template("gui/message.html", message=message)

    return resp


@app.route("/add_member/")
@admin_only
def handle_add_member():
    """
    Handle adding new members to the database.
    Not all arguments has to be specified in order for a user to be added.
    Only id and name is required.
    """
    args = request.args

    required_arguments = ["id", "name"]
    optional_arguments = ["email", "joined", "receive_email"]
    optional_default = ["{}@student.liu.se".format(args["id"]),
            datetime.date.today().isoformat(), "1"]

    member_args = []

    for required_argument in required_arguments:
        if required_argument not in args:
            return f"No '{required_argument}' specifed", 400
        else:
            member_args.append(args[required_argument])

    for optional_argument, default in zip(optional_arguments, optional_default):
        if optional_argument not in args:
            member_args.append(default)
        else:
            member_args.append(args[optional_argument])

    success, message = add_member(*member_args)

    if success:
        for action in ACTIONS:
            add_link(args["id"], action)

        if SENDER_PASSWORD != "dev":

            with open("email-templates/welcome.html") as f:
                html = f.read()

            send_mail(
                get_mailing_list(args["id"]),
                "Welcome to LiTHe kod!",
                html,
                get_links()
            )

    return message, 200 if success else 400


@app.route("/modify/")
@admin_only
def handle_modify():
    """
    Handle modifying a members data in the database.
    The member id, field and new value must be specified in the arguments.
    """
    args = request.args

    if "id" not in args:
        return "No id specified.", 400

    if "field" not in args:
        return "No field specified.", 400

    if "new" not in args:
        return "No new specified.", 400

    def err_msg(msg):
        """ Return a informative error message. """
        return f"Failed to modify user with id: {args['id']} - {msg}.", 400

    if query_db(SELECT_MEMBER_WITH_ID, (args["id"],), True) is None:
        return err_msg("No such user")

    field_verification = {
        "name": lambda x: True,
        "email": is_email,
        "joined": is_date,
        "renewed": is_date,
        "receive_email": is_bool
    }

    if args["field"] not in field_verification:
        return err_msg(f"No such field '{args['field']}'")

    if not field_verification[args["field"]](args["new"]):
        return err_msg("Badly formatted value '{}' for field '{}'"
                .format(args['new'], args['field']))

    try:
        # FIXME: I no longer think this is a good idea.
        #
        # Formatting the query with user input is insecure
        # but we have already verified that the
        # field argument is valid and not malicious.
        modify_db(UPDATE_MEMBER_FIELD.format(args["field"]), (args["new"], args["id"]))
    except sqlite3.Error as e:
        return err_msg(e.args[0])

    return f"Successfully set '{args['field']}' to '{args['new']}' for '{args['id']}'", 200


@app.route("/members/")
@admin_only
def get_members():
    """
    Return information about the database.
    Basically a JSON of the members and links in the database.
    If a member id is specified in the arguments, return only that member.
    """
    links = get_links()
    if "id" in request.args:
        member = query_db(SELECT_MEMBER_WITH_ID, [request.args["id"]], True)
        if member is None:
            return "No such member", 400

        member = member_to_dict(member)
        member["links"] = links.get(member["id"], [])
        return jsonify(member)

    members = [member_to_dict(member) for member in query_db(SELECT_MEMBER)]
    members.sort(key=lambda member: member["id"])

    for member in members:
        member["links"] = links.get(member["id"], [])

    return jsonify(members)


@app.route("/member_count/")
def get_member_count():
    """
    Return information about how many members there are.
    This endpoint does not require admin privileges.
    """
    return jsonify({
        "total_members": len(query_db(SELECT_MEMBER)),
        "active_members": len(query_db(SELECT_MEMBER_ACTIVE)),
    })


def get_mailing_list(receivers):
    """
    Create a mailing list for the spcified receivers.
    receivers can be any of the following values:
        default - All members that wants to receive emails.
        all - All members.
        inactive - All inactive members.
        liuid(s) - Only the members with the specified liuid(s) (space separated).
    """
    mailing_list = []
    if receivers == "default":
        mailing_list = query_db(SELECT_MEMBER_SUBSCRIBED)
    elif receivers == "all":
        mailing_list = query_db(SELECT_MEMBER)
    elif receivers == "inactive":
        mailing_list = query_db(SELECT_MEMBER_INACTIVE)
    else:
        for liu_id in receivers.split():
            mailing_list += query_db(SELECT_MEMBER_WITH_ID, (liu_id,))

    return mailing_list


@app.route("/email_members/")
@admin_only
def email_members():
    """
    Send emails to all members.
    Specify subject and html file as arguments.
    """
    args = request.args
    if "receivers" not in args:
        return "No receivers spcified.", 400
    receivers = args["receivers"]

    if "subject" not in args:
        return "No subject specified.", 400
    subject = args["subject"]

    if "template" not in args:
        return "No template spcified.", 400
    template = args["template"]

    with open("email-templates/{}.html".format(template)) as f:
        html = f.read()

    Thread(target=send_mail, args=(get_mailing_list(receivers), subject, html,
        get_links())).run()

    return "Emails are being sent!", 200


@app.teardown_appcontext
def close_connection(e):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


@app.route("/")
def index():
    return render_template("gui/index.html")


@app.route("/gui/add_member/")
def gui_add_member():
    return render_template("gui/add_member.html")


@app.route("/gui/login/")
def gui_login():
    return render_template("gui/login.html")


@app.route("/gui/manage_members/")
def gui_manage_members():
    return render_template("gui/member_list.html")


@app.route("/gui/manage_members/<member_id>")
def gui_edit_member(member_id):
    return render_template("gui/edit_member.html", member_id=member_id)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
