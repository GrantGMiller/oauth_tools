import datetime
import json
import time
import requests
from urllib.parse import urlencode
import threading

# based on the steps here:https://developers.google.com/identity/protocols/OAuth2ForDevices

USE_COMMON_TENANT = False  # per microsoft: Usage of the /common endpoint is not supported for such applications created after '10/15/2018'


class _BaseOauthDeviceCode:
    @property
    def Type(self):
        return self._type


class OauthDeviceCode_Microsoft(_BaseOauthDeviceCode):
    def __init__(self, **k):
        self.clientID = k.get('clientID')
        self.tenantID = k.get('tenantID')

        self._type = 'Microsoft'

        # will be filled in later
        self._accessToken = k.get('accessToken', None)
        self._refreshToken = k.get('refreshToken', None)
        self._accessTokenExpiresAt = k.get('accessTokenExpiresAt', None) or time.time()  # time.time
        self._verificationURI = k.get('verificationURI', None)
        self._userCode = k.get('userCode', None)
        self._deviceCode = k.get('deviceCode', None)
        self._deviceCodeExpiresAt = k.get('deviceCodeExpiresAt', time.time())
        self._interval = k.get('interval', 5)
        self._lastRequest = k.get('lastRequest', time.time() - self._interval)

        self._debug = k.get('debug', False)
        self.print('Microsoft.__init__(k=', k)
        if self._userCode is None:
            self.GetUserCode()

    def print(self, *a, **k):
        if self._debug:
            print(*a, **k)

    def dict(self):
        return {
            'clientID': self.clientID,
            'tenantID': self.tenantID,
            'type': self._type,
            'accessToken': self._accessToken,
            'accessTokenExpiresAt': self._accessTokenExpiresAt,
            'refreshToken': self._refreshToken,
            'verificationURI': self._verificationURI,
            'userCode': self._userCode,
            'deviceCode': self._deviceCode,
            'deviceCodeExpiresAt': self._deviceCodeExpiresAt,
            'interval': self._interval,
            'lastRequest': self._lastRequest,
        }

    def GetUserCode(self):
        if self._userCode:
            return self._userCode

        data = {
            'client_id': self.clientID,
            'scope': ' '.join([
                'openid',
                'offline_access',
                'https://outlook.office.com/Calendars.ReadWrite',
                'https://outlook.office.com/EWS.AccessAsUser.All',
                'email',
                'User.Read'
            ]),
        }
        url = 'https://login.microsoftonline.com/{}/oauth2/v2.0/devicecode'.format(self.tenantID)
        resp = requests.post(url, data=data)
        if not 200 <= resp.status_code < 300:
            return

        self._verificationURI = resp.json().get('verification_uri')
        self._userCode = resp.json().get('user_code')
        self._deviceCode = resp.json().get('device_code')
        self._interval = resp.json().get('interval')
        self._deviceCodeExpiresAt = time.time() + resp.json().get('expires_in', 0)
        self._lastRequest = time.time()
        return self._userCode

    @property
    def VerificationURI(self):
        return self._verificationURI

    @property
    def Interval(self):
        return self._interval

    def DeviceCodeExpired(self):
        return time.time() > self._deviceCodeExpiresAt

    def GetRefreshToken(self):
        return self._refreshToken

    def GetAccessTokenExpriesAt(self):
        return self._accessTokenExpiresAt

    def GetAccessToken(self, forceRefresh=False):
        """
        Tries to get an access token.
        Call this before every HTTP request that needs oauth_tools,
            because the token may have expired.
        This method will refresh the token if needed and return the new token.
        Might return None if the user has not authenticated yet
        :return: str or None
        """

        deltaUntilExpired = self._accessTokenExpiresAt - time.time()
        deltaLastRequest = time.time() - self._lastRequest

        if deltaLastRequest < self._interval and deltaUntilExpired > 0:
            self.print('276 assuming access token is valid. Should only make request once per "interval"')
            self.print('deltaLastRequest=', deltaLastRequest)
            self.print('264 The accessToken is valid for {}'.format(datetime.timedelta(seconds=deltaUntilExpired)))
            return self._accessToken

        if self._accessToken:
            self.print('280 We already received an access token previously')
            if time.time() > self._accessTokenExpiresAt or \
                    forceRefresh:
                self.print('282 Access token is expired. Get a new one. Force Refresh=', forceRefresh)
                if USE_COMMON_TENANT:
                    url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
                else:
                    url = 'https://login.microsoftonline.com/{}/oauth2/v2.0/token'.format(self.tenantID)

                data = {
                    'client_id': self.clientID,
                    'scope': ' '.join([
                        'openid',
                        'offline_access',
                        'https://outlook.office.com/Calendars.ReadWrite',
                        'https://outlook.office.com/EWS.AccessAsUser.All',
                        'email',
                        'User.Read'
                    ]),
                    'refresh_token': self._refreshToken,
                    'grant_type': 'refresh_token',
                }
                try:
                    resp = requests.post(url, data)
                    self._lastRequest = time.time()
                    self._accessToken = resp.json().get('access_token')
                    self._refreshToken = resp.json().get('refresh_token')
                    self._accessTokenExpiresAt = time.time() + resp.json().get('expires_in')
                    self.print('Got new Access Token')
                except Exception as e:
                    print(e)
                return self._accessToken
            else:
                delta = int(self._accessTokenExpiresAt - time.time())
                self.print('The accessToken is valid for {}'.format(datetime.timedelta(seconds=delta)))
                return self._accessToken
        else:
            # This is the first time we are retrieving an access token

            if USE_COMMON_TENANT:
                url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
            else:
                url = 'https://login.microsoftonline.com/{}/oauth2/v2.0/token'.format(self.tenantID)

            resp = requests.post(
                url,
                data={
                    'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                    'client_id': self.clientID,
                    'device_code': self._deviceCode
                }
            )
            if not resp.ok:
                self.print('resp.text=', resp.text)
            self._lastRequest = time.time()
            self._accessToken = resp.json().get('access_token', None)

            self._refreshToken = resp.json().get('refresh_token', None)
            if self._accessToken:
                self._accessTokenExpiresAt = time.time() + resp.json().get('expires_in', None)
            return self._accessToken


class User:
    def __init__(self, ID, authManagerParent, authType):
        self._ID = ID

        data = authManagerParent.Get(ID)
        if authType == 'Google':
            self._oa = OauthDeviceCode_Google(
                jsonPath=authManagerParent.GoogleJSONPath,
                initAccessToken=data.get('accessToken', None),
                initRefreshToken=data.get('refreshToken', None),
                initAccessTokenExpiresAt=data.get('expiresAt', None),
            )
        elif authType == 'Microsoft':
            self._oa = OauthDeviceCode_Microsoft(
                clientID=authManagerParent.ClientID,
                tenantID=authManagerParent.TenantID,
                accessToken=data.get('accessToken', None),
                refreshToken=data.get('refreshToken', None),
                accessTokenExpiresAt=data.get('accessTokenExpiresAt', None),
                debug=authManagerParent._debug,
            )
        self._emailAddress = data.get('emailAddress', None)
        self._authManagerParent = authManagerParent

    def __str__(self):
        return '<User: ID={}, EmailAddress={}, AccessToken={}>'.format(
            self.ID,
            self.EmailAddress,
            self.GetAccessToken()[:10] if self.GetAccessToken() else 'None'
        )

    @property
    def ID(self):
        return self._ID

    @property
    def Data(self):
        return {
            'accessToken': self._oa.GetAccessToken(),
            'refreshToken': self._oa.GetRefreshToken(),
            'expiresAt': self._oa.GetAccessTokenExpriesAt(),
            'emailAddress': self.EmailAddress,
            'type': self._oa.Type,
        }

    @property
    def AccessToken(self):
        ret = self._oa.GetAccessToken()
        self._authManagerParent.Update(self)
        return ret

    @property
    def RefreshToken(self):
        ret = self._oa.GetRefreshToken()
        self._authManagerParent.Update(self)
        return ret

    @property
    def EmailAddress(self):
        if self._oa.Type != 'Microsoft':
            return

        if self._emailAddress is None:
            resp = requests.get(
                # 'https://graph.microsoft.com/v1.0/me',
                'https://outlook.office.com/api/v2.0/me',
                headers={
                    'Authorization': 'Bearer {}'.format(self._oa.GetAccessToken()),
                    'Content-Type': 'application/json',
                }
            )
            if resp.ok:
                self._emailAddress = resp.json().get('EmailAddress', None)
                self._authManagerParent.Set(self._ID, self.Data)

        return self._emailAddress

    def GetAccessToken(self):
        ret = self._oa.GetAccessToken()
        self._authManagerParent.Set(self.ID, self._oa.dict())
        return ret


class AuthManager:
    def __init__(self,
                 microsoftClientID=None,
                 microsoftTenantID=None,
                 googleJSONpath=None,
                 debug=False,
                 ):
        self._microsoftClientID = microsoftClientID
        self._microsoftTenantID = microsoftTenantID
        self._googleJSONpath = googleJSONpath
        self._debug = debug

        self.SaveToDBCallback = None
        # will be called when the system needs to save oauth_tools creds to the database,
        # should accept a single parameter User() object, you prob want to save user.Data as json

        self.GetFromDBCallback = None  # called when data needs to be retrieved from the database. accepts one parameter,
        # a str() object which is the ID (an arbitrary unique alias for the set of creds).
        # Should return a dict like that found in user.Data
        # return None if not found

        self.SaveIncompleteOACallback = None
        # Should accept two arguments
        # ID > a str identifying this set of creds,
        # data > a dict that will be used to reconstruct the OA later

        self.GetIncompleteOACallback = None
        # accepts one argument
        # ID > str
        # should return dict or None

    @property
    def ClientID(self):
        return self._microsoftClientID

    @property
    def TenantID(self):
        return self._microsoftTenantID

    @property
    def GoogleJSONPath(self):
        return self._googleJSONpath

    @property
    def GoogleData(self):
        with open(self._googleJSONpath, mode='rt') as file:
            d = json.loads(file.read())['installed']
            return d

    def Set(self, ID, data):
        if self.SaveToDBCallback:
            self.SaveToDBCallback(ID, data)

    def Get(self, ID):
        if self.GetFromDBCallback:
            ret = self.GetFromDBCallback(ID)
            self.print('481 ret=', ret)
            return ret
        else:
            return {}

    def GetUserByID(self, ID):
        assert isinstance(ID, str), '"ID" must be a string not {}'.format(type(ID))

        d = self.Get(ID)
        if d:
            return User(
                ID,
                authManagerParent=self,
                authType=d['type'],
            )
        else:
            return None

    def CheckOAStatus(self, ID):
        oa = self.GetOA(ID)
        if oa.DeviceCodeExpired():
            raise TimeoutError('DeviceCodeExpired')
        else:
            accessToken = oa.GetAccessToken()
            if accessToken is not None:
                self.Set(ID, oa.dict())
                if self._debug:
                    print('New User added to AuthManager. ID="{}"'.format(ID))
                return 'Success'
            else:
                return 'Waiting for user to authenticate'

    def SaveOA(self, ID, oa):
        if self.SaveIncompleteOACallback:
            return self.SaveIncompleteOACallback(ID, oa.dict())
        else:
            raise RuntimeError(
                'You must first assign a callback to AuthManager.SaveIncompleteOACallback. '
                'It must accept two params, ID(str), data(dict)')

    def GetOA(self, ID):
        if self.GetIncompleteOACallback:
            d = self.GetIncompleteOACallback(ID)
            self.print('521 d=', d)
            if d is None:
                return None
            else:
                if d['type'] == 'Microsoft':
                    return OauthDeviceCode_Microsoft(debug=self._debug, **d)
                elif d['type'] == 'Google':
                    return OauthDeviceCode_Google(**d)
        else:
            raise RuntimeError(
                'You must first assign a callback to AuthManager.GetIncompleteOACallback. '
                'It must accept one param ID(str) '
                'and return a dict that was previously saved using '
                'AuthManager.SaveIncompleteOACallback, '
                'or return None if not found.')

    def CreateNewUser(self, ID, authType='Microsoft'):
        assert isinstance(ID, str), '"ID" must be a string not {}'.format(type(ID))

        if authType == 'Google':
            tempOA = OauthDeviceCode_Google(self._googleJSONpath)
        elif authType == 'Microsoft':
            tempOA = OauthDeviceCode_Microsoft(
                clientID=self._microsoftClientID,
                tenantID=self._microsoftTenantID,
                debug=self._debug,
            )
        else:
            raise TypeError('Unrecognized authType "{}"'.format(authType))

        self.SaveOA(ID, tempOA)

        if self._debug:
            print('Go to "{}" and enter code "{}"'.format(tempOA.VerificationURI, tempOA.GetUserCode()))

        return {
            'verification_uri': tempOA.VerificationURI,
            'user_code': tempOA.GetUserCode(),
            'interval': tempOA.Interval,
        }

    def print(self, *a, **k):
        if self._debug:
            print(*a, **k)


if __name__ == '__main__':
    # from oauth_tools import AuthManager
    import webbrowser
    import creds
    import os

    if not os.path.exists('users.json'):
        open('users.json', mode='wt').write(json.dumps({}))

    authManager = AuthManager(
        microsoftClientID=creds.clientID,
        microsoftTenantID=creds.tenantID,
    )

    authManager.SaveIncompleteOACallback = lambda ID, data: open('incomplete.json', mode='wt').write(
        json.dumps({ID: data}, indent=2))
    authManager.GetIncompleteOACallback = lambda ID: json.loads(open('incomplete.json', mode='rt').read()).get(ID, None)

    authManager.SaveToDBCallback = lambda ID, data: open('users.json', mode='wt').write(
        json.dumps({ID: data}, indent=2))
    authManager.GetFromDBCallback = lambda ID: json.loads(open('users.json', mode='rt').read()).get(ID, None)

    MY_ID = 'Grant'

    user = authManager.GetUserByID(MY_ID)
    if user is None:
        # the user has not authenticated before
        d = authManager.CreateNewUser(MY_ID)
        webbrowser.open(d['verification_uri'])
        print('Enter the code', d['user_code'])

        while True:
            time.sleep(d['interval'])
            status = authManager.CheckOAStatus(MY_ID)
            print('status=', status)
            if status == 'Success':
                break

        user = authManager.GetUserByID(MY_ID)

    print('user=', user)
