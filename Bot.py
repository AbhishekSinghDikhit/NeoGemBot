import os
import io
from PIL import Image 
import fitz
from PyPDF2 import PdfReader
import logging
import datetime
import asyncio
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)
from pymongo import MongoClient
import requests
import google.generativeai as genai
from decouple import config, UndefinedValueError
from google.api_core.exceptions import ResourceExhausted
from urllib.parse import quote_plus

# Initialize logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
try:
    GEMINI_API_KEY = "AIzaSyATo_VGl0FUVWZAi3yYCKsRleyJIfy0M78"
    TELEGRAM_BOT_TOKEN = "7577465285:AAHc5OF1PM6fb0TlLCFYgz35l9bpeQlmKQ8"
    MONGO_USERNAME = "aabhishek576"
    MONGO_PASSWORD = quote_plus("1S2i3n4g5h")
except UndefinedValueError as e:
    logger.error(f"Environment variable not set: {str(e)}")
    raise

# Initialize MongoDB connection
try:
    MONGO_URI = f"mongodb+srv://{MONGO_USERNAME}:{MONGO_PASSWORD}@infomate.r9goy.mongodb.net/?retryWrites=true&w=majority"
    client = MongoClient(MONGO_URI)
    client.admin.command('ping')
    db = client["NeoGem"]
    users_collection = db["users"]
    chats_collection = db["chats"]
    files_collection = db["files"]
    logger.info("Connected to MongoDB successfully.")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {str(e)}")
    raise

# Initialize Gemini API
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if not users_collection.find_one({"chat_id": chat_id}):
        users_collection.insert_one({
            "first_name": user.first_name,
            "username": user.username,
            "chat_id": chat_id,
            "timestamp": datetime.datetime.utcnow()
        })
        await update.message.reply_text("Welcome! Please share your phone number.")
        await request_contact(update, context)
    else:
        # List of commands and their descriptions
        commands = [
            "/start - Start the bot and display this message.",
            "/websearch <query or link> - Search the web for the specified query or link.",
            "/stop - Stop the bot.",
            # Add more commands as needed
        ]
        command_text = "\n".join(commands)
        
        await update.message.reply_text(f"Welcome back!\n\nHere are the available commands:\n{command_text}")


# Request contact info
async def request_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    button = KeyboardButton(text="Share Contact", request_contact=True)
    await update.message.reply_text(
        "Click the button to share your contact info.",
        reply_markup=ReplyKeyboardMarkup([[button]], one_time_keyboard=True)
    )

# Save contact info
async def save_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if contact:
        users_collection.update_one(
            {"chat_id": update.effective_chat.id},
            {"$set": {"phone_number": contact.phone_number}}
        )
        await update.message.reply_text("Contact saved! You're all set.")

#Gemini-powered chat handler
async def gemini_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    chat_id = update.effective_chat.id
    retries = 3
    delay = 5  # seconds
    bot_response = ""

    for attempt in range(retries):
        try:
            # Generate response using Gemini API
            response = model.generate_content(user_input, stream=True)
            
            response.resolve()

            bot_response = response.text

            # Save chat history in MongoDB
            chats_collection.insert_one({
                "chat_id": chat_id,
                "user_input": user_input,
                "bot_response": bot_response,
                "timestamp": datetime.datetime.utcnow()
            })

            if bot_response:
                await update.message.reply_text(bot_response)
            else:
                await update.message.reply_text("No response generated.")
            return  # Exit after successfully sending the response

        except ResourceExhausted:
            if attempt < retries - 1:
                await update.message.reply_text("Rate limit exceeded. Retrying...")
                await asyncio.sleep(delay)  # Wait before retrying
                delay *= 2  # Exponential backoff
            else:
                await update.message.reply_text("Quota exceeded, please try again later.")
                break
        except Exception as e:
            logger.error(f"Error in Gemini chat: {str(e)}")
            await update.message.reply_text("Sorry, I couldn't process your request at the moment.")
            break

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document or (update.message.photo[-1] if update.message.photo else None)
    
    if not file:
        await update.message.reply_text("Please send a valid file or image.")
        return

    file_id = file.file_id
    file_name = getattr(file, "file_name", f"{file_id}.jpg")
    retries = 3
    delay = 5  # seconds

    for attempt in range(retries):
        try:
            # Save file metadata and download the file locally
            file_info = await context.bot.get_file(file_id)
            os.makedirs("downloads", exist_ok=True)
            file_path = f"downloads/{file_name}"
            await file_info.download_to_drive(file_path)

            # Read the file into memory for MongoDB storage (if storing as binary)
            with open(file_path, "rb") as file_data:
                file_binary = file_data.read()

            # Store the file in MongoDB along with its metadata
            file_metadata = {
                "chat_id": update.effective_chat.id,
                "file_name": file_name,
                "file_data": file_binary,  # Store the binary content
                "timestamp": datetime.datetime.utcnow()
            }
            files_collection.insert_one(file_metadata)

            # If the file is a PDF, process it accordingly
            if file_name.lower().endswith('.pdf'):
                # Extract text from the PDF using PyMuPDF (fitz)
                pdf_reader = PdfReader(file_path)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text()
                # Generate a prompt for Gemini to describe the content of the PDF
                prompt = f"Summarize the content of the PDF: {file_name}. The extracted text is: {text[:1000]}..."  # Limit text for context

                # Send the prompt along with the extracted text to the Gemini API
                response = model.generate_content([prompt])

                # Resolve the response and get the description text
                response.resolve()
                file_description = response.text

                # Update metadata with description
                files_collection.update_one(
                    {"file_name": file_name},
                    {"$set": {"description": file_description}}
                )

            else:
                # Handle image or other file types (like JPG, PNG) as before
                image = Image.open(io.BytesIO(file_binary))  # Open the file from binary data
                prompt = f"Describe the content of the image: {file_name}"
                response = model.generate_content([prompt, image])
                response.resolve()
                file_description = response.text

                # Update metadata with description
                files_collection.update_one(
                    {"file_name": file_name},
                    {"$set": {"description": file_description}}
                )

            await update.message.reply_text(f"File analyzed: {file_description}")
            return  # Exit after successfully processing the file

        except ResourceExhausted:
            if attempt < retries - 1:
                await update.message.reply_text("Rate limit exceeded. Retrying...")
                await asyncio.sleep(delay)  # Wait before retrying
                delay *= 2  # Exponential backoff
            else:
                await update.message.reply_text("Quota exceeded, please try again later.")
                break
        except Exception as e:
            logger.error(f"Error handling file: {str(e)}")
            await update.message.reply_text("An error occurred while processing the file.")
            break

# Web search handler
import re

async def web_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    
    if not query:
        await update.message.reply_text("Usage: /websearch <query or link>")
        return

    # Check if the query is a URL
    is_url = re.match(r'^(https?|ftp):\/\/[^\s/$.?#].[^\s]*$', query)

    try:
        if is_url:
            # Handle the case where the query is a URL
            await update.message.reply_text(f"Fetching data for the URL: {query}")
            
            # Example: Perform web scraping or metadata extraction (simplified here)
            response = requests.get(query)
            if response.status_code == 200:
                # Extract title or summary (this requires further parsing, e.g., BeautifulSoup)
                content_preview = response.text[:200]  # Preview first 200 characters
                await update.message.reply_text(
                    f"**Preview of {query}:**\n\n{content_preview}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("Failed to fetch the URL content.")
        else:
            # Handle the case where the query is a text search
            response = requests.get(f"https://api.duckduckgo.com/?q={query}&format=json")
            results = response.json()

            links = results.get("RelatedTopics", [])
            if not links:
                await update.message.reply_text("No results found.")
                return

            summary = f"**Search Results for:** {query}\n\n"
            for link in links[:5]:
                summary += f"- [{link['Text']}]({link['FirstURL']})\n"

            await update.message.reply_text(summary, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in web search: {str(e)}")
        await update.message.reply_text("An error occurred during the search.")


# Stop command handler
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    logger.info(f"Stop command received from {user.first_name} (chat_id: {chat_id})")
    # Send a reply and remove the custom keyboard
    await update.message.reply_text(
        "The bot is shutting down. Goodbye!",
        reply_markup=ReplyKeyboardRemove()  
    )
    
    # Stop the application
    await context.application.stop()

# Main function to run the bot
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("websearch", web_search))
    app.add_handler(CommandHandler("stop", stop))

    # Message handlers
    app.add_handler(MessageHandler(filters.CONTACT, save_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gemini_chat))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))

    # Start polling for updates
    app.run_polling()

if __name__ == "__main__":
    main()