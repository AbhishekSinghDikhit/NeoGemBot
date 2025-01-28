A Telegram bot that allows users to upload and analyze images and PDF files. The bot is designed to generate descriptions for images, process PDF files, and can even generate images based on prompts. The bot also integrates with the Gemini API for content generation and image creation.

## Features
- **File Upload and Processing**: Users can upload images or PDFs. The bot can handle various file types and process them accordingly.
- **Image Description Generation**: The bot uses the Gemini API to generate descriptions for images.
- **Image Generation**: Users can provide a prompt, and the bot will generate an image based on the input using the Gemini API.
- **PDF Text Extraction**: The bot extracts text from PDF files for further processing.
- **MongoDB Storage**: The bot stores metadata of processed files in MongoDB for tracking and record-keeping.

## Technologies Used
- **Python**: For the core bot functionality.
- **Telegram Bot API**: For interacting with users.
- **Gemini API**: For image description generation and image creation.
- **MongoDB**: For storing metadata about processed files.
- **PIL (Python Imaging Library)**: For handling image files.

## Prerequisites

- Python 3.7+
- MongoDB instance (local or cloud)
- Telegram Bot API Token
- Gemini API Key for image generation

## Installation

1. Clone the repository:
    ```bash
    git clone https://github.com/yourusername/telegram-image-file-handler-bot.git
    cd telegram-image-file-handler-bot
    ```

2. Create a virtual environment and activate it:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3. Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

4. Create a `.env` file in the root directory with the following environment variables:
    ```
    TELEGRAM_API_TOKEN=your-telegram-bot-api-token
    GEMINI_API_KEY=your-gemini-api-key
    MONGO_URI=your-mongodb-uri
    ```

5. Run the bot:
    ```bash
    python bot.py
    ```

## Usage

1. **Start the Bot**: 
   - Open Telegram and search for your bot.
   - Start a conversation with the bot.

2. **Upload an Image**:
   - Send an image to the bot, and it will generate a description based on the image content.

3. **Upload a PDF**:
   - Send a PDF file to the bot, and it will extract the text for analysis.

4. **Generate an Image**:
   - Send a command like `/generate_image Fuzzy bunnies in my kitchen` to generate an image based on the prompt.

## Commands

- `/generate_image <prompt>`: Generate an image based on the provided prompt.

## Example Output

When a user sends an image:
