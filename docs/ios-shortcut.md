# Saving to Wander from an iPhone

iOS Safari doesn't support web share targets ([WebKit bug 194593](https://bugs.webkit.org/show_bug.cgi?id=194593)), so on
an iPhone, sharing goes through an Apple Shortcut that posts to `/api/capture` (PLAN.md §4.1). It signs in with a
Cloudflare Access **service token**, which Wander lets save captures and nothing else.

Do this once per iPhone. You need about ten minutes and access to the Cloudflare Zero Trust dashboard.

## 1. Create a service token (Cloudflare)

1. Zero Trust → **Access → Service auth → Service tokens → Create service token**.
2. Name it after the person, e.g. `wander-shortcut-sam`. Choose a long duration (or non-expiring) and note when it
   expires.
3. Copy the **Client ID** and **Client Secret** now. The secret is shown only once.

## 2. Let the token reach the capture endpoint (Cloudflare)

Add a second Access application just for the capture path, so the token works there and nowhere else:

1. Access → **Applications → Add an application → Self-hosted**.
2. Domain: your Wander host, with **path** `api/capture`.
3. Policies, both on this application (a path application replaces the main one for that path, so people need to be
   allowed here too):
   - **Allow** with the same email rule as the main Wander application.
   - **Service Auth** with *Include → Service Token →* the token(s) from step 1.
4. Save. Leave the main Wander application as it is.

## 3. Tell Wander who the token saves for

Map the token's Client ID to the person's login email in the deployment's secrets:

```
WANDER_SERVICE_TOKENS=<client id>=sam@example.com
```

Separate several tokens with commas. Restart the API. A token that isn't in this list gets *403*, and a mapped token
gets *403* everywhere except `POST /api/capture`.

## 4. Build the Shortcut (iPhone)

In the **Shortcuts** app, create a new shortcut called **Save to Wander**:

1. Open its settings (ⓘ) and turn on **Show in Share Sheet**. Under *Share Sheet Types*, keep **Images, URLs, Text and
   Safari web pages**. Set *If there's no input* to **Ask For → Text**.
2. Add **If** → *Shortcut Input* → *has any value*… then change the condition to **Shortcut Input is Image**
   (tap the variable → *Type* → *Image*).
3. Inside the *If* branch, add **Get Contents of URL**:
   - URL: `https://<your Wander host>/api/capture`
   - Method: **POST**
   - Headers: `CF-Access-Client-Id` = *Client ID*, `CF-Access-Client-Secret` = *Client Secret*
   - Request Body: **Form**, with fields `file` (type *File*) = *Shortcut Input*, and `source_app` = `ios-shortcut`
4. In the **Otherwise** branch, add another **Get Contents of URL** with the same URL, method and headers, but a
   **JSON** body: `text` = *Shortcut Input*, `source_app` = `ios-shortcut`.
5. After *End If*, add **Show Notification** with the text *Saved to Wander ✓*.

## 5. Try it

Share a TikTok or Instagram post, or a Safari page, then **Save to Wander**. The notification appears within a
second, and the capture shows up in the app as *Saved*, then *Filed* once the worker has read it.

If it fails:
- *403*: the Client ID isn't in `WANDER_SERVICE_TOKENS`, or the path application's Service Auth policy doesn't include
  the token.
- An HTML page or a redirect instead of JSON: the request didn't match the path application. Check that the path is
  `api/capture`.
- When the token expires, create a new one, update the Shortcut's two headers and the mapping, and restart the API.
