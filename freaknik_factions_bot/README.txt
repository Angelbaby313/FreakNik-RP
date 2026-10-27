FREAKNIK RP FACTIONS BOT
Server ID: 1564703180154077247

WHAT IT DOES
- /setup creates the full Factions Discord layout, roles, permissions, VCs and panels.
- Become A Faction application -> private staff review with Approve/Deny buttons.
- Private interaction clip submission -> staff review with Approve/Deny buttons.
- Keeps a normal interaction-approval channel too.
- General support ticket button + Support VC.
- /strike logs faction strikes.
- /whitelist gives WL Faction access.

DISCORD DEVELOPER PORTAL
1. Create a new application and Bot.
2. Turn ON Server Members Intent under Bot > Privileged Gateway Intents.
3. Reset/copy your bot token. NEVER post the token in Discord or send it to anyone.
4. OAuth2 > URL Generator: select bot + applications.commands.
5. Bot permissions: Administrator is easiest for initial setup because /setup creates roles/channels and manages permissions.
6. Invite the bot to FreakNik RP Factions server.
7. IMPORTANT: Move the bot's role ABOVE the faction roles after setup if you want /whitelist to manage those roles.

RAILWAY
1. Upload these files to a new Railway service/repo.
2. Add Variable: DISCORD_TOKEN = your bot token
3. Deploy.
4. In Discord run /setup ONE TIME as an Administrator.

IMPORTANT
- /setup is designed for Server ID 1564703180154077247.
- config.json is generated automatically after /setup. On hosts with ephemeral storage, rerunning /setup will rediscover existing named roles/channels and refresh config without intentionally duplicating them.
- Do not run /setup repeatedly unless needed.
- The bot needs Manage Channels, Manage Roles, View Channels, Send Messages, Embed Links, Read Message History, and Use Application Commands. Administrator covers these during setup.
