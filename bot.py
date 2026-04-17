import os
import logging
import asyncio
import aiohttp
import io
from datetime import datetime
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
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
GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')

# Configure Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # Use Gemini 2.0 Flash for image generation
    image_model = genai.GenerativeModel('gemini-2.0-flash-exp')
    text_model = genai.GenerativeModel('gemini-2.0-flash-exp')
else:
    image_model = None
    text_model = None
    logger.error("Google API Key not found!")

# Store user sessions
user_sessions = {}

async def generate_image(prompt: str):
    """Generate image using Gemini AI"""
    try:
        if not image_model:
            return None, "API not configured. Please check your API key."
        
        # Generate image
        response = image_model.generate_content(
            f"Generate a high-quality, detailed image of: {prompt}",
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                top_p=0.95,
                top_k=40,
                max_output_tokens=2048,
            )
        )
        
        # Check if response contains image
        if hasattr(response, '_result') and response._result.candidates:
            for part in response._result.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data.mime_type.startswith('image/'):
                    return part.inline_data.data, None
        
        return None, "Could not generate image. Please try a different prompt."
    
    except Exception as e:
        logger.error(f"Image generation error: {str(e)}")
        return None, f"Error: {str(e)}"

async def enhance_prompt(prompt: str):
    """Enhance user prompt for better image generation"""
    try:
        if not text_model:
            return prompt
        
        enhancement_prompt = f"""
        Enhance this image generation prompt to be more detailed and specific.
        Add details about style, lighting, composition, and mood.
        Original prompt: "{prompt}"
        
        Return ONLY the enhanced prompt, no additional text:
        """
        
        response = text_model.generate_content(enhancement_prompt)
        enhanced = response.text.strip()
        
        # Don't return empty or too short enhanced prompts
        if len(enhanced) > len(prompt) + 5:
            return enhanced
        return prompt
    
    except Exception as e:
        logger.error(f"Prompt enhancement error: {str(e)}")
        return prompt

# Command handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start is issued"""
    welcome_text = """
🎨 **AI Image Generator Bot**

Send me any text description, and I'll generate an image using AI!

**Commands:**
/start - Show this welcome message
/help - Show help information
/settings - Configure generation settings
/quality - Set image quality preference

**How to use:**
Simply type your image description and I'll generate it!
Example: "A beautiful sunset over mountains with a lake reflection"

**Tips:**
• Be specific with your descriptions
• Include style preferences (realistic, anime, watercolor, etc.)
• Add mood and lighting details for better results

**Credits:** Powered by Google Gemini AI
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help information when /help is issued"""
    help_text = """
📖 **Help Guide**

**Basic Usage:**
1. Type any image description
2. Wait a few seconds
3. Receive your AI-generated image

**Example prompts:**
• "A cyberpunk city at night with neon lights and rain"
• "A cute cat wearing a wizard hat, cartoon style"
• "Futuristic spaceship landing on Mars, realistic"
• "Watercolor painting of a forest with magical creatures"

**Settings:**
/quality low|medium|high - Set generation quality
/enhance on|off - Toggle prompt enhancement

**Need better results?**
• Add art style: "oil painting", "digital art", "sketch"
• Add mood: "peaceful", "dramatic", "dreamy"
• Add lighting: "golden hour", "neon", "soft light"

**Support:** @BotSupport
"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set image quality preference"""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /quality [low|medium|high]\n"
            "Example: /quality high"
        )
        return
    
    quality = args[0].lower()
    if quality not in ['low', 'medium', 'high']:
        await update.message.reply_text("Please choose: low, medium, or high")
        return
    
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    
    user_sessions[user_id]['quality'] = quality
    await update.message.reply_text(f"✅ Quality set to: {quality}")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current settings"""
    user_id = update.effective_user.id
    settings = user_sessions.get(user_id, {})
    
    quality = settings.get('quality', 'medium')
    enhance = settings.get('enhance', 'on')
    
    keyboard = [
        [InlineKeyboardButton(f"Quality: {quality}", callback_data='toggle_quality')],
        [InlineKeyboardButton(f"Enhance: {enhance}", callback_data='toggle_enhance')],
        [InlineKeyboardButton("Reset to Default", callback_data='reset_settings')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚙️ **Current Settings**\n\n"
        f"Quality: {quality}\n"
        f"Prompt Enhancement: {enhance}\n\n"
        "Click buttons below to change:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def handle_image_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate image from text prompt"""
    prompt = update.message.text.strip()
    
    # Ignore commands
    if prompt.startswith('/'):
        return
    
    # Send typing indicator
    await update.message.chat.send_action(action="upload_photo")
    
    # Send initial message
    processing_msg = await update.message.reply_text(
        "🎨 Generating your image...\n"
        f"Prompt: *{prompt[:100]}*",
        parse_mode='Markdown'
    )
    
    try:
        # Get user settings
        user_id = update.effective_user.id
        settings = user_sessions.get(user_id, {})
        enhance = settings.get('enhance', 'on')
        
        # Enhance prompt if enabled
        final_prompt = prompt
        if enhance == 'on':
            final_prompt = await enhance_prompt(prompt)
        
        # Generate image
        image_data, error = await generate_image(final_prompt)
        
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
            caption=f"🎨 Generated for: *{prompt[:100]}*\n\n"
                    f"✨ Powered by Google Gemini AI",
            parse_mode='Markdown'
        )
        
        # Delete processing message
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"Error in handle_image_generation: {str(e)}")
        await processing_msg.edit_text(
            "❌ An unexpected error occurred.\n"
            "Please try again or contact support."
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    
    data = query.data
    settings = user_sessions[user_id]
    
    if data == 'toggle_quality':
        qualities = ['low', 'medium', 'high']
        current = settings.get('quality', 'medium')
        next_idx = (qualities.index(current) + 1) % len(qualities)
        settings['quality'] = qualities[next_idx]
        await query.edit_message_text(f"✅ Quality set to: {settings['quality']}")
    
    elif data == 'toggle_enhance':
        current = settings.get('enhance', 'on')
        settings['enhance'] = 'off' if current == 'on' else 'on'
        await query.edit_message_text(f"✅ Prompt enhancement: {settings['enhance']}")
    
    elif data == 'reset_settings':
        user_sessions[user_id] = {'quality': 'medium', 'enhance': 'on'}
        await query.edit_message_text("✅ Settings reset to default")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")

def run_bot():
    """Run the bot"""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quality", quality_command))
    application.add_handler(CommandHandler("settings", settings_command))
    
    # Add message handler for text (image generation)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_generation))
    
    # Add callback handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# Flask route for Render
@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle webhook requests from Telegram"""
    return "Webhook received", 200

if __name__ == '__main__':
    import threading
    from flask import Flask
    
    # Run Flask in a separate thread for health checks
    def run_flask():
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    # Run the bot
    run_bot()
