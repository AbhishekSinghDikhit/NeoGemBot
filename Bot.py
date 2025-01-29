import os
import io
import re
from PIL import Image 
import fitz
from PyPDF2 import PdfReader
import logging
from dotenv import load_dotenv
import datetime
from pydub import AudioSegment
import whisper
import asyncio
from textblob import TextBlob
from googletrans import Translator
import pandas as pd
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)
from pymongo import MongoClient
import requests
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from urllib.parse import quote_plus

# Initialize logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# Load .env file
load_dotenv()

# Fetch environment variables
try:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    MONGO_URL = os.getenv("MONGO_URL")
except Exception as e:
    print(f"Error loading environment variables: {e}")

try:
    client = MongoClient(MONGO_URL)
    client.admin.command("ping")
    db = client["NeoGem"]
    users_collection = db["users"]
    chats_collection = db["chats"]
    files_collection = db["files"]

    logger.info("✅ Connected to MongoDB successfully.")
except Exception as e:
    logger.error(f"❌ Error connecting to MongoDB: {str(e)}", exc_info=True)
    raise

# Initialize Gemini API
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")
translator = Translator()
whisper_model = whisper.load_model("base")
API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-dev"
HEADERS = {"Authorization": f"Bearer {os.getenv('HF_TOKEN')}"}

def analyze_sentiment(text):
    blob = TextBlob(text)
    sentiment_score = blob.sentiment.polarity  
    if sentiment_score > 0:
        return "Positive 😊"
    elif sentiment_score < 0:
        return "Negative 😞"
    return "Neutral 😐"

# Auto-Translation Function
def translate_text(text, target_lang="en"):
    translated_text = translator.translate(text, dest=target_lang).text
    return translated_text

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
            "/generate_image - generate image with prompt",
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

# Function to query the Hugging Face Inference API
def generate_image_from_prompt(prompt):
    payload = {
        "inputs": prompt,
        "parameters": {
            "height": 256, 
            "width": 256,
            "guidance_scale": 7.5,
            "num_inference_steps": 30  
        }
    }

    response = requests.post(API_URL, headers=HEADERS, json=payload)

    if response.status_code == 200:
        return response.content  # Returns image bytes
    else:
        raise Exception(f"Failed to generate image: {response.status_code}, {response.text}")

# Telegram bot command handler for image generation
async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /generate_image <prompt>")
        return

    prompt = " ".join(context.args)
    await update.message.reply_text(f"Generating an image for: '{prompt}'...")

    try:
        # Generate image from the prompt
        image_bytes = generate_image_from_prompt(prompt)

        # Load the image using PIL and save it temporarily
        image = Image.open(io.BytesIO(image_bytes))
        temp_path = "generated_image.png"
        image.save(temp_path)

        # Send the generated image to the user
        await update.message.reply_photo(photo=open(temp_path, "rb"))
    except Exception as e:
        await update.message.reply_text(f"An error occurred: {str(e)}")

#Gemini-powered chat handler
async def gemini_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    chat_id = update.effective_chat.id
    retries = 3
    delay = 5
    
    # Retrieve previous chat history (last 5 messages)
    chat_history = chats_collection.find({"chat_id": chat_id}).sort("timestamp", -1).limit(5)
    chat_context = "\n".join([f"User: {chat['user_input']}\nBot: {chat['bot_response']}" for chat in chat_history])
    prompt = f"Previous conversation:\n{chat_context}\nUser: {user_input}\nBot:"
    
    for attempt in range(retries):
        try:
            response = model.generate_content(prompt, stream=True)
            response.resolve()
            bot_response = response.text
            
            # Save chat history
            chats_collection.insert_one({
                "chat_id": chat_id,
                "user_input": user_input,
                "bot_response": bot_response,
                "timestamp": datetime.datetime.utcnow()
            })
            
            await update.message.reply_text(bot_response if bot_response else "No response generated.")
            return
        except ResourceExhausted:
            if attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                await update.message.reply_text("Quota exceeded, please try again later.")
                break
        except Exception as e:
            logger.error(f"Error in Gemini chat: {str(e)}")
            await update.message.reply_text("Sorry, I couldn't process your request.")
            break

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = (update.message.document or 
            (update.message.photo[-1] if update.message.photo else None) or
            update.message.audio or update.message.voice)
    
    if not file:
        await update.message.reply_text("Please send a valid file, image, or audio.")
        return

    file_id = file.file_id
    file_name = getattr(file, "file_name", f"{file_id}.jpg")
    retries = 3
    delay = 5  # seconds

    for attempt in range(retries):
        try:
            file_info = await context.bot.get_file(file_id)
            os.makedirs("downloads", exist_ok=True)
            file_path = f"downloads/{file_name}"
            await file_info.download_to_drive(file_path)

            with open(file_path, "rb") as file_data:
                file_binary = file_data.read()

            file_metadata = {
                "chat_id": update.effective_chat.id,
                "file_name": file_name,
                "file_data": file_binary,
                "timestamp": datetime.datetime.utcnow()
            }
            files_collection.insert_one(file_metadata)

            if file_name.lower().endswith('.pdf'):
                text = ""
                pdf_reader = fitz.open(file_path)
                for page in pdf_reader:
                    text += page.get_text()
                response_text = summarize_text(text[:1000])

            elif file_name.lower().endswith(('.jpg', '.jpeg', '.png')):
                image = Image.open(io.BytesIO(file_binary))
                response_text = describe_image(image)

            elif file_name.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a')):
                audio_text = transcribe_audio(file_path)
                response_text = f"Transcribed Audio: {audio_text}"

            else:
                response_text = "File uploaded successfully. No analysis available."

            files_collection.update_one(
                {"file_name": file_name},
                {"$set": {"description": response_text}}
            )

            await update.message.reply_text(f"File analyzed: {response_text}")
            return

        except Exception as e:
            logger.error(f"Error handling file: {str(e)}")
            await update.message.reply_text("An error occurred while processing the file.")
            break

# Helper functions
def summarize_text(text):
    prompt = f"Summarize the following text: {text}"
    response = model.generate_content([prompt])
    response.resolve()
    return response.text

def describe_image(image):
    prompt = "Describe the content of this image."
    response = model.generate_content([prompt, image])
    response.resolve()
    return response.text

def transcribe_audio(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("temp.wav", format="wav")
    result = whisper_model.transcribe("temp.wav")
    os.remove("temp.wav")
    return result["text"]


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
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(CommandHandler("stop", stop))

    # Message handlers
    app.add_handler(MessageHandler(filters.CONTACT, save_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gemini_chat))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))

    # Start polling for updates
    app.run_polling()

if __name__ == "__main__":
    main()