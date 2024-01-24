from discord.ext.commands import Bot, Context, check, command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from discord_bots.checks import is_admin
from discord_bots.cogs.base import BaseCog
from discord_bots.models import (
    FinishedGame,
    InProgressGame,
    Map,
    MapVote,
    Queue,
    Rotation,
    RotationMap,
)
from discord_bots.utils import send_message


class MapCog(BaseCog):
    def __init__(self, bot: Bot):
        super().__init__(bot)

    @command()
    @check(is_admin)
    async def addmap(self, ctx: Context, map_full_name: str, map_short_name: str):
        session = ctx.session
        map_short_name = map_short_name.upper()

        try:
            session.add(Map(map_full_name, map_short_name))
            session.commit()
        except IntegrityError:
            session.rollback()
            await self.send_error_message(
                f"Error adding map {map_full_name} ({map_short_name}). Does it already exist?"
            )
        else:
            await self.send_success_message(
                f"**{map_full_name} ({map_short_name})** added to maps"
            )

    @command()
    async def changegamemap(self, ctx: Context, game_id: str, map_short_name: str):
        """
        TODO: tests
        """
        session = ctx.session

        ipg = (
            session.query(InProgressGame)
            .filter(InProgressGame.id.startswith(game_id))
            .first()
        )
        finished_game = (
            session.query(FinishedGame)
            .filter(FinishedGame.game_id.startswith(game_id))
            .first()
        )
        if ipg:
            game = ipg
        elif finished_game:
            game = finished_game
        else:
            await self.send_error_message(f"Could not find game: **{game_id}**")
            return

        map: Map | None = (
            session.query(Map).filter(Map.short_name.ilike(map_short_name)).first()
        )
        if not map:
            await self.send_error_message(
                f"Could not find map: **{map_short_name}**. Add to map pool first."
            )
            return

        game.map_full_name = map.full_name
        game.map_short_name = map.short_name
        session.commit()
        await self.send_success_message(
            f"Map for game **{game_id}** changed to **{map.short_name}**"
        )

    @command()
    @check(is_admin)
    async def changequeuemap(self, ctx: Context, queue_name: str, map_short_name: str):
        """
        User specifies queue for ease of use, but under the hood this affects the rotation.
        Every queue with that rotation is also affected.
        TODO: tests
        """

        session = ctx.session

        queue: Queue | None = (
            session.query(Queue).filter(Queue.name.ilike(queue_name)).first()
        )
        if not queue:
            await self.send_error_message(f"Could not find queue: **{queue_name}**")
            return

        map: Map | None = (
            session.query(Map).filter(Map.short_name.ilike(map_short_name)).first()
        )
        if not map:
            await self.send_error_message(f"Could not find map: **{map_short_name}**")
            return

        rotation: Rotation | None = (
            session.query(Rotation).filter(queue.rotation_id == Rotation.id).first()
        )
        if not rotation:
            await self.send_error_message(
                f"**{queue.name}** has not been assigned a rotation.\nPlease assign one with `!setqueuerotation`."
            )
            return

        next_rotation_map: RotationMap | None = (
            session.query(RotationMap)
            .filter(RotationMap.rotation_id == rotation.id, RotationMap.map_id = map.id)
            .first()
        )
        if not next_rotation_map:
            await self.send_error_message(
                f"The rotation for **{queue.name}** doesn't have that map.\nPlease add it to the **{rotation.name}** rotation with `!addrotationmap`."
            )
            return

        session.query(RotationMap).filter(
            RotationMap.rotation_id == rotation.id
        ).filter(RotationMap.is_next == True).update({"is_next": False})
        next_rotation_map.is_next = True
        session.commit()

        output = f"**{queue.name}** next map changed to **{map.short_name}**"
        affected_queues = (
            session.query(Queue.name)
            .filter(Queue.rotation_id == rotation.id)
            .filter(Queue.name != queue.name)
            .all()
        )
        if affected_queues:
            output += "\n\nQueues also affected:"
            for name in affected_queues:
                output += f"\n- {name[0]}"

        await self.send_success_message(output)

    @command()
    async def listmaps(self, ctx: Context):
        session = ctx.session
        maps = session.query(Map).order_by(Map.created_at.asc()).all()

        if not maps:
            output = "_-- No Maps --_"
        else:
            output = ""
            for map in maps:
                output += f"- {map.full_name} ({map.short_name})\n"

        await self.send_info_message(output)

    # TODO: update to !map <queue_name>
    # @command(name="map")
    # async def map_(ctx: Context):
    #     # TODO: This is duplicated
    #     session = ctx.session
    #     output = ""
    #     current_map: CurrentMap | None = session.query(CurrentMap).first()
    #     if current_map:
    #         rotation_maps: list[RotationMap] = session.query(RotationMap).order_by(RotationMap.created_at.asc()).all()  # type: ignore
    #         next_rotation_map_index = (current_map.map_rotation_index + 1) % len(
    #             rotation_maps
    #         )
    #         next_map = rotation_maps[next_rotation_map_index]

    #         time_since_update: timedelta = datetime.now(
    #             timezone.utc
    #         ) - current_map.updated_at.replace(tzinfo=timezone.utc)
    #         time_until_rotation = MAP_ROTATION_MINUTES - (time_since_update.seconds // 60)
    #         if current_map.map_rotation_index == 0:
    #             output += f"**Next map: {current_map.full_name} ({current_map.short_name})**\n_Map after next: {next_map.full_name} ({next_map.short_name})_\n"
    #         else:
    #             output += f"**Next map: {current_map.full_name} ({current_map.short_name})**\n_Map after next (auto-rotates in {time_until_rotation} minutes): {next_map.full_name} ({next_map.short_name})_\n"
    #     skip_map_votes: list[SkipMapVote] = session.query(SkipMapVote).all()
    #     output += (
    #         f"_Votes to skip (voteskip): [{len(skip_map_votes)}/{MAP_VOTE_THRESHOLD}]_\n"
    #     )

    #     # TODO: This is duplicated
    #     map_votes: list[MapVote] = session.query(MapVote).all()
    #     voted_map_ids: list[str] = [map_vote.map_id for map_vote in map_votes]
    #     voted_maps: list[Map] = (
    #         session.query(Map).filter(Map.id.in_(voted_map_ids)).all()  # type: ignore
    #     )
    #     voted_maps_str = ", ".join(
    #         [
    #             f"{voted_map.short_name} [{voted_map_ids.count(voted_map.id)}/{MAP_VOTE_THRESHOLD}]"
    #             for voted_map in voted_maps
    #         ]
    #     )
    #     output += f"_Votes to change map (votemap): {voted_maps_str}_\n\n"
    #     session.close()
    #     await ctx.send(embed=Embed(description=output, colour=Colour.blue()))

    @command()
    @check(is_admin)
    async def removemap(self, ctx: Context, map_short_name: str):
        session = ctx.session

        try:
            map = session.query(Map).filter(Map.short_name.ilike(map_short_name)).one()
        except NoResultFound:
            await self.send_error_message(f"Could not find map **{map_short_name}**")
            return

        session.delete(map)
        session.commit()
        await self.send_success_message(
            f"**{map.full_name} ({map.short_name})** removed from maps"
        )
