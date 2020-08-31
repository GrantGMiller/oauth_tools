An easy interface for Microsoft Office 365 Oauth Device Code authentication.

Install
=======
pip install oauth_tools

Example
=======

::


    from oauth_tools import AuthManager
    import webbrowser
    import creds
    import os

    if not os.path.exists('users.json'):
        open('users.json', mode='wt').write(json.dumps({}))

    authManager = AuthManager(
        # Get your client/tenant ID by following these instructions:
        # https://docs.microsoft.com/en-us/azure/storage/common/storage-auth-aad-app
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

The output looks like

::

    >>> Enter the code A4S4QS4EG
    >>> status= Waiting for user to authenticate
    >>> status= Success
    >>> user= <User: ID=Grant, EmailAddress=grant@grant-miller.com, AccessToken=abcdefghijklm...>
