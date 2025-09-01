import os
import tempfile
from dataclasses import dataclass
from typing import List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import speech_recognition as sr
from gtts import gTTS
import traceback
import subprocess
from datetime import datetime
import json
from rapidfuzz import process, fuzz 

from agents import (
    Agent, AsyncOpenAI, Runner, OpenAIChatCompletionsModel,
    RunContextWrapper, function_tool, trace
)
from agents.run import RunConfig

# ---------------- ENV & CONFIG ----------------
load_dotenv()

required_env_vars = ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "MONGO_URI", "GEMINI_API_KEY"]
for var in required_env_vars:
    if not os.getenv(var):
        raise RuntimeError(f" Missing environment variable: {var}")

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# ---------------- FASTAPI APP ----------------

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- DATABASE ----------------
client = MongoClient(os.getenv("MONGO_URI"))
db = client["menudb"]
products = db["products"]
deals = db["deals"]
orders = db["orders"]

# ---------------- HELPERS ----------------
def serialize_item(item):
    return {
        "_id": str(item["_id"]),
        "name": item.get("name", ""),
        "price": item.get("price", ""),
        "category": item.get("category", ""),
        "description": item.get("description", ""),
        "image": item.get("image", "")
    }

def upload_image_to_cloudinary(file: UploadFile) -> str:
    try:
        result = cloudinary.uploader.upload(file.file)
        return result["secure_url"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image upload failed: {e}")

def safe_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format.")

# ---------------- MODELS ----------------
class OrderItemModel(BaseModel):
    id: str = Field(..., alias="_id")
    name: str
    price: float
    category: str
    description: str
    image: str
    quantity: int

    class Config:
        populate_by_name = True

class OrderModel(BaseModel):
    tableNumber: str
    items: List[OrderItemModel]
    totalAmount: float

class OrderItem(BaseModel):
    product_name: str
    quantity: int
    price: float

class Order(BaseModel):
    table_number: int
    items: list[OrderItem]
    total: float
    timestamp: datetime = datetime.now()

@dataclass
class AllOrders:
    orders: List[Order]

def load_orders_context() -> AllOrders:
    all_orders = []
    for doc in orders.find():
        order_items = [
            OrderItem(
                product_name=item.get("name", "Unknown"),
                quantity=item.get("quantity", 1),
                price=item.get("price", 0.0)
            ) for item in doc.get("items", [])
        ]
        all_orders.append(Order(
            table_number=doc.get("tableNumber"),
            items=order_items,
            total=doc.get("totalAmount", 0)
        ))
    return AllOrders(orders=all_orders)

# ---------------- PRODUCT ENDPOINTS ----------------
@app.post("/products")
async def add_product(
    name: str = Form(...),
    price: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    image: UploadFile = File(...)
):
    image_url = upload_image_to_cloudinary(image)
    products.insert_one({
        "name": name,
        "price": price,
        "category": category,
        "description": description,
        "image": image_url
    })
    return {"success": True, "message": "Product added successfully"}

@app.get("/products")
def get_all_products():
    menu = {}
    for item in products.find():
        cat = item.get("category", "Uncategorized")
        menu.setdefault(cat, []).append(serialize_item(item))
    return menu

@app.get("/products/{product_id}")
def get_product(product_id: str):
    product = products.find_one({"_id": safe_object_id(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize_item(product)

# ---------------- DEALS ENDPOINTS ----------------
@app.post("/deals")
async def add_deal(
    name: str = Form(...),
    price: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    image: UploadFile = File(...)
):
    image_url = upload_image_to_cloudinary(image)
    deals.insert_one({
        "name": name,
        "price": price,
        "category": category,
        "description": description,
        "image": image_url
    })
    return {"success": True, "message": "Deal added successfully"}

@app.get("/deals")
def get_all_deals():
    deal_list = {}
    for item in deals.find():
        cat = item.get("category", "Uncategorized")
        deal_list.setdefault(cat, []).append(serialize_item(item))
    return deal_list

# ---------------- ORDERS ----------------
@app.post("/orders")
async def create_order(order: OrderModel):
    try:
        orders.insert_one(order.model_dump(by_alias=True))
        return {"success": True, "message": "Order submitted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------- AGENTS SETUP ----------------
external_client = AsyncOpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)
model = OpenAIChatCompletionsModel(
    model="gemini-2.0-flash",
    openai_client=external_client,
)
run_config = RunConfig(model=model, model_provider=external_client)

@function_tool
async def greet_user(wrapper: RunContextWrapper[None]) -> str:
    return "Hello!  Welcome to Buddies party. Have a great day and a great meal with your buddies. What would you like to order?"

@function_tool
async def show_menu_tool(wrapper: RunContextWrapper[None]) -> dict:
    return {"message": "Ok, I am showing you the menu.", "redirect": True, "redirect_url": "/menu"}

@function_tool
async def add_to_order_tool(
    wrapper: RunContextWrapper[None],
    table_number: int,
    product_name: str,
    quantity: int
) -> dict:
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get("http://localhost:8000/products")
        products_data = response.json()

    # Flatten products (since products are grouped by category)
    all_products = []
    for category, items in products_data.items():
        all_products.extend(items)

    #  First try exact match
    product = next((p for p in all_products if p["name"].lower() == product_name.lower()), None)

    #  If exact match not found → try fuzzy match with rapidfuzz
    if not product and all_products:
        product_names = [p["name"] for p in all_products]
        best_match, score, idx = process.extractOne(
            product_name, product_names, scorer=fuzz.ratio
        )
        if score >= 70:  # Threshold (adjustable)
            product = all_products[idx]

    if not product:
        return {
            "message": f" Sorry, {product_name} is not available in our menu.",
            "table_number": table_number,
            "items": [],
            "total": 0,
            "redirect": False,
            "redirect_url": "",
            "audio_url": ""
        }

    # Product found
    price = float(product.get("price", 0))
    subtotal = price * quantity

    return {
        "message": f" {quantity} x {product['name']} (Rs {price} each) added to Table {table_number}'s order. Total Rs {subtotal}.",
        "table_number": table_number,
        "items": [
            {
                "name": product["name"],
                "quantity": quantity,
                "price": price,
                "subtotal": subtotal,
                "image": product.get("image", "")
            }
        ],
        "total": subtotal,
        "redirect": True,
        "redirect_url": "/order_summary",
        "audio_url": "/agent-audio?file=bdlz401o.mp3"
    }

class OrderToolItem(BaseModel):
    name: str
    quantity: int
    
@function_tool
async def place_order(
    wrapper: RunContextWrapper[None],
    table_number: int,
    items: list[OrderToolItem]
) -> dict:
    """
    Final order ko DB me save karega (sirf confirmation pe).
    """
    validated_items = []
    total = 0

    for item in items:
        product = products.find_one(
            {"name": {"$regex": f"^{item.name}$", "$options": "i"}}
        )
        if not product:
            return {"message": f" Item '{item.name}' not found in menu."}

        price = float(product.get("price", 0))
        subtotal = price * item.quantity

        validated_items.append({
            "_id": str(product["_id"]),
            "name": product["name"],
            "quantity": item.quantity,
            "price": price,
            "subtotal": subtotal,
            "category": product.get("category", ""),
            "description": product.get("description", ""),
            "image": product.get("image", "")
        })
        total += subtotal

    order_doc = {
        "tableNumber": table_number,  
        "items": validated_items,
        "totalAmount": total,
        "timestamp": datetime.now()
    }

    orders.insert_one(order_doc)

    return {
        "message": f" Order confirmed & saved for Table {table_number}! Total bill Rs {total}",
        "success": True,
        "table_number": table_number,
        "items": validated_items,
        "total": total,
        "redirect": True,
        "redirect_url": "/order_summary"
    }

# ===================================Agents=======================================
# Order Agent
order_agent = Agent[dict](
    name="Order Assistant",
    instructions="""
You are responsible ONLY for finalizing orders.

- If the user says any phrase indicating order confirmation (such as "confirm order", "ok confirm order", "finalize order", "place my order", "submit order", "order now", "done with order", "complete my order", or similar), you MUST call the `place_order` tool IMMEDIATELY.
- If an `order_summary` is provided in the context, ALWAYS use its `table_number` and `items` for the `place_order` tool call, regardless of the user's message content.
- If `order_summary` is NOT present in the context, you MUST extract both `table_number` and `items` from the user's message. If either is missing or cannot be determined, return an error dict with a clear message (e.g., {"message": "❌ Please specify both table number and items to confirm your order."}) and STOP.
- NEVER attempt to guess or invent items or table numbers if they are not provided.
- After calling `place_order` and returning its output, you MUST STOP. Do NOT continue the conversation, do NOT call any other tool, and do NOT generate any additional messages.
- Do NOT generate normal text responses. Only return the output from the `place_order` tool or an error dict as described above.
- Do NOT loop or retry if there is an error; simply return the error dict and STOP.
""",
    model=model,
    tools=[place_order]
)    




greeting_agent = Agent[None](
    name="Greeting Assistant",
    instructions="""
Always call the tool `greet_user` when you receive any greeting like "hello", "hi", "salam".
Do not reply by yourself. You must call the tool.
""",
    model=model,
    tools=[greet_user]
)

menu_agent = Agent[None](
    name="Menu Assistant",
    instructions="""
When the user says anything related to menu (e.g., "menu", "show me menu", "show me foods", "mujhe menu"),
you MUST call the tool `show_menu_tool`. 
Never respond directly yourself.
""",
    model=model,
    tools=[show_menu_tool]
)

add_to_order_agent = Agent[dict](
    name="Add to Order Assistant",
    instructions="""
You are responsible for adding items to the order.
If the user says something like "table 2 order 1 pizza 2 burger ...":
- Parse table_number and all items with their quantities from the message.
- For each item, call `add_to_order_tool` with table_number, product_name, and quantity.
- After calling the tool for all items, collect all added items from the tool outputs into an `order_summary` dict with:
    - table_number
    - items (list of dicts from tool outputs, combining all items)
    - total (sum of all subtotals)
    - message (combined messages, e.g., "Added: item1, item2")
    - redirect: True
    - redirect_url: "/order_summary"
- If any item fails, include the error in the message.
- Return this `order_summary` as your final response.
- Do not generate normal text responses.
Example: For "table 2 order 1 Chinese rice 2 soup", call tool twice, collect outputs, combine items list, sum totals, and return the summary dict.
""",
    model=model,
    tools=[add_to_order_tool]
)

main_agent = Agent[None](
    name="Main Restaurant Agent",
    instructions="""
You are the main restaurant assistant.
- If the user says "hello", "hi", "salam", you must handoff to Greeting Assistant. 
- If the user asks about "menu", "show me menu", "show me foods", "mujhe menu", you must handoff to Menu Assistant. 
- If the user says something like "table 2 order 1 pizza", handoff to Add to Order Assistant.
- If the user says something like "confirm order", "ok confirm order", "finalize order", or "place order", handoff to Order Assistant.
Do not answer by yourself.
""",
    model=model,
    tools=[],
    handoffs=[greeting_agent, menu_agent, order_agent, add_to_order_agent]
)
# ---------------- AGENT ROUTE ----------------
@app.post("/agent")
async def ask_agent(
    question: str = Form(None),
    audio: UploadFile = File(None),
    order_summary: str = Form(None)
):
    try:
        # ( audio to text conversion)
        if audio:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio:
                temp_audio.write(await audio.read())
                temp_audio_path = temp_audio.name

            temp_wav_path = tempfile.mktemp(suffix=".wav")
            subprocess.run(
                ["ffmpeg", "-y", "-i", temp_audio_path, temp_wav_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            recognizer = sr.Recognizer()
            with sr.AudioFile(temp_wav_path) as source:
                audio_data = recognizer.record(source)
                question = recognizer.recognize_google(audio_data)

            os.remove(temp_audio_path)
            os.remove(temp_wav_path)

        if not question:
            raise HTTPException(status_code=400, detail="No question or audio provided.")

        #  run the agent
        with trace("Restaurant Management"):  
            print("order summary --------------------> ", order_summary)
            context = json.loads(order_summary) if order_summary else None

            result = await Runner.run(main_agent, question, run_config=run_config, context=context)
            final_output = result.final_output

            print("FINAL OUTPUT FROM AGENT:", final_output)

            # --- Default response ---
            response_data = {
                "message": "",
                "redirect": False,
                "redirect_url": None,
                "table_number": None,
                "items": [],
                "total": 0,
            }

            # Agar dict aayi
            if isinstance(final_output, dict):
                for key in ["message", "redirect", "redirect_url", "table_number", "items", "total", "success"]:
                    if key in final_output:
                        response_data[key] = final_output[key]

            # Agar string aayi
            elif isinstance(final_output, str):
                try:
                    cleaned_output = final_output.strip()
                    if cleaned_output.startswith("```json\n") and cleaned_output.endswith("\n```"):
                        cleaned_output = cleaned_output[7:-3].strip()
                    parsed_output = json.loads(cleaned_output)
                    if isinstance(parsed_output, dict):
                        for key in ["message", "redirect", "redirect_url", "table_number", "items", "total", "success"]:
                            if key in parsed_output:
                                response_data[key] = parsed_output[key]
                    else:
                        response_data["message"] = final_output
                except json.JSONDecodeError:
                    response_data["message"] = final_output

            #  Force redirect logic
            question_lower = question.lower()
            if ("menu" in question_lower or "show menu" in question_lower or "mujhe menu" in question_lower) and not response_data["redirect"]:
                response_data["redirect"] = True
                response_data["redirect_url"] = "/menu"
            elif ("order" in question_lower or "order confirmation" in question_lower or "my order" in question_lower or "mera order" in question_lower) and not response_data["redirect"]:
                response_data["redirect"] = True
                response_data["redirect_url"] = "/order_summary"

            #  SPECIAL HANDLING for confirm order
            if "confirm order" in question_lower:
                try:
                    if context and context.get("table_number") and context.get("items"):
                        #  MongoDB me order save karo
                        saved_order = {
                            "tableNumber": context["table_number"],
                            "items": context["items"],
                            "totalAmount": context.get("total", 0),
                            "timestamp": datetime.now()
                        }
                        orders.insert_one(saved_order)

                        response_data.update({
                            "message": " Order confirmed and saved successfully!",
                            "redirect": True,
                            "redirect_url": "/order_summary",
                            "table_number": saved_order["tableNumber"],
                            "items": saved_order["items"],
                            "total": saved_order["totalAmount"],
                        })
                    else:
                        response_data["message"] = (
                            " Please specify both table number and items to confirm your order."
                        )
                except Exception as e:
                    print(" Order save error:", e)
                    response_data["message"] = " Failed to confirm order. Please try again."

            # 🎤 TTS - hamesha message ko speech banao
            if response_data["message"]:
                tts = gTTS(response_data["message"], lang="en")
                audio_file_path = os.path.join(
                    tempfile.gettempdir(), next(tempfile._get_candidate_names()) + ".mp3"
                )
                tts.save(audio_file_path)
                response_data["audio_url"] = f"/agent-audio?file={os.path.basename(audio_file_path)}"

            print("FINAL RESPONSE DATA:", response_data)
            return response_data

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agent-audio")
async def get_agent_audio(file: str):
    file_path = os.path.join(tempfile.gettempdir(), file)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(file_path, media_type="audio/mpeg", filename=file)

# ---------------- SERVER ----------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)