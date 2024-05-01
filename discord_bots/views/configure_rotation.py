import logging
from sqlalchemy.orm.session import Session as SQLAlchemySession
from typing import List

from discord import (
    ButtonStyle,
    Client,
    Colour,
    Embed,
    Interaction,
    Message,
    SelectOption,
    TextStyle,
)
from discord.ui import button, Button, Modal, Select, TextInput

from discord_bots.models import Map, Rotation, RotationMap, Session
from discord_bots.views.base import BaseView
from discord_bots.views.confirmation import ConfirmationView

_log = logging.getLogger(__name__)


class RotationConfigureView(BaseView):
    def __init__(self, interaction: Interaction, rotation: Rotation):
        super().__init__(timeout=300)
        self.value: bool = False
        self.rotation: Rotation = rotation
        self.maps_view: RotationMapsView
        self.interaction: Interaction = interaction
        self.embed: Embed
        self.add_item(RotationRandomSelect(self))
    
    @button(label="Set Name", style=ButtonStyle.primary, row=0)
    async def setname(self, interaction: Interaction, button: Button):
        modal = RotationNameModal(self)
        await interaction.response.send_modal(modal)
        return True
    
    @button(label="Add Maps", style=ButtonStyle.primary, row=0)
    async def addmaps(self, interaction: Interaction, button: Button):
        await interaction.response.defer()
        await self.disable_children(interaction)
        self.maps_view = RotationMapsView(interaction, self)
        self.maps_view.embed = Embed(
            description=f"**{self.rotation.name}** Rotation Map Configure\n-----",
            colour=Colour.blue()
        )

        # Get RotationMaps
        session: SQLAlchemySession
        with Session() as session:
            rotation_maps = (
                session.query(Map.short_name, Map.full_name, RotationMap.ordinal)
                .join(RotationMap, Map.id == RotationMap.map_id)
                .filter(RotationMap.rotation_id == self.rotation.id)
                .order_by(RotationMap.ordinal.asc())
                .all()
            )
            if rotation_maps and self.maps_view.embed.description:
                for map in rotation_maps:
                    self.maps_view.embed.description = (
                        self.maps_view.embed.description
                        + f"\n#{map.ordinal} - **{map.full_name} ({map.short_name})**"
                    )
        
        maps_message: Message = await interaction.followup.send(
            embed=self.maps_view.embed,
            view=self.maps_view,
            ephemeral=True,
        )
        
        self.timeout = self.timeout + self.maps_view.timeout # type: ignore
        await self.maps_view.wait()
        self._refresh_timeout()

        await maps_message.delete()
        await self.enable_children(interaction)
        return True        

    @button(label="Save", style=ButtonStyle.success, row=4)
    async def save(self, interaction: Interaction, button: Button):
        await interaction.response.defer()
        await self.disable_children(interaction)

        confirmation_buttons = ConfirmationView(interaction.user.id)
        confirmation_buttons.message = await interaction.followup.send(
            embed=Embed(
                description=f"⚠️ Are you sure you want to save configurations for category **{self.rotation.name}**?⚠️",
                colour=Colour.yellow(),
            ),
            view=confirmation_buttons,
            ephemeral=True,
        )
        await confirmation_buttons.wait()
        if not confirmation_buttons.value:
            await self.enable_children(interaction)
            return False
        else:
            self.value = True
            self.stop()
            return True

    @button(label="Cancel", style=ButtonStyle.danger, row=4)
    async def cancel(self, interaction: Interaction, button: Button):
        self.stop()
        return False


class RotationMapsView(BaseView):
    def __init__(self, interaction: Interaction, view: RotationConfigureView):
        super().__init__(timeout=300)
        self.value: bool = False
        self.rotation: Rotation = view.rotation
        self.options: List[SelectOption] = self.populate_options()
        self.interaction: Interaction = interaction
        self.embed: Embed
        
        
    # TODO: Add a Select for adding maps, and another for removing.
    # Removing might need to be it's own view, but if can condense into one is better

    def populate_options(self) -> List[SelectOption]:
        options: List[SelectOption] = []
        
        session: SQLAlchemySession
        with Session() as session:
            maps: List[Map] = (
                session.query(Map)
                .join(RotationMap, RotationMap.map_id == Map.id)
                .filter(RotationMap.rotation_id != self.rotation.id)
                .order_by(Map.full_name.asc())
                .all()
            )
            for map in maps:
                options.append(
                    SelectOption(
                        label=map.full_name,
                        value=map.full_name
                    )
                )
            
        self.add_item(
            Select(
                row=1,
                options=options,
            )
        )
        return options

    @button(label="Save", style=ButtonStyle.success, row=4)
    async def save(self, interaction: Interaction, button: Button):
        await interaction.response.defer()
        await self.disable_children(interaction)

        confirmation_buttons = ConfirmationView(interaction.user.id)
        confirmation_buttons.message = await interaction.followup.send(
            embed=Embed(
                description=f"⚠️ Are you sure you want to save configurations for category **{self.rotation.name}**?⚠️",
                colour=Colour.yellow(),
            ),
            view=confirmation_buttons,
            ephemeral=True,
        )
        await confirmation_buttons.wait()
        if not confirmation_buttons.value:
            await self.enable_children(interaction)
            return False
        else:
            # TODO: Update original embed
            self.value = True
            self.stop()
            return True
    
    @button(label="Cancel", style=ButtonStyle.danger, row=4)
    async def cancel(self, interaction: Interaction, button: Button):
        self.stop()
        return False
    

class RotationNameModal(Modal):
    def __init__(
        self,
        view: RotationConfigureView,
    ):
        super().__init__(title="Set Name", timeout=30)
        self.view: RotationConfigureView = view
        self.input: TextInput = TextInput(
            label="Rotation Name",
            style=TextStyle.short,
            required=True,
            placeholder=self.view.rotation.name,
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: Interaction[Client]) -> None:
        self.view.rotation.name = self.input.value
        if self.view.embed.description:
            self.view.embed.description = (
                self.view.embed.description
                + f"\nRotation name: **{self.view.rotation.name}**"
            )
        await self.view.interaction.edit_original_response(embed=self.view.embed)

        # Interaction must be responded to, but is then deleted
        await interaction.response.send_message(
            embed=Embed(
                description=f"Set name **{self.view.rotation.name}** successful",
                colour=Colour.blue(),
            ),
            ephemeral=True,
        )
        await interaction.delete_original_response()
        return

class RotationRandomSelect(Select):
    def __init__(self, view: RotationConfigureView):
        super().__init__(
            placeholder=f"Is_Random: {str(view.rotation.is_random)}",
            row=1,
            options=[
                SelectOption(label="True", value="True"),
                SelectOption(label="False", value="False"),
            ],
        )
        self.view: RotationConfigureView

    async def callback(self, interaction: Interaction[Client]):
        self.view.rotation.is_random = self.values[0] == "True"
        if self.view.embed.description:
            self.view.embed.description = (
                self.view.embed.description
                + f"\nIs_Random: **{self.view.rotation.is_random}**"
            )
        await self.view.interaction.edit_original_response(embed=self.view.embed)

        await interaction.response.send_message(
            embed=Embed(
                description=f"Set is_random **{self.view.rotation.is_random}** successful",
                colour=Colour.blue(),
            ),
            ephemeral=True,
        )
        await interaction.delete_original_response()
        return