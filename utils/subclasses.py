from typing import TYPE_CHECKING, Dict, Any
from discord import app_commands, Message
from . import misc, errors, paginator
from dataclasses import dataclass
from discord.ext import commands
import traceback
import discord
import time

if TYPE_CHECKING:
    from main import AceBot


async def reply(
    ctx: commands.Context,
    content: str,
    prefix: str = "",
    suffix: str = "",
    *args,
    **kwargs,
) -> Message:
    if ctx.interaction and ctx.interaction.response.is_done():
        if len(prefix + content + suffix) > 2000:
            p = paginator.Paginator(ctx, prefix=prefix, suffix=suffix, max_lines=100)
            for line in content.split("\n"):
                p.add_line(line)
            return await p.start()

        return await ctx.interaction.followup.send(
            prefix + content + suffix, *args, **kwargs
        )
    else:
        if len(prefix + content + suffix) > 2000:
            p = paginator.Paginator(ctx, prefix=prefix, suffix=suffix, max_lines=100)
            for line in content.split("\n"):
                p.add_line(line)
            return await p.start()

        return await ctx.reply(prefix + content + suffix, *args, **kwargs)


async def can_use(ctx: commands.Context):
    if ctx.guild:
        if isinstance(ctx.command, commands.HybridCommand):
            app_cmds: list[app_commands.AppCommand] = (
                await ctx.bot.tree.fetch_commands()
            )
            for cmd in app_cmds:
                if cmd.name == ctx.command.qualified_name:
                    try:
                        perms = await cmd.fetch_permissions(ctx.guild)
                        targets = [p.target for p in perms.permissions]
                        return any(
                            [
                                ctx.author in targets,
                                any([r in targets for r in ctx.author.roles]),
                                ctx.channel in targets,
                            ]
                        )
                    except discord.NotFound:
                        break
    return True


@dataclass
class Setting:
    annotation: Any
    default: Any = None


class Cog(commands.Cog):
    def __init__(self, bot=None):
        self.bot: "AceBot" = bot
        self.emoji: str = "<:sadcowboy:1002608868360208565>"
        self.time: float = time.time()
        self.config: Dict[str, Setting] = {"disabled": Setting(bool, False)}

    async def get_setting(self, ctx: commands.Context, setting: str) -> Any:
        async with self.bot.pool.acquire() as conn:
            setting = await conn.fetchone(
                "SELECT value FROM guildConfig WHERE id = ? AND key LIKE '%:?';",
                (ctx.guild.id, setting.upper()),
            )
            return setting[0] if setting else None

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return await super().cog_before_invoke(ctx)

        try:
            if await commands.run_converters(
                ctx, bool, await self.get_setting(ctx, "disabled"), commands.Parameter
            ):
                raise errors.ModuleDisabled(self)
        except:
            pass

        if await can_use(ctx) or ctx.author.guild_permissions.administrator:
            return await super().cog_before_invoke(ctx)
        else:
            raise commands.errors.CheckFailure


class View(discord.ui.View):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def add_quit(
        self,
        author: discord.User,
        guild: discord.Guild = None,
        delete_reference: bool = True,
        **kwargs,
    ):
        self.author = author
        self.delete_reference = delete_reference
        attributes = {
            "style": discord.ButtonStyle.red,
            "label": "Quit",
            "disabled": not guild,
        }
        attributes.update(**kwargs)
        button = discord.ui.Button(**attributes)
        button.callback = self.quit_callback
        return self.add_item(button)

    async def quit_callback(self, interaction: discord.Interaction):
        await self.quit(interaction, self.author, self.delete_reference)

    @classmethod
    async def quit(
        cls,
        interaction: discord.Interaction,
        author: discord.User = None,
        delete_reference: bool = True,
    ):
        if interaction.user != author:
            raise errors.NotYourButton

        reference = interaction.message.reference
        if reference and delete_reference:
            try:
                msg = await interaction.channel.fetch_message(reference.message_id)
                await msg.delete()
            except:
                pass

        await interaction.message.delete()

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ):
        if errors.iserror(error, errors.NotYourButton):
            return await interaction.response.send_message(
                error.reason or "This is not your button !", ephemeral=True
            )

        if errors.iserror(error, errors.NoVoiceFound):
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=":musical_note: No Voice Found",
                    description=f"> Please join a voice channel first before using this command.",
                ),
                delete_after=15,
            )

        # UNHANDLED ERRORS BELLOW
        # Process the traceback to clean path !
        trace = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        embed = discord.Embed(
            title=f":warning: Unhandled error in item : {item.type}",
            description=f"```py\n{misc.clean_traceback(trace)}```",
        )
        embed.set_footer(
            text=f"Caused by {interaction.user.display_name} in {interaction.guild.name if interaction.guild else 'DMs'} ({interaction.guild.id if interaction.guild else 0})",
            icon_url=interaction.user.avatar.url,
        )

        view = View()
        view.add_quit(interaction.user, interaction.guild)

        # Owner embed w full traceback
        await interaction.client.get_user(interaction.client.owner_id).send(embed=embed)

        # User error
        embed = discord.Embed(
            title=f":warning: {type(error).__qualname__}",
            description=(f"> {' '.join(error.args)}" if len(error.args) > 0 else None),
        )
        return await interaction.response.send_message(embed=embed, view=view)

    async def on_timeout(self):
        self.clear_items()
