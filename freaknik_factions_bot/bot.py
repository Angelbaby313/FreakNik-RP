import os, json, asyncio
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

class DecisionView(discord.ui.View):
    def __init__(self, kind: str):
        super().__init__(timeout=None)
        self.kind = kind

    async def decide(self, interaction: discord.Interaction, approved: bool):
        cfg = guild_cfg(interaction.guild_id)
        if not staff_check(interaction.user, cfg):
            return await interaction.response.send_message('Faction Staff only.', ephemeral=True)
        embed = interaction.message.embeds[0].copy() if interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.green() if approved else discord.Color.red()
        embed.add_field(name='Decision', value=f"{'APPROVED ✅' if approved else 'DENIED ❌'} by {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label='Approve', style=discord.ButtonStyle.success, custom_id='factions:approve')
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.decide(interaction, True)

    @discord.ui.button(label='Deny', style=discord.ButtonStyle.danger, custom_id='factions:deny')
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.decide(interaction, False)

class FactionApplicationModal(discord.ui.Modal, title='Become a Faction'):
    faction = discord.ui.TextInput(label='Faction / Gang Name', max_length=80)
    leader = discord.ui.TextInput(label='Leader Name / Discord', max_length=100)
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
        e.add_field(name='Leader', value=self.leader.value, inline=False)
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
    bot.add_view(TicketView()); bot.add_view(CloseTicketView()); bot.add_view(ApplyView()); bot.add_view(SubmitInteractionView()); bot.add_view(DecisionView('persistent'))
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
        return await g.create_text_channel(name,category=cat,overwrites=ow)
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

    become=g.get_channel(channels['become']); ticket=g.get_channel(channels['open_ticket']); submit=g.get_channel(channels['submit_interaction'])
    await become.send(embed=discord.Embed(title='🔫 Become A Faction',description='Ready to bring your faction into FreakNik RP? Hit the button below to submit your application.',color=discord.Color.dark_red()),view=ApplyView())
    await ticket.send(embed=discord.Embed(title='🎧 Faction Support',description='Need help? Open one general support ticket below.',color=discord.Color.dark_red()),view=TicketView())
    await submit.send(embed=discord.Embed(title='🎥 Submit An Interaction',description='Submit your interaction clip privately for Faction Staff to review and approve or deny.',color=discord.Color.dark_red()),view=SubmitInteractionView())
    await interaction.followup.send('✅ FreakNik RP Factions setup is complete. Roles, categories, channels, VCs and panels were created.',ephemeral=True)

@bot.tree.command(name='strike', description='Issue a faction strike', guild=guild_obj)
@app_commands.describe(faction='Faction/gang name', reason='Reason for the strike')
async def strike(interaction: discord.Interaction, faction: str, reason: str):
    cfg=guild_cfg(interaction.guild_id)
    if not staff_check(interaction.user,cfg): return await interaction.response.send_message('Faction Staff only.',ephemeral=True)
    ch=interaction.guild.get_channel(cfg.get('channels',{}).get('faction_strikes'))
    e=discord.Embed(title='⚠️ Faction Strike',color=discord.Color.red(),timestamp=datetime.now(timezone.utc))
    e.add_field(name='Faction',value=faction,inline=False); e.add_field(name='Reason',value=reason,inline=False); e.add_field(name='Issued By',value=interaction.user.mention,inline=False)
    await ch.send(embed=e); await interaction.response.send_message('Strike logged.',ephemeral=True)

@bot.tree.command(name='whitelist', description='Give a member the WL Faction role', guild=guild_obj)
async def whitelist(interaction: discord.Interaction, member: discord.Member):
    cfg=guild_cfg(interaction.guild_id)
    if not staff_check(interaction.user,cfg): return await interaction.response.send_message('Faction Staff only.',ephemeral=True)
    role=interaction.guild.get_role(cfg.get('roles',{}).get('wl'))
    await member.add_roles(role,reason=f'Whitelisted by {interaction.user}')
    await interaction.response.send_message(f'💯 {member.mention} now has WL Faction access.',ephemeral=True)

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
