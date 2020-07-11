import copy
import inspect
import json
import random
import typing

import discord
from discord.ext import commands

from godfather.cogs.mafia.checks import *  # pylint: disable=wildcard-import, unused-wildcard-import
from godfather.errors import PhaseChangeError
from godfather.factions import factions
from godfather.game import Game, Phase, Player
from godfather.game.player_manager import PlayerManager
from godfather.game.vote_manager import VoteError
from godfather.roles import all_roles
from godfather.utils import (CustomContext, confirm, from_now,
                             get_random_sequence)


class Mafia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['create', 'create-game'])
    async def creategame(self, ctx: CustomContext):
        if ctx.guild.id in self.bot.games:
            return await ctx.send('A game of mafia is already running '
                                  'in this server.')
        new_game = Game.create(ctx, self.bot)
        self.bot.games[ctx.guild.id] = new_game
        return await ctx.send('Started a game of mafia in '
                              f'{ctx.message.channel.mention}, '
                              f'hosted by **{ctx.message.author}**')

    @commands.command()
    @game_only()
    async def join(self, ctx: CustomContext):
        game = self.bot.games[ctx.guild.id]

        if ctx.author in game.players:
            return await ctx.send('You have already joined this game.')

        if game.has_started:
            if ctx.author in game.players.replacements:
                return await ctx.send('You are already a replacement.')
            confirm_replacement = await confirm(
                ctx.bot, ctx.author, ctx.channel,
                'Sign-ups for this game have ended.'
                'Would you like to be a replacement?'
            )
            if confirm_replacement is None:
                return
            if not confirm_replacement:
                return await ctx.message.add_reaction('❌')
            game.players.add(ctx.author, replacement=True)
            await ctx.send('You have decided to become a replacement.')
            return

        if game.players.is_full:
            return await ctx.send('Maximum number of players reached.')
        else:
            game.players.add(ctx.author)
            return await ctx.send('✅ Game joined successfully.')

    @commands.command()
    @game_only()
    async def leave(self, ctx: CustomContext):
        game = self.bot.games[ctx.guild.id]

        if ctx.author in game.players.replacements:
            game.players.replacements.remove(ctx.author)
            return await ctx.send("You're not a replacement anymore.")
        elif ctx.author not in game.players:
            return await ctx.send('You have not joined this game')
        elif ctx.author.id == game.host.id:
            return await ctx.send('The host cannot leave the game.')

        if game.has_started:
            replace_text = 'Are you sure you want to leave the game?' \ 
                           'You will be mod-killed.' \
            if len(game.players.replacements) == 0 \
                else 'Are you sure you want to leave the game? You will be replaced out.'
            confirm_replacement = await confirm(ctx.bot, ctx.author, ctx.channel, replace_text)
            if confirm_replacement is None:
                return
            if not confirm_replacement:
                return await ctx.message.add_reaction('❌')

            player = game.players.get(ctx.author)

            if len(game.players.replacements) == 0:
                phase_str = 'd' if game.phase == Phase.DAY else 'n'
                async with game.channel.typing():
                    await game.channel.send(f'{player.user.name} was modkilled. They were a *{player.display_role}*.')
                    await player.remove(game, f'modkilled {phase_str}{game.cycle}')
                    game_ended, winning_faction, independent_wins = game.check_endgame()
                    if game_ended:
                        await game.end(self.bot, winning_faction, independent_wins)
                    return

            else:
                replacement = game.players.replacements.pop(0)
                player.user = replacement
                await ctx.send(f'{replacement} has replaced {ctx.author}.')
                await replacement.send(player.role_pm)
                return

        else:
            game.players.remove(ctx.author)
            if ctx.author.id in game.votes:
                del game.votes[ctx.author.id]
            return await ctx.send('✅ Game left successfully')

    @commands.command()
    @game_only()
    async def playerlist(self, ctx: CustomContext):
        game = self.bot.games[ctx.guild.id]
        msg = f'**Players: {len(game.players)}**\n'
        msg += game.players.show(show_replacements=True)

        return await ctx.send(msg)

    @commands.command()
    @game_started_only()
    @game_only()
    async def remaining(self, ctx):
        game = self.bot.games[ctx.guild.id]
        await ctx.send(f'🕰️ The current phase ends {from_now(game.phase_end_at)}')

    @commands.command()
    async def setupinfo(self, ctx: CustomContext, roleset: typing.Optional[str] = None):
        # show the current setup if a game is ongoing
        if ctx.guild.id in ctx.bot.games \
                and ctx.game.phase != Phase.PREGAME \
                and roleset is None:
            roleset = ctx.game.setup['name']

        rolesets = json.load(open('rolesets/rolesets.json'))
        if roleset is None or roleset == 'all':
            txt = ('**All available setups:** (to view a specific setup, use '
                   f'{ctx.prefix}setupinfo <name>)')
            txt += '```\n'
            for _roleset in rolesets:
                txt += f'{_roleset["name"]} ({len(_roleset["roles"])} players)\n'
            txt += '```'
            return await ctx.send(txt)

        found_setup = next(
            (rs for rs in rolesets if rs['name'] == roleset.lower()), None)
        if found_setup is None:
            return await ctx.send(
                f"Couldn't find {roleset}, use {ctx.prefix}setupinfo to view all setups."
            )

        txt = [f'**{roleset}** ({len(found_setup["roles"])} players)', '```\n']
        for i, role in enumerate(found_setup['roles']):
            txt.append(
                f'{i+1}. {role["faction"].title()} {role["id"].title()}')
        txt.append('```')
        await ctx.send('\n'.join(txt))

    @commands.command()
    async def roleinfo(self, ctx: CustomContext, *, rolename: typing.Optional[str] = None):
        if rolename is None:
            # show all available roles here sometime
            return
        for role in all_roles.values():
            role = role()  # initialize the class
            if role.name.lower() == rolename.lower():
                if role.__doc__ is None:
                    return await ctx.send('No documentation on {} available.'.format(rolename))
                text = [f'**{role.name}**', '```diff']
                text.append(inspect.getdoc(role))
                text.append('```')
                return await ctx.send('\n'.join(text))
        await ctx.send("Couldn't find that role!")

    @ commands.command()
    @ game_only()
    @ game_started_only()
    async def rolepm(self, ctx: CustomContext):
        player = ctx.game.players.get(ctx.author)
        try:
            await player.user.send(player.role_pm)
            await ctx.message.add_reaction('✅')
        except discord.Forbidden:
            await ctx.send('Cannot send you your role PM. Make sure your DMs are enabled!')

    @ commands.command(aliases=['start'])
    @ host_only()
    @ game_only()
    async def startgame(self, ctx: CustomContext,
                        r_setup: typing.Optional[str] = None):
        game = self.bot.games[ctx.guild.id]

        if game.has_started:
            await ctx.send("Game has already started!")
            return

        try:
            found_setup = game.find_setup(r_setup)
        except Exception as err:  # pylint: disable=broad-except
            return await ctx.send(err)
        game.setup = found_setup

        # set to standby so people can't join while the bot is sending rolepms
        game.phase = Phase.STANDBY
        await ctx.send(f'Chose the setup **{found_setup["name"]}**. '
                       'Randing roles...')
        roles = copy.deepcopy(found_setup['roles'])

        # Create a random sequence of role indexes, enumerate the player list.
        # And assign the nth number in the random sequence to the nth player.
        # Then use the resulting number as index for the role.
        role_sequence = get_random_sequence(0, len(roles)-1)

        # people the bot couldn't dm
        no_dms = []
        async with ctx.channel.typing():
            for num, player in enumerate(game.players):
                player_role = roles[role_sequence[num]]

                # assign role and faction to the player
                player.role = all_roles.get(player_role['id'])()
                player.faction = factions.get(player_role['faction'])()

                # send role PMs
                try:
                    await player.user.send(player.role_pm)
                except discord.Forbidden:
                    no_dms.append(player.user)

            for player in filter(lambda pl: pl.faction.informed, game.players):
                teammates = game.players.filter(faction=player.faction.id)
                if len(teammates) > 1:
                    await player.user.send(
                        f'Your team consists of: {", ".join(map(lambda pl: pl.user.name, teammates))}'
                    )

            for player in game.players.filter(role='Executioner'):
                targets = list(filter(lambda pl: pl.faction.name == 'Town' and pl.role.name not in [
                    'Jailor', 'Mayor'], game.players))
                target = random.choice(targets)
                player.target = target
                await player.user.send('Your target is {}'.format(target.user))

        await ctx.send('Sent all role PMs!')

        if len(no_dms) > 0:
            no_dms = [*map(lambda usr: usr.name, no_dms)]
            await ctx.send(f"I couldn't DM {', '.join(no_dms)}."
                           f" Use the {ctx.prefix}rolepm command to receive your PM.")

        # night starts
        night_start = 'night_start' in game.setup
        if night_start:
            game.cycle = 1
            game.phase = Phase.DAY
        try:
            await game.increment_phase(self.bot)
        except Exception as exc:
            raise PhaseChangeError(None, *exc.args)

    @commands.command()
    @day_only()
    @game_started_only()
    @player_only()
    @game_only()
    async def vote(self, ctx: CustomContext, *, target: Player):
        game: Game = ctx.game
        try:
            hammered = game.votes.vote(game.players.get(ctx.author), target)
        except VoteError as err:
            return await ctx.send(*err.args)

        await ctx.send(f'Voted {target.user.name}')

        if hammered and not game.phase == Phase.STANDBY:
            game.phase = Phase.STANDBY

            await game.lynch(target)
            game_ended, winning_faction, independent_wins = game.check_endgame()
            if game_ended:
                await game.end(self.bot, winning_faction, independent_wins)
            else:
                game.phase = Phase.DAY
                await game.increment_phase()

    @commands.command(aliases=['vtnl'])
    @day_only()
    @game_started_only()
    @player_only()
    @game_only()
    async def nolynch(self, ctx: CustomContext):
        game = self.bot.games[ctx.guild.id]
        try:
            nolynch = game.votes.nolynch(game.players.get(ctx.author))
        except VoteError as err:
            return await ctx.send(*err.args)
        await ctx.send('You have voted to no-lynch.')

        if nolynch and not game.phase == Phase.STANDBY:
            game.phase = Phase.STANDBY
            await ctx.send('Nobody was lynched!')
            game.phase = Phase.DAY
            await game.increment_phase(self.bot)

    @ commands.command()
    @day_only()
    @ game_started_only()
    @ player_only()
    @ game_only()
    async def unvote(self, ctx: CustomContext):
        unvoted = ctx.game.votes.unvote(ctx.game.players.get(ctx.author))
        if unvoted:
            return await ctx.message.add_reaction('✅')

        await ctx.send('No votes to remove.')

    @ commands.command()
    @day_only()
    @ game_started_only()
    @ player_only()
    @ game_only()
    async def votecount(self, ctx: CustomContext):
        msg = ctx.game.votes.show()
        return await ctx.send(msg)
