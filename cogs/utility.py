from typing import Literal, Optional, Union, TYPE_CHECKING
from utils import subclasses, ui, misc
from discord.ext import commands
from discord import app_commands
from utils import errors
from ext import rtfm
import unicodedata
import discord
import pathlib
import string
import psutil
import json
import time
import re

if TYPE_CHECKING:
    from main import AceBot


class Utility(subclasses.Cog):
    def __init__(self, bot: "AceBot"):
        super().__init__()
        self.emoji = "\N{HAMMER AND WRENCH}"
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ui.PartyMenu(self.bot, {}))
        self.bot.logger.info(
            "Loaded persistent view %s from %s",
            ui.PartyMenu.__qualname__,
            self.qualified_name,
        )

    @commands.Cog.listener("on_voice_state_update")
    async def party_event(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        async with self.bot.pool.acquire() as conn:
            party_config = await conn.fetchone(
                "SELECT value FROM guildConfig WHERE id = :id AND key = :key;",
                {"id": member.id, "key": "party_id"},
            )

        if party_config:
            if not hasattr(self, "vcs"):
                self.vcs = {}

            name = member.name + "'s vc"
            if after.channel and after.channel.id in party_config:
                vc = await member.guild.create_voice_channel(
                    name=name, category=after.channel.category, bitrate=63000
                )
                self.vcs[str(vc.id)] = member.id
                await member.move_to(vc)

            if (
                before.channel
                and before.channel.bitrate == 63000
                and after.channel != before.channel
            ):
                if not before.channel.members:
                    await before.channel.delete()
                elif len(before.channel.members) == 1:
                    self.vcs[str(before.channel.id)] = before.channel.members[0].id

    @commands.guild_only()
    @commands.group(aliases=["vc", "voice"], invoke_without_command=True)
    async def party(self, ctx: commands.Context):
        """An all-in-one menu to configure your own voice channel"""
        vc = ctx.author.voice.channel if ctx.author.voice else None
        msg = ""
        if vc and vc.bitrate == 63000:
            menu = ui.PartyMenu(self.bot, self.vcs)
            await menu.check_ownership(ctx)

            await ctx.reply(
                msg,
                embed=ui.PartyMenu.Embed(ctx, self.vcs),
                view=ui.PartyMenu(self.bot, self.vcs),
            )
        elif vc:
            await ctx.reply(":warning: You are not in a party !")
        else:
            await ctx.reply(":warning: You are not in a vc !")

    @party.command(name="config")
    @commands.guild_only()
    @commands.is_owner()
    async def party_config(
        self, ctx: commands.Context, channel: Union[discord.VoiceChannel, int] = None
    ):
        """Sets the party lobby"""
        if channel:
            channel_id = (
                channel if type(channel) is int else channel.id or ctx.channel.id
            )
            async with self.bot.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO guildConfig (id, key, value) VALUES (:id, :key, :value) ON CONFLICT(id, key) DO UPDATE SET value = :value WHERE id = :id AND key = :key;",
                    {"id": ctx.guild.id, "key": "party_id", "value": channel_id},
                )
            if isinstance(channel, discord.VoiceChannel):
                await ctx.send(f"Party lobby is now {channel.mention}")
            else:
                await ctx.send("Disabled party lobby")
        else:
            async with self.bot.pool.acquire() as conn:
                channel_id = await conn.fetchone(
                    "SELECT value FROM guildConfig WHERE id = :id AND key = :key;",
                    {"id": ctx.guild.id, "key": "party_id"},
                )
            channel = self.bot.get_channel(channel_id[1])
            await ctx.send(
                f"Current channel is {channel.mention if isinstance(channel, discord.VoiceChannel) else None}"
            )

    @commands.hybrid_command(aliases=["char", "character"])
    @app_commands.describe(characters="The characters to get info on")
    async def charinfo(self, ctx: commands.Context, *, characters: str):
        """Gets information on one or multiple characters
        Supports discord emojis, emojis, numbers and any special character !

        P.S.
        {curve} Numbers must be seperated with spaces"""

        results = []
        i: int = 0
        # Process discord-only emojis first
        discord_emojis: list[str] = re.findall(r"<:\w+:\d+>", characters)
        for emoji in discord_emojis:
            characters = characters.replace(emoji, "")
            results.append([emoji, emoji, emoji.split(":")[1]])

        # Check for numbers to convert
        numbers: list[int] = re.findall(r"\d+", characters)
        for num in numbers:
            characters = characters.replace(
                num, chr(int(num)) if int(num) >= 161 and int(num) <= 55291 else ""
            )

        for char in characters:
            if char in string.ascii_letters:
                continue

            name = r"\N{%s}" % unicodedata.name(char, "EXTREMELY RARE ERROR")

            if ord(char) == 32:
                continue

            # If VARIATION SELECTOR
            if ord(char) == 65039:
                results[i - 1][1] += name
                continue

            unicode = (
                str(char.encode("unicode-escape")).strip("b'\\u").strip("0").strip("U")
            )
            url = f"[\\U{unicode}](https://www.fileformat.info/info/unicode/char/{unicode}/index.htm)"
            results.append([char, name, url])

            i += 1

        embed = discord.Embed(
            description="\n".join(
                [
                    f"[{c[0]}] {c[2]} #{ord(c[0]) if len(c[0]) == 1 else 0}```\n{c[1]}```"
                    for c in results
                ]
            )
            or "Nothing to convert",
            color=discord.Color.blurple(),
        )

        await ctx.reply(embed=embed, mention_author=False)


    @commands.hybrid_command(aliases=["rtfd"])
    @app_commands.describe(source="From where to gather docs", obj="What to search for")
    async def rtfm(
        self,
        ctx: commands.Context,
        source: Optional[Literal[tuple(rtfm.literal_rtfm)]] = ("stable"),  # type: ignore
        obj: str = None,
    ):
        """Read The Fucking Manual
        Will fetch discord.py docs for the specifed object"""
        for src, _ in rtfm.RTFM_PAGES.items():
            if source in src:
                await rtfm.do_rtfm(ctx, key=src, obj=obj)

    @rtfm.autocomplete("source")
    async def rtfm_autocomplete(self, interaction: discord.Interaction, current: str):
        return sorted(
            [
                app_commands.Choice(name=source[0].capitalize(), value=source)
                for source, _ in rtfm.RTFM_PAGES.items()
                if current.casefold() in source or len(current) == 0
            ],
            key=lambda c: c.name,
        )[:25]

    async def refresh_info(self, ctx: commands.Context):
        async with ctx.channel.typing():
            self.stats = {}
            # Total lines of code
            self.stats["lines"] = 0
            root = pathlib.Path(__file__).parent.parent
            for file in pathlib.Path(__file__).parent.parent.glob("**/*"):
                if file.name.endswith(".py") and not any(
                    file.is_relative_to(bad) for bad in root.glob("**/.*")
                ):
                    with open(file, "r") as f:
                        self.stats["lines"] += len(f.readlines())

            self.stats["#commands"] = len(self.bot.commands)
            self.stats["#modules"] = len(self.bot.cogs)
            self.stats["#guilds"] = len(self.bot.guilds)
            self.stats["#users"] = len(self.bot.users)

            process = psutil.Process()
            self.stats["pid"] = process.pid
            self.stats["mem"] = process.memory_full_info().rss / 1024**2
            self.stats["mem%"] = process.memory_percent()
            self.stats["cpu%"] = process.cpu_percent()

    @commands.hybrid_command(aliases=["stats", "about"], invoke_without_command=True)
    async def info(self, ctx: commands.Context):
        """Statistics for nerds"""
        if not hasattr(self, "stats"):
            embed = discord.Embed(
                title="\N{BAR CHART} Stats not found",
                description=">>> Gathering information..\nThis may take a few seconds",
                color=discord.Color.red(),
            )
            await ctx.channel.send(embed=embed, delete_after=5)
            await self.refresh_info(ctx)

        embed = discord.Embed(
            title=self.bot.user.display_name,
            description=f"{misc.space}{misc.server}servers: `{self.stats['#guilds']}`\n{misc.space}{misc.members}users: `{self.stats['#users']:,}`",
            color=discord.Color.blurple(),
        )
        embed.set_footer(
            text=f"Made by aceroph using discord.py v{discord.__version__}",
            icon_url=misc.python,
        )
        embed.set_author(
            name="View source on github",
            url=misc.git_source(self.bot),
            icon_url=misc.github,
        )

        embed.add_field(
            name="Timestamps",
            value=f"{misc.space}created on: {discord.utils.format_dt(self.bot.user.created_at, 'd')}\
            \n{misc.space}joined on: {discord.utils.format_dt(ctx.guild.me.joined_at, 'd') if ctx.guild else '`never.`'}\
            \n{misc.space}uptime: `{misc.time_format(time.time()-self.bot.boot)}`",
            inline=False,
        )
        embed.add_field(
            name=f"Code statistics",
            value=f"{misc.space}lines of code: `{self.stats['lines']:,}`\
            \n{misc.space}commands: `{self.stats['#commands']}`\
            \n{misc.space}modules: `{self.stats['#modules']}`",
            inline=False,
        )
        embed.add_field(
            name="Process",
            value=f"{misc.space}pid: `{self.stats['pid']}`\
                    \n{misc.space}cpu: `{self.stats['cpu%']:.1f}%`\
                    \n{misc.space}mem: `{self.stats['mem']:,.1f}MB` (`{self.stats['mem%']:.1f}%`)",
            inline=False,
        )

        # UI
        async def info_show_more(interaction: discord.Interaction):
            # Fetch more stats if non existant or its been more that 5 minutes
            if (
                not "last_updated" in self.stats.keys()
                or time.time() - self.stats["last_updated"] >= 300
            ):
                async with self.bot.pool.acquire() as conn:
                    self.stats["last_updated"] = time.time()

                    # COMMANDS STATS
                    self.stats["total_cmds_ran"] = (
                        await conn.fetchone(
                            "SELECT total(value) FROM statistics WHERE key LIKE 'CMD_RAN:%';"
                        )
                    )[0]
                    self.stats["guild_cmds_ran"] = (
                        await conn.fetchone(
                            "SELECT total(value) FROM statistics WHERE key LIKE 'CMD_RAN:%' AND id = ?;",
                            (interaction.guild_id or 0),
                        )
                    )[0]

                    # MUSIC STATS
                    self.stats["total_songs_played"] = (
                        await conn.fetchone(
                            "SELECT total(value) FROM statistics WHERE key = 'SONG_PLAYED';"
                        )
                    )[0]
                    self.stats["guild_songs_played"] = (
                        await conn.fetchone(
                            "SELECT total(value) FROM statistics WHERE key = 'SONG_PLAYED' AND id = ?;",
                            (interaction.guild_id),
                        )
                    )[0]
                    self.stats["total_playtime"] = (
                        await conn.fetchone(
                            "SELECT total(value) FROM statistics WHERE key = 'SONG_PLAYTIME';"
                        )
                    )[0]
                    self.stats["guild_playtime"] = (
                        await conn.fetchone(
                            "SELECT total(value) FROM statistics WHERE key = 'SONG_PLAYTIME' AND id = ?;",
                            (interaction.guild_id),
                        )
                    )[0]

                    # TOP COMMANDS
                    self.stats["top_guild_commands"] = await conn.fetchall(
                        "SELECT key, value FROM statistics WHERE key LIKE 'CMD_RAN:%' AND id = ? ORDER BY value DESC LIMIT 5;",
                        (interaction.guild_id or 0),
                    )

            medals = [
                "\N{FIRST PLACE MEDAL}",
                "\N{SECOND PLACE MEDAL}",
                "\N{THIRD PLACE MEDAL}",
                "\N{SPORTS MEDAL}",
                "\N{SPORTS MEDAL}",
            ]
            top_commands = f"\n{misc.space}".join(
                [
                    f"{medals[i]} {cmd[0].split(':')[1]}: `{cmd[1]}`"
                    for i, cmd in enumerate(self.stats["top_guild_commands"])
                ]
            )

            embed = discord.Embed(color=discord.Color.blurple())
            embed.add_field(
                name="Top commands",
                value=f"{misc.space}{top_commands}\n\n{misc.space}Total ran: `{self.stats['total_cmds_ran']:.0f}`\
                \n{misc.space}{misc.curve} from {'guild' if interaction.guild else 'DMs'}: `{self.stats['guild_cmds_ran']:.0f}`",
            )
            embed.add_field(
                name="Music statistics",
                value=f"{misc.space}Total songs played: `{self.stats['total_songs_played']:.0f}`\
                \n{misc.space}{misc.curve} from guild: `{self.stats['guild_songs_played']:.0f}`\
                \n\n{misc.space}Total playtime: `{misc.time_format(self.stats['total_playtime'])}`\
                \n{misc.space}{misc.curve} from guild: `{misc.time_format(self.stats['guild_playtime'])}`",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        async def refresh_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.bot.owner_id:
                raise errors.NotYourButton("Only the owner can refresh stats manually")

            embed = discord.Embed(
                title="\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS} Reloading stats",
                description=">>> Gathering information..\nThis may take a few seconds",
                color=discord.Color.blurple(),
            )
            await interaction.response.edit_message(
                embed=embed, view=None, delete_after=5
            )
            await self.refresh_info(ctx)
            await self.info(ctx)

        show_more = discord.ui.Button(
            label="See more", style=discord.ButtonStyle.blurple
        )
        show_more.callback = info_show_more

        refresh = discord.ui.Button(label="Refresh")
        refresh.callback = refresh_callback

        view = subclasses.View()
        view.add_item(show_more)
        view.add_item(refresh)
        view.add_quit(ctx.author, ctx.guild)

        await ctx.reply(embed=embed, mention_author=False, view=view)

    @commands.hybrid_command(name="eval")
    @app_commands.describe(
        language="The language to run the code with", body="The code to run"
    )
    async def _eval(
        self,
        ctx: commands.Context,
        language: Optional[str] = None,
        *,
        body: str,
    ):
        """Runs code in the specified language, aliases work too !"""

        # Get language
        if not language in misc.literal_runtimes:
            language = (
                language + " " if language else ""
            )  # Fix language being none in some cases
            body = language + body
            language = "python"

        # Clean body
        body = misc.clean_codeblock(body)

        # Convert language
        for r in misc.runtimes:
            if (
                language.casefold() == r["language"]
                or language.casefold() in r["aliases"]
            ):
                language = r
                break

        # Format code if python
        if language["language"] == "python":
            code = "import asyncio\nasync def func():\n"
            for i, line in enumerate(body.splitlines()):
                if len(line.strip()) == 0:
                    continue

                if i == len(body.splitlines()) - 1:
                    if not any(
                        [
                            line.strip().startswith(
                                ("print", "raise", "import", "return")
                            ),
                            "=" in line,
                        ]
                    ):
                        code += " " * 2 + f"print({line})\n"
                        continue

                code += " " * 2 + line + "\n"

            body = code + "asyncio.run(func())"

        payload = {
            "language": language["language"],
            "version": language["version"],
            "files": [{"content": body}],
        }
        response = await (
            await self.bot.session.post(
                "https://emkc.org/api/v2/piston/execute", data=json.dumps(payload)
            )
        ).json()

        output = response["run"]["output"] or "No output"

        view = subclasses.View()
        view.add_quit(
            ctx.author,
            ctx.guild,
            False,
            style=discord.ButtonStyle.gray,
            emoji=misc.delete,
            label="Delete",
        )

        await subclasses.reply(
            ctx,
            output,
            prefix=f"```{language['language']}\n",
            suffix="```",
            mention_author=False,
        )

        if not ctx.interaction:
            if response["run"]["code"] != 0:
                await ctx.message.add_reaction(misc.no)
            else:
                await ctx.message.add_reaction(misc.yes)

    @_eval.autocomplete("language")
    async def eval_autocomplete(self, interaction: discord.Interaction, current: str):
        # Avoid repetition
        names = set(
            r["language"]
            for r in misc.runtimes
            if current.casefold() in r["language"] or len(current) == 0
        )
        return sorted(
            [app_commands.Choice(name=n.capitalize(), value=n) for n in names],
            key=lambda c: c.name,
        )[:25]


async def setup(bot):
    await bot.add_cog(Utility(bot))
