import os
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(level=logging.INFO)

# Bot configuration
BOT_TOKEN = "6586633230:AAEVOfh-pBOsnZULNRDSBDssZ_ocOHFg7HU"
WEBHOOK_HOST = "https://purplestreambot-mrblackgod.koyeb.app"  # Your Koyeb domain
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# MongoDB configuration (explicit connection string with default database "koyebbot")
MONGODB_URI = "mongodb+srv://nehal969797:nehalsingh969797@cluster0.7ccmpy4.mongodb.net/koyebbot?retryWrites=true&w=majority&appName=Cluster0"
mongo_client = AsyncIOMotorClient(MONGODB_URI)
db = mongo_client.get_default_database()
accounts_collection = db["accounts"]

# Utility: Retrieve an account document by its ObjectId (as a string)
async def get_account_by_id(account_id: str):
    from bson import ObjectId
    try:
        account = await accounts_collection.find_one({"_id": ObjectId(account_id)})
        return account
    except Exception as e:
        logging.error("Error retrieving account: %s", e)
        return None

# Show start message and list all accounts (if any)
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
        text = "Welcome to Advanced Koyeb Manager Bot.\nSelect an account to manage:\n"
        for acc in accounts:
            # Display both service_id and account name
            text += f"Service ID: {acc.get('service_id')} | Name: {acc.get('name')}\n"
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        for acc in accounts:
            # Use the MongoDB _id as the identifier for callbacks
            keyboard.add(types.InlineKeyboardButton(f"{acc.get('service_id')} - {acc.get('name')}",
                                                    callback_data=f"account_{str(acc['_id'])}"))
        keyboard.add(types.InlineKeyboardButton("Add Account", callback_data="add_account"))
        await bot.send_message(chat_id, text, reply_markup=keyboard)

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await show_start(message.chat.id)

# Callback to add a new account
@dp.callback_query_handler(lambda c: c.data == "add_account")
async def process_add_account(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    text = ("Please add your Koyeb account info in the following format:\n\n"
            "AddAccount: <service_id> <account_name> <koyeb_api_key>\n\n"
            "Example:\n"
            "AddAccount: myService1 MyKoyebAccount ABCDEFGHIJKLMNOP")
    await bot.send_message(callback_query.from_user.id, text)

# Handle adding account message (format: AddAccount: <service_id> <account_name> <koyeb_api_key>)
@dp.message_handler(lambda message: message.text and message.text.startswith("AddAccount:"))
async def handle_add_account(message: types.Message):
    try:
        # Split into three parts after the colon
        _, details = message.text.split(":", 1)
        parts = details.strip().split(" ", 2)
        if len(parts) < 3:
            raise ValueError("Insufficient data")
        service_id = parts[0].strip()
        account_name = parts[1].strip()
        koyeb_api = parts[2].strip()
    except Exception:
        await message.reply("Invalid format. Use: AddAccount: <service_id> <account_name> <koyeb_api_key>")
        return

    account_data = {"service_id": service_id, "name": account_name, "api_key": koyeb_api}
    result = await accounts_collection.insert_one(account_data)
    if result.inserted_id:
        await message.reply(f"Account '{account_name}' with Service ID '{service_id}' added successfully!")
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
    text = (f"Managing account:\nService ID: {account.get('service_id')}\n"
            f"Name: {account.get('name')}\nSelect an action:")
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

@dp.callback_query_handler(lambda c: c.data == "back_accounts")
async def back_to_accounts(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await show_start(callback_query.from_user.id)

# Helper function to fetch the free app using a 30-second timeout
async def get_free_app(api_key: str):
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
        try:
            async with session.get("https://app.koyeb.com/api/v1/apps", headers=headers) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception as json_err:
                        logging.error("Failed to decode JSON from Koyeb API: %s", json_err)
                        return None
                    apps = data.get("apps", [])
                    if apps:
                        return apps[0]
                    else:
                        logging.error("No apps found in response: %s", data)
                        return None
                else:
                    text = await resp.text()
                    logging.error("Koyeb API returned status %s: %s", resp.status, text)
                    return None
        except Exception as e:
            logging.error("Error fetching free app: %s", e)
            return None

@dp.callback_query_handler(lambda c: c.data.startswith("redeploy_"))
async def redeploy_app(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found or error fetching app info.")
        return
    app_id = free_app.get("id")
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        try:
            async with session.post(f"https://app.koyeb.com/api/v1/apps/{app_id}/redeploy", headers=headers) as resp:
                if resp.status in (200, 201):
                    text = f"App '{free_app.get('name')}' redeployed successfully."
                else:
                    text = f"Failed to redeploy app. Status: {resp.status}"
        except Exception as e:
            logging.error("Error redeploying app: %s", e)
            text = "Error redeploying app."
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("logs_"))
async def see_logs(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found or error fetching app info.")
        return
    app_id = free_app.get("id")
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        try:
            async with session.get(f"https://app.koyeb.com/api/v1/apps/{app_id}/logs", headers=headers) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json(content_type=None)
                        logs = data.get("logs", [])
                        text = "Recent Logs:\n" + "\n".join(logs[-10:]) if logs else "No logs available."
                    except Exception as json_err:
                        text = f"Error decoding logs JSON: {json_err}"
                else:
                    text = f"Failed to retrieve logs. Status: {resp.status}"
        except Exception as e:
            logging.error("Error fetching logs: %s", e)
            text = "Error fetching logs."
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("stop_"))
async def stop_app(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found or error fetching app info.")
        return
    app_id = free_app.get("id")
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        try:
            async with session.post(f"https://app.koyeb.com/api/v1/apps/{app_id}/stop", headers=headers) as resp:
                if resp.status == 200:
                    text = f"App '{free_app.get('name')}' stopped successfully."
                else:
                    text = f"Failed to stop app. Status: {resp.status}"
        except Exception as e:
            logging.error("Error stopping app: %s", e)
            text = "Error stopping app."
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("resume_"))
async def resume_app(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found or error fetching app info.")
        return
    app_id = free_app.get("id")
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        try:
            async with session.post(f"https://app.koyeb.com/api/v1/apps/{app_id}/resume", headers=headers) as resp:
                if resp.status == 200:
                    text = f"App '{free_app.get('name')}' resumed successfully."
                else:
                    text = f"Failed to resume app. Status: {resp.status}"
        except Exception as e:
            logging.error("Error resuming app: %s", e)
            text = "Error resuming app."
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("env_"))
async def see_env(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    account = await get_account_by_id(account_id)
    if not account:
        await bot.answer_callback_query(callback_query.id, "Account not found.")
        return
    free_app = await get_free_app(account.get("api_key"))
    if not free_app:
        await bot.send_message(callback_query.from_user.id, "No app found or error fetching app info.")
        return
    app_id = free_app.get("id")
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}"}
        try:
            async with session.get(f"https://app.koyeb.com/api/v1/apps/{app_id}/env", headers=headers) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json(content_type=None)
                        env_vars = data.get("env", {})
                        text = "Environment Variables:\n" + "\n".join([f"{k}: {v}" for k, v in env_vars.items()]) if env_vars else "No environment variables found."
                    except Exception as json_err:
                        text = f"Error decoding env JSON: {json_err}"
                else:
                    text = f"Failed to retrieve environment variables. Status: {resp.status}"
        except Exception as e:
            logging.error("Error fetching environment variables: %s", e)
            text = "Error fetching environment variables."
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("changeenv_"))
async def prompt_change_env(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    await bot.send_message(callback_query.from_user.id,
                           f"Please send the new environment variable in the format:\nChangeEnv: {account_id} <key> <value>")
    await bot.answer_callback_query(callback_query.id)

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
        await message.reply("No app found or error fetching app info.")
        return
    app_id = free_app.get("id")
    payload = {"env": {key: value}}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = {"Authorization": f"Bearer {account.get('api_key')}", "Content-Type": "application/json"}
        try:
            async with session.patch(f"https://app.koyeb.com/api/v1/apps/{app_id}/env", headers=headers, json=payload) as resp:
                if resp.status == 200:
                    text = f"Environment variable '{key}' updated successfully."
                else:
                    text = f"Failed to update environment variable. Status: {resp.status}"
        except Exception as e:
            logging.error("Error updating environment variable: %s", e)
            text = "Error updating environment variable."
    await message.reply(text)

@dp.callback_query_handler(lambda c: c.data.startswith("delete_"))
async def delete_account(callback_query: types.CallbackQuery):
    account_id = callback_query.data.split("_", 1)[1]
    from bson import ObjectId
    result = await accounts_collection.delete_one({"_id": ObjectId(account_id)})
    text = "Account deleted successfully." if result.deleted_count else "Failed to delete account."
    await bot.send_message(callback_query.from_user.id, text)
    await bot.answer_callback_query(callback_query.id)
    await show_start(callback_query.from_user.id)

async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")

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
