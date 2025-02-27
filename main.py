import os
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from motor.motor_asyncio import AsyncIOMotorClient

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # e.g. https://your-app.koyeb.app
PORT = int(os.getenv("PORT", 8080))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# Replace the MONGODB_URI with your full connection string including the database name.
MONGO_URI = "mongodb+srv://nehal969797:nehalsingh969797@cluster0.7ccmpy4.mongodb.net/koyebbot?retryWrites=true&w=majority&appName=Cluster0"
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client.get_default_database()  # This now returns the "koyebbot" database.
accounts_collection = db["accounts"]

# Utility: Retrieve an account document by its ObjectId (as a string)
async def get_account_by_id(account_id: str):
    from bson import ObjectId
    try:
        account = await accounts_collection.find_one({"_id": ObjectId(account_id)})
        return account
    except Exception:
        return None

# Display the start message and list all accounts (if any)
async def show_start(chat_id):
    accounts_cursor = accounts_collection.find({})
    accounts = await accounts_cursor.to_list(length=100)
    if not accounts:
        text = ("Welcome to Advanced Koyeb Manager Bot.\n"
                "No account added yet. Please add a Koyeb account.")
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Add Account", callback_data="add_account"))
        await bot.send_message(chat_id, text, reply_markup=keyboard)
    else:
        text = "Welcome to Advanced Koyeb Manager Bot.\nSelect an account to manage:"
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        for acc in accounts:
            keyboard.add(types.InlineKeyboardButton(acc.get("name", "Unnamed"), callback_data=f"account_{str(acc['_id'])}"))
        keyboard.add(types.InlineKeyboardButton("Add Account", callback_data="add_account"))
        await bot.send_message(chat_id, text, reply_markup=keyboard)

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await show_start(message.chat.id)

# -------------------- Account Management --------------------

# When user clicks "Add Account" button
@dp.callback_query_handler(lambda c: c.data == "add_account")
async def process_add_account(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    text = ("Please add your Koyeb account info in the following format:\n\n"
            "AddAccount: <account_name> <koyeb_api_key>")
    await bot.send_message(callback_query.from_user.id, text)

# Handle message to add an account (format: AddAccount: <account_name> <koyeb_api_key>)
@dp.message_handler(lambda message: message.text and message.text.startswith("AddAccount:"))
async def handle_add_account(message: types.Message):
    try:
        _, details = message.text.split(":", 1)
        parts = details.strip().split(" ", 1)
        if len(parts) < 2:
            raise ValueError("Insufficient data")
        account_name = parts[0].strip()
        koyeb_api = parts[1].strip()
    except Exception:
        await message.reply("Invalid format. Use: AddAccount: <account_name> <koyeb_api_key>")
        return

    account_data = {"name": account_name, "api_key": koyeb_api}
    result = await accounts_collection.insert_one(account_data)
    if result.inserted_id:
        await message.reply(f"Account '{account_name}' added successfully!")
    else:
        await message.reply("Failed to add account.")
    await show_start(message.chat.id)

# When user selects an account from the list
@dp.callback_query_handler(lambda c: c.data.startswith("account_"))
async def account_menu(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    text = f"Managing account: {account.get('name')}\nSelect an action:"
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("Redeploy", callback_data=f"redeploy_{account_id}"),
        types.InlineKeyboardButton("See Logs", callback_data=f"logs_{account_id}"),
        types.InlineKeyboardButton("Stop", callback_data=f"stop_{account_id}"),
        types.InlineKeyboardButton("Resume", callback_data=f"resume_{account_id}"),
        types.InlineKeyboardButton("Env Vars", callback_data=f"env_{account_id}"),
        types.InlineKeyboardButton("Change Env", callback_data=f"changeenv_{account_id}"),
        types.InlineKeyboardButton("Delete Account", callback_data=f"delete_{account_id}")
    )
    keyboard.add(types.InlineKeyboardButton("Back to Accounts", callback_data="back_accounts"))
    await bot.send_message(callback_query.from_user.id, text, reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Go back to accounts list
@dp.callback_query_handler(lambda c: c.data == "back_accounts")
async def back_to_accounts(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await show_start(callback_query.from_user.id)

# -------------------- Koyeb App Operations --------------------

# Utility: Retrieve the free app for an account using its API key
async def get_free_app(api_key: str):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {api_key}"}
        async with session.get("https://app.koyeb.com/api/v1/apps", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                apps = data.get("apps", [])
                if apps:
                    return apps[0]  # Assumes the free app is the first one
    return None

# Redeploy the app
@dp.callback_query_handler(lambda c: c.data.startswith("redeploy_"))
async def redeploy_app(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found for this account.")
        return
    app_id = free_app.get("id")
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        async with session.post(f"https://app.koyeb.com/api/v1/apps/{app_id}/redeploy", headers=headers) as resp:
            if resp.status in (200, 201):
                text = f"App '{free_app.get('name')}' redeployed successfully."
            else:
                text = f"Failed to redeploy app. Status: {resp.status}"
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

# See logs for the app
@dp.callback_query_handler(lambda c: c.data.startswith("logs_"))
async def see_logs(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found for this account.")
        return
    app_id = free_app.get("id")
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        async with session.get(f"https://app.koyeb.com/api/v1/apps/{app_id}/logs", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                logs = data.get("logs", [])
                text = "Recent Logs:\n" + "\n".join(logs[-10:]) if logs else "No logs available."
            else:
                text = f"Failed to retrieve logs. Status: {resp.status}"
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

# Stop the app
@dp.callback_query_handler(lambda c: c.data.startswith("stop_"))
async def stop_app(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found for this account.")
        return
    app_id = free_app.get("id")
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        async with session.post(f"https://app.koyeb.com/api/v1/apps/{app_id}/stop", headers=headers) as resp:
            if resp.status == 200:
                text = f"App '{free_app.get('name')}' stopped successfully."
            else:
                text = f"Failed to stop app. Status: {resp.status}"
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

# Resume the app
@dp.callback_query_handler(lambda c: c.data.startswith("resume_"))
async def resume_app(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found for this account.")
        return
    app_id = free_app.get("id")
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        async with session.post(f"https://app.koyeb.com/api/v1/apps/{app_id}/resume", headers=headers) as resp:
            if resp.status == 200:
                text = f"App '{free_app.get('name')}' resumed successfully."
            else:
                text = f"Failed to resume app. Status: {resp.status}"
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

# View Environment Variables
@dp.callback_query_handler(lambda c: c.data.startswith("env_"))
async def see_env(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found for this account.")
        return
    app_id = free_app.get("id")
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        async with session.get(f"https://app.koyeb.com/api/v1/apps/{app_id}/env", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                env_vars = data.get("env", {})
                if env_vars:
                    text = "Environment Variables:\n" + "\n".join([f"{k}: {v}" for k, v in env_vars.items()])
                else:
                    text = "No environment variables found."
            else:
                text = f"Failed to retrieve environment variables. Status: {resp.status}"
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

# Prompt to change environment variables.
@dp.callback_query_handler(lambda c: c.data.startswith("changeenv_"))
async def prompt_change_env(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    await bot.send_message(callback_query.from_user.id,
                           f"Please send the new environment variable in the format:\n"
                           f"ChangeEnv: {account_id} <key> <value>")
    await bot.answer_callback_query(callback_query.id)

# Handle message to change an environment variable (format: ChangeEnv: <account_id> <key> <value>)
@dp.message_handler(lambda message: message.text and message.text.startswith("ChangeEnv:"))
async def handle_change_env(message: types.Message):
    try:
        _, details = message.text.split(":", 1)
        parts = details.strip().split(" ", 2)
        if len(parts) < 3:
            raise ValueError("Insufficient data")
        account_id = parts[0].strip()
        key = parts[1].strip()
        value = parts[2].strip()
    except Exception:
        await message.reply("Invalid format. Use: ChangeEnv: <account_id> <key> <value>")
        return
    account = await get_account_by_id(account_id)
    if not account:
        await message.reply("Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await message.reply("No app found for this account.")
        return
    app_id = free_app.get("id")
    payload = {"env": {key: value}}
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}", "Content-Type": "application/json"}
        async with session.patch(f"https://app.koyeb.com/api/v1/apps/{app_id}/env", headers=headers, json=payload) as resp:
            if resp.status == 200:
                text = f"Environment variable '{key}' updated successfully."
            else:
                text = f"Failed to update environment variable. Status: {resp.status}"
    await message.reply(text)

# Delete an account from the database
@dp.callback_query_handler(lambda c: c.data.startswith("delete_"))
async def delete_account(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    from bson import ObjectId
    result = await accounts_collection.delete_one({"_id": ObjectId(account_id)})
    if result.deleted_count:
        text = "Account deleted successfully."
    else:
        text = "Failed to delete account."
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)
    await show_start(callback_query.from_user.id)

# -------------------- Webhook Setup --------------------

async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(dp):
    logging.warning("Shutting down..")
    await bot.delete_webhook()

if __name__ == '__main__':
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host="0.0.0.0",
        port=PORT,
    )
