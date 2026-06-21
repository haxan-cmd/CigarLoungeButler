import discord
import os
import asyncio
import gspread
import json
from google.oauth2.service_account import Credentials
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime

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

SUBMISSIONS_CHANNEL_ID = 1328832440927518920

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.reactions = True

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
    "Heavy Cavalry Sword", "Knife", "Mallet", "One-Handed Spear",
    "Pick Axe", "Rapier", "Short Sword", "Sword", "Warhammer", "Cudgel"
]

CLASS_WEAPON_MAP = {
    "Devastator": ["Battle Axe", "Executioner's Axe", "Greatsword", "Highland Sword", "Maul", "War Club"],
    "Raider": ["Dane Axe", "Glaive", "Messer", "Two-Handed Hammer"],
    "Ambusher": ["Cudgel", "Dagger", "Hatchet", "Katars", "Knife", "Short Sword"],
    "Poleman": ["Glaive", "Goedendag", "Halberd", "Polehammer", "Quarterstaff", "Spear"],
    "Man-at-Arms": ["Falchion", "Fist and Shield", "Healing Horn", "Heavy Cavalry Sword", "Morning Star", "One-Handed Spear", "Rapier", "Sword"],
    "Field Engineer": ["Goedendag", "Mallet", "Pick Axe", "Shovel", "Sledge Hammer"],
    "Officer": ["Greatsword", "Heavy Mace", "Longsword", "Pole Axe", "War Axe"],
    "Guardian": ["Axe", "Falchion", "Fist and Shield", "Heavy Cavalry Sword", "One-Handed Spear", "Warhammer"],
    "Crusader": ["Battle Axe", "Executioner's Axe", "Messer", "Quarterstaff", "Two-Handed Hammer"],
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

def log_submission(discord_name, discord_id, weapon, cls, map_name, faction, takedowns, kills, deaths, vip, feats, message_link):
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    vip_str = "Yes" if vip else "No"
    feats_str = ", ".join(feats) if feats else "None"
    submissions_ws.append_row([
        timestamp, discord_name, str(discord_id), weapon, cls,
        map_name, faction, takedowns, kills, deaths, vip_str, feats_str, message_link
    ])

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
    if message.channel.id != SUBMISSIONS_CHANNEL_ID:
        return
    if not message.attachments:
        return

    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
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

    @discord.ui.button(label='Submit Run', style=discord.ButtonStyle.green, emoji='⚔️')
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        view = WeaponTypeView(self.original_message, self.prompt_msg)
        await interaction.response.send_message(
            content="**Step 1 of 6:** Did you use a two-handed or one-handed weapon?",
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
            await interaction.response.send_message("Terribly sorry, but Takedowns, Kills, and Deaths must be whole numbers. Shall we try again?", ephemeral=True)
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
    await original_message.reply(summary, mention_author=False)
    await asyncio.sleep(1)
    try:
        await prompt_msg.delete()
    except discord.NotFound:
        pass

    # Log to Google Sheets
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
    except Exception as e:
        print(f"Sheet logging error: {e}")

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

    # weapon_hs — only if score qualifies for the weapon leaderboard (not VIP)
    if not vip:
        all_values = leaderboard_data_ws.get_all_values()
        weapon_entries = [row for row in all_values[1:] if row[0] == selected_weapon]
        scores = sorted(
            [int(row[3]) for row in weapon_entries if len(row) > 3 and row[3]],
            reverse=True
        )
        qualifies = len(scores) < 10 or takedowns > scores[9]
        if qualifies:
            await original_message.add_reaction("<:weapon_hs:1350656128635375698>")

    # Update leaderboards
    any_updated = False
    try:
        any_updated = await update_leaderboards(
            interaction, selected_weapon, selected_map, faction,
            takedowns, kills, deaths, vip, feats,
            interaction.user.display_name, message_link
        )
    except Exception as e:
        print(f"Leaderboard update error: {e}")

    if any_updated:
        await original_message.add_reaction("<a:highscore:1360312918545269057>")

async def update_leaderboards(interaction, selected_weapon, selected_map, faction,
                              takedowns, kills, deaths, vip, feats,
                              player_name, message_link):
    guild = interaction.guild
    discord_id = str(interaction.user.id)
    any_updated = False

    # (lb_name, score, top_10, personal_best)
    updates = []

    # Weapon board — exclude VIP, top 10
    if not vip:
        updates.append((selected_weapon, takedowns, True, True))

    # Map board — top 10
    map_lb_name = f"{selected_map} - {faction}"
    updates.append((map_lb_name, takedowns, True, True))

    # Feat boards
    if "Flawless" in feats:
        updates.append(("Flawless", takedowns, False, True))
    if "100 Kills" in feats:
        updates.append(("100 Kills", kills, False, False))
    if "200 Takedowns" in feats:
        updates.append(("200 Takedowns", takedowns, False, False))
    if selected_weapon == "Mallet" and kills >= 100:
        updates.append(("Mallet", takedowns, True, True))
    if selected_weapon == "Knife" and kills >= 100:
        updates.append(("Knife", takedowns, True, True))
    if selected_weapon == "Healing Horn" and kills >= 100:
        updates.append(("Healing Horn", kills, False, True))

    # Columns: A=Leaderboard Name, B=Player, C=Discord ID, D=Score, E=Message Link
    all_values = leaderboard_data_ws.get_all_values()
    all_lb_rows = leaderboards_ws.get_all_records()

    for lb_name, score, top_10, personal_best in updates:
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

        if personal_best:
            if existing_sheet_row is not None:
                if score > existing_score:
                    leaderboard_data_ws.update_cell(existing_sheet_row, 2, player_name)
                    leaderboard_data_ws.update_cell(existing_sheet_row, 4, score)
                    leaderboard_data_ws.update_cell(existing_sheet_row, 5, message_link)
                    any_updated = True
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
                                break
                leaderboard_data_ws.append_row([lb_name, player_name, discord_id, score, message_link])
                any_updated = True
        else:
            leaderboard_data_ws.append_row([lb_name, player_name, discord_id, score, message_link])
            any_updated = True

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
        chunks = format_leaderboard_text(entries)

        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
        if not lb_row:
            print(f"No Leaderboards sheet entry found for: {lb_name}")
            continue

        thread_id = int(lb_row['Thread ID'])
        message_id = int(lb_row['Message ID'])

        try:
            thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
            msg = await thread.fetch_message(message_id)
            await msg.edit(content=chunks[0])
        except Exception as e:
            print(f"Discord update error for {lb_name}: {e}")

    return any_updated

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
                'link': row[4] if len(row) > 4 else ''
            })
    return sorted(entries, key=lambda x: x['score'], reverse=True)

def format_leaderboard_text(entries):
    if not entries:
        return ["No entries yet."]

    lines = []
    for e in entries:
        if e['link']:
            lines.append(f"• {e['player']} - [{e['score']}]({e['link']})")
        else:
            lines.append(f"• {e['player']} - {e['score']}")

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
    if not interaction.user.guild_permissions.manage_messages:
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
        for chunk in attack_chunks:
            attack_msg = await thread.send(chunk)
        await thread.send(file=discord.File(DECORATION_BOTTOM))
        await thread.send(defense_header)
        for chunk in defense_chunks:
            defense_msg = await thread.send(chunk)
        await thread.send(file=discord.File(DECORATION_BOTTOM))

        leaderboards_ws.append_row([attack_name, str(thread.id), str(attack_msg.id), "map"])
        leaderboards_ws.append_row([defense_name, str(thread.id), str(defense_msg.id), "map"])

        await interaction.edit_original_response(content=f"✅ Map leaderboard for **{name}** set up with both factions.")

    else:
        entries = get_leaderboard_entries(name)
        chunks = format_leaderboard_text(entries)
        await thread.send(file=discord.File(DECORATION_TOP))
        lb_msg = None
        for chunk in chunks:
            lb_msg = await thread.send(chunk)
        await thread.send(file=discord.File(DECORATION_BOTTOM))

        leaderboards_ws.append_row([name, str(thread.id), str(lb_msg.id), type])

        await interaction.edit_original_response(content=f"✅ Leaderboard for **{name}** set up successfully.")

import traceback
try:
    bot.run(TOKEN)
except Exception as e:
    traceback.print_exc()
    input("Press Enter to exit...")