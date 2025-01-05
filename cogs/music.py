import aiohttp
import io
from enum import Enum
from PIL import Image

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View

from . import vocaloid_scraper as vs
    


class LyricsCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.user_install
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.command(name="lyrics", description="Enter a name of a vocaloid song to search Fandom for its lyrics!")
    async def lyrics(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        embed = discord.Embed(
            title=f"Fetching results for \"{query}\"...",
            color=discord.Color.orange())
        
        msg = await interaction.followup.send(embed=embed)
        user = interaction.user
        embed_footer = f"Requested by {user.display_name} • Powered by vocaloidlyrics.fandom.com"

        class LyricsSession:
            def __init__(self, interaction, query):
                self.interaction = interaction

                self.query = query
                self.selector_data = None
                self.selector_page_index = 0
                self.selector_max_links = 6
                self.selector_total_pages = 0

                self.lyrics_data = None
                self.lyrics_color = None
                self.lyrics_extras = None
                self.lyrics_video = None
                self.lyrics_video_msg = None
                self.lyrics_page = None

            def set_selector_data(self):
                self.selector_data = vs.Song(self.query)
                self.selector_total_pages = (len(self.selector_data.links) + self.selector_max_links - 1) // self.selector_max_links

            async def set_lyrics_data(self, index):
                self.lyrics_data = vs.Song(self.selector_data.links[index]['href'])
                self.lyrics_color = await self.get_average_color(self.lyrics_data.image)
                self.lyrics_extras = "\n".join([f"• [{link['title']}]({link['href']})" for link in self.lyrics_data.links])
                self.lyrics_video = next((link['href'] for link in self.lyrics_data.links if link['title'] == "YouTube Broadcast"), None)
                self.lyrics_page = ["Original", 0]

            async def get_average_color(self, image_url: str) -> int:
                # Get image data
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url) as response:
                        image_data = await response.read()
            
                # Prepare for averaging
                image = Image.open(io.BytesIO(image_data))
                image = image.resize((100, 100))
                image = image.convert("RGB")

                # Average Pixels
                pixels = list(image.getdata())
                avg_color = tuple(map(lambda x: sum(x) // len(x), zip(*pixels)))

                # Convert to hexadecimal
                avg_color_hex = (avg_color[0] << 16) + (avg_color[1] << 8) + avg_color[2]
                return avg_color_hex

        class ButtonType(Enum):
            PAGE = "page"
            DELETE = "delete"
            SELECTOR = "selector"
            LYRICS = "lyrics"
            AI_TRANSLATE = "ai_translate" # Not implemented
            UNDO = "undo"
            YOUTUBE = "youtube"

        class BaseButton(Button):
            def __init__(self, label, row, button_type: ButtonType, callback_func=None, **kwargs):
                self.button_type = button_type
                self.callback_func = callback_func
                super().__init__(label=label, row=row, **kwargs)
                
            async def callback(self, interaction: discord.Interaction):
                if interaction.user != user:
                    await interaction.response.send_message("Only the command sender can use these buttons!", ephemeral=True)
                    return
                await interaction.response.defer()

                if self.callback_func:
                    await self.callback_func(interaction, self)

        async def page_callback(_interaction, button): 
            button.view.stop()
            button.view.clear_items()
            session.selector_page_index = (session.selector_page_index + (1 if button.custom_id == "True" else -1)) % session.selector_total_pages
            await initialize_selector()

        async def delete_callback(_interaction, _button):
            if session.lyrics_video_msg:
                await session.lyrics_video_msg.delete()
                session.lyrics_video_msg = None
            await msg.delete()

        async def selector_callback(_interaction, button):
            button.view.stop()
            button.view.clear_items()
            index = int(button.custom_id)
            embed = discord.Embed(
                title=f"You selected Song {index + 1}. Fetching lyrics...",
                color=discord.Color.orange())
            await msg.edit(embed=embed, view=None)
            await session.set_lyrics_data(index)
            await initialize_lyrics()

        async def lyrics_callback(_interaction, button):
            session.lyrics_page = [button.label, int(button.custom_id)]
            await lyrics_embed()

        async def undo_callback(_interaction, button):
            button.view.stop()
            button.view.clear_items()
            if session.lyrics_video_msg:
                await session.lyrics_video_msg.delete()
                session.lyrics_video_msg = None
            session.lyrics_page = ["Original", 0]
            await initialize_selector()

        async def youtube_callback(interaction, _button):
            if not session.lyrics_video:
                await interaction.response.send_message("No valid video for this song.", ephemeral=True)
                return
            if not session.lyrics_video_msg:
                session.lyrics_video_msg = await interaction.followup.send(content=f"{session.lyrics_video}")
            else:
                await session.lyrics_video_msg.delete()
                session.lyrics_video_msg = None
            await lyrics_embed()




        async def nothing_found() -> None:
            embed = discord.Embed(
                title=f"No results found. If you think this is a mistake, it probably is and im too lazy to fix it.",
                color=discord.Color.orange())
            await msg.edit(embed=embed)

        def get_page_size() -> tuple[int, int]:
            start_id = session.selector_page_index * session.selector_max_links
            end_id = min((session.selector_page_index + 1) * session.selector_max_links, len(session.selector_data.links))
            return start_id, end_id



        async def selector_embed() -> None:
            start_id, end_id = get_page_size()
            description = "\n".join(f"{i+1}. [{link['title']}]({link['href']})" for i, link in enumerate(session.selector_data.links[start_id:end_id]))
            embed = discord.Embed(
                title=f"Results for \"{query}\" - Page {session.selector_page_index + 1}",
                color=discord.Color.orange(),
                description=description
            )

            embed.set_footer(text=embed_footer, icon_url=user.avatar.url)

            await msg.edit(embed=embed)

        async def lyrics_embed():
            embed = discord.Embed(
                url=session.lyrics_data.query,
                title=f"{session.lyrics_page[0]} lyrics for {session.lyrics_data.title}",
                color=discord.Color(session.lyrics_color),
                description=session.lyrics_data.lyrics[session.lyrics_page[1]],
            )

            embed.add_field(name=f"\u200B", value="\u200B") # Padding between lyrics & extras
            embed.add_field(name=f"═ External Links ═", value=session.lyrics_extras, inline=False)

            if not session.lyrics_video_msg:
                embed.set_image(url=session.lyrics_data.image)

            embed.set_footer(text=embed_footer, icon_url=user.avatar.url)

            await msg.edit(embed=embed)



        async def selector_view() -> None:
            start_id, end_id = get_page_size()
            view = View(timeout=120)
            delete_button = BaseButton(label="✖", 
                                    row=1, 
                                    button_type=ButtonType.DELETE, 
                                    callback_func=delete_callback, 
                                    style=discord.ButtonStyle.danger
            )
            back_button = BaseButton(label="◀", 
                                    row=1, 
                                    button_type=ButtonType.PAGE, 
                                    callback_func=page_callback, 
                                    style=discord.ButtonStyle.primary,
                                    custom_id=str(False)
            )
            next_button = BaseButton(label="▶",
                                    row=1,
                                    button_type=ButtonType.PAGE,
                                    callback_func=page_callback,
                                    style=discord.ButtonStyle.primary,
                                    custom_id=str(True)
            )
            view.add_item(back_button)
            view.add_item(delete_button)
            view.add_item(next_button)
            for i in range(len(session.selector_data.links[start_id:end_id])):
                row = 2 + (i >= 3) 
                selector_button = BaseButton(label=f"{i+1}", 
                                             row=row, 
                                             button_type=ButtonType.SELECTOR, 
                                             callback_func=selector_callback, 
                                             custom_id=str(i)
                )
                view.add_item(selector_button)
            await msg.edit(view=view)

        async def lyrics_view():
            view = View(timeout=600)
            original_button = BaseButton(label="Original",
                                         row=1,
                                         button_type=ButtonType.LYRICS,
                                         callback_func=lyrics_callback,
                                         style=discord.ButtonStyle.primary,
                                         custom_id="0"
            )
            romanized_button = BaseButton(label="Romanized",    
                                          row=1,
                                          button_type=ButtonType.LYRICS,
                                          callback_func=lyrics_callback,
                                          style=discord.ButtonStyle.primary,
                                          custom_id="1",
                                          disabled=len(session.lyrics_data.lyrics) < 2 or session.lyrics_data.lyrics[1] == ""
            )
            translated_button = BaseButton(label="Translated", 
                                           row=1,
                                           button_type=ButtonType.LYRICS,
                                           callback_func=lyrics_callback,
                                           style=discord.ButtonStyle.primary,
                                           custom_id="2",
                                           disabled=len(session.lyrics_data.lyrics) < 3 or session.lyrics_data.lyrics[2] == ""
            )
            undo_button = BaseButton(label="↶", 
                                    row=2,
                                    button_type=ButtonType.UNDO,
                                    callback_func=undo_callback
            )
            youtube_button = BaseButton(label="YouTube Popout", 
                                       row=2,
                                       button_type=ButtonType.YOUTUBE,
                                       callback_func=youtube_callback,
                                       disabled=not session.lyrics_video
            )
            delete_button = BaseButton(label="✖", 
                                     row=2,
                                     button_type=ButtonType.DELETE,
                                     callback_func=delete_callback,
                                     style=discord.ButtonStyle.danger
            )
            view.add_item(original_button)
            view.add_item(romanized_button)
            view.add_item(translated_button)
            view.add_item(undo_button)
            view.add_item(youtube_button)
            view.add_item(delete_button)
            await msg.edit(view=view)



        async def initialize_selector():
            if not session.selector_data.links_found:
                await nothing_found()
                return
            await selector_embed()
            await selector_view()

        async def initialize_lyrics():
            if not session.lyrics_data.lyrics:
                await nothing_found()
                return
            await lyrics_embed()
            await lyrics_view()



        session = LyricsSession(interaction, query)
        session.set_selector_data()
        await initialize_selector()


async def setup(bot):
    await bot.add_cog(LyricsCommand(bot))