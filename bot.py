import os
import subprocess
import math
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from pydub import AudioSegment
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB

# Fetch sensitive data from environment variables set on Heroku
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ensure environment variables are set
if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET or not BOT_TOKEN:
    raise EnvironmentError("Please set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, and BOT_TOKEN environment variables.")

# Initialize Spotify API client
spotify_client = Spotify(
    client_credentials_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
)

# Global variables to store search results and pagination
search_results = {}
current_page = {}

# Function to handle /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! You can search for a song by typing the album or movie name. 🎶"
    )

# Function to fetch and display paginated search results
async def search_and_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    
    if not query:
        await update.message.reply_text("Please provide a search query.")
        return

    await display_search_results(update, context, query=query, page=1)

# Function to display search results with pagination
async def display_search_results(update: Update, context, query, page=1):
    global search_results
    global current_page

    try:
        # Search for tracks on Spotify
        results = spotify_client.search(q=query, type="track", limit=20)  # Fetch up to 20 results
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            await update.message.reply_text("No results found. Try a different query.")
            return

        # Store the search results and current page
        search_results[update.message.chat_id] = tracks
        current_page[update.message.chat_id] = page

        # Pagination setup
        items_per_page = 5
        total_pages = math.ceil(len(tracks) / items_per_page)
        start_index = (page - 1) * items_per_page
        end_index = start_index + items_per_page

        # Fetch and send poster (use the first track's album artwork)
        poster_url = tracks[0]["album"]["images"][0]["url"] if tracks[0]["album"]["images"] else None
        if poster_url:
            await context.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=poster_url,
                caption=f"Search results for: {query}"
            )

        # Generate buttons for the current page
        keyboard = []
        for index, track in enumerate(tracks[start_index:end_index], start=start_index):
            track_name = track["name"]
            track_artist = ", ".join([artist["name"] for artist in track["artists"]])
            button = InlineKeyboardButton(f"{track_name} - {track_artist}", callback_data=f"track_{index}")
            keyboard.append([button])

        # Add navigation buttons
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ BACK", callback_data="prev_page"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("NEXT ➡️", callback_data="next_page"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send the message with buttons
        await update.message.reply_text("Choose a track:", reply_markup=reply_markup)

    except Exception as e:
        await update.message.reply_text(f"An error occurred while fetching results: {e}")

# Function to handle pagination navigation
async def handle_pagination(update: Update, context):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    if "next_page" in query.data:
        current_page[chat_id] += 1
    elif "prev_page" in query.data:
        current_page[chat_id] -= 1

    # Redisplay the search results
    tracks = search_results.get(chat_id, [])
    if not tracks:
        await query.message.reply_text("No results found.")
        return

    query_text = query.message.text.split(":")[1].strip()  # Extract the original query
    await display_search_results(update, context, query=query_text, page=current_page[chat_id])

# Function to handle selection of a song (using yt-dlp without cookies)
async def select_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Extract track index from callback data
    track_index = int(query.data.split("_")[1])
    chat_id = query.message.chat_id

    # Get the selected track details
    track = search_results[chat_id][track_index]
    track_name = track["name"]
    track_artist = ", ".join([artist["name"] for artist in track["artists"]])
    track_url = track["external_urls"]["spotify"]  # Spotify URL for the track

    await query.edit_message_text(
        f"Selected: {track_name} by {track_artist}\nDownloading..."
    )

    try:
        # Download the song using yt-dlp (no cookies required)
        command = [
            "yt-dlp",
            "--extract-audio",  # Extract audio only (e.g., mp3)
            "--audio-format", "mp3",  # Convert to mp3 format
            track_url  # The track URL from Spotify
        ]
        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode != 0:
            await query.message.reply_text(f"Error downloading the track: {result.stderr}")
            return

        # Find the downloaded file (assuming it has the .mp3 extension)
        for file in os.listdir("."):
            if file.endswith(".mp3"):
                # Use pydub to convert audio if necessary (e.g., to adjust bitrate)
                audio = AudioSegment.from_mp3(file)
                audio = audio.set_channels(1)  # Mono
                audio = audio.set_frame_rate(44100)  # 44.1kHz sample rate
                audio.export(file, format="mp3")

                # Use mutagen to add metadata (ID3 tags)
                audio_file = MP3(file, ID3=ID3)
                audio_file.tags.add(TIT2(encoding=3, text=track_name))  # Title
                audio_file.tags.add(TPE1(encoding=3, text=track_artist))  # Artist
                audio_file.tags.add(TALB(encoding=3, text="Spotify"))  # Album (custom tag)

                # Send the MP3 file to the user
                with open(file, "rb") as audio_data:
                    await query.message.reply_audio(audio_data)
                os.remove(file)  # Clean up the downloaded file
                return

        await query.message.reply_text("Failed to find the downloaded file.")

    except Exception as e:
        await query.message.reply_text(f"An error occurred: {e}")

# Main function to start the bot
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_download))
    application.add_handler(CallbackQueryHandler(handle_pagination, pattern="prev_page|next_page"))
    application.add_handler(CallbackQueryHandler(select_song, pattern="track_.*"))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
