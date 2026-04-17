import os
import logging
import io
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app for Render health checks
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

# Bot configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# Configure Gemini AI
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash-exp')
else:
    model = None
    logger.error("Google API Key not found!")

async def generate_image(prompt: str):
    """Generate image using Gemini AI"""
    try:
        if not model:
            return None, "API not configured. Please check your API key."
        
        # Generate image
        response = model.generate_content(
            f"Generate a high-quality, detailed image of: {prompt}",
            generation_config={
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 40,
            }
        )
        
        # Extract image data
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data.mime_type.startswith('image/'):
                    return part.inline_data.data, None
        
        return None, "Could not generate image. Please try a different prompt."
    
    except Exception as e:
        logger.error(f"Image generation error: {str(e)}")
        return None, f"Error: {str(e)}"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start is issued"""
    welcome_text = """
🎨 **AI Image Generator Bot**

Send me any text description, and I'll generate an image using Google Gemini AI!

**Commands:**
/start - Show this message
/help - Show help information

**How to use:**
Simply type your image description and I'll generate it!

**Example prompts:**
• "A beautiful sunset over mountains with a lake"
• "A cute cat wearing a wizard hat, cartoon style"
• "Futuristic city with neon lights at night"
• "A dragon flying over a medieval castle"

**Tips for better results:**
• Be specific with your descriptions
• Include style (realistic, anime, painting)
• Add mood and lighting details

Powered by Google Gemini AI
"""
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help information when /help is issued"""
    help_text = """
📖 **How to use this bot**

Simply type any image description and I'll generate it!

**Examples:**
• "A cyberpunk city at night with neon lights"
• "A cute cat wearing a wizard hat, cartoon style"
• "Futuristic spaceship landing on Mars, realistic"
• "Watercolor painting of a forest"

**Tips for amazing images:**
• Add art style: "oil painting", "digital art", "sketch"
• Add mood: "peaceful", "dramatic", "dreamy"  
• Add lighting: "golden hour", "neon", "soft light"
• Be detailed: "A red fox jumping over a log in a snowy forest"
"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate image from any text message"""
    prompt = update.message.text.strip()
    
    # Ignore commands
    if prompt.startswith('/'):
        return
    
    # Send typing indicator
    await update.message.chat.send_action(action="upload_photo")
    
    # Send processing message
    processing_msg = await update.message.reply_text(
        f"🎨 Generating image...\n\n*Prompt:* {prompt[:100]}",
        parse_mode='Markdown'
    )
    
    try:
        # Generate the image
        image_data, error = await generate_image(prompt)
        
        if error:
            await processing_msg.edit_text(
                f"❌ Failed to generate image\n\n"
                f"Error: {error}\n\n"
                f"Try:\n"
                f"• Rewording your prompt\n"
                f"• Making it more specific\n"
                f"• Using /help for tips"
            )
            return
        
        # Send the generated image
        await update.message.reply_photo(
            photo=io.BytesIO(image_data),
            caption=f"🎨 Generated for: *{prompt[:100]}*\n\n✨ Powered by Google Gemini AI",
            parse_mode='Markdown'
        )
        
        # Delete processing message
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await processing_msg.edit_text(
            "❌ An unexpected error occurred.\n"
            "Please try again or contact support."
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")

def run_bot():
    """Run the bot"""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    
    # Create application with updated builder pattern
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    # Start bot with polling (updated method for v21)
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    import threading
    
    # Run Flask in a separate thread for health checks
    def run_flask():
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)), debug=False)
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    # Run the bot
    run_bot()
