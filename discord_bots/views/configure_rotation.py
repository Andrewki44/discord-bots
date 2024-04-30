import logging

from discord import (
    ButtonStyle,
    Client,
    Colour,
    Embed,
    Interaction,
    SelectOption,
    TextStyle,
)
from discord.ui import button, Button, Modal, Select, TextInput

from discord_bots.models import Rotation
from discord_bots.views.base import BaseView
from discord_bots.views.confirmation import ConfirmationView

_log = logging.getLogger(__name__)


class RotationConfigureView(BaseView):
    def __init__(self, interaction: Interaction, rotation: Rotation):
        super().__init__(timeout=300)
        self.value: bool = False
        self.rotation: Rotation = rotation
        self.interaction: Interaction = interaction
        self.embed: Embed
        # self.add_item(CategoryRatedSelect(self))

    @button(label="Set Name", style=ButtonStyle.primary, row=0)
    async def setname(self, interaction: Interaction, button: Button):
        modal = RotationNameModal(self)
        await interaction.response.send_modal(modal)
        return True

    @button(label="Save", style=ButtonStyle.success, row=4)
    async def save(self, interaction: Interaction, button: Button):
        await interaction.response.defer()
        confirmation_buttons = ConfirmationView(interaction.user.id)
        confirmation_buttons.message = await interaction.followup.send(
            embed=Embed(
                description=f"⚠️ Are you sure you want to save configurations for category **{self.category.name}**?⚠️",
                colour=Colour.yellow(),
            ),
            view=confirmation_buttons,
            ephemeral=True,
        )
        await confirmation_buttons.wait()
        if not confirmation_buttons.value:
            return False
        else:
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
            label="Category Name",
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
                + f"\nCategory name: **{self.view.rotation.name}**"
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
