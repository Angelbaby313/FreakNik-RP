import os, json, asyncio, re
from datetime import datetime, timezone
import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_GUILD_ID = int(os.getenv('GUILD_ID', '1564703180154077247'))
OWNER_ID = int(os.getenv('OWNER_ID', '1218157284715401322'))
CONFIG_FILE = 'config.json'

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def guild_cfg(guild_id):
    return load_config().get(str(guild_id), {})

def owner_check(member: discord.Member):
    return member.id == OWNER_ID

def staff_check(member: discord.Member, cfg):
    ids = {cfg.get('roles', {}).get(k) for k in ['head','management','staff']}
    return owner_check(member) or member.guild_permissions.administrator or any(r.id in ids for r in member.roles)

async def safe_defer(interaction, ephemeral=True):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=ephemeral)


COLOR_NAMES = {'red':0xE74C3C,'green':0x2ECC71,'lime':0x39FF14,'blue':0x3498DB,'purple':0x9B59B6,'pink':0xFF69B4,'orange':0xE67E22,'yellow':0xF1C40F,'gold':0xF1C40F,'black':0x111111,'white':0xFFFFFF,'gray':0x95A5A6,'grey':0x95A5A6,'teal':0x1ABC9C,'cyan':0x00FFFF}

def parse_gang_color(value):
    raw=(value or '').strip()
    if raw.lower() in COLOR_NAMES: return discord.Color(COLOR_NAMES[raw.lower()])
    h=raw.lstrip('#')
    if re.fullmatch(r'[0-9a-fA-F]{6}', h): return discord.Color(int(h,16))
    return discord.Color.default()

def field_value(embed, name):
    for f in embed.fields:
        if f.name.lower()==name.lower(): return f.value
    return None

def submitter_id(embed):
    m=re.search(r'(\d{15,22})\s*$', embed.footer.text or '')
    return int(m.group(1)) if m else None

async def build_approved_faction(interaction, embed, cfg):
    g=interaction.guild
    name=(field_value(embed,'Faction') or 'Faction').strip()[:80]
    color_text=(field_value(embed,'Gang Color') or '').strip()
    uid=submitter_id(embed)
    leader=g.get_member(uid) if uid else None
    if leader is None and uid:
        try: leader=await g.fetch_member(uid)
        except discord.HTTPException: leader=None
    if leader is None: raise RuntimeError('Could not find the leader who submitted this application.')

    gang_role=discord.utils.get(g.roles,name=f'🔫・{name}')
    if gang_role is None:
        gang_role=await g.create_role(name=f'🔫・{name}',color=parse_gang_color(color_text),reason=f'Faction approved by {interaction.user}')

    leader_role=g.get_role(cfg.get('roles',{}).get('leader'))
    wl_role=g.get_role(cfg.get('roles',{}).get('wl'))

    # Keep the gang-specific role above Gang Leaders/WL Faction so the gang
    # color becomes the member's displayed Discord name color.
    if leader_role:
        try:
            await g.edit_role_positions(
                positions={gang_role: leader_role.position + 1},
                reason=f'Prioritize {name} gang color'
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
    add=[r for r in (leader_role,wl_role,gang_role) if r]
    if add: await leader.add_roles(*add,reason=f'Faction approved by {interaction.user}')

    ow={g.default_role:discord.PermissionOverwrite(view_channel=False),
        gang_role:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,connect=True,speak=True)}
    for k in ['head','management','staff']:
        r=g.get_role(cfg.get('roles',{}).get(k))
        if r: ow[r]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,connect=True,speak=True)

    cat_name=f'🔒・{name.upper()}'[:100]
    cat=discord.utils.get(g.categories,name=cat_name)
    if cat is None: cat=await g.create_category(cat_name,overwrites=ow,reason=f'Faction approved by {interaction.user}')

    for chname,readonly in [('📢・announcements',True),('💬・gang-chat',False),('🎥・gang-clips',False)]:
        if not discord.utils.get(cat.text_channels,name=chname):
            cow=dict(ow)
            if readonly: cow[gang_role]=discord.PermissionOverwrite(view_channel=True,send_messages=False,read_message_history=True)
            await g.create_text_channel(chname,category=cat,overwrites=cow)
    if not discord.utils.get(cat.voice_channels,name='🔊・Gang VC'):
        await g.create_voice_channel('🔊・Gang VC',category=cat,overwrites=ow)

    wlch=g.get_channel(cfg.get('channels',{}).get('whitelisted'))
    if wlch:
        e=discord.Embed(title=f'💯 {name}',color=parse_gang_color(color_text))
        e.add_field(name='Leader',value=leader.mention,inline=False)
        e.add_field(name='Block',value=field_value(embed,'Block') or 'N/A',inline=True)
        e.add_field(name='Gang Color',value=color_text or 'Default',inline=True)
        await wlch.send(embed=e)
    return leader,gang_role,cat

class DecisionView(discord.ui.View):
    def __init__(self, kind: str):
        super().__init__(timeout=None)
        self.kind = kind

    async def decide(self, interaction: discord.Interaction, approved: bool):
        cfg=guild_cfg(interaction.guild_id)
        if not staff_check(interaction.user,cfg):
            return await interaction.response.send_message('Faction Staff only.',ephemeral=True)
        embed=interaction.message.embeds[0].copy() if interaction.message.embeds else discord.Embed()
        if approved and self.kind=='application':
            await interaction.response.defer(ephemeral=True)
            try:
                leader,gang_role,cat=await build_approved_faction(interaction,embed,cfg)
            except Exception as exc:
                return await interaction.followup.send(f'Could not finish faction approval: {exc}',ephemeral=True)
            embed.color=discord.Color.green()
            embed.add_field(name='Decision',value=f'APPROVED ✅ by {interaction.user.mention}\nLeader: {leader.mention}\nRole: {gang_role.mention}\nCategory: **{cat.name}**',inline=False)
            await interaction.message.edit(embed=embed,view=None)
            return await interaction.followup.send(f'✅ {field_value(embed,"Faction")} approved. Gang role and private section created.',ephemeral=True)
        embed.color=discord.Color.green() if approved else discord.Color.red()
        embed.add_field(name='Decision',value=f"{'APPROVED ✅' if approved else 'DENIED ❌'} by {interaction.user.mention}",inline=False)
        await interaction.response.edit_message(embed=embed,view=None)

    @discord.ui.button(label='Approve', style=discord.ButtonStyle.success, custom_id='factions:approve')
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.decide(interaction, True)

    @discord.ui.button(label='Deny', style=discord.ButtonStyle.danger, custom_id='factions:deny')
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.decide(interaction, False)

class FactionApplicationModal(discord.ui.Modal, title='Become a Faction'):
    faction = discord.ui.TextInput(label='Faction / Gang Name', max_length=80)
    color = discord.ui.TextInput(label='Gang Color', placeholder='Green or #39FF14', max_length=30)
    members = discord.ui.TextInput(label='Current Member Count', max_length=30)
    block = discord.ui.TextInput(label='Requested Block / Area', required=False, max_length=100)
    info = discord.ui.TextInput(label='Tell us about your faction', style=discord.TextStyle.paragraph, max_length=1000)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = guild_cfg(interaction.guild_id)
        ch = interaction.guild.get_channel(cfg.get('channels', {}).get('faction_applications'))
        if not ch:
            return await interaction.response.send_message('Application review channel is not configured. Run /setup.', ephemeral=True)
        e = discord.Embed(title='🔫 New Faction Application', color=discord.Color.dark_red(), timestamp=datetime.now(timezone.utc))
        e.add_field(name='Faction', value=self.faction.value, inline=False)
        e.add_field(name='Leader', value=interaction.user.mention, inline=False)
        e.add_field(name='Gang Color', value=self.color.value, inline=True)
        e.add_field(name='Members', value=self.members.value, inline=True)
        e.add_field(name='Block', value=self.block.value or 'N/A', inline=True)
        e.add_field(name='About', value=self.info.value, inline=False)
        e.set_footer(text=f'Submitted by {interaction.user} • {interaction.user.id}')
        await ch.send(embed=e, view=DecisionView('application'))
        await interaction.response.send_message('Your faction application was submitted to staff. 💯', ephemeral=True)

class InteractionModal(discord.ui.Modal, title='Submit Interaction Clip'):
    faction = discord.ui.TextInput(label='Faction Name', max_length=80)
    players = discord.ui.TextInput(label='Players / Factions Involved', max_length=200)
    details = discord.ui.TextInput(label='Interaction Details', style=discord.TextStyle.paragraph, max_length=700)
    clip = discord.ui.TextInput(label='Clip Link', placeholder='https://...', max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = guild_cfg(interaction.guild_id)
        ch = interaction.guild.get_channel(cfg.get('channels', {}).get('interaction_reviews'))
        if not ch:
            return await interaction.response.send_message('Interaction review channel is not configured. Run /setup.', ephemeral=True)
        e = discord.Embed(title='🎥 Interaction Review', color=discord.Color.orange(), timestamp=datetime.now(timezone.utc))
        e.add_field(name='Faction', value=self.faction.value, inline=False)
        e.add_field(name='Involved', value=self.players.value, inline=False)
        e.add_field(name='Details', value=self.details.value, inline=False)
        e.add_field(name='Clip', value=self.clip.value, inline=False)
        e.set_footer(text=f'Submitted by {interaction.user} • {interaction.user.id}')
        await ch.send(embed=e, view=DecisionView('interaction'))
        await interaction.response.send_message('Clip submitted to Faction Staff for review. 🎥', ephemeral=True)


class GangRoleRequestModal(discord.ui.Modal, title='Request A Gang Role'):
    gang = discord.ui.TextInput(label='Gang Name', placeholder='Example: Cheetah Girls', max_length=80)

    async def on_submit(self, interaction: discord.Interaction):
        cfg=guild_cfg(interaction.guild_id)
        gang_role=find_gang_role(interaction.guild,self.gang.value)
        if gang_role is None:
            return await interaction.response.send_message(
                f'❌ I could not find an approved gang named **{self.gang.value}**.',ephemeral=True
            )
        ch=interaction.guild.get_channel(cfg.get('channels',{}).get('role_requests'))
        if not ch:
            return await interaction.response.send_message('Role request channel is not configured.',ephemeral=True)

        e=discord.Embed(title='🎭 Gang Role Request',color=gang_role.color,timestamp=datetime.now(timezone.utc))
        e.add_field(name='Member',value=f'{interaction.user.mention} (`{interaction.user.id}`)',inline=False)
        e.add_field(name='Gang',value=gang_role.name.split('・',1)[-1],inline=False)
        e.add_field(name='Status',value='⏳ Waiting for Gang Leader approval',inline=False)
        e.set_footer(text=f'Requester ID: {interaction.user.id} • Gang Role ID: {gang_role.id}')
        await ch.send(embed=e)
        await interaction.response.send_message(
            f'✅ Your request for **{gang_role.name.split("・",1)[-1]}** was sent. Your Gang Leader must use `/approve` on you.',
            ephemeral=True
        )

class GangRoleRequestView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='Request Gang Role',emoji='🎭',style=discord.ButtonStyle.primary,custom_id='factions:role_request')
    async def request_role(self,interaction,button):
        await interaction.response.send_modal(GangRoleRequestModal())

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Open Ticket', emoji='🎟️', style=discord.ButtonStyle.primary, custom_id='factions:ticket')
    async def ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = guild_cfg(interaction.guild_id)
        guild = interaction.guild
        category = guild.get_channel(cfg.get('categories', {}).get('support'))
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message('Support category missing. Run /setup.', ephemeral=True)
        existing = discord.utils.get(category.text_channels, topic=f'ticket-owner:{interaction.user.id}')
        if existing:
            return await interaction.response.send_message(f'You already have an open ticket: {existing.mention}', ephemeral=True)
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)}
        for key in ['head','management','staff']:
            role = guild.get_role(cfg.get('roles', {}).get(key))
            if role: overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        ch = await guild.create_text_channel(f'ticket-{interaction.user.name}'[:90], category=category, topic=f'ticket-owner:{interaction.user.id}', overwrites=overwrites)
        await ch.send(f'{interaction.user.mention} welcome. Tell Faction Staff what you need help with.', view=CloseTicketView())
        await interaction.response.send_message(f'Ticket opened: {ch.mention}', ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label='Close Ticket', emoji='🔒', style=discord.ButtonStyle.danger, custom_id='factions:close_ticket')
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Closing ticket...', ephemeral=True)
        await asyncio.sleep(1)
        await interaction.channel.delete(reason=f'Ticket closed by {interaction.user}')

class ApplyView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='Apply To Be A Faction', emoji='🔫', style=discord.ButtonStyle.danger, custom_id='factions:apply')
    async def apply(self, interaction, button): await interaction.response.send_modal(FactionApplicationModal())

class SubmitInteractionView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='Submit Interaction', emoji='🎥', style=discord.ButtonStyle.primary, custom_id='factions:submit_interaction')
    async def submit(self, interaction, button): await interaction.response.send_modal(InteractionModal())

@bot.event
async def on_ready():
    bot.add_view(TicketView()); bot.add_view(CloseTicketView()); bot.add_view(ApplyView()); bot.add_view(SubmitInteractionView()); bot.add_view(GangRoleRequestView()); bot.add_view(DecisionView('persistent'))
    guild = bot.get_guild(TARGET_GUILD_ID)
    if guild:
        try:
            await bot.tree.sync(guild=guild)
        except Exception as e: print('Sync error:', e)
    print(f'Logged in as {bot.user}')

guild_obj = discord.Object(id=TARGET_GUILD_ID)

@bot.tree.command(name='setup', description='Build the FreakNik RP Factions Discord', guild=guild_obj)
async def setup(interaction: discord.Interaction):
    if not (owner_check(interaction.user) or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message('Only the bot owner or a server Administrator can run /setup.', ephemeral=True)
    await safe_defer(interaction)
    g = interaction.guild
    # roles bottom-up to preserve hierarchy
    role_specs = [('wl','💯・WL Faction'),('leader','💰・Gang Leaders'),('staff','🔫・Faction Staff'),('management','💼・Faction Management'),('head','👑・Head Of Factions')]
    roles = {}
    for key,name in role_specs:
        role = discord.utils.get(g.roles, name=name) or await g.create_role(name=name, reason='FreakNik Factions setup')
        roles[key]=role.id

    staff_roles = [g.get_role(roles[k]) for k in ['staff','management','head']]
    wl_roles = [g.get_role(roles[k]) for k in ['wl','leader','staff','management','head']]
    async def category(name, private=False, wl=False):
        c = discord.utils.get(g.categories, name=name)
        if c: return c
        ow = None
        if private or wl:
            ow={g.default_role: discord.PermissionOverwrite(view_channel=False)}
            for r in (wl_roles if wl else staff_roles): ow[r]=discord.PermissionOverwrite(view_channel=True)
        if ow is None:
            return await g.create_category(name)
        return await g.create_category(name, overwrites=ow)
    welcome=await category('🔫・WELCOME')
    factions=await category('💰・FACTIONS')
    wlcat=await category('🔒・WL FACTIONS', wl=True)
    support=await category('🎧・SUPPORT')
    staffcat=await category('🔐・FACTION STAFF', private=True)

    async def text(cat,name, readonly=False):
        ch=discord.utils.get(cat.text_channels,name=name)
        if ch:return ch
        ow=None
        if readonly:
            ow={g.default_role:discord.PermissionOverwrite(send_messages=False,view_channel=True)}
            for r in staff_roles: ow[r]=discord.PermissionOverwrite(send_messages=True,view_channel=True)
        if ow is None:
            return await g.create_text_channel(name, category=cat)
        return await g.create_text_channel(name, category=cat, overwrites=ow)
    async def voice(cat,name):
        return discord.utils.get(cat.voice_channels,name=name) or await g.create_voice_channel(name,category=cat)

    channels={}
    channels['welcome']=(await text(welcome,'👋🏾・welcome',True)).id
    channels['announcements']=(await text(welcome,'📢・announcements',True)).id
    channels['rules']=(await text(welcome,'📜・faction-rules',True)).id
    channels['become']=(await text(welcome,'🎟️・become-a-faction')).id
    channels['blocks']=(await text(factions,'📍・blocks',True)).id
    channels['whitelisted']=(await text(factions,'💯・whitelisted-gangs',True)).id
    channels['events']=(await text(factions,'📅・faction-events',True)).id
    channels['recruitment']=(await text(factions,'📣・recruitment')).id
    channels['clips']=(await text(wlcat,'🎥・faction-clips')).id
    channels['beef']=(await text(wlcat,'🥩・beef-chat')).id
    channels['interaction_approval']=(await text(wlcat,'📹・interaction-approval')).id
    channels['submit_interaction']=(await text(wlcat,'🎫・submit-interaction')).id
    channels['role_requests']=(await text(factions,'🎭・role-request')).id
    channels['faction_meeting_vc']=(await voice(wlcat,'🔊・Faction Meeting VC')).id
    channels['open_ticket']=(await text(support,'🎟️・open-a-ticket')).id
    channels['suggestions']=(await text(support,'💡・suggestions')).id
    channels['support_vc']=(await voice(support,'🔊・Support VC')).id
    channels['staff_chat']=(await text(staffcat,'💬・staff-chat')).id
    channels['faction_applications']=(await text(staffcat,'📥・faction-applications')).id
    channels['interaction_reviews']=(await text(staffcat,'🎥・interaction-reviews')).id
    channels['faction_strikes']=(await text(staffcat,'⚠️・faction-strikes')).id
    channels['staff_notes']=(await text(staffcat,'📝・staff-notes')).id
    channels['staff_vc']=(await voice(staffcat,'🔊・Staff VC')).id

    data=load_config(); data[str(g.id)]={'roles':roles,'channels':channels,'categories':{'support':support.id,'staff':staffcat.id,'wl':wlcat.id}}; save_config(data)

    become=g.get_channel(channels['become']); ticket=g.get_channel(channels['open_ticket']); submit=g.get_channel(channels['submit_interaction']); role_req=g.get_channel(channels['role_requests'])
    await become.send(embed=discord.Embed(title='🔫 Become A Faction',description='Ready to bring your faction into FreakNik RP? Hit the button below to submit your application.',color=discord.Color.dark_red()),view=ApplyView())
    await ticket.send(embed=discord.Embed(title='🎧 Faction Support',description='Need help? Open one general support ticket below.',color=discord.Color.dark_red()),view=TicketView())
    await submit.send(embed=discord.Embed(title='🎥 Submit An Interaction',description='Submit your interaction clip privately for Faction Staff to review and approve or deny.',color=discord.Color.dark_red()),view=SubmitInteractionView())
    await role_req.send(embed=discord.Embed(title='🎭 Request Your Gang Role',description='Need your gang role? Hit the button below, enter your gang name, then have your Gang Leader approve you with `/approve`.',color=discord.Color.dark_red()),view=GangRoleRequestView())
    await interaction.followup.send('✅ FreakNik RP Factions setup is complete. Roles, categories, channels, VCs and panels were created.',ephemeral=True)


def normalize_faction_name(name):
    # Ignore capitalization, extra spaces, Discord separators, emoji/prefixes and punctuation.
    value = (name or '').strip().lower()
    value = value.replace('・', ' ').replace('_', ' ').replace('-', ' ')
    value = re.sub(r'^[^a-z0-9]+', '', value)
    value = re.sub(r'\s+', ' ', value).strip()
    return value

def find_gang_role(guild, faction):
    wanted = normalize_faction_name(faction)
    for role in guild.roles:
        role_name = role.name
        if role_name.startswith('🔫・'):
            role_name = role_name.split('・', 1)[1]
        if normalize_faction_name(role_name) == wanted:
            return role
    return None

def find_gang_category(guild, faction):
    wanted = normalize_faction_name(faction)
    for category in guild.categories:
        category_name = category.name
        if category_name.startswith('🔒・'):
            category_name = category_name.split('・', 1)[1]
        if normalize_faction_name(category_name) == wanted:
            return category
    return None

def faction_strike_record(guild_id, faction):
    data = load_config()
    gid = str(guild_id)
    data.setdefault(gid, {})
    data[gid].setdefault('strikes', {})
    key = normalize_faction_name(faction)
    data[gid]['strikes'].setdefault(key, {'name': faction.strip(), 'active': [], 'history': []})
    return data, data[gid]['strikes'][key]


@bot.tree.command(name='registergang', description='Faction Staff: register a gang and create its full Discord setup', guild=guild_obj)
@app_commands.describe(
    gang_name='Official gang/faction name',
    leader='Initial Gang Leader',
    gang_color='Gang color name or hex, e.g. Red or #FF0000'
)
async def registergang(
    interaction: discord.Interaction,
    gang_name: str,
    leader: discord.Member,
    gang_color: str
):
    cfg = guild_cfg(interaction.guild_id)

    if not staff_check(interaction.user, cfg):
        return await interaction.response.send_message('❌ Faction Staff only.', ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    g = interaction.guild
    name = gang_name.strip()[:80]
    color_text = gang_color.strip()

    if not name:
        return await interaction.followup.send('❌ Enter a gang name.', ephemeral=True)

    # Stop duplicate gang registrations.
    if find_gang_role(g, name) or find_gang_category(g, name):
        return await interaction.followup.send(
            f'❌ **{name}** is already registered. No duplicate was created.',
            ephemeral=True
        )

    try:
        # Create gang-specific colored role.
        gang_role = await g.create_role(
            name=f'🔫・{name}',
            color=parse_gang_color(color_text),
            reason=f'Faction registered by {interaction.user}'
        )

        leader_role = g.get_role(cfg.get('roles', {}).get('leader'))
        wl_role = g.get_role(cfg.get('roles', {}).get('wl'))

        # Put gang role above Gang Leader/WL so gang color displays.
        if leader_role:
            try:
                await g.edit_role_positions(
                    positions={gang_role: leader_role.position + 1},
                    reason=f'Prioritize {name} gang color'
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

        # Give initial leader all required faction roles.
        roles_to_add = [r for r in (leader_role, wl_role, gang_role) if r]
        if roles_to_add:
            await leader.add_roles(
                *roles_to_add,
                reason=f'Initial leader of {name}; registered by {interaction.user}'
            )

        # Private permissions for this gang and faction staff.
        overwrites = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            gang_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                connect=True,
                speak=True
            )
        }

        for key in ['head', 'management', 'staff']:
            staff_role = g.get_role(cfg.get('roles', {}).get(key))
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    connect=True,
                    speak=True
                )

        # Create private gang category.
        category = await g.create_category(
            f'🔒・{name.upper()}'[:100],
            overwrites=overwrites,
            reason=f'Faction registered by {interaction.user}'
        )

        # Create gang channels.
        announcement_overwrites = dict(overwrites)
        announcement_overwrites[gang_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True
        )

        await g.create_text_channel(
            '📢・announcements',
            category=category,
            overwrites=announcement_overwrites
        )
        await g.create_text_channel(
            '💬・gang-chat',
            category=category,
            overwrites=overwrites
        )
        await g.create_text_channel(
            '🎥・gang-clips',
            category=category,
            overwrites=overwrites
        )
        await g.create_voice_channel(
            '🔊・Gang VC',
            category=category,
            overwrites=overwrites
        )

        # Add official faction listing.
        whitelist_ch = g.get_channel(cfg.get('channels', {}).get('whitelisted'))
        if whitelist_ch:
            embed = discord.Embed(
                title=f'💯 {name}',
                description='Officially registered by Faction Staff.',
                color=parse_gang_color(color_text),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name='Gang Leader', value=leader.mention, inline=False)
            embed.add_field(name='Gang Color', value=color_text or 'Default', inline=True)
            embed.add_field(name='Registered By', value=interaction.user.mention, inline=True)
            await whitelist_ch.send(embed=embed)

        await interaction.followup.send(
            f'✅ **{name}** is registered!\n'
            f'👑 Leader: {leader.mention}\n'
            f'🎭 Role: {gang_role.mention}\n'
            f'🔒 Private gang category + channels created.',
            ephemeral=True
        )

    except discord.Forbidden:
        await interaction.followup.send(
            '❌ I am missing Discord permissions. Make sure my bot role is high enough and has Manage Roles + Manage Channels.',
            ephemeral=True
        )
    except discord.HTTPException as exc:
        await interaction.followup.send(f'❌ Discord could not finish the gang setup: {exc}', ephemeral=True)


@bot.tree.command(name='strike', description='Give a faction an official strike', guild=guild_obj)
@app_commands.describe(faction='Exact faction/gang name', reason='Reason for the strike')
async def strike(interaction: discord.Interaction, faction: str, reason: str):
    cfg = guild_cfg(interaction.guild_id)
    if not staff_check(interaction.user, cfg):
        return await interaction.response.send_message('Faction Staff only.', ephemeral=True)

    gang_role = find_gang_role(interaction.guild, faction)
    if gang_role is None:
        return await interaction.response.send_message(
            f'❌ I could not find an approved faction named **{faction.strip()}**. Check the gang name and try again.',
            ephemeral=True
        )

    data, record = faction_strike_record(interaction.guild_id, faction)
    if len(record['active']) >= 3:
        return await interaction.response.send_message(
            f'🚨 **{record["name"]}** already has 3/3 active strikes and is up for disband review.',
            ephemeral=True
        )

    entry = {
        'reason': reason,
        'issued_by_id': interaction.user.id,
        'issued_by': str(interaction.user),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    record['active'].append(entry)
    record['history'].append({'action': 'issued', **entry})
    save_config(data)

    count = len(record['active'])
    ch = interaction.guild.get_channel(cfg.get('channels', {}).get('faction_strikes'))
    if ch:
        e = discord.Embed(
            title='⚠️ Official Faction Strike',
            color=discord.Color.red() if count >= 3 else discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        e.add_field(name='Faction', value=record['name'], inline=False)
        e.add_field(name='Strike Count', value=f'**{count}/3**', inline=True)
        e.add_field(name='Reason', value=reason, inline=False)
        e.add_field(name='Issued By', value=interaction.user.mention, inline=False)
        if count >= 3:
            e.add_field(
                name='🚨 Status',
                value='**3/3 STRIKES — UP FOR DISBAND REVIEW**\nStaff must use `/disband` if the faction is being removed.',
                inline=False
            )
        await ch.send(embed=e)

    msg = f'⚠️ **{record["name"]}** now has **{count}/3** active strikes.'
    if count >= 3:
        msg += ' 🚨 They are now **UP FOR DISBAND REVIEW**.'
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name='removestrike', description='Remove one active strike from a faction', guild=guild_obj)
@app_commands.describe(faction='Exact faction/gang name', reason='Why the strike is being removed')
async def removestrike(interaction: discord.Interaction, faction: str, reason: str):
    cfg = guild_cfg(interaction.guild_id)
    if not staff_check(interaction.user, cfg):
        return await interaction.response.send_message('Faction Staff only.', ephemeral=True)

    data = load_config()
    gid = str(interaction.guild_id)
    key = normalize_faction_name(faction)
    record = data.get(gid, {}).get('strikes', {}).get(key)

    if not record or not record.get('active'):
        return await interaction.response.send_message(
            f'❌ **{faction.strip()}** does not have any active strikes to remove.',
            ephemeral=True
        )

    removed = record['active'].pop()
    record.setdefault('history', []).append({
        'action': 'removed',
        'original_reason': removed.get('reason', 'N/A'),
        'removal_reason': reason,
        'removed_by_id': interaction.user.id,
        'removed_by': str(interaction.user),
        'timestamp': datetime.now(timezone.utc).isoformat()
    })
    save_config(data)

    count = len(record['active'])
    ch = interaction.guild.get_channel(cfg.get('channels', {}).get('faction_strikes'))
    if ch:
        e = discord.Embed(
            title='✅ Faction Strike Removed',
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        e.add_field(name='Faction', value=record['name'], inline=False)
        e.add_field(name='New Strike Count', value=f'**{count}/3**', inline=True)
        e.add_field(name='Removed Strike', value=removed.get('reason', 'N/A'), inline=False)
        e.add_field(name='Removal Reason', value=reason, inline=False)
        e.add_field(name='Removed By', value=interaction.user.mention, inline=False)
        await ch.send(embed=e)

    await interaction.response.send_message(
        f'✅ Removed one strike from **{record["name"]}**. They now have **{count}/3** active strikes.',
        ephemeral=True
    )


@bot.tree.command(name='strikes', description='Check a faction strike count and recent history', guild=guild_obj)
@app_commands.describe(faction='Exact faction/gang name')
async def strikes(interaction: discord.Interaction, faction: str):
    cfg = guild_cfg(interaction.guild_id)
    if not staff_check(interaction.user, cfg):
        return await interaction.response.send_message('Faction Staff only.', ephemeral=True)

    data = load_config()
    key = normalize_faction_name(faction)
    record = data.get(str(interaction.guild_id), {}).get('strikes', {}).get(key)

    if not record:
        return await interaction.response.send_message(
            f'**{faction.strip()}** has **0/3** active strikes and no strike history.',
            ephemeral=True
        )

    active = record.get('active', [])
    history = record.get('history', [])
    e = discord.Embed(
        title=f'⚠️ {record["name"]} Strike Record',
        color=discord.Color.red() if len(active) >= 3 else discord.Color.orange(),
        timestamp=datetime.now(timezone.utc)
    )
    e.add_field(name='Active Strikes', value=f'**{len(active)}/3**', inline=False)

    if active:
        active_text = '\n'.join(
            f'**{i}.** {item.get("reason", "No reason")}'
            for i, item in enumerate(active, 1)
        )
        e.add_field(name='Current Strikes', value=active_text[:1024], inline=False)

    if history:
        recent = history[-5:]
        history_lines = []
        for item in reversed(recent):
            if item.get('action') == 'issued':
                history_lines.append(f'➕ {item.get("reason", "No reason")} — {item.get("issued_by", "Staff")}')
            else:
                history_lines.append(f'➖ Removed: {item.get("original_reason", "N/A")} — {item.get("removal_reason", "No reason")}')
        e.add_field(name='Recent History', value='\n'.join(history_lines)[:1024], inline=False)

    if len(active) >= 3:
        e.add_field(name='🚨 Status', value='UP FOR DISBAND REVIEW', inline=False)

    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name='whitelist', description='Give a member the WL Faction role', guild=guild_obj)
async def whitelist(interaction: discord.Interaction, member: discord.Member):
    cfg=guild_cfg(interaction.guild_id)
    if not staff_check(interaction.user,cfg): return await interaction.response.send_message('Faction Staff only.',ephemeral=True)
    role=interaction.guild.get_role(cfg.get('roles',{}).get('wl'))
    await member.add_roles(role,reason=f'Whitelisted by {interaction.user}')
    await interaction.response.send_message(f'💯 {member.mention} now has WL Faction access.',ephemeral=True)



@bot.tree.command(name='setuprolerequest', description='Create the gang role request channel and panel', guild=guild_obj)
async def setuprolerequest(interaction: discord.Interaction):
    if not (owner_check(interaction.user) or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message('Only the bot owner or a server Administrator can run this.',ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    g=interaction.guild
    cfg=guild_cfg(g.id)
    factions_cat=discord.utils.get(g.categories,name='💰・FACTIONS')
    if not isinstance(factions_cat,discord.CategoryChannel):
        return await interaction.followup.send('FACTIONS category is missing.',ephemeral=True)

    ch=discord.utils.get(factions_cat.text_channels,name='🎭・role-request')
    if ch is None:
        # If a role-request channel already exists elsewhere, move/reuse it instead of duplicating it.
        ch=discord.utils.get(g.text_channels,name='🎭・role-request')
        if ch:
            await ch.edit(category=factions_cat,reason='Move role requests to public FACTIONS category')
        else:
            ch=await g.create_text_channel('🎭・role-request',category=factions_cat)

    data=load_config()
    data.setdefault(str(g.id),{}).setdefault('channels',{})['role_requests']=ch.id
    save_config(data)

    await ch.send(
        embed=discord.Embed(
            title='🎭 Request Your Gang Role',
            description='Need your gang role? Hit the button below, enter your gang name, then have your Gang Leader approve you with `/approve`.',
            color=discord.Color.dark_red()
        ),
        view=GangRoleRequestView()
    )
    await interaction.followup.send(f'✅ Gang role requests are ready in {ch.mention}.',ephemeral=True)


def member_gang_roles(member, cfg):
    protected={
        cfg.get('roles',{}).get('staff'),
        cfg.get('roles',{}).get('management'),
        cfg.get('roles',{}).get('head')
    }
    return [r for r in member.roles if r.name.startswith('🔫・') and r.id not in protected]

@bot.tree.command(name='approve', description='Approve a member for your own gang role', guild=guild_obj)
@app_commands.describe(member='Member requesting your gang role')
async def approve_member(interaction: discord.Interaction, member: discord.Member):
    cfg=guild_cfg(interaction.guild_id)
    leader_role=interaction.guild.get_role(cfg.get('roles',{}).get('leader'))
    is_staff=staff_check(interaction.user,cfg)

    leader_gangs=member_gang_roles(interaction.user,cfg)
    if not is_staff and (not leader_role or leader_role not in interaction.user.roles):
        return await interaction.response.send_message('❌ Only Gang Leaders or Faction Staff can approve gang roles.',ephemeral=True)
    if not is_staff and not leader_gangs:
        return await interaction.response.send_message('❌ You do not have a gang role to approve members for.',ephemeral=True)

    if is_staff:
        # Staff override: infer the gang from the member's pending request.
        req_ch=interaction.guild.get_channel(cfg.get('channels',{}).get('role_requests'))
        target_role=None
        if req_ch:
            async for msg in req_ch.history(limit=100):
                if not msg.embeds: continue
                e=msg.embeds[0]
                footer=e.footer.text or ''
                if f'Requester ID: {member.id}' in footer and 'Gang Role ID:' in footer:
                    try:
                        rid=int(footer.split('Gang Role ID:')[-1].strip())
                        target_role=interaction.guild.get_role(rid)
                    except ValueError: pass
                    if target_role: break
        if target_role is None:
            return await interaction.response.send_message('❌ I could not find a pending role request for that member.',ephemeral=True)
    else:
        if len(leader_gangs)>1:
            return await interaction.response.send_message('❌ You have more than one gang role. Ask Faction Staff to approve this request.',ephemeral=True)
        target_role=leader_gangs[0]

    # Verify the member actually requested THIS gang.
    req_ch=interaction.guild.get_channel(cfg.get('channels',{}).get('role_requests'))
    request_message=None
    if req_ch:
        async for msg in req_ch.history(limit=100):
            if not msg.embeds: continue
            footer=msg.embeds[0].footer.text or ''
            if f'Requester ID: {member.id}' in footer and f'Gang Role ID: {target_role.id}' in footer:
                status=field_value(msg.embeds[0],'Status') or ''
                if 'Waiting' in status:
                    request_message=msg
                    break
    if request_message is None:
        return await interaction.response.send_message(
            f'❌ {member.mention} does not have a pending request for **{target_role.name.split("・",1)[-1]}**.',
            ephemeral=True
        )

    wl_role=interaction.guild.get_role(cfg.get('roles',{}).get('wl'))
    add=[r for r in (wl_role,target_role) if r]
    await member.add_roles(*add,reason=f'Gang role approved by {interaction.user}')

    e=request_message.embeds[0].copy()
    for i,f in enumerate(e.fields):
        if f.name=='Status':
            e.set_field_at(i,name='Status',value=f'✅ Approved by {interaction.user.mention}',inline=False)
            break
    e.color=discord.Color.green()
    await request_message.edit(embed=e)

    await interaction.response.send_message(
        f'✅ {member.mention} was approved for **{target_role.name.split("・",1)[-1]}** and given WL Faction access.',
        ephemeral=True
    )

@bot.tree.command(name='removegangmember', description='Remove a member from your own gang', guild=guild_obj)
@app_commands.describe(member='Member to remove from your gang')
async def remove_gang_member(interaction: discord.Interaction, member: discord.Member):
    cfg=guild_cfg(interaction.guild_id)
    leader_role=interaction.guild.get_role(cfg.get('roles',{}).get('leader'))
    is_staff=staff_check(interaction.user,cfg)
    leader_gangs=member_gang_roles(interaction.user,cfg)

    if not is_staff and (not leader_role or leader_role not in interaction.user.roles or not leader_gangs):
        return await interaction.response.send_message('❌ Only Gang Leaders or Faction Staff can remove gang members.',ephemeral=True)

    if is_staff:
        target_roles=member_gang_roles(member,cfg)
        if len(target_roles)!=1:
            return await interaction.response.send_message('❌ Staff removal needs the member to have exactly one gang role.',ephemeral=True)
        target_role=target_roles[0]
    else:
        if len(leader_gangs)>1:
            return await interaction.response.send_message('❌ You have more than one gang role. Ask Faction Staff for help.',ephemeral=True)
        target_role=leader_gangs[0]
        if target_role not in member.roles:
            return await interaction.response.send_message(f'❌ {member.mention} is not in your gang.',ephemeral=True)

    # Capture whether they should lose WL before Discord's member cache updates.
    other_gang_roles=[
        r for r in member_gang_roles(member,cfg)
        if r.id != target_role.id
    ]
    wl_role=interaction.guild.get_role(cfg.get('roles',{}).get('wl'))

    # Remove the gang role.
    await member.remove_roles(target_role,reason=f'Removed from gang by {interaction.user}')

    # If this was their only gang, remove WL Faction too.
    if not other_gang_roles and wl_role and wl_role in member.roles:
        await member.remove_roles(wl_role,reason=f'No remaining gang after removal by {interaction.user}')

    await interaction.response.send_message(
        f'✅ Removed **{target_role.name.split("・",1)[-1]}** from {member.mention}'
        + (' and removed **WL Faction**.' if not other_gang_roles else '.'),
        ephemeral=True
    )


@bot.tree.command(name='disband', description='Disband a whitelisted faction and remove its Discord setup', guild=guild_obj)
@app_commands.describe(faction='Exact faction/gang name to disband')
async def disband(interaction: discord.Interaction, faction: str):
    cfg = guild_cfg(interaction.guild_id)
    if not staff_check(interaction.user, cfg):
        return await interaction.response.send_message('Faction Staff only.', ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    g = interaction.guild
    name = faction.strip()[:80]

    gang_role = find_gang_role(g, name)
    category = find_gang_category(g, name)

    if gang_role is None and category is None:
        return await interaction.followup.send(
            f'❌ I could not find an approved faction named **{name}**. Check the gang name and try again.',
            ephemeral=True
        )

    # Capture every gang member BEFORE deleting the gang role.
    affected = list(gang_role.members) if gang_role else []

    leader_role = g.get_role(cfg.get('roles', {}).get('leader'))
    wl_role = g.get_role(cfg.get('roles', {}).get('wl'))

    # First remove the gang-specific role from everybody.
    if gang_role:
        for member in affected:
            try:
                await member.remove_roles(gang_role, reason=f'{name} disbanded by {interaction.user}')
            except discord.HTTPException:
                pass

    # Then remove Gang Leaders/WL Faction only when the member does not belong
    # to another approved gang. This prevents stripping access from someone
    # who is legitimately in another faction too.
    for member in affected:
        other_gang_roles = [
            role for role in member.roles
            if role != gang_role and role.name.startswith('🔫・')
            and role.id not in {
                cfg.get('roles', {}).get('staff'),
                cfg.get('roles', {}).get('management'),
                cfg.get('roles', {}).get('head')
            }
        ]
        if not other_gang_roles:
            remove_roles = [r for r in (leader_role, wl_role) if r and r in member.roles]
            if remove_roles:
                try:
                    await member.remove_roles(*remove_roles, reason=f'{name} disbanded by {interaction.user}')
                except discord.HTTPException:
                    pass

    # Delete every channel in the gang category, then the category.
    if category:
        for channel in list(category.channels):
            try:
                await channel.delete(reason=f'{name} disbanded by {interaction.user}')
            except discord.HTTPException:
                pass
        try:
            await category.delete(reason=f'{name} disbanded by {interaction.user}')
        except discord.HTTPException:
            pass

    if gang_role:
        try:
            await gang_role.delete(reason=f'{name} disbanded by {interaction.user}')
        except discord.HTTPException:
            pass

    # Clear active strikes when a faction is disbanded, while preserving history.
    data = load_config()
    gid = str(g.id)
    key = normalize_faction_name(name)
    record = data.get(gid, {}).get('strikes', {}).get(key)
    if record:
        record.setdefault('history', []).append({
            'action': 'disbanded',
            'disbanded_by_id': interaction.user.id,
            'disbanded_by': str(interaction.user),
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        record['active'] = []
        save_config(data)

    # Post a clear disband notice in the whitelist channel.
    whitelist_ch = g.get_channel(cfg.get('channels', {}).get('whitelisted'))
    if whitelist_ch:
        e = discord.Embed(
            title='🚫 Faction Disbanded',
            description=f'**{name}** has been removed from the FreakNik RP faction whitelist.',
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        e.add_field(name='Disbanded By', value=interaction.user.mention, inline=False)
        await whitelist_ch.send(embed=e)

    await interaction.followup.send(
        f'✅ **{name}** has been disbanded. Gang role, WL/leader access for its members, and private faction category/channels were removed.',
        ephemeral=True
    )

@setup.error
async def setup_error(interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message('Only the bot owner or a server Administrator can run /setup.',ephemeral=True)
    else:
        if interaction.response.is_done(): await interaction.followup.send(f'Setup error: {error}',ephemeral=True)
        else: await interaction.response.send_message(f'Setup error: {error}',ephemeral=True)

if not TOKEN:
    raise RuntimeError('DISCORD_TOKEN environment variable is missing.')
bot.run(TOKEN)
