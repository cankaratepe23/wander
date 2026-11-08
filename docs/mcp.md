# Using Wander from the Claude app (MCP)

Wander serves a remote MCP server at `/mcp` (PLAN.md §4.4) with the same tools as in-app chat: search ideas, read and
update them, fix or merge places, save new ideas, shortlist, and rank hotspots. Long "plan our spring" brainstorms then
run in the Claude app on a Claude subscription and write their results back into Wander, with no API credit spent.

## How it's protected

The MCP server lives on its own hostname (`wander-mcp.<your domain>`) behind a Cloudflare Access application that
uses **managed OAuth**: when you add the connector, the Claude app opens Access's sign-in, and Access hands it a token.
Every request still reaches Wander with an Access JWT, which Wander verifies like any API call (signature, audience,
issuer, allowed emails). The tools run as the signed-in person.

## Setup (once)

1. **Route the hostname.** In the tunnel, add `wander-mcp.<your domain>` → the same service as the app
   (`http://wander-api:8000` on the shared network).
2. **Create the Access application.** Zero Trust → Access → Applications → Add → *Self-hosted* (or the *MCP server*
   type, if your dashboard offers it) for `wander-mcp.<your domain>`, with **managed OAuth** turned on and the same
   allow-by-email policy as the app.
3. **Trust its audience.** Copy the new application's AUD tag and add it to Wander's secrets next to the app's, as a
   comma-separated list:
   ```
   WANDER_ACCESS_AUD=<app AUD>,<mcp AUD>
   ```
   Restart the API.
4. **Add the connector.** In the Claude app: Settings → Connectors → *Add custom connector*, URL
   `https://wander-mcp.<your domain>/mcp`. Sign in when Access asks.

## Check it

Ask Claude: *"What do we have around the Aegean coast?"* It should call `search_ideas` and answer from your saved ideas.
Then try a change (*"shortlist the Lycian Way"*) and watch it appear in the app.

If the connector can't connect:
- *401 invalid Access token* in the API log: the MCP application's AUD isn't in `WANDER_ACCESS_AUD`.
- *403 email not allowed*: the address you signed in with isn't in `WANDER_ALLOWED_EMAILS`.
- No request reaches the API at all: check the tunnel route for the hostname.
