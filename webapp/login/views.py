import os
from urllib.parse import quote

import flask
from django_openid_auth.teams import TeamsRequest, TeamsResponse
from flask_openid import OpenID
from webapp import authentication
from webapp.api.exceptions import ApiCircuitBreaker, ApiError, ApiResponseError
from webapp.extensions import csrf
from webapp.login.macaroon import MacaroonRequest, MacaroonResponse

login = flask.Blueprint(
    "login", __name__, 
    template_folder="/templates", 
    static_folder="/static"
)

LOGIN_URL = os.getenv("LOGIN_URL", "https://login.ubuntu.com")

LP_CANONICAL_TEAM = "canonical"

open_id = OpenID(
    stateless=True, safe_roots=[], extension_responses=[MacaroonResponse, TeamsResponse]
)

def process_response(response):
    try:
        body = response.json()
    except ValueError as decode_error:
        api_error_exception = ApiResponseDecodeError(
            "JSON decoding failed: {}".format(decode_error)
        )
        raise api_error_exception

    if not response.ok:
        if "error_list" in body:
            for error in body["error_list"]:
                if error["code"] == "user-not-ready":
                    if "has not signed agreement" in error["message"]:
                        raise AgreementNotSigned
                    elif "missing store username" in error["message"]:
                        raise MissingUsername

            raise ApiResponseErrorList(
                "The api returned a list of errors",
                response.status_code,
                body["error_list"],
            )
        elif not body:
            raise ApiResponseError(
                "Unknown error from api", response.status_code
            )

    return body


def get_authorization_header(session):
    authorization = authentication.get_authorization_header(
        session["macaroon_root"], session["macaroon_discharge"]
    )

    return {"Authorization": authorization}


def get_account(session):
    headers = get_authorization_header(session)

    response = api_session.get(url=ACCOUNT_URL, headers=headers)

    if authentication.is_macaroon_expired(response.headers):
        raise MacaroonRefreshRequired

    return process_response(response)


def get_agreement(session):
    headers = get_authorization_header(session)

    agreement_response = api_session.get(url=AGREEMENT_URL, headers=headers)

    if authentication.is_macaroon_expired(agreement_response.headers):
        raise MacaroonRefreshRequired

    return agreement_response.json()


def post_agreement(session, agreed):
    headers = get_authorization_header(session)

    json = {"latest_tos_accepted": agreed}
    agreement_response = api_session.post(
        url=AGREEMENT_URL, headers=headers, json=json
    )

    if authentication.is_macaroon_expired(agreement_response.headers):
        raise MacaroonRefreshRequired

    return process_response(agreement_response)


def post_username(session, username):
    headers = get_authorization_header(session)
    json = {"short_namespace": username}
    username_response = api_session.patch(
        url=ACCOUNT_URL, headers=headers, json=json
    )

    if authentication.is_macaroon_expired(username_response.headers):
        raise MacaroonRefreshRequired

    if username_response.status_code == 204:
        return {}
    else:
        return process_response(username_response)


def get_publisher_metrics(session, json):
    authed_metrics_headers = PUB_METRICS_QUERY_HEADERS.copy()
    auth_header = get_authorization_header(session)["Authorization"]
    authed_metrics_headers["Authorization"] = auth_header

    metrics_response = api_session.post(
        url=SNAP_PUB_METRICS_URL, headers=authed_metrics_headers, json=json
    )

    if authentication.is_macaroon_expired(metrics_response.headers):
        raise MacaroonRefreshRequired

    return process_response(metrics_response)


def post_register_name(
    session, snap_name, registrant_comment=None, is_private=False, store=None
):

    json = {"snap_name": snap_name}

    if registrant_comment:
        json["registrant_comment"] = registrant_comment

    if is_private:
        json["is_private"] = is_private

    if store:
        json["store"] = store

    response = api_session.post(
        url=REGISTER_NAME_URL,
        headers=get_authorization_header(session),
        json=json,
    )

    if authentication.is_macaroon_expired(response.headers):
        raise MacaroonRefreshRequired

    return process_response(response)


def post_register_name_dispute(session, snap_name, claim_comment):
    json = {"snap_name": snap_name, "comment": claim_comment}

    response = api_session.post(
        url=REGISTER_NAME_DISPUTE_URL,
        headers=get_authorization_header(session),
        json=json,
    )

    if authentication.is_macaroon_expired(response.headers):
        raise MacaroonRefreshRequired

    return process_response(response)


def get_snap_info(snap_name, session):
    response = api_session.get(
        url=SNAP_INFO_URL.format(snap_name=snap_name),
        headers=get_authorization_header(session),
    )

    if authentication.is_macaroon_expired(response.headers):
        raise MacaroonRefreshRequired

    return process_response(response)


def get_snap_id(snap_name, session):
    snap_info = get_snap_info(snap_name, session)

    return snap_info["snap_id"]


def snap_metadata(snap_id, session, json=None):
    method = "PUT" if json is not None else None

    metadata_response = api_session.request(
        method=method,
        url=METADATA_QUERY_URL.format(snap_id=snap_id),
        headers=get_authorization_header(session),
        json=json,
    )

    if authentication.is_macaroon_expired(metadata_response.headers):
        raise MacaroonRefreshRequired

    return process_response(metadata_response)


def snap_screenshots(snap_id, session, data=None, files=None):
    method = "GET"
    files_array = None
    headers = get_authorization_header(session)
    headers["Accept"] = "application/json"

    if data:
        method = "PUT"

        files_array = []
        if files:
            for f in files:
                files_array.append(
                    (f.filename, (f.filename, f.stream, f.mimetype))
                )
        else:
            # API requires a multipart request, but we have no files to push
            # https://github.com/requests/requests/issues/1081
            files_array = {"info": ("", data["info"])}
            data = None

    screenshot_response = api_session.request(
        method=method,
        url=SCREENSHOTS_QUERY_URL.format(snap_id=snap_id),
        headers=headers,
        data=data,
        files=files_array,
    )

    if authentication.is_macaroon_expired(screenshot_response.headers):
        raise MacaroonRefreshRequired

    return process_response(screenshot_response)


def snap_revision_history(session, snap_id):
    response = api_session.get(
        url=REVISION_HISTORY_URL.format(snap_id=snap_id),
        headers=get_authorization_header(session),
    )

    if authentication.is_macaroon_expired(response.headers):
        raise MacaroonRefreshRequired

    return process_response(response)


def snap_release_history(session, snap_name, page=1):
    response = api_session.get(
        url=SNAP_RELEASE_HISTORY_URL.format(snap_name=snap_name, page=page),
        headers=get_authorization_header(session),
    )

    if authentication.is_macaroon_expired(response.headers):
        raise MacaroonRefreshRequired

    return process_response(response)


def post_snap_release(session, snap_name, json):
    response = api_session.post(
        url=SNAP_RELEASE, headers=get_authorization_header(session), json=json
    )

    if authentication.is_macaroon_expired(response.headers):
        raise MacaroonRefreshRequired

    return process_response(response)


def post_close_channel(session, snap_id, json):
    url = CLOSE_CHANNEL.format(snap_id=snap_id)
    response = api_session.post(
        url=url, headers=get_authorization_header(session), json=json
    )

    if authentication.is_macaroon_expired(response.headers):
        raise MacaroonRefreshRequired

    return process_response(response)



def login_blueprint(app, testing=False):

    @login.route("/login", methods=["GET", "POST"])
    
    @csrf.exempt
    @open_id.loginhandler
    def login_handler():
        if authentication.is_authenticated(flask.session):
            return flask.redirect(open_id.get_next_url())

        try:
            root = authentication.request_macaroon()
        except ApiResponseError as api_response_error:
            if api_response_error.status_code == 401:
                return login.redirect(login.url_for(".logout"))
            else:
                return login.abort(502, str(api_response_error))
        except ApiCircuitBreaker:
            login.abort(503)
        except ApiError as api_error:
            return login.abort(502, str(api_error))

        openid_macaroon = MacaroonRequest(caveat_id=authentication.get_caveat_id(root))
        login.session["macaroon_root"] = root
.
        lp_teams = TeamsRequest(query_membership=[LP_CANONICAL_TEAM])

        return open_id.try_login(
            LOGIN_URL,
            ask_for=["email", "nickname", "image"],
            ask_for_optional=["fullname"],
            extensions=[openid_macaroon, lp_teams],
        )


    @open_id.after_login
    def after_login(resp):
        login.session["macaroon_discharge"] = resp.extensions["macaroon"].discharge
        if not resp.nickname:
            return login.redirect(LOGIN_URL)

        try:
            account = dashboard.get_account(login.session)
            login.session["openid"] = {
                "identity_url": resp.identity_url,
                "nickname": account["username"],
                "fullname": account["displayname"],
                "image": resp.image,
                "email": account["email"],
                "is_canonical": LP_CANONICAL_TEAM in resp.extensions["lp"].is_member,
            }
            owned, shared = logic.get_snap_names_by_ownership(account)
            login.session["user_shared_snaps"] = shared

        except ApiCircuitBreaker:
            login.abort(503)
        except Exception:
            login.session["openid"] = {
                "identity_url": resp.identity_url,
                "nickname": resp.nickname,
                "fullname": resp.fullname,
                "image": resp.image,
                "email": resp.email,
            }

        return login.redirect(open_id.get_next_url())


    @login.route("/logout")
    def logout():
        no_redirect = login.request.args.get("no_redirect", default="false")

        if authentication.is_authenticated(login.session):
            authentication.empty_session(login.session)

        if no_redirect == "true":
            return login.redirect("/")
        else:
            redirect_url = quote(login.request.url_root, safe="")
            return login.redirect(
                f"{LOGIN_URL}/+logout?return_to={redirect_url}&return_now=True"
            )

    return login