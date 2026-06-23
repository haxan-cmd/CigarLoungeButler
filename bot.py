import discord
import os
import asyncio
import gspread
import json
from google.oauth2.service_account import Credentials
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
SHEET_ID = '1aT7MbBa3qZxx9ZyaFvlgmbjvCDe2kkQMt5Qsnq_6lzY'
DECORATION_TOP = os.getenv('DECORATION_TOP', 'WMMR_Spacer_Top.png')
DECORATION_BOTTOM = os.getenv('DECORATION_BOTTOM', 'WMMR_Spacer_Bottom.png')

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
creds = Credentials.from_service_account_info(json.loads(google_creds_json), scopes=SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID)
submissions_ws = sheet.worksheet('Submissions')
players_ws = sheet.worksheet('Players')
leaderboards_ws = sheet.worksheet('Leaderboards')
leaderboard_data_ws = sheet.worksheet('LeaderboardData')

# BountyPlayers sheet — columns: BountyTitle, DiscordID, PlayerName, ForumPostID, Progress (JSON)
try:
    bounty_players_ws = sheet.worksheet('BountyPlayers')
except gspread.exceptions.WorksheetNotFound:
    bounty_players_ws = sheet.add_worksheet(title='BountyPlayers', rows=500, cols=10)
    bounty_players_ws.append_row(['BountyTitle','DiscordID','PlayerName','ForumPostID','Progress'])

# Bounty sheet — columns: Title, ChannelID, MessageID, ThemeEmoji, Weapons (JSON),
#                          SpecialChallenge, SpecialDone (0/1), Completions (JSON), Active (TRUE/FALSE), RoleID
try:
    bounty_ws = sheet.worksheet('Bounty')
except gspread.exceptions.WorksheetNotFound:
    bounty_ws = sheet.add_worksheet(title='Bounty', rows=100, cols=20)
    bounty_ws.append_row(['Title','ChannelID','MessageID','ThemeEmoji','Weapons','SpecialChallenge','SpecialDone','Completions','Active','RoleID','ForumChannelID','CompletionsMsgID','BonusMsgID'])

SUBMISSIONS_CHANNEL_ID = 1328832440927518920
BOUNTY_FORUM_CHANNEL_ID = 1456640264004435978  # The Ledger forum for player bounty cards
BULLETIN_BOARD_CATEGORY_ID = 1359537379039252550
LEDGER_CATEGORY_ID = 1456640264004435978
MOD_ROLE_ID = 1472259982241300611
BUTLERS_NOTES_CHANNEL_ID = 1518771519075909702
BUTLERS_FAVOURITES_CHANNEL_ID = 1518822798116524092
MAIN_CHANNEL_ID = 1324447691467526338  # #main

GRAND_MARSHAL_ROLE_ID = 1467680214560674020
WEAPONS_MASTER_ROLE_ID = 1467679890706010277
CAMPAIGN_MASTER_ROLE_ID = 1518820158821367858
HEADHUNTER_ROLE_ID = 1518827472718921819
BUTCHER_ROLE_ID = 1518827620572205097

# Rate limiting for /butlers_report — user_id -> last used timestamp
_butlers_report_cooldowns = {}

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

WEAPONS_2H = [
    "Battle Axe", "Dane Axe", "Executioner's Axe", "Glaive",
    "Goedendag", "Greatsword", "Halberd", "Highland Sword", "Katars",
    "Longsword", "Maul", "Messer", "Morning Star", "Pole Axe", "Polehammer",
    "Quarterstaff", "Shovel", "Sledge Hammer", "Spear", "Two-Handed Hammer",
    "War Axe", "War Club", "Heavy Mace"
]

WEAPONS_1H = [
    "Axe", "Dagger", "Falchion", "Fist and Shield", "Hatchet", "Healing Horn",
    "Heavy Cavalry Sword", "Knife", "Mace", "Mallet", "One-Handed Spear",
    "Pick Axe", "Rapier", "Short Sword", "Sword", "Warhammer", "Cudgel"
]

CLASS_WEAPON_MAP = {
    "Devastator": ["Battle Axe", "Executioner's Axe", "Greatsword", "Highland Sword", "Maul", "War Club"],
    "Raider": ["Dane Axe", "Glaive", "Messer", "Two-Handed Hammer"],
    "Ambusher": ["Cudgel", "Dagger", "Hatchet", "Katars", "Knife", "Short Sword"],
    "Poleman": ["Glaive", "Goedendag", "Halberd", "Polehammer", "Quarterstaff", "Spear"],
    "Man-at-Arms": ["Falchion", "Fist and Shield", "Healing Horn", "Heavy Cavalry Sword", "Mace", "Morning Star", "One-Handed Spear", "Rapier", "Sword"],
    "Field Engineer": ["Goedendag", "Mallet", "Pick Axe", "Shovel", "Sledge Hammer"],
    "Officer": ["Greatsword", "Heavy Mace", "Longsword", "Mace", "Pole Axe", "War Axe"],
    "Guardian": ["Axe", "Falchion", "Fist and Shield", "Heavy Cavalry Sword", "One-Handed Spear", "Warhammer"],
    "Crusader": ["Battle Axe", "Executioner's Axe", "Messer", "Morning Star", "Quarterstaff", "Two-Handed Hammer"],
}

MAP_FACTIONS = {
    "Aberfell": ["Agatha", "Mason"],
    "Askandir": ["Mason", "Tenosia"],
    "Baudwyn": ["Mason", "Tenosia"],
    "Bridgetown": ["Agatha", "Tenosia"],
    "Coxwell": ["Agatha", "Mason"],
    "Darkforest": ["Agatha", "Mason"],
    "Falmire": ["Agatha", "Mason"],
    "Galencourt": ["Agatha", "Mason"],
    "Lionspire": ["Agatha", "Mason"],
    "Montcrux": ["Agatha", "Tenosia"],
    "Rudhelm": ["Agatha", "Mason"],
    "Thayic Stronghold": ["Agatha", "Mason"],
    "Trayan Citadel": ["Agatha", "Mason"],
}

MAPS = sorted(MAP_FACTIONS.keys())
FEAT_WEAPONS = ["Mallet", "Knife", "Healing Horn", "Fist and Shield"]

MARKSMAN_SUBCLASSES = {
    "Longbowman": ["Bow", "War Bow"],
    "Crossbowman": ["Crossbow", "Siege Crossbow"],
    "Skirmisher": ["Javelin", "Throwing Axe"],
}

def get_classes_for_category(category):
    weapon_list = WEAPONS_2H if category == "2h" else WEAPONS_1H
    result = []
    for cls, weapons in CLASS_WEAPON_MAP.items():
        if any(w in weapon_list for w in weapons):
            result.append(cls)
    return sorted(set(result))

def get_weapons_for_class_and_category(selected_class, category):
    weapon_list = WEAPONS_2H if category == "2h" else WEAPONS_1H
    class_weapons = CLASS_WEAPON_MAP.get(selected_class, [])
    return sorted([w for w in class_weapons if w in weapon_list]) + ["Other"]

def upsert_player(discord_id, discord_name):
    try:
        rows = players_ws.get_all_values()
        discord_id_str = str(discord_id)
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == discord_id_str:
                # Update name if changed
                if len(row) < 2 or row[1] != discord_name:
                    players_ws.update_cell(i, 2, discord_name)
                return
        # Not found — append new row
        players_ws.append_row([discord_id_str, discord_name, ""])
    except Exception as e:
        print(f"Player upsert error: {e}")

def log_submission(discord_name, discord_id, weapon, cls, map_name, faction, takedowns, kills, deaths, vip, feats, message_link):
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    vip_str = "Yes" if vip else "No"
    feats_str = ", ".join(feats) if feats else "None"
    submissions_ws.append_row([
        timestamp, discord_name, str(discord_id), weapon, cls,
        map_name, faction, takedowns, kills, deaths, vip_str, feats_str, message_link
    ])
    upsert_player(discord_id, discord_name)

GUILD_ID = 1324379304544567356

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    print(f'Logged in as {bot.user}')

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Middle finger at the bot = middle finger back
    if bot.user in message.mentions and '\U0001f595' in message.content:
        await message.channel.send('\U0001f595')
        return

    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')

    # Check if this is an art post in the active bounty channel
    bounty = get_active_bounty()
    if bounty and message.channel.id == bounty['channel_id']:
        has_image = any(
            att.filename.lower().endswith(image_extensions)
            for att in message.attachments
        )
        if has_image and not bounty['completions_msg_id'] and not bounty['bonus_msg_id']:
            # Post placeholder completions and bonus boards
            completions_placeholder = (
                f"```\n"
                f"╭──────────────────────────────╮\n"
                f"  {bounty['theme_emoji']} COMPLETIONS {bounty['theme_emoji']}\n"
                f"╰──────────────────────────────╯\n"
                f"No completions yet.\n"
                f"```"
            )
            bonus_placeholder = (
                f"```\n"
                f"╭──────────────────────────────╮\n"
                f"  {bounty['theme_emoji']} BONUS COMPLETIONS {bounty['theme_emoji']}\n"
                f"╰──────────────────────────────╯\n"
                f"No bonus completions yet.\n"
                f"```"
            )
            try:
                comp_msg = await message.channel.send(completions_placeholder)
                bonus_msg = await message.channel.send(bonus_placeholder)
                # Save message IDs to sheet (cols 12 & 13)
                bounty_ws.update_cell(bounty['row'], 12, str(comp_msg.id))
                bounty_ws.update_cell(bounty['row'], 13, str(bonus_msg.id))
            except Exception as e:
                print(f"Bounty placeholder post error: {e}")
        return

    if message.channel.id != SUBMISSIONS_CHANNEL_ID:
        return
    if not message.attachments:
        return

    has_image = any(
        att.filename.lower().endswith(image_extensions)
        for att in message.attachments
    )
    if not has_image:
        return

    prompt_msg = await message.reply("📋 Splendid! Please submit this run.", mention_author=False)
    view = SubmitView(message, prompt_msg)
    await prompt_msg.edit(view=view)

class SubmitView(discord.ui.View):
    def __init__(self, original_message, prompt_msg):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg

    async def on_timeout(self):
        try:
            await self.prompt_msg.delete()
        except Exception:
            pass
        self.stop()


    @discord.ui.button(label='Submit Run', style=discord.ButtonStyle.green, emoji='⚔️')
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        view = WeaponTypeView(self.original_message, self.prompt_msg)
        await interaction.response.send_message(
            content="**Step 1 of 6:** What type of weapon did you use?",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label='Dismiss', style=discord.ButtonStyle.grey, emoji='✖️')
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self.prompt_msg.delete()
        await interaction.response.defer()

class WeaponTypeView(discord.ui.View):
    def __init__(self, original_message, prompt_msg):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg

    @discord.ui.button(label='Two-Handed', style=discord.ButtonStyle.blurple, emoji='⚔️')
    async def two_handed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        classes = get_classes_for_category("2h")
        view = ClassSelectView(self.original_message, self.prompt_msg, "2h", classes)
        await interaction.response.edit_message(
            content="**Step 2 of 6:** Which class were you playing?",
            view=view
        )

    @discord.ui.button(label='One-Handed', style=discord.ButtonStyle.blurple, emoji='🗡️')
    async def one_handed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        classes = get_classes_for_category("1h")
        view = ClassSelectView(self.original_message, self.prompt_msg, "1h", classes)
        await interaction.response.edit_message(
            content="**Step 2 of 6:** Which class were you playing?",
            view=view
        )

    @discord.ui.button(label='Ranged', style=discord.ButtonStyle.blurple)
    async def ranged(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        view = MarksmanSubclassView(self.original_message, self.prompt_msg)
        await interaction.response.edit_message(
            content="**Step 2 of 6:** Class: `Marksman`\nWhich subclass were you playing?",
            view=view
        )

class MarksmanSubclassView(discord.ui.View):
    def __init__(self, original_message, prompt_msg):
        super().__init__(timeout=300)
        self.add_item(MarksmanSubclassSelect(original_message, prompt_msg))

class MarksmanSubclassSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        options = [discord.SelectOption(label=s) for s in MARKSMAN_SUBCLASSES.keys()]
        super().__init__(placeholder="Choose your subclass...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        subclass = self.values[0]
        weapons = sorted(MARKSMAN_SUBCLASSES[subclass])
        view = RangedWeaponSelectView(self.original_message, self.prompt_msg, subclass, weapons)
        await interaction.response.edit_message(
            content=f"**Step 3 of 6:** Class: `Marksman` | Subclass: `{subclass}`\nWhich weapon did you use?",
            view=view
        )

class RangedWeaponSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, subclass, weapons):
        super().__init__(timeout=300)
        self.add_item(RangedWeaponSelect(original_message, prompt_msg, subclass, weapons))

class RangedWeaponSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, subclass, weapons):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.subclass = subclass
        options = [discord.SelectOption(label=w) for w in weapons]
        super().__init__(placeholder="Choose your weapon...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_weapon = self.values[0]
        view = MapSelectView(self.original_message, self.prompt_msg, f"Marksman ({self.subclass})", selected_weapon)
        await interaction.response.edit_message(
            content=f"**Step 4 of 6:** Class: `Marksman ({self.subclass})` | Weapon: `{selected_weapon}`\nWhich map were you on?",
            view=view
        )


class ClassSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, category, classes):
        super().__init__(timeout=300)
        self.add_item(ClassSelect(original_message, prompt_msg, category, classes))

class ClassSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, category, classes):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.category = category
        options = [discord.SelectOption(label=c) for c in classes] + [discord.SelectOption(label="Other")]
        super().__init__(placeholder="Choose your class...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_class = self.values[0]
        if selected_class == "Other":
            weapons = sorted(WEAPONS_2H if self.category == "2h" else WEAPONS_1H) + ["Other"]
        else:
            weapons = get_weapons_for_class_and_category(selected_class, self.category)
        view = WeaponSelectView(self.original_message, self.prompt_msg, selected_class, weapons)
        await interaction.response.edit_message(
            content=f"**Step 3 of 6:** Class: `{selected_class}`\nWhich weapon did you use?",
            view=view
        )

class WeaponSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, weapons):
        super().__init__(timeout=300)
        self.add_item(WeaponSelect(original_message, prompt_msg, selected_class, weapons))

class WeaponSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, weapons):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        options = [discord.SelectOption(label=w) for w in weapons]
        super().__init__(placeholder="Choose your weapon...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_weapon = self.values[0]
        view = MapSelectView(self.original_message, self.prompt_msg, self.selected_class, selected_weapon)
        await interaction.response.edit_message(
            content=f"**Step 4 of 6:** Class: `{self.selected_class}` | Weapon: `{selected_weapon}`\nWhich map were you on?",
            view=view
        )

class MapSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon):
        super().__init__(timeout=300)
        self.add_item(MapSelect(original_message, prompt_msg, selected_class, selected_weapon))

class MapSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        options = [discord.SelectOption(label=m) for m in MAPS]
        super().__init__(placeholder="Choose your map...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_map = self.values[0]
        view = FactionSelectView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, selected_map)
        await interaction.response.edit_message(
            content=f"**Step 5 of 6:** Class: `{self.selected_class}` | Weapon: `{self.selected_weapon}` | Map: `{selected_map}`\nWhich faction were you playing as?",
            view=view
        )

class FactionSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map):
        super().__init__(timeout=300)
        self.add_item(FactionSelect(original_message, prompt_msg, selected_class, selected_weapon, selected_map))

class FactionSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        options = [discord.SelectOption(label=f) for f in MAP_FACTIONS.get(selected_map, ["Agatha", "Mason", "Tenosia"])]
        super().__init__(placeholder="Choose your faction...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_faction = self.values[0]
        await interaction.response.send_modal(
            StatsModal(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, selected_faction)
        )

class RetryStatsView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, error_msg):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction
        self.error_msg = error_msg


    @discord.ui.button(label='Try Again', style=discord.ButtonStyle.blurple, emoji='🔄')
    async def try_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await interaction.response.send_modal(
            StatsModal(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction)
        )

class StatsModal(discord.ui.Modal, title="Enter Your Run Statistics"):
    takedowns = discord.ui.TextInput(label="Takedowns", placeholder="e.g. 215", required=True)
    kills = discord.ui.TextInput(label="Kills", placeholder="e.g. 104", required=True)
    deaths = discord.ui.TextInput(label="Deaths", placeholder="e.g. 0", required=True)

    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction):
        super().__init__()
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction

    async def on_submit(self, interaction: discord.Interaction):
        try:
            takedowns = int(self.takedowns.value)
            kills = int(self.kills.value)
            deaths = int(self.deaths.value)
        except ValueError:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "invalid")
            await interaction.response.send_message(
                "❌ Takedowns, Kills, and Deaths must be whole numbers. Please try again.",
                view=view,
                ephemeral=True
            )
            return

        # Sanity checks
        if takedowns < 0 or kills < 0 or deaths < 0:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "negative")
            await interaction.response.send_message(
                "❌ Takedowns, Kills, and Deaths cannot be negative. Please try again.",
                view=view,
                ephemeral=True
            )
            return

        if kills > takedowns:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "kills>td")
            await interaction.response.send_message(
                f"❌ Kills ({kills}) cannot exceed Takedowns ({takedowns}) — takedowns include kills plus assists. Please try again.",
                view=view,
                ephemeral=True
            )
            return

        view = VIPView(
            self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
            self.selected_map, self.faction, takedowns, kills, deaths
        )
        await interaction.response.send_message(
            "**Almost done!** Were you playing as VIP?",
            view=view,
            ephemeral=True
        )

class VIPView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction
        self.takedowns = takedowns
        self.kills = kills
        self.deaths = deaths


    @discord.ui.button(label='Yes', style=discord.ButtonStyle.red)
    async def vip_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self.handle_vip(interaction, True)

    @discord.ui.button(label='No', style=discord.ButtonStyle.green)
    async def vip_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self.handle_vip(interaction, False)

    async def handle_vip(self, interaction, vip):
        if self.takedowns >= 150 and self.kills >= 100:
            view = TripleCheckView(
                self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
                self.selected_map, self.faction, self.takedowns, self.kills, self.deaths, vip
            )
            await interaction.response.edit_message(
                content="Was your score over 20,000 points?",
                view=view
            )
        else:
            await finalise_submission(
                interaction, self.original_message, self.prompt_msg, self.selected_class,
                self.selected_weapon, self.selected_map, self.faction,
                self.takedowns, self.kills, self.deaths, vip, False
            )

class TripleCheckView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction
        self.takedowns = takedowns
        self.kills = kills
        self.deaths = deaths
        self.vip = vip


    @discord.ui.button(label='Yes', style=discord.ButtonStyle.green)
    async def score_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await finalise_submission(
            interaction, self.original_message, self.prompt_msg, self.selected_class,
            self.selected_weapon, self.selected_map, self.faction,
            self.takedowns, self.kills, self.deaths, self.vip, True
        )

    @discord.ui.button(label='No', style=discord.ButtonStyle.red)
    async def score_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await finalise_submission(
            interaction, self.original_message, self.prompt_msg, self.selected_class,
            self.selected_weapon, self.selected_map, self.faction,
            self.takedowns, self.kills, self.deaths, self.vip, False
        )


class EditSubmissionView(discord.ui.View):
    def __init__(self, original_message, author, submission_row,
                 weapon, cls, map_name, faction, takedowns, kills, deaths, vip, feats, message_link):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.author = author
        self.submission_row = submission_row
        self.weapon = weapon
        self.cls = cls
        self.map_name = map_name
        self.faction = faction
        self.takedowns = takedowns
        self.kills = kills
        self.deaths = deaths
        self.vip = vip
        self.feats = feats
        self.message_link = message_link

    async def on_timeout(self):
        try:
            # Remove the edit button but keep the summary message
            await self._message.edit(view=None)
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label='✏️ Edit', style=discord.ButtonStyle.grey)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Only the person who submitted can edit this.", ephemeral=True)
            return
        view = EditFieldSelectView(self)
        await interaction.response.send_message(
            content="**Which field would you like to correct?**",
            view=view,
            ephemeral=True
        )


class EditFieldSelectView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.edit_view = edit_view
        self.add_item(EditFieldSelect(edit_view))


class EditFieldSelect(discord.ui.Select):
    def __init__(self, edit_view):
        self.edit_view = edit_view
        options = [
            discord.SelectOption(label="Weapon / Class", value="weapon"),
            discord.SelectOption(label="Map", value="map"),
            discord.SelectOption(label="Faction", value="faction"),
            discord.SelectOption(label="Stats (TD/K/D)", value="stats"),
            discord.SelectOption(label="VIP", value="vip"),
        ]
        super().__init__(placeholder="Choose a field to edit...", options=options)

    async def callback(self, interaction: discord.Interaction):
        field = self.values[0]
        ev = self.edit_view

        if field == "weapon":
            view = WeaponTypeView(ev.original_message, None, edit_view=ev)
            await interaction.response.edit_message(
                content="**Step 1:** What type of weapon did you use?",
                view=view
            )
        elif field == "map":
            view = EditMapSelectView(ev)
            await interaction.response.edit_message(
                content="**Edit Map:** Which map were you on?",
                view=view
            )
        elif field == "faction":
            view = EditFactionSelectView(ev)
            await interaction.response.edit_message(
                content="**Edit Faction:** Which faction were you playing?",
                view=view
            )
        elif field == "stats":
            await interaction.response.send_modal(EditStatsModal(ev))
        elif field == "vip":
            view = EditVIPView(ev)
            await interaction.response.edit_message(
                content="**Edit VIP:** Were you a VIP?",
                view=view
            )


class EditMapSelectView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.add_item(EditMapSelect(edit_view))

class EditMapSelect(discord.ui.Select):
    def __init__(self, edit_view):
        self.edit_view = edit_view
        options = [discord.SelectOption(label=m) for m in sorted(MAPS)]
        super().__init__(placeholder="Choose map...", options=options[:25])
    async def callback(self, interaction: discord.Interaction):
        ev = self.edit_view
        ev.map_name = self.values[0]
        await _apply_edit(interaction, ev)

class EditFactionSelectView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.add_item(EditFactionSelect(edit_view))

class EditFactionSelect(discord.ui.Select):
    def __init__(self, edit_view):
        self.edit_view = edit_view
        factions = MAP_FACTIONS.get(edit_view.map_name, {})
        options = [discord.SelectOption(label=f) for f in factions.keys()] if factions else [
            discord.SelectOption(label="Agatha"),
            discord.SelectOption(label="Mason"),
            discord.SelectOption(label="Tenosia"),
        ]
        super().__init__(placeholder="Choose faction...", options=options)
    async def callback(self, interaction: discord.Interaction):
        ev = self.edit_view
        ev.faction = self.values[0]
        await _apply_edit(interaction, ev)

class EditStatsModal(discord.ui.Modal, title="Edit Stats"):
    def __init__(self, edit_view):
        super().__init__()
        self.edit_view = edit_view
        self.td = discord.ui.TextInput(label="Takedowns", default=str(edit_view.takedowns), required=True)
        self.k = discord.ui.TextInput(label="Kills", default=str(edit_view.kills), required=True)
        self.d = discord.ui.TextInput(label="Deaths", default=str(edit_view.deaths), required=True)
        self.add_item(self.td)
        self.add_item(self.k)
        self.add_item(self.d)
    async def on_submit(self, interaction: discord.Interaction):
        ev = self.edit_view
        try:
            ev.takedowns = int(self.td.value)
            ev.kills = int(self.k.value)
            ev.deaths = int(self.d.value)
        except ValueError:
            await interaction.response.send_message("Invalid numbers.", ephemeral=True)
            return
        await _apply_edit(interaction, ev)

class EditVIPView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.edit_view = edit_view
    @discord.ui.button(label='Yes', style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.edit_view.vip = True
        await _apply_edit(interaction, self.edit_view)
    @discord.ui.button(label='No', style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.edit_view.vip = False
        await _apply_edit(interaction, self.edit_view)


async def _apply_edit(interaction, ev):
    """Write the updated submission back to the sheet and update the summary message."""
    try:
        if ev.submission_row:
            vip_str = "Yes" if ev.vip else "No"
            feats_str = ", ".join(ev.feats) if ev.feats else "None"
            submissions_ws.update_cell(ev.submission_row, 4, ev.weapon)
            submissions_ws.update_cell(ev.submission_row, 5, ev.cls)
            submissions_ws.update_cell(ev.submission_row, 6, ev.map_name)
            submissions_ws.update_cell(ev.submission_row, 7, ev.faction)
            submissions_ws.update_cell(ev.submission_row, 8, ev.takedowns)
            submissions_ws.update_cell(ev.submission_row, 9, ev.kills)
            submissions_ws.update_cell(ev.submission_row, 10, ev.deaths)
            submissions_ws.update_cell(ev.submission_row, 11, vip_str)
            submissions_ws.update_cell(ev.submission_row, 12, feats_str)
    except Exception as e:
        print(f"Edit sheet update error: {e}")

    # Rebuild summary
    new_summary = (
        f"⚔️ **Run Submitted** *(edited)*\n"
        f"{ev.author.display_name}\n"
        f"{ev.weapon} • {ev.cls}\n"
        f"{ev.map_name} — {ev.faction}\n"
        f"{ev.takedowns} TD / {ev.kills} K / {ev.deaths} D\n"
        f"VIP: {'Yes' if ev.vip else 'No'}"
    )
    if ev.feats:
        new_summary += f"\n{', '.join(ev.feats)}"

    try:
        await ev._message.edit(content=new_summary, view=None)
    except Exception:
        pass

    await interaction.response.send_message("✅ Submission updated!", ephemeral=True)


async def finalise_submission(interaction, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip, score_over_20k):
    feats = []
    if kills >= 100:
        feats.append("100 Kills")
    if takedowns >= 200:
        feats.append("200 Takedowns")
    if deaths == 0:
        feats.append("Flawless")
    if takedowns >= 150 and deaths == 0:
        feats.append("Predator")
    if takedowns >= 150 and kills >= 100 and score_over_20k:
        feats.append("Triple")
    if selected_weapon in FEAT_WEAPONS and kills >= 100:
        feats.append(selected_weapon)

    vip_str = "Yes" if vip else "No"
    feats_str = ", ".join(feats) if feats else None

    summary = (
        f"⚔️ **Run Submitted**\n"
        f"{interaction.user.display_name}\n"
        f"{selected_weapon} • {selected_class}\n"
        f"{selected_map} — {faction}\n"
        f"{takedowns} TD / {kills} K / {deaths} D\n"
        f"VIP: {vip_str}"
    )
    if feats_str:
        summary += f"\n{feats_str}"

    message_link = f"https://discord.com/channels/{original_message.guild.id}/{original_message.channel.id}/{original_message.id}"

    await interaction.response.edit_message(content="✅ Most impressive! Your run has been recorded.", view=None)

    # Log to Google Sheets first so we get the row index
    submission_row = None
    try:
        log_submission(
            interaction.user.display_name,
            interaction.user.id,
            selected_weapon,
            selected_class,
            selected_map,
            faction,
            takedowns,
            kills,
            deaths,
            vip,
            feats,
            message_link
        )
        # Row index is last row in submissions sheet
        submission_row = len(submissions_ws.get_all_values())
    except Exception as e:
        print(f"Sheet logging error: {e}")

    # Post summary with Edit button
    edit_view = EditSubmissionView(
        original_message, interaction.user,
        submission_row, selected_weapon, selected_class,
        selected_map, faction, takedowns, kills, deaths, vip, feats, message_link
    )
    summary_reply = await original_message.reply(summary, mention_author=False, view=edit_view)
    edit_view._message = summary_reply

    await asyncio.sleep(1)
    try:
        await prompt_msg.delete()
    except discord.NotFound:
        pass

    # React to the original screenshot
    await original_message.add_reaction("<:cigar:1444893851427803298>")
    if deaths == 0:
        await original_message.add_reaction("<a:flawless:1360358300834599062>")
    if kills >= 100:
        await original_message.add_reaction("<a:100kill:1361412390339608686>")
    if takedowns >= 200:
        await original_message.add_reaction("<a:200tkd:1363648828414230538>")
    if takedowns >= 150 and deaths == 0:
        await original_message.add_reaction("<a:predator:1366794896081555567>")
    if takedowns >= 150 and kills >= 100 and score_over_20k:
        await original_message.add_reaction("<a:triple:1365532698260668466>")

    is_ranged = selected_class.startswith("Marksman")

    # weapon_hs — only if score qualifies for the weapon leaderboard (not VIP, not ranged)
    if not vip and not is_ranged:
        all_values = leaderboard_data_ws.get_all_values()
        weapon_entries = [row for row in all_values[1:] if row[0] == selected_weapon]
        scores = sorted(
            [int(row[3]) for row in weapon_entries if len(row) > 3 and row[3]],
            reverse=True
        )
        qualifies = len(scores) < 10 or takedowns > scores[9]
        if qualifies:
            await original_message.add_reaction("<:weapon_hs:1350656128635375698>")

    # Update leaderboards (skip for ranged submissions)
    any_updated = False
    placements = []
    if not is_ranged:
        try:
            any_updated, placements = await update_leaderboards(
                interaction, selected_weapon, selected_map, faction,
                takedowns, kills, deaths, vip, feats,
                interaction.user.display_name, message_link
            )
        except Exception as e:
            print(f"Leaderboard update error: {e}")

    if any_updated:
        await original_message.add_reaction("<a:highscore:1360312918545269057>")

    # Bounty check (skip for ranged submissions)
    if not is_ranged:
        try:
            bounty_hit = await update_bounty(
                interaction.guild, selected_weapon,
                interaction.user.display_name, interaction.user.id, takedowns
            )
            print(f"[BOUNTY] bounty_hit={bounty_hit} weapon={selected_weapon} takedowns={takedowns}")
            if bounty_hit:
                await original_message.add_reaction("🐱")
        except Exception as e:
            import traceback
            print(f"Bounty update error: {e}")
            traceback.print_exc()

    # Edit the summary reply to include placements
    if placements:
        placement_lines = "\n".join(f"🏆 {lb} — #{pos}" for lb, pos in placements)
        try:
            # Find the reply we sent and edit it
            async for msg in original_message.channel.history(limit=10, after=original_message):
                if msg.author == original_message.guild.me and msg.reference and msg.reference.message_id == original_message.id:
                    await msg.edit(content=msg.content + f"\n{placement_lines}")
                    break
        except Exception as e:
            print(f"Placement edit error: {e}")

    # Silently update Butler's Favourites pinned message
    try:
        if BUTLERS_FAVOURITES_CHANNEL_ID:
            fav_channel = interaction.guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
            if fav_channel:
                stats = calculate_butler_stats()
                embed_text = build_favourites_embed(stats)
                async for msg in fav_channel.history(limit=5):
                    if msg.author == interaction.guild.me:
                        await msg.edit(content=embed_text)
                        break
                else:
                    await fav_channel.send(embed_text)
                await update_title_roles(interaction.guild, stats)
    except Exception as e:
        print(f"Butler favourites update error: {e}")

async def update_leaderboards(interaction, selected_weapon, selected_map, faction,
                              takedowns, kills, deaths, vip, feats,
                              player_name, message_link):
    guild = interaction.guild
    discord_id = str(interaction.user.id)
    any_updated = False
    placements = []  # list of (lb_name, position)

    # (lb_name, score, top_10, personal_best, unlimited_top50)
    updates = []

    # Weapon board — exclude VIP, top 10
    if not vip:
        updates.append((selected_weapon, takedowns, True, True, False))

    # Map board — top 10
    map_lb_name = f"{selected_map} - {faction}"
    updates.append((map_lb_name, takedowns, True, True, False))

    # Feat boards
    if "Flawless" in feats:
        updates.append(("Flawless", takedowns, False, True, False))
    if "100 Kills" in feats:
        updates.append(("100 Kills", kills, False, False, True))
    if "200 Takedowns" in feats:
        updates.append(("200 Takedowns", takedowns, False, False, True))
    if selected_weapon == "Mallet" and kills >= 100:
        updates.append(("Mallet", takedowns, True, True, False))
    if selected_weapon == "Knife" and kills >= 100:
        updates.append(("Knife", takedowns, True, True, False))
    if selected_weapon == "Healing Horn" and kills >= 100:
        updates.append(("Healing Horn", kills, False, True, False))

    # Columns: A=Leaderboard Name, B=Player, C=Discord ID, D=Score, E=Message Link
    all_values = leaderboard_data_ws.get_all_values()
    all_lb_rows = leaderboards_ws.get_all_records()

    for lb_name, score, top_10, personal_best, unlimited_top50 in updates:
        existing_sheet_row = None
        existing_score = None
        for i, row in enumerate(all_values[1:], start=2):
            row_lb = row[0] if len(row) > 0 else ''
            row_discord_id = row[2] if len(row) > 2 else ''
            row_score = row[3] if len(row) > 3 else ''
            if row_lb == lb_name and row_discord_id == discord_id:
                existing_sheet_row = i
                existing_score = int(row_score) if row_score else 0
                break

        if unlimited_top50:
            # Always append, no cap, no personal best check
            leaderboard_data_ws.append_row([lb_name, player_name, discord_id, score, message_link, selected_weapon])
            any_updated = True
            # Find position after append
            all_board = [int(r[3]) for r in all_values[1:] if r[0] == lb_name and len(r) > 3 and r[3]]
            all_board.append(score)
            all_board.sort(reverse=True)
            pos = all_board.index(score) + 1
            placements.append((lb_name, pos))
        elif personal_best:
            if existing_sheet_row is not None:
                if score > existing_score:
                    leaderboard_data_ws.update_cell(existing_sheet_row, 2, player_name)
                    leaderboard_data_ws.update_cell(existing_sheet_row, 4, score)
                    leaderboard_data_ws.update_cell(existing_sheet_row, 5, message_link)
                    leaderboard_data_ws.update_cell(existing_sheet_row, 6, selected_weapon)
                    any_updated = True
                    # Find position
                    board_scores = sorted([int(r[3]) for r in all_values[1:] if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
                    # Replace old score with new
                    board_scores = [s for s in board_scores if s != existing_score]
                    board_scores.append(score)
                    board_scores.sort(reverse=True)
                    pos = board_scores.index(score) + 1
                    placements.append((lb_name, pos))
                else:
                    continue
            else:
                if top_10:
                    board_entries = [row for row in all_values[1:] if row[0] == lb_name]
                    board_entries_sorted = sorted(
                        board_entries, key=lambda x: int(x[3]) if len(x) > 3 and x[3] else 0, reverse=True
                    )
                    if len(board_entries_sorted) >= 10:
                        lowest_score = int(board_entries_sorted[9][3]) if board_entries_sorted[9][3] else 0
                        if score <= lowest_score:
                            continue
                        tenth_discord_id = board_entries_sorted[9][2] if len(board_entries_sorted[9]) > 2 else ''
                        for i, row in enumerate(all_values[1:], start=2):
                            if row[0] == lb_name and (row[2] if len(row) > 2 else '') == tenth_discord_id:
                                leaderboard_data_ws.delete_rows(i)
                                all_values = leaderboard_data_ws.get_all_values()  # reload after delete
                                break
                leaderboard_data_ws.append_row([lb_name, player_name, discord_id, score, message_link, selected_weapon])
                any_updated = True
                board_scores = sorted([int(r[3]) for r in all_values[1:] if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
                board_scores.append(score)
                board_scores.sort(reverse=True)
                pos = board_scores.index(score) + 1
                placements.append((lb_name, pos))
        else:
            leaderboard_data_ws.append_row([lb_name, player_name, discord_id, score, message_link, selected_weapon])
            any_updated = True
            board_scores = sorted([int(r[3]) for r in all_values[1:] if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
            board_scores.append(score)
            board_scores.sort(reverse=True)
            pos = board_scores.index(score) + 1
            placements.append((lb_name, pos))

        # Reload and update Discord message
        updated_values = leaderboard_data_ws.get_all_values()
        entries = []
        for row in updated_values[1:]:
            if row[0] == lb_name:
                entries.append({
                    'player': row[1] if len(row) > 1 else '',
                    'score': int(row[3]) if len(row) > 3 and row[3] else 0,
                    'link': row[4] if len(row) > 4 else ''
                })
        entries = sorted(entries, key=lambda x: x['score'], reverse=True)

        # Cap 100 Kills / 200 Takedowns display at top 50
        if lb_name in ("100 Kills", "200 Takedowns"):
            display_entries = entries[:50]
            overflow = len(entries) - 50
        else:
            display_entries = entries
            overflow = 0

        chunks = format_leaderboard_text(display_entries, overflow, show_weapon=(lb_name in ("100 Kills", "200 Takedowns")))

        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
        if not lb_row:
            print(f"No Leaderboards sheet entry found for: {lb_name}")
            continue

        thread_id = int(lb_row['Thread ID'])
        message_ids = [int(mid.strip()) for mid in str(lb_row['Message ID']).split(',') if mid.strip()]

        try:
            thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)

            # Pack all chunks into existing messages — never post new ones (would appear after decoration)
            packed = pack_chunks_into_slots(chunks, len(message_ids))

            for idx, mid in enumerate(message_ids):
                try:
                    msg = await thread.fetch_message(mid)
                    await msg.edit(content=packed[idx])
                except Exception as e:
                    print(f"Discord edit error for {lb_name} msg {mid}: {e}")

        except Exception as e:
            print(f"Discord update error for {lb_name}: {e}")

    return any_updated, placements

FACTION_EMOJIS = {
    "Mason": "<:mason:1350669458863292426>",
    "Agatha": "<:agatha:1350669712593260554>",
    "Tenosia": "<:tenosia:1350669567269273682>",
}

MAP_ATTACK_DEFENSE = {
    "Lionspire": {"attack": "Mason", "defense": "Agatha"},
    "Galencourt": {"attack": "Mason", "defense": "Agatha"},
    "Aberfell": {"attack": "Agatha", "defense": "Mason"},
    "Coxwell": {"attack": "Mason", "defense": "Agatha"},
    "Darkforest": {"attack": "Mason", "defense": "Agatha"},
    "Baudwyn": {"attack": "Tenosia", "defense": "Mason"},
    "Rudhelm": {"attack": "Agatha", "defense": "Mason"},
    "Trayan Citadel": {"attack": "Agatha", "defense": "Mason"},
    "Montcrux": {"attack": "Agatha", "defense": "Tenosia"},
    "Bridgetown": {"attack": "Tenosia", "defense": "Agatha"},
    "Thayic Stronghold": {"attack": "Mason", "defense": "Agatha"},
    "Falmire": {"attack": "Agatha", "defense": "Mason"},
    "Askandir": {"attack": "Mason", "defense": "Tenosia"},
}

def get_leaderboard_entries(name):
    rows = leaderboard_data_ws.get_all_values()
    entries = []
    for row in rows[1:]:  # skip header
        if row[0] == name:
            entries.append({
                'player': row[1] if len(row) > 1 else '',
                'score': int(row[3]) if len(row) > 3 and row[3] else 0,
                'link': row[4] if len(row) > 4 else '',
                'weapon': row[5] if len(row) > 5 else ''
            })
    return sorted(entries, key=lambda x: x['score'], reverse=True)

def pack_chunks_into_slots(chunks, num_slots):
    """Pack chunks into exactly num_slots messages.
    If chunks > slots, concatenate overflow into the last slot (up to 1900 chars).
    If chunks < slots, fill remaining slots with zero-width space.
    """
    if num_slots == 0:
        return []

    if len(chunks) <= num_slots:
        packed = list(chunks)
        while len(packed) < num_slots:
            packed.append("\u200b")
        return packed

    # More chunks than slots — merge excess into last slot
    packed = list(chunks[:num_slots - 1])
    last = chunks[num_slots - 1]
    for extra in chunks[num_slots:]:
        candidate = last + "\n" + extra
        if len(candidate) <= 1900:
            last = candidate
        else:
            # Truncate with overflow note
            last = last + "\n*...continued*"
            break
    packed.append(last)
    return packed


def format_leaderboard_text(entries, overflow=0, show_weapon=False):
    if not entries:
        return ["No entries yet."]

    lines = []
    for e in entries:
        weapon_str = f" — *{e['weapon']}*" if show_weapon and e.get('weapon') else ""
        if e['link']:
            lines.append(f"• {e['player']} — [{e['score']}]({e['link']}){weapon_str}")
        else:
            lines.append(f"• {e['player']} — {e['score']}{weapon_str}")

    if overflow > 0:
        lines.append(f"*...and {overflow} more entries*")

    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 1900:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)

    return chunks

@bot.tree.command(name="setup", description="Set up a bot-owned leaderboard in this thread")
@discord.app_commands.describe(
    name="Name of the leaderboard e.g. War Axe",
    type="Type: weapon, feat, or map"
)
async def setup_leaderboard(interaction: discord.Interaction, name: str, type: str):
    if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
        return

    await interaction.response.send_message("Setting up leaderboard...", ephemeral=True)
    thread = interaction.channel

    if type == "map":
        map_info = MAP_ATTACK_DEFENSE.get(name)
        if not map_info:
            await interaction.edit_original_response(content=f"No attack/defense info found for map: {name}")
            return

        attack_faction = map_info["attack"]
        defense_faction = map_info["defense"]
        attack_emoji = FACTION_EMOJIS[attack_faction]
        defense_emoji = FACTION_EMOJIS[defense_faction]

        attack_name = f"{name} - {attack_faction}"
        defense_name = f"{name} - {defense_faction}"

        attack_entries = get_leaderboard_entries(attack_name)
        defense_entries = get_leaderboard_entries(defense_name)

        attack_chunks = format_leaderboard_text(attack_entries)
        defense_chunks = format_leaderboard_text(defense_entries)

        attack_header = f"{attack_emoji} **{name} {attack_faction}** <:weapon_hs:1350656128635375698>"
        defense_header = f"{defense_emoji} **{name} {defense_faction}** 🛡️"

        await thread.send(file=discord.File(DECORATION_TOP))
        await thread.send(attack_header)
        attack_msg_ids = []
        for chunk in attack_chunks:
            attack_msg = await thread.send(chunk)
            attack_msg_ids.append(str(attack_msg.id))
        await thread.send(file=discord.File(DECORATION_BOTTOM))
        await thread.send(defense_header)
        defense_msg_ids = []
        for chunk in defense_chunks:
            defense_msg = await thread.send(chunk)
            defense_msg_ids.append(str(defense_msg.id))
        await thread.send(file=discord.File(DECORATION_BOTTOM))

        leaderboards_ws.append_row([attack_name, str(thread.id), ",".join(attack_msg_ids), "map"])
        leaderboards_ws.append_row([defense_name, str(thread.id), ",".join(defense_msg_ids), "map"])

        await interaction.edit_original_response(content=f"✅ Map leaderboard for **{name}** set up with both factions.")

    else:
        entries = get_leaderboard_entries(name)
        chunks = format_leaderboard_text(entries, show_weapon=(name in ("100 Kills", "200 Takedowns")))
        await thread.send(file=discord.File(DECORATION_TOP))
        msg_ids = []
        for chunk in chunks:
            lb_msg = await thread.send(chunk)
            msg_ids.append(str(lb_msg.id))
        await thread.send(file=discord.File(DECORATION_BOTTOM))

        leaderboards_ws.append_row([name, str(thread.id), ",".join(msg_ids), type])

        await interaction.edit_original_response(content=f"✅ Leaderboard for **{name}** set up successfully.")

@bot.tree.command(name="refresh", description="Refresh the leaderboard in this thread, or specify a name")
@discord.app_commands.describe(name="Optional: exact leaderboard name. Leave blank to auto-detect from this channel.")
async def refresh_leaderboard(interaction: discord.Interaction, name: str = None):
    if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
        return

    all_lb_rows = leaderboards_ws.get_all_records()

    if name is None:
        # Auto-detect by current channel/thread ID
        channel_id = str(interaction.channel.id)
        matching = [r for r in all_lb_rows if str(r['Thread ID']) == channel_id]
        if not matching:
            await interaction.response.send_message("❌ No leaderboard found for this channel. Try specifying the name manually.", ephemeral=True)
            return
        # If multiple (e.g. map boards with attack + defense), refresh all
        names_to_refresh = [r['Leaderboard Name'] for r in matching]
    else:
        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == name), None)
        if not lb_row:
            await interaction.response.send_message(f"❌ No leaderboard found with name: `{name}`", ephemeral=True)
            return
        names_to_refresh = [name]

    await interaction.response.send_message(f"Refreshing **{', '.join(names_to_refresh)}**...", ephemeral=True)

    for lb_name in names_to_refresh:
        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
        if not lb_row:
            continue

        entries = get_leaderboard_entries(lb_name)
        entries = sorted(entries, key=lambda x: x['score'], reverse=True)

        if lb_name in ("100 Kills", "200 Takedowns"):
            overflow = max(0, len(entries) - 50)
            display_entries = entries[:50]
        else:
            overflow = 0
            display_entries = entries

        chunks = format_leaderboard_text(display_entries, overflow, show_weapon=(lb_name in ("100 Kills", "200 Takedowns")))

        thread_id = int(lb_row['Thread ID'])
        message_ids = [int(mid.strip()) for mid in str(lb_row['Message ID']).split(',') if mid.strip()]

        try:
            guild = interaction.guild
            thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)

            # Pack all chunks into existing messages — never post new ones (would appear after decoration)
            packed = pack_chunks_into_slots(chunks, len(message_ids))

            for idx, mid in enumerate(message_ids):
                try:
                    msg = await thread.fetch_message(mid)
                    await msg.edit(content=packed[idx])
                except Exception as e:
                    print(f"Refresh edit error for {lb_name} msg {mid}: {e}")

        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Error refreshing {lb_name}: {e}")
            return

    await interaction.edit_original_response(content=f"✅ **{', '.join(names_to_refresh)}** refreshed successfully.")

# ── BOUNTY HELPERS ────────────────────────────────────────────────────────────

def get_active_bounty():
    """Return the active bounty row as a dict, or None."""
    rows = bounty_ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 9 and row[8] == 'TRUE':
            return {
                'row': i,
                'title': row[0],
                'channel_id': int(row[1]) if row[1] else None,
                'message_id': int(row[2]) if row[2] else None,
                'theme_emoji': row[3],
                'weapons': json.loads(row[4]) if row[4] else {},
                'special_challenge': row[5],
                'special_done': row[6] == '1',
                'completions': json.loads(row[7]) if row[7] else [],
                'role_id': int(row[9]) if len(row) > 9 and row[9] else None,
                'forum_channel_id': int(row[10]) if len(row) > 10 and row[10] else None,
                'completions_msg_id': int(row[11]) if len(row) > 11 and row[11] else None,
                'bonus_msg_id': int(row[12]) if len(row) > 12 and row[12] else None,
            }
    return None

def build_bounty_card(title, theme_emoji, weapons, special_challenge, special_done, completions):
    """
    weapons: dict of { display_name: {"current": int, "total": int} }
    completions: list of {"name": str, "date": str}
    """
    lines = []
    lines.append("╭──────────────────────────────╮")
    lines.append(f"     😼 {title} ◈")
    lines.append("╰──────────────────────────────╯")

    for weapon, data in weapons.items():
        cur = data['current']
        tot = data['total']
        label = f"~~{weapon}~~" if cur >= tot else weapon
        progress = f"{cur}/{tot}"
        lines.append(f"▸ {label:<22} {progress:>4}")

    lines.append("╭──────────────────────────────╮")
    lines.append(f"      {theme_emoji} SPECIAL CHALLENGE {theme_emoji}")
    lines.append("╰──────────────────────────────╯")
    sc_progress = "1/1" if special_done else "0/1"
    lines.append(f"▸ {special_challenge:<22} {sc_progress:>4}")

    if completions:
        lines.append("")
        lines.append("🏆 **Completions**")
        for idx, c in enumerate(completions, 1):
            lines.append(f"{idx}. {c['name']} — {c['date']}")

    return "```\n" + "\n".join(lines) + "\n```"

def save_bounty_state(row_idx, weapons, special_done, completions, message_id=None):
    bounty_ws.update_cell(row_idx, 5, json.dumps(weapons))
    bounty_ws.update_cell(row_idx, 7, '1' if special_done else '0')
    bounty_ws.update_cell(row_idx, 8, json.dumps(completions))
    if message_id:
        bounty_ws.update_cell(row_idx, 3, str(message_id))

async def check_bounty_completion(guild, bounty, player_name, player_id):
    """Check if player just completed the full bounty. Returns True if newly completed."""
    weapons = bounty['weapons']
    # All weapons maxed out
    all_weapons_done = all(w['current'] >= w['total'] for w in weapons.values())
    if not all_weapons_done:
        return False
    # Check they're not already in completions
    completions = bounty['completions']
    already = any(str(c.get('id')) == str(player_id) for c in completions)
    if already:
        return False
    return True

# ── BOUNTY COMMANDS ───────────────────────────────────────────────────────────

@bot.tree.command(name="bounty_create", description="Create a new monthly bounty (mod only)")
@discord.app_commands.describe(
    title="Bounty title e.g. Meowy's Birthday Bounty",
    channel_name="Channel name e.g. meowys-birthday-bounty",
    theme_emoji="Emoji pair for special challenge header e.g. 🐾",
    weapon1="Weapon slot 1 — e.g. Messer or Messer:9 for custom total (default 3)",
    weapon2="Weapon slot 2 — e.g. Dane Axe or Dane Axe:6",
    weapon3="Weapon slot 3", weapon4="Weapon slot 4",
    weapon5="Weapon slot 5", weapon6="Weapon slot 6",
    weapon7="Weapon slot 7 (optional)",
    special_challenge="Special challenge description e.g. 100 Takedowns on Cat Claws (Katars)"
)
async def bounty_create(
    interaction: discord.Interaction,
    title: str,
    channel_name: str,
    theme_emoji: str,
    weapon1: str, weapon2: str, weapon3: str,
    weapon4: str, weapon5: str, weapon6: str,
    special_challenge: str,
    weapon7: str = None,
):
    if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
        return

    await interaction.response.send_message("Creating bounty...", ephemeral=True)

    # Deactivate any existing active bounty
    rows = bounty_ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 9 and row[8] == 'TRUE':
            bounty_ws.update_cell(i, 9, 'FALSE')

    # Parse weapons — supports "WeaponName" (default 3) or "WeaponName:9" (custom total)
    def parse_weapon(raw):
        if raw is None:
            return None
        raw = raw.strip()
        if ':' in raw:
            parts = raw.rsplit(':', 1)
            name = parts[0].strip()
            try:
                total = int(parts[1].strip())
            except ValueError:
                total = 3
        else:
            name = raw
            total = 3
        return name, total

    raw_weapons = [weapon1, weapon2, weapon3, weapon4, weapon5, weapon6]
    if weapon7:
        raw_weapons.append(weapon7)

    # Build weapons dict: name → {current, total}
    weapons = {}
    for raw in raw_weapons:
        parsed = parse_weapon(raw)
        if parsed:
            name, total = parsed
            weapons[name] = {"current": 0, "total": total}

    guild = interaction.guild

    # Format channel name with cat emoji prefix
    formatted_channel_name = f"🐱 ┃{channel_name}"

    # Create the text channel under The Bulletin Board category
    bulletin_board = guild.get_channel(BULLETIN_BOARD_CATEGORY_ID)
    channel = await guild.create_text_channel(formatted_channel_name, category=bulletin_board)

    # Create the forum channel under The Ledger category
    ledger = guild.get_channel(LEDGER_CATEGORY_ID)
    forum_channel = None
    forum_error = None
    if not ledger:
        forum_error = f"Ledger category not found (ID: {LEDGER_CATEGORY_ID})"
    else:
        try:
            forum_channel = await guild.create_forum(formatted_channel_name, category=ledger)
        except Exception as e:
            forum_error = str(e)
            print(f"Forum channel create error: {e}")

    # Create the bounty role — lavender colour, cat emoji icon
    lavender = discord.Colour(0xB57EDC)
    bounty_role = await guild.create_role(
        name=title,
        colour=lavender,
        mentionable=True,
        reason=f"Bounty role for: {title}"
    )
    # Set the role icon to the cat emoji (requires server with role icons feature)
    try:
        await bounty_role.edit(unicode_emoji="🐱")
    except Exception:
        pass  # Server may not support role icons — silently skip

    # Save to sheet (col 10 = RoleID, col 11 = ForumChannelID, cols 12-13 = msg IDs set later)
    bounty_ws.append_row([
        title,
        str(channel.id),
        '',
        theme_emoji,
        json.dumps(weapons),
        special_challenge,
        '0',
        json.dumps([]),
        'TRUE',
        str(bounty_role.id),
        str(forum_channel.id) if forum_channel else '',
        '',
        ''
    ])

    forum_mention = forum_channel.mention if forum_channel else f"*(forum creation failed: {forum_error})*"
    msg = (
        f"✅ Bounty **{title}** created!\n"
        f"📋 Bulletin Board: {channel.mention} — post your art there to activate the leaderboards\n"
        f"📖 Ledger: {forum_mention}\n"
        f"🎭 Role: {bounty_role.mention}"
    )
    await interaction.edit_original_response(content=msg)


@bot.tree.command(name="bounty_end", description="End the active bounty with a 24hr grace period (mod only)")
async def bounty_end(interaction: discord.Interaction):
    if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
        return

    bounty = get_active_bounty()
    if not bounty:
        await interaction.response.send_message("No active bounty found.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"⏳ Grace period started for **{bounty['title']}**. Channel will be deleted in 24 hours.",
        ephemeral=False
    )

    # Mark inactive immediately so no new completions count
    bounty_ws.update_cell(bounty['row'], 9, 'FALSE')

    # Wait 24 hours then delete the channel and role
    await asyncio.sleep(86400)
    guild = interaction.guild
    channel = guild.get_channel(bounty['channel_id'])
    if channel:
        await channel.delete(reason=f"Bounty ended: {bounty['title']}")
    if bounty['role_id']:
        role = guild.get_role(bounty['role_id'])
        if role:
            await role.delete(reason=f"Bounty ended: {bounty['title']}")


@bot.tree.command(name="bounty_status", description="Show the current active bounty card")
async def bounty_status(interaction: discord.Interaction):
    bounty = get_active_bounty()
    if not bounty:
        await interaction.response.send_message("No active bounty right now.", ephemeral=True)
        return
    card = build_bounty_card(
        bounty['title'], bounty['theme_emoji'], bounty['weapons'],
        bounty['special_challenge'], bounty['special_done'], bounty['completions']
    )
    await interaction.response.send_message(card, ephemeral=True)



def get_player_bounty_progress(bounty_title, discord_id):
    """Get a player's row from BountyPlayers sheet, or None."""
    rows = bounty_players_ws.get_all_values()
    discord_id_str = str(discord_id)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and row[0] == bounty_title and row[1] == discord_id_str:
            return {
                'row': i,
                'player_name': row[2] if len(row) > 2 else '',
                'forum_post_id': int(row[3]) if len(row) > 3 and row[3] else None,
                'progress': json.loads(row[4]) if len(row) > 4 and row[4] else {}
            }
    return None

def save_player_bounty_progress(row_idx, player_name, forum_post_id, progress):
    bounty_players_ws.update_cell(row_idx, 3, player_name)
    bounty_players_ws.update_cell(row_idx, 4, str(forum_post_id) if forum_post_id else '')
    bounty_players_ws.update_cell(row_idx, 5, json.dumps(progress))

def build_player_bounty_card(bounty, player_progress):
    """Build a personal bounty card for a player showing only their own progress."""
    weapons = bounty['weapons']
    lines = []
    lines.append("╭──────────────────────────────╮")
    lines.append(f"     😼 {bounty['title']} ◈")
    lines.append("╰──────────────────────────────╯")

    for weapon, data in weapons.items():
        tot = data['total']
        raw = player_progress.get(weapon, 0)
        cur = raw['current'] if isinstance(raw, dict) else int(raw)
        label = f"~~{weapon}~~" if cur >= tot else weapon
        progress = f"{cur}/{tot}"
        lines.append(f"▸ {label:<22} {progress:>4}")

    lines.append("╭──────────────────────────────╮")
    lines.append(f"      {bounty['theme_emoji']} SPECIAL CHALLENGE {bounty['theme_emoji']}")
    lines.append("╰──────────────────────────────╯")
    sc_cur = player_progress.get('__special__', 0)
    sc_progress = f"{sc_cur}/1"
    lines.append(f"▸ {bounty['special_challenge']:<22} {sc_progress:>4}")

    return "```\n" + "\n".join(lines) + "\n```"

async def update_bounty(guild, weapon, player_name, player_id, takedowns):
    """Called from finalise_submission. Updates bounty progress if weapon qualifies. Returns True if weapon matched."""
    if takedowns < 100:
        return False

    bounty = get_active_bounty()
    if not bounty:
        return False

    weapons = bounty['weapons']

    # Normalize weapon name for matching (case-insensitive)
    matched_key = next((k for k in weapons if k.lower() == weapon.lower()), None)
    if not matched_key:
        return False  # Weapon not on this bounty

    # Increment global participation counter (informational only — no cap)
    w = weapons[matched_key]
    w['current'] += 1
    weapons[matched_key] = w

    # Assign the bounty role to the player if not already assigned
    bounty_channel = guild.get_channel(bounty['channel_id'])
    bounty_role = guild.get_role(bounty['role_id']) if bounty['role_id'] else None
    member = guild.get_member(player_id)
    if member and bounty_role and bounty_role not in member.roles:
        try:
            await member.add_roles(bounty_role, reason="Bounty participant")
        except Exception as e:
            print(f"Bounty role assign error: {e}")

    # ── PLAYER PROGRESS ───────────────────────────────────────────────────────
    player_row = get_player_bounty_progress(bounty['title'], str(player_id))
    if player_row:
        player_progress = player_row['progress']
        forum_post_id = player_row['forum_post_id']
    else:
        player_progress = {}
        forum_post_id = None

    # Increment player's personal count for this weapon
    raw = player_progress.get(matched_key, 0)
    cur = raw['current'] if isinstance(raw, dict) else int(raw)
    player_progress[matched_key] = cur + 1

    # Get or create the player's forum post
    forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
    forum_channel = guild.get_channel(forum_channel_id)
    if forum_channel and isinstance(forum_channel, discord.ForumChannel):
        if forum_post_id:
            # Edit the card message (second message, after the theme emoji)
            try:
                forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
                messages = []
                async for msg in forum_thread.history(limit=5, oldest_first=True):
                    messages.append(msg)
                bot_messages = [m for m in messages if m.author.bot]
                card_text = build_player_bounty_card(bounty, player_progress)
                if bot_messages:
                    await bot_messages[-1].edit(content=card_text)
                else:
                    await forum_thread.send(card_text)
            except Exception as e:
                print(f"Forum post update error: {e}")
                forum_post_id = None

        if not forum_post_id:
            # Create new forum post for this player
            # First message is the theme emoji, bot then posts the bounty card
            try:
                new_thread, first_msg = await forum_channel.create_thread(
                    name=player_name,
                    content=bounty['theme_emoji']
                )
                card_text = build_player_bounty_card(bounty, player_progress)
                await new_thread.send(card_text)
                forum_post_id = new_thread.id
            except Exception as e:
                print(f"Forum post create error: {e}")

    # Save player progress
    if player_row:
        save_player_bounty_progress(player_row['row'], player_name, forum_post_id, player_progress)
    else:
        bounty_players_ws.append_row([
            bounty['title'], str(player_id), player_name,
            str(forum_post_id) if forum_post_id else '', json.dumps(player_progress)
        ])

    # ── COMPLETIONS & BONUS BOARDS ───────────────────────────────────────────
    completions = bounty['completions']
    newly_completed = await check_bounty_completion(guild, bounty, player_name, player_id)
    if newly_completed:
        date_str = datetime.now(timezone.utc).strftime('%b %d')
        completions.append({"id": str(player_id), "name": player_name, "date": date_str})
        # Ping the bounty role in the bounty channel
        if bounty_channel and bounty_role:
            try:
                await bounty_channel.send(
                    f"{bounty_role.mention} 🏆 **{player_name}** has completed the **{bounty['title']}**!"
                )
            except Exception as e:
                print(f"Bounty completion ping error: {e}")

    # Save updated state
    save_bounty_state(bounty['row'], weapons, bounty['special_done'], completions)

    # Update completions board in Bulletin Board channel
    if bounty_channel and bounty.get('completions_msg_id'):
        try:
            if completions:
                lines = [f"```"]
                lines.append(f"╭──────────────────────────────╮")
                lines.append(f"  {bounty['theme_emoji']} COMPLETIONS {bounty['theme_emoji']}")
                lines.append(f"╰──────────────────────────────╯")
                for idx, c in enumerate(completions, 1):
                    lines.append(f"{idx}. {c['name']}  {c['date']}")
                lines.append("```")
                comp_text = "\n".join(lines)
            else:
                comp_text = (
                    f"```\n╭──────────────────────────────╮\n"
                    f"  {bounty['theme_emoji']} COMPLETIONS {bounty['theme_emoji']}\n"
                    f"╰──────────────────────────────╯\n"
                    f"No completions yet.\n```"
                )
            comp_msg = await bounty_channel.fetch_message(bounty['completions_msg_id'])
            await comp_msg.edit(content=comp_text)
        except Exception as e:
            print(f"Completions board update error: {e}")

    return True


@bot.tree.command(name="bounty_add_card", description="Manually create a bounty forum card for a player (mod only)")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(member="The player to create a card for")
async def bounty_add_card(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)

    bounty = get_active_bounty()
    if not bounty:
        await interaction.followup.send("No active bounty found.", ephemeral=True)
        return

    guild = interaction.guild
    forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
    forum_channel = guild.get_channel(forum_channel_id)
    if not forum_channel:
        await interaction.followup.send("❌ Ledger forum channel not found.", ephemeral=True)
        return

    player_name = member.nick if member.nick else member.display_name
    player_id = member.id

    # Check if player already has a card
    player_row = get_player_bounty_progress(bounty['title'], str(player_id))
    if player_row and player_row.get('forum_post_id'):
        await interaction.followup.send(f"⚠️ {player_name} already has a forum card.", ephemeral=True)
        return

    # Build progress from existing BountyPlayers data or empty
    if player_row:
        player_progress = player_row['progress']
        row_idx = player_row['row']
    else:
        player_progress = {w: {"current": 0, "total": bounty['weapons'][w]['total']} for w in bounty['weapons']}
        row_idx = None

    # Create forum post
    try:
        new_thread, _ = await forum_channel.create_thread(
            name=player_name,
            content=bounty['theme_emoji']
        )
        card_text = build_player_bounty_card(bounty, player_progress)
        await new_thread.send(card_text)
        forum_post_id = new_thread.id

        # Save to BountyPlayers sheet
        if row_idx:
            save_player_bounty_progress(row_idx, player_name, forum_post_id, player_progress)
        else:
            bounty_players_ws.append_row([
                bounty['title'],
                str(player_id),
                player_name,
                str(forum_post_id),
                json.dumps(player_progress)
            ])

        await interaction.followup.send(f"✅ Created bounty card for **{player_name}**.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="seed_players", description="Seed the Players tab from a Discord role (admin only)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def seed_players(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        role = guild.get_role(1433215577173786758)

        if not role:
            await interaction.followup.send("❌ Role not found.", ephemeral=True)
            return

        existing_rows = players_ws.get_all_values()
        existing_ids = set(row[0] for row in existing_rows[1:] if row)

        rows_to_add = []
        skipped = 0

        for member in role.members:
            discord_id = str(member.id)
            display_name = member.nick if member.nick else member.display_name

            if discord_id in existing_ids:
                skipped += 1
                continue

            rows_to_add.append([discord_id, display_name, ""])

        if rows_to_add:
            players_ws.append_rows(rows_to_add, value_input_option="RAW")

        await interaction.followup.send(
            f"✅ Seeded **{len(rows_to_add)}** players from role.\n"
            f"⏭️ Skipped **{skipped}** already in the sheet.",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)



@bot.tree.command(name="patch_notes", description="Post patch notes to the current channel (mod only)")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(version="Version number e.g. v1.3.0", notes="What changed — use | to separate bullet points")
async def patch_notes(interaction: discord.Interaction, version: str, notes: str):
    await interaction.response.defer(ephemeral=True)

    bullets = [f"• {n.strip()}" for n in notes.split("|")]
    bullet_text = "\n".join(bullets)

    msg = (
        f"📝 **Cigar Lounge Butler {version}**\n"
        f"──────────────────────\n"
        f"{bullet_text}"
    )

    await interaction.channel.send(msg)
    await interaction.followup.send(f"✅ Patch notes posted for {version}.", ephemeral=True)

@bot.tree.command(name="bounty_refresh_card", description="Refresh a player's bounty forum card (mod only)")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(member="The player whose card to refresh")
async def bounty_refresh_card(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)

    bounty = get_active_bounty()
    if not bounty:
        await interaction.followup.send("No active bounty found.", ephemeral=True)
        return

    guild = interaction.guild
    player_name = member.nick if member.nick else member.display_name
    player_id = str(member.id)

    player_row = get_player_bounty_progress(bounty['title'], player_id)
    if not player_row:
        await interaction.followup.send(f"❌ No bounty data found for {player_name}.", ephemeral=True)
        return

    forum_post_id = player_row.get('forum_post_id')
    if not forum_post_id:
        await interaction.followup.send(f"❌ No forum card found for {player_name}. Use /bounty_add_card instead.", ephemeral=True)
        return

    forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
    forum_channel = guild.get_channel(forum_channel_id)
    if not forum_channel:
        await interaction.followup.send("❌ Ledger forum channel not found.", ephemeral=True)
        return

    try:
        forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
        player_progress = player_row['progress']
        print(f"[REFRESH] player_progress={json.dumps(player_progress)}")
        card_text = build_player_bounty_card(bounty, player_progress)
        messages = []
        async for msg in forum_thread.history(limit=5, oldest_first=True):
            messages.append(msg)
        # Find the last bot message to edit
        bot_messages = [m for m in messages if m.author.bot]
        if bot_messages:
            await bot_messages[-1].edit(content=card_text)
        else:
            await forum_thread.send(card_text)
        await interaction.followup.send(f"✅ Refreshed bounty card for **{player_name}**.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


def calculate_butler_stats():
    """Pull stats from Submissions and LeaderboardData sheets."""
    subs = submissions_ws.get_all_values()[1:]
    ld = leaderboard_data_ws.get_all_values()[1:]

    # Submission stats
    player_counts = {}
    weapon_counts = {}
    map_counts = {}
    top_td = (0, "")
    top_kills = (0, "")
    players_set = set()

    for row in subs:
        if len(row) < 9:
            continue
        player = row[1].strip()
        weapon = row[3].strip()
        map_name = row[5].strip()
        try:
            td = int(row[7])
            kills = int(row[8])
        except (ValueError, IndexError):
            td, kills = 0, 0

        player_counts[player] = player_counts.get(player, 0) + 1
        weapon_counts[weapon] = weapon_counts.get(weapon, 0) + 1
        map_counts[map_name] = map_counts.get(map_name, 0) + 1
        players_set.add(player)
        if td > top_td[0]:
            top_td = (td, player)
        if kills > top_kills[0]:
            top_kills = (kills, player)

    most_active = max(player_counts, key=player_counts.get) if player_counts else "N/A"
    fav_weapon = max(weapon_counts, key=weapon_counts.get) if weapon_counts else "N/A"
    fav_map = max(map_counts, key=map_counts.get) if map_counts else "N/A"

    # Also check LeaderboardData 100 Kills board for historical entries missing from Submissions
    for row in ld:
        if len(row) < 4:
            continue
        if row[0].strip() == '100 Kills':
            player = row[1].strip()
            try:
                score = int(row[3])
            except ValueError:
                continue
            if score > top_kills[0]:
                top_kills = (score, player)

    # Title calculations from LeaderboardData
    # Placement boards: weapon boards, map boards (" - "), and feat top-10 boards (Mallet, Knife, Flawless, Healing Horn)
    # Excluded from placement titles: 100 Kills, 200 Takedowns (have their own title logic)
    weapon_placements = {}   # player -> [placements] — weapon + feat boards
    map_placements = {}      # player -> [placements] — map boards
    non_weapon_feat_placements = {}  # player -> [placements] — Flawless/Healing Horn (grand marshal only)

    WEAPON_FEAT_BOARDS = {'Mallet', 'Knife'}
    NON_WEAPON_FEAT_BOARDS = {'Flawless', 'Healing Horn'}
    SKIP_LB = {'100 Kills', '200 Takedowns'}

    lb_groups = {}
    for row in ld:
        if len(row) < 4:
            continue
        lb_name = row[0].strip()
        player = row[1].strip()
        if lb_name not in lb_groups:
            lb_groups[lb_name] = []
        lb_groups[lb_name].append(player)

    for lb_name, players in lb_groups.items():
        if lb_name in SKIP_LB:
            continue
        is_map = ' - ' in lb_name
        for i, player in enumerate(players[:10]):
            placement = i + 1
            if is_map:
                map_placements.setdefault(player, []).append(placement)
            elif lb_name in NON_WEAPON_FEAT_BOARDS:
                # Flawless and Healing Horn count toward Grand Marshal only
                non_weapon_feat_placements.setdefault(player, []).append(placement)
            else:
                # Regular weapon boards + Mallet/Knife count toward Weapons Master
                weapon_placements.setdefault(player, []).append(placement)

    def best_placement_title(d, min_boards=1, breadth_first=False):
        """Return player with best placement title.
        breadth_first=True: most boards wins, avg placement as tiebreaker.
        breadth_first=False: best avg wins, most boards as tiebreaker.
        min_boards: minimum boards required to qualify.
        """
        if not d:
            return None
        qualified = {p: v for p, v in d.items() if len(v) >= min_boards}
        if not qualified:
            return None
        if breadth_first:
            return min(qualified.keys(), key=lambda p: (-len(qualified[p]), sum(qualified[p]) / len(qualified[p])))
        else:
            return min(qualified.keys(), key=lambda p: (sum(qualified[p]) / len(qualified[p]), -len(qualified[p])))

    combined = {}
    for p, v in weapon_placements.items():
        combined.setdefault(p, []).extend(v)
    for p, v in map_placements.items():
        combined.setdefault(p, []).extend(v)
    for p, v in non_weapon_feat_placements.items():
        combined.setdefault(p, []).extend(v)

    grand_marshal = best_placement_title(combined, min_boards=15, breadth_first=True)
    weapons_master = best_placement_title(weapon_placements, min_boards=9, breadth_first=True)
    campaign_master = best_placement_title(map_placements, min_boards=6, breadth_first=True)

    # Headhunter — 100 Kills board: best average kills score, tiebreak on submission count
    # Butcher — 200 Takedowns board: best average takedowns score, tiebreak on submission count
    kills_scores = {}    # player -> [kill scores]
    td_scores = {}       # player -> [takedown scores]

    for row in ld:
        if len(row) < 3:
            continue
        lb_name = row[0].strip()
        player = row[1].strip()
        try:
            score = int(row[2])
        except (ValueError, IndexError):
            continue
        if lb_name == '100 Kills':
            kills_scores.setdefault(player, []).append(score)
        elif lb_name == '200 Takedowns':
            td_scores.setdefault(player, []).append(score)

    def best_score_title(d):
        """Return player with best weighted score: avg * log(count+1)."""
        if not d:
            return None
        import math
        return max(d.keys(), key=lambda p: (sum(d[p]) / len(d[p])) * math.log(len(d[p]) + 1))

    headhunter = best_score_title(kills_scores)
    butcher = best_score_title(td_scores)

    return {
        'most_active': f"{most_active} — {player_counts.get(most_active, 0)} runs",
        'top_td': f"{top_td[1]} — {top_td[0]} TD",
        'top_kills': f"{top_kills[1]} — {top_kills[0]} K",
        'fav_weapon': f"{fav_weapon} — {weapon_counts.get(fav_weapon, 0)} runs",
        'fav_map': f"{fav_map} — {map_counts.get(fav_map, 0)} runs",
        'total_runs': len(subs),
        'total_players': len(players_set),
        'grand_marshal': grand_marshal or "N/A",
        'weapons_master': weapons_master or "N/A",
        'campaign_master': campaign_master or "N/A",
        'headhunter': headhunter or "N/A",
        'butcher': butcher or "N/A",
    }


def build_favourites_embed(stats):
    return (
        f"**📋 The Butler's Favourites**\n"
        f"\n"
        f"**Most Active Knight**\n{stats['most_active']}\n"
        f"\n"
        f"**Highest Takedowns**\n{stats['top_td']}\n"
        f"\n"
        f"**Most Kills**\n{stats['top_kills']}\n"
        f"\n"
        f"**Favourite Weapon**\n{stats['fav_weapon']}\n"
        f"\n"
        f"**Favourite Map**\n{stats['fav_map']}\n"
        f"\n"
        f"**Total Runs:** {stats['total_runs']} | **Total Players:** {stats['total_players']}\n"
        f"\n"
        f"─────────────────────\n"
        f"🏆 **Grand Marshal** — {stats['grand_marshal']}\n"
        f"⚔️ **Weapons Master** — {stats['weapons_master']}\n"
        f"🗺️ **Campaign Master** — {stats['campaign_master']}\n"
        f"💀 **Headhunter** — {stats['headhunter']}\n"
        f"🩸 **Butcher** — {stats['butcher']}"
    )


async def update_title_roles(guild, stats):
    """Assign title roles and announce changes in #main."""
    main_channel = guild.get_channel(MAIN_CHANNEL_ID)

    title_configs = [
        ('grand_marshal', GRAND_MARSHAL_ROLE_ID, 'Grand Marshal',
         "After careful review of the battlefield records, I must inform {old} that your commission has been reassigned. {new}, the Grand Marshal's standard is yours to carry. Try not to embarrass the household."),
        ('weapons_master', WEAPONS_MASTER_ROLE_ID, 'Weapons Master',
         "It appears the armory has a new curator. {old}, your weapons have been... redistributed. {new}, the Weapons Master title is yours. Do try to keep the blades sharp."),
        ('campaign_master', CAMPAIGN_MASTER_ROLE_ID, 'Campaign Master',
         "The campaign maps have been redrawn. {old}, your routes have been rerouted. {new}, you are hereby appointed Campaign Master. The butler expects nothing less than total domination."),
        ('headhunter', HEADHUNTER_ROLE_ID, 'Headhunter',
         "The tally has been reviewed. {old}, your count has been surpassed. {new}, the Headhunter title is yours. The butler suggests you stop being modest about it."),
        ('butcher', BUTCHER_ROLE_ID, 'Butcher',
         "The battlefield reports are in. {old}, someone has left more bodies behind. {new}, you are hereby declared the Butcher. The butler finds the whole affair rather distasteful, but acknowledges your commitment."),
    ]

    for stat_key, role_id, title_name, msg_template in title_configs:
        new_holder_name = stats.get(stat_key, 'N/A')
        if new_holder_name == 'N/A':
            continue

        role = guild.get_role(role_id)
        if not role:
            continue

        # Find current holder
        current_holders = [m for m in guild.members if role in m.roles]

        # Find new holder by display name
        new_member = discord.utils.find(
            lambda m: (m.nick or m.display_name).lower() == new_holder_name.lower(),
            guild.members
        )
        if not new_member:
            continue

        # Check if it changed hands
        if current_holders and new_member in current_holders:
            continue  # Same person, no change

        # Remove from old holders
        for old_member in current_holders:
            try:
                await old_member.remove_roles(role)
            except Exception:
                pass

        # Give to new holder
        try:
            await new_member.add_roles(role)
        except Exception:
            pass

        # Announce in main
        if main_channel and current_holders:
            old_mention = current_holders[0].mention
            new_mention = new_member.mention
            msg = msg_template.format(old=old_mention, new=new_mention)
            try:
                await main_channel.send(msg)
            except Exception as e:
                print(f"Title announcement error: {e}")


@bot.tree.command(name="butlers_report", description="Summon the Butler's Favourites report")
async def butlers_report(interaction: discord.Interaction):
    import time

    # Check if user is in Players sheet
    player_ids = set()
    for row in players_ws.get_all_values()[1:]:
        if row and row[0]:
            player_ids.add(row[0].strip())

    if str(interaction.user.id) not in player_ids:
        await interaction.response.send_message(
            "I'm afraid I don't recognise you, sir. Only registered players may summon the report.",
            ephemeral=True
        )
        return

    # Rate limit — 5 minutes
    now = time.time()
    last = _butlers_report_cooldowns.get(interaction.user.id, 0)
    if now - last < 300:
        remaining = int(300 - (now - last))
        await interaction.response.send_message(
            f"Do you really think my manager would stand for this kind of excessive nagging? Try again in {remaining} seconds.",
            ephemeral=True
        )
        return

    _butlers_report_cooldowns[interaction.user.id] = now

    await interaction.response.defer()

    try:
        stats = calculate_butler_stats()
        embed_text = build_favourites_embed(stats)

        # Post publicly in the channel
        await interaction.followup.send(embed_text)

        # Update pinned favourites channel if set
        if BUTLERS_FAVOURITES_CHANNEL_ID:
            fav_channel = interaction.guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
            if fav_channel:
                try:
                    async for msg in fav_channel.history(limit=5):
                        if msg.author == interaction.guild.me:
                            await msg.edit(content=embed_text)
                            break
                    else:
                        await fav_channel.send(embed_text)
                except Exception as e:
                    print(f"Favourites channel update error: {e}")

        # Update title roles
        try:
            await update_title_roles(interaction.guild, stats)
        except Exception as e:
            print(f"Title role update error: {e}")

    except Exception as e:
        await interaction.followup.send(f"❌ The butler has encountered an error: {e}")


import traceback
try:
    bot.run(TOKEN)
except Exception as e:
    traceback.print_exc()
    input("Press Enter to exit...")