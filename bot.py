import subprocess
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Define the command to search for songs
async def search_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    chat_id = update.message.chat_id

    # Assume the search_results are populated with relevant song data
    search_results = {}  # Define your search_results here

    # Prepare keyboard with song options
    keyboard = [
        [
            InlineKeyboardButton(f"{track['name']} - {', '.join([artist['name'] for artist in track['artists']])}",
                                 callback_data=f"track_{index}")
            for index, track in enumerate(search_results.get(chat_id, []))
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose a song:", reply_markup=reply_markup)

# Define the function to select and download the song
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
    track_url = track["external_urls"]["spotify"]

    await query.edit_message_text(
        f"Selected: {track_name} by {track_artist}\nDownloading..."
    )

    try:
        # Define output directory and clean up any existing files
        output_dir = "downloads"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Clear existing MP3 files in the output directory
        for file in os.listdir(output_dir):
            if file.endswith(".mp3"):
                os.remove(os.path.join(output_dir, file))

        # Download the song using spotdl
        command = [
            "spotdl",
            "download",  # Command to download
            "--format", "mp3",  # Force mp3 format
            "--output", f"{output_dir}/%(artist)s - %(title)s.%(ext)s",  # Output path
            track_url,  # Track URL
        ]
        
        # Ensure that spotdl recognizes the arguments properly
        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode != 0:
            await query.message.reply_text(f"Download failed: {result.stderr}")
            return

        # Find the downloaded file and send it to the user
        for file in os.listdir(output_dir):
            if file.endswith(".mp3"):
                file_path = os.path.join(output_dir, file)
                with open(file_path, "rb") as audio:
                    await query.message.reply_audio(audio)
                os.remove(file_path)  # Clean up the downloaded file
                return

        await query.message.reply_text("Failed to find the downloaded file.")

    except Exception as e:
        await query.message.reply_text(f"An error occurred: {e}")

    finally:
        # Ensure all files are cleaned up
        for file in os.listdir(output_dir):
            os.remove(os.path.join(output_dir, file))

# Add your token and initialize the bot
application = Application.builder().token('YOUR_BOT_TOKEN').build()

# Add command handlers
application.add_handler(CommandHandler("search", search_song))

# Add callback handler for song selection
application.add_handler(CallbackQueryHandler(select_song))

# Run the bot
application.run_polling()
