from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from mailbox import Message
from typing import TYPE_CHECKING, Literal, Optional

import discord
from discord.ext import commands
from trueskill import Rating, rate

from discord_bots import config
from discord_bots.checks import is_admin_app_command
from discord_bots.cogs.confirmation import ConfirmationView
from discord_bots.cogs.economy import EconomyCommands
from discord_bots.models import (
    Category,
    FinishedGame,
    FinishedGamePlayer,
    InProgressGame,
    InProgressGameChannel,
    InProgressGamePlayer,
    Map,
    Player,
    PlayerCategoryTrueskill,
    Queue,
    QueueWaitlist,
    Rotation,
    RotationMap,
    Session,
)
from discord_bots.utils import (
    create_cancelled_game_embed,
    create_finished_game_embed,
    short_uuid,
    upload_stats_screenshot_imgkit_channel,
    upload_stats_screenshot_imgkit_interaction,
)

if TYPE_CHECKING:
    import sqlalchemy.orm
    from discord.ext.commands import Bot


_log = logging.getLogger(__name__)

class InProgressGameCog(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.views: list[InProgressGameView] = []

    async def cog_load(self) -> None:
        session: sqlalchemy.orm.Session
        with Session.begin() as session:  # type: ignore
            in_progress_games: list[InProgressGame] = session.query(
                InProgressGame
            ).all()
            for game in in_progress_games:
                if game.message_id:
                    self.views.append(InProgressGameView(game.id, self))
                    self.bot.add_view(
                        InProgressGameView(game.id, self),
                        message_id=game.message_id,
                    )

    async def cog_unload(self) -> None:
        for view in self.views:
            view.stop()

    def get_player_and_in_progress_game(
        self,
        session: sqlalchemy.orm.Session,
        player_id: int,
        game_id: Optional[str] = None,
    ) -> tuple[InProgressGamePlayer, InProgressGame] | None:
        game_player: InProgressGamePlayer | None = (
            session.query(InProgressGamePlayer)
            .filter(InProgressGamePlayer.player_id == player_id)
            .first()
        )
        if not game_player:
            return None
        in_progress_game: InProgressGame | None
        if game_id:
            in_progress_game = (
                session.query(InProgressGame)
                .filter(InProgressGame.id == game_player.in_progress_game_id)
                .filter(InProgressGame.id == game_id)
                .first()
            )
            if not in_progress_game:
                return None
        else:
            in_progress_game = (
                session.query(InProgressGame)
                .filter(InProgressGame.id == game_player.in_progress_game_id)
                .first()
            )
            if not in_progress_game:
                _log.warn(
                    f"No in_progress_game found with id {game_player.in_progress_game_id} for game_player with id ={game_player.id}"
                )
                return None
        return game_player, in_progress_game

    @discord.app_commands.command(
        name="finishgame", description="Ends the current game you are in"
    )
    @discord.app_commands.describe(outcome="win, loss, or tie")
    @discord.app_commands.guild_only()
    async def finishgame(
        self,
        interaction: discord.Interaction,
        outcome: Literal["win", "loss", "tie"],
    ):
        await interaction.response.defer(ephemeral=False)
        session = Session()
        result = self.get_player_and_in_progress_game(session, interaction.user.id)
        if result is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="You are not in this game!",
                    color=discord.Colour.red(),
                ),
                ephemeral=True,
            )
            return
        game_player, in_progress_game = result[0], result[1]
        await self.finish_in_progress_game(
            session, interaction, outcome, game_player, in_progress_game
        )
        session.commit()
        session.close()

    @discord.app_commands.command(
        name="cancelgame", description="Cancels the specified game"
    )
    @discord.app_commands.check(is_admin_app_command)
    @discord.app_commands.guild_only()
    async def cancelgame(self, interaction: discord.Interaction, game_id: str):
        await interaction.response.defer()
        await self.cancel_in_progress_game(interaction, game_id)

    async def finish_in_progress_game(
        self,
        session: sqlalchemy.orm.Session,
        interaction: discord.Interaction,
        outcome: Literal["win", "loss", "tie"],
        game_player: InProgressGamePlayer,
        in_progress_game: InProgressGame,
    ) -> bool:
        assert interaction is not None
        assert interaction.guild is not None
        queue: Queue | None = (
            session.query(Queue).filter(Queue.id == in_progress_game.queue_id).first()
        )
        if not queue:
            # should never happen
            _log.error(
                f"Could not find queue with id {in_progress_game.queue_id} for in_progress_game with id {in_progress_game.id}"
            )
            await interaction.followup.send(
                embed=discord.Embed(
                    description="Something went wrong, please contact the server owner",
                    color=discord.Colour.red(),
                ),
                ephemeral=True,
            )
            return False

        winning_team = -1
        if outcome == "win":
            winning_team = game_player.team
        elif outcome == "loss":
            winning_team = (game_player.team + 1) % 2
        else:
            # tie
            winning_team = -1

        players = (
            session.query(Player)
            .join(InProgressGamePlayer)
            .filter(
                InProgressGamePlayer.player_id == Player.id,
                InProgressGamePlayer.in_progress_game_id == in_progress_game.id,
            )
        ).all()
        player_ids: list[str] = [player.id for player in players]
        players_by_id: dict[int, Player] = {player.id: player for player in players}
        player_category_trueskills_by_id: dict[int, PlayerCategoryTrueskill] = {}
        if queue.category_id:
            player_category_trueskills: list[PlayerCategoryTrueskill] = (
                session.query(PlayerCategoryTrueskill)
                .filter(
                    PlayerCategoryTrueskill.player_id.in_(player_ids),
                    PlayerCategoryTrueskill.category_id == queue.category_id,
                )
                .all()
            )
            player_category_trueskills_by_id = {
                pct.player_id: pct for pct in player_category_trueskills
            }
        in_progress_game_players = (
            session.query(InProgressGamePlayer)
            .filter(InProgressGamePlayer.in_progress_game_id == in_progress_game.id)
            .all()
        )
        team0_rated_ratings_before = []
        team1_rated_ratings_before = []
        team0_players: list[InProgressGamePlayer] = []
        team1_players: list[InProgressGamePlayer] = []
        for in_progress_game_player in in_progress_game_players:
            player = players_by_id[in_progress_game_player.player_id]
            if in_progress_game_player.team == 0:
                team0_players.append(in_progress_game_player)
                if player.id in player_category_trueskills_by_id:
                    pct = player_category_trueskills_by_id[player.id]
                    team0_rated_ratings_before.append(Rating(pct.mu, pct.sigma))
                else:
                    team0_rated_ratings_before.append(
                        Rating(player.rated_trueskill_mu, player.rated_trueskill_sigma)
                    )
            else:
                team1_players.append(in_progress_game_player)
                if player.id in player_category_trueskills_by_id:
                    pct = player_category_trueskills_by_id[player.id]
                    team1_rated_ratings_before.append(Rating(pct.mu, pct.sigma))
                else:
                    team1_rated_ratings_before.append(
                        Rating(player.rated_trueskill_mu, player.rated_trueskill_sigma)
                    )

        if queue.category_id:
            category: Category | None = (
                session.query(Category).filter(Category.id == queue.category_id).first()
            )
            if category:
                category_name = category.name
            else:
                # should never happen
                _log.error(
                    f"Could not find category with id {queue.category_id} for queue with id {queue.id}"
                )
                await interaction.followup.send(
                    embed=discord.Embed(
                        description="Something went wrong, please contact the server owner",
                        color=discord.Colour.red(),
                    ),
                    ephemeral=True,
                )
                return False
        else:
            category_name = None

        finished_game = FinishedGame(
            average_trueskill=in_progress_game.average_trueskill,
            finished_at=datetime.now(timezone.utc),
            game_id=in_progress_game.id,
            is_rated=queue.is_rated,
            map_full_name=in_progress_game.map_full_name,
            map_short_name=in_progress_game.map_short_name,
            queue_name=queue.name,
            category_name=category_name,
            started_at=in_progress_game.created_at,
            team0_name=in_progress_game.team0_name,
            team1_name=in_progress_game.team1_name,
            win_probability=in_progress_game.win_probability,
            winning_team=winning_team,
        )
        session.add(finished_game)

        result = None
        if winning_team == -1:
            result = [0, 0]
        elif winning_team == 0:
            result = [0, 1]
        elif winning_team == 1:
            result = [1, 0]

        team0_rated_ratings_after: list[Rating]
        team1_rated_ratings_after: list[Rating]
        if len(players) > 1:
            team0_rated_ratings_after, team1_rated_ratings_after = rate(
                [team0_rated_ratings_before, team1_rated_ratings_before], result
            )
        else:
            # Mostly useful for creating solo queues for testing, no real world
            # application
            team0_rated_ratings_after, team1_rated_ratings_after = (
                team0_rated_ratings_before,
                team1_rated_ratings_before,
            )

        def update_ratings(
            team_players: list[InProgressGamePlayer],
            ratings_before: list[Rating],
            ratings_after: list[Rating],
        ):
            for i, team_gip in enumerate(team_players):
                player = players_by_id[team_gip.player_id]
                finished_game_player = FinishedGamePlayer(
                    finished_game_id=finished_game.id,
                    player_id=player.id,
                    player_name=player.name,
                    team=team_gip.team,
                    rated_trueskill_mu_before=ratings_before[i].mu,
                    rated_trueskill_sigma_before=ratings_before[i].sigma,
                    rated_trueskill_mu_after=ratings_after[i].mu,
                    rated_trueskill_sigma_after=ratings_after[i].sigma,
                )
                trueskill_rating = ratings_after[i]
                # Regardless of category, always update the master trueskill. That way
                # when we create new categories off of it the data isn't completely
                # stale
                player.rated_trueskill_mu = trueskill_rating.mu
                player.rated_trueskill_sigma = trueskill_rating.sigma
                if player.id in player_category_trueskills_by_id:
                    pct = player_category_trueskills_by_id[player.id]
                    pct.mu = trueskill_rating.mu
                    pct.sigma = trueskill_rating.sigma
                    pct.rank = trueskill_rating.mu - 3 * trueskill_rating.sigma
                else:
                    session.add(
                        PlayerCategoryTrueskill(
                            player_id=player.id,
                            category_id=queue.category_id,
                            mu=trueskill_rating.mu,
                            sigma=trueskill_rating.sigma,
                            rank=trueskill_rating.mu - 3 * trueskill_rating.sigma,
                        )
                    )
                session.add(finished_game_player)

        update_ratings(
            team0_players, team0_rated_ratings_before, team0_rated_ratings_after
        )
        update_ratings(
            team1_players, team1_rated_ratings_before, team1_rated_ratings_after
        )
        if config.ECONOMY_ENABLED:
            economy_cog = self.bot.get_cog("EconomyCommands")
            if economy_cog is not None and isinstance(economy_cog, EconomyCommands):
                await economy_cog.resolve_predictions(
                    interaction, outcome, in_progress_game.id
                )
            else:
                _log.warning("Could not get EconomyCommands cog")

        session.query(InProgressGamePlayer).filter(
            InProgressGamePlayer.in_progress_game_id == in_progress_game.id
        ).delete()
        # session.query(InProgressGame).filter(
        #     InProgressGame.id == in_progress_game.id
        # ).delete()
        in_progress_game.is_finished = True
        session.add(
            QueueWaitlist(
                channel_id=interaction.channel_id,  # not sure about this column and what it's used for
                finished_game_id=finished_game.id,
                guild_id=interaction.guild_id,
                queue_id=queue.id,
                end_waitlist_at=datetime.now(timezone.utc)
                + timedelta(seconds=config.RE_ADD_DELAY),
            )
        )

        # Reward raffle tickets
        reward = (
            session.query(RotationMap.raffle_ticket_reward)
            .join(Map, Map.id == RotationMap.map_id)
            .join(Rotation, Rotation.id == RotationMap.rotation_id)
            .join(Queue, Queue.rotation_id == Rotation.id)
            .filter(Map.short_name == in_progress_game.map_short_name)
            .filter(Queue.id == in_progress_game.queue_id)
            .scalar()
        )
        if reward == 0:
            reward = config.DEFAULT_RAFFLE_VALUE

        for player in players:
            player.raffle_tickets += reward
            session.add(player)
        queue_name = queue.name

        game_history_message: discord.Message
        if config.GAME_HISTORY_CHANNEL:
            channel: discord.channel.TextChannel | None = discord.utils.get(
                interaction.guild.text_channels, id=config.GAME_HISTORY_CHANNEL
            )
            if channel:
                embed = create_finished_game_embed(
                    session, finished_game, interaction.user.name
                )
                game_history_message = await channel.send(embed=embed)
                await upload_stats_screenshot_imgkit_channel(channel)
        elif config.STATS_DIR:
            await upload_stats_screenshot_imgkit_interaction(interaction)

        embed_description: str = ""
        if game_history_message is not None:
            embed_description = game_history_message.jump_url
        embed = discord.Embed(
            title=f"✅ Game '{queue_name}' ({short_uuid(finished_game.game_id)}) finished",
            description=embed_description,
            colour=discord.Colour.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Finished by {interaction.user.name}")
        if interaction.channel:
            await interaction.followup.send(embed=embed, ephemeral=False)
        if config.CHANNEL_ID and interaction.channel_id != config.CHANNEL_ID:
            # if this interaction was not used in the main channel, post the update message in the main channel
            main_channel = interaction.guild.get_channel(config.CHANNEL_ID)
            if isinstance(main_channel, discord.TextChannel):
                await main_channel.send(embed=embed)

        return True

    async def cancel_in_progress_game(
        self, interaction: discord.Interaction, game_id: str
    ):
        session: sqlalchemy.orm.Session
        with Session.begin() as session:  # type: ignore
            game = (
                session.query(InProgressGame)
                .filter(InProgressGame.id.startswith(game_id))
                .first()
            )
            if not game:
                await interaction.followup.send(
                    embed=discord.Embed(
                        description=f"Could not find game with id {game_id}",
                        colour=discord.Colour.red(),
                    ),
                    ephemeral=True,
                )
                return False

            queue: Queue | None = (
                session.query(Queue).filter(Queue.id == game.queue_id).first()
            )
            queue_name = f"'{queue.name}'" if queue is not None else ""
            game_history_message: discord.Message
            if config.GAME_HISTORY_CHANNEL:
                channel: discord.channel.TextChannel | None = discord.utils.get(
                    interaction.guild.text_channels, id=config.GAME_HISTORY_CHANNEL
                )
                if channel:
                    embed = create_cancelled_game_embed(
                        session, game, interaction.user.name
                    )
                    game_history_message = await channel.send(embed=embed)

            embed_description: str = ""
            if game_history_message is not None:
                embed_description = game_history_message.jump_url
            embed = discord.Embed(
                title=f":x: Game {queue_name}g({short_uuid(game.id)}) cancelled",
                description=embed_description,
                colour=discord.Colour.red(),
                timestamp=discord.utils.utcnow(),
            )
            embed.set_footer(text=f"Cancelled by {interaction.user.name}")

            # temporary solution for when the command is used in the game channel
            # since we need to reply to the interaction before the channel is deleted
            # ideally all messages should be sent at the end of the function
            await interaction.followup.send(embed=embed, ephemeral=False)
            if (
                config.CHANNEL_ID
                and interaction.channel_id != config.CHANNEL_ID
                and interaction.guild
            ):
                # if this interaction was not used in the main channel, post the update message in the main channel
                main_channel = interaction.guild.get_channel(config.CHANNEL_ID)
                if isinstance(main_channel, discord.TextChannel):
                    await main_channel.send(embed=embed)
                    if config.ECONOMY_ENABLED:
                        try:
                            economy_cog = self.bot.get_cog("EconomyCommands")
                            if economy_cog is not None and isinstance(
                                economy_cog, EconomyCommands
                            ):
                                await economy_cog.cancel_predictions(game_id)
                            else:
                                _log.warning("Could not get EconomyCommands cog")
                        except ValueError as ve:
                            # Raised if there are no predictions on this game
                            await main_channel.send(
                                embed=discord.Embed(
                                    description="No predictions to be refunded",
                                    colour=discord.Colour.blue(),
                                )
                            )
                        except Exception as e:
                            await main_channel.send(
                                embed=discord.Embed(
                                    description=f"Predictions failed to refund: {e}",
                                    colour=discord.Colour.red(),
                                )
                            )
                        else:
                            await main_channel.send(
                                embed=discord.Embed(
                                    description="Predictions refunded",
                                    colour=discord.Colour.blue(),
                                )
                            )

            session.query(InProgressGamePlayer).filter(
                InProgressGamePlayer.in_progress_game_id == game.id
            ).delete()

            for ipg_channel in session.query(InProgressGameChannel).filter(
                InProgressGameChannel.in_progress_game_id == game.id
            ):
                if interaction.guild:
                    guild_channel = interaction.guild.get_channel(
                        ipg_channel.channel_id
                    )
                    if guild_channel:
                        await guild_channel.delete()
                session.delete(ipg_channel)
            session.query(InProgressGame).filter(InProgressGame.id == game.id).delete()
            return True


class InProgressGameView(discord.ui.View):
    def __init__(self, game_id: str, cog: InProgressGameCog):
        super().__init__(timeout=None)
        self.game_id: str = game_id
        self.is_game_finished: bool = False
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction[discord.Client]):
        if self.is_game_finished:
            await interaction.response.send_message(
                "This game has already finished", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Win",
        style=discord.ButtonStyle.primary,
        custom_id="in_progress_game_view:win",
        emoji="🥇",
    )
    async def win_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        session: sqlalchemy.orm.Session
        with Session.begin() as session:  # type: ignore
            result = self.cog.get_player_and_in_progress_game(
                session, interaction.user.id, self.game_id
            )
            if result is None:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description="You are not in this game!",
                        color=discord.Colour.red(),
                    ),
                    ephemeral=True,
                )
                return

            game_player: InProgressGamePlayer = result[0]
            in_progress_game: InProgressGame = result[1]
            confirmation_buttons = ConfirmationView()
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="Are you sure you want to finish this game as a **Win**?",
                    color=discord.Colour.orange(),
                ),
                view=confirmation_buttons,
                ephemeral=True,
            )
            await confirmation_buttons.wait()
            if not confirmation_buttons.value:
                return
            self.is_game_finished = await self.cog.finish_in_progress_game(
                session, interaction, "win", game_player, in_progress_game
            )
        if self.is_game_finished:
            await self.disable_buttons(interaction)
            self.stop()

    @discord.ui.button(
        label="Loss",
        style=discord.ButtonStyle.primary,
        custom_id="in_progress_game_view:loss",
        emoji="🥈",
    )
    async def loss_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        session: sqlalchemy.orm.Session
        with Session.begin() as session:  # type: ignore
            result = self.cog.get_player_and_in_progress_game(
                session, interaction.user.id, self.game_id
            )
            if result is None:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description="You are not in this game!",
                        color=discord.Colour.red(),
                    ),
                    ephemeral=True,
                )
                return

            game_player: InProgressGamePlayer = result[0]
            in_progress_game: InProgressGame = result[1]
            confirmation_buttons = ConfirmationView()
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="Are you sure you want to finish this game as a **Loss**?",
                    color=discord.Colour.orange(),
                ),
                view=confirmation_buttons,
                ephemeral=True,
            )
            await confirmation_buttons.wait()
            if not confirmation_buttons.value:
                return
            self.is_game_finished = await self.cog.finish_in_progress_game(
                session, interaction, "loss", game_player, in_progress_game
            )
        if self.is_game_finished:
            await self.disable_buttons(interaction)
            self.stop()

    @discord.ui.button(
        label="Tie",
        style=discord.ButtonStyle.primary,
        custom_id="in_progress_game_view:tie",
        emoji="🤞",
    )
    async def tie_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        session: sqlalchemy.orm.Session
        with Session.begin() as session:  # type: ignore
            result = self.cog.get_player_and_in_progress_game(
                session, interaction.user.id, self.game_id
            )
            if result is None:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description="You are not in this game!",
                        color=discord.Colour.red(),
                    ),
                    ephemeral=True,
                )
                return

            game_player: InProgressGamePlayer = result[0]
            in_progress_game: InProgressGame = result[1]
            confirmation_buttons = ConfirmationView()
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="Are you sure you want to finish this game as a **Tie**?",
                    color=discord.Colour.orange(),
                ),
                view=confirmation_buttons,
                ephemeral=True,
            )
            await confirmation_buttons.wait()
            if not confirmation_buttons.value:
                return
            self.is_game_finished = await self.cog.finish_in_progress_game(
                session, interaction, "tie", game_player, in_progress_game
            )
        if self.is_game_finished:
            await self.disable_buttons(interaction)
            self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.red,
        custom_id="in_progress_game_view:cancel",
    )
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await is_admin_app_command(interaction):
            return

        confirmation_buttons = ConfirmationView()
        await interaction.response.send_message(
            embed=discord.Embed(
                description="Are you sure you want **Cancel** this game?",
                color=discord.Colour.orange(),
            ),
            view=confirmation_buttons,
            ephemeral=True,
        )
        await confirmation_buttons.wait()
        if not confirmation_buttons.value:
            return

        self.is_game_finished = await self.cog.cancel_in_progress_game(
            interaction, self.game_id
        )
        if self.is_game_finished:
            # no need to disable the buttons, since the channel will be deleted immediately
            self.stop()

    async def disable_buttons(self, interaction: discord.Interaction):
        for child in self.children:
            if type(child) == discord.ui.Button and not child.disabled:
                child.disabled = True
        if interaction.message is not None:
            await interaction.message.edit(view=self)
