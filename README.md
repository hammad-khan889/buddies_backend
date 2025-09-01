Restaurant Management System - README
Yeh Project Kya Hai?
Yeh ek restaurant management system hai jo FastAPI ke zariye banaya gaya hai. Ismein customers ke orders ko manage karna, menu items aur deals ko add/update/delete karna, aur voice commands ke zariye orders lena shamil hai. Yeh system MongoDB, Cloudinary, aur AI-based agents ka istemaal karta hai.
Maine Kya Kaam Kiya Hai?
1. FastAPI Backend

Setup: FastAPI ka server banaya jo http://localhost:3000 se frontend ke sath connect hota hai (CORS enabled).
Endpoints:
Products: Menu items ko add (/products), list (/products), single item dekhnay (/products/{id}), update (/products/{id}), aur delete (/products/{id}) ke endpoints banaye.
Deals: Deals ke liye bhi same tarah ke endpoints banaye (/deals, /deals/{id}).
Orders: Orders create karne ke liye endpoint banaya (/orders) jo table number, items, aur total amount save karta hai.
Voice Agent: Voice input ke liye endpoint (/voice-agent) jo audio file leta hai aur response deta hai.
Text Agent: Text-based queries ke liye endpoint (/agent) jo AI agent ke sath kaam karta hai.



2. Database (MongoDB)

MongoDB ka istemal karke products, deals, aur orders ke collections banaye.
Items ko JSON-compatible banane ke liye serialize_item function banaya.
Orders ko table number ke sath save kiya aur items aur total amount track kiya.

3. Image Upload

Cloudinary ka istemal karke menu items aur deals ke images upload karne ka system banaya.
Har image ka secure URL database mein save hota hai.

4. AI Agent

Gemini API (gemini-2.0-flash) ka istemal karke do agents banaye:
Greeting Agent: User ke "hi", "hello" jaisay greetings ka jawab deta hai.
Order Agent: Orders place karne, table ka total bill check karne, aur order details dikhane ke tools ke sath kaam karta hai.


Tools banaye:
place_order_tool: Table number aur item name ke sath order place karta hai.
get_table_total: Table ka total bill batata hai.
list_all_orders: Sab orders ki list deta hai.
get_table_order_details: Table ke order ki details deta hai.



5. Voice Agent

Speech-to-Text: Whisper model (base) ka istemal karke audio ko text mein convert kiya.
Text-to-Speech: pyttsx3 aur ffmpeg ka istemal karke text ko MP3 audio mein convert kiya.
Features:
Greetings ka jawab dena (e.g., "Hello, what would you like to order?").
Table number extract karna regex ke zariye.
Menu items ko fuzzy matching (rapidfuzz) se find karna.
Orders place karna, bill check karna, aur order details dikhana.


Audio files ko generated_audio folder mein save kiya aur /voice-audio/{filename} se serve kiya.

6. Server

Uvicorn ka istemal karke server ko port 8000 (ya environment variable PORT) pe chalaya.

Kya Kya Install Kiya Hai?
Yeh dependencies uv add ke zariye install ki hain:
uv add fastapi uvicorn python-dotenv pymongo cloudinary pyttsx3 whisper rapidfuzz

Aur yeh additional tools ya services:

MongoDB: Database ke liye  cloud pe install kiya (MONGO_URI set kiya).
Cloudinary: Image uploads ke liye account banaya aur environment variables (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET) set kiye.
Gemini API: AI agent ke liye API key (GEMINI_API_KEY) set kiya.
ffmpeg: Text-to-speech ke liye MP3 to wav conversion ke liye install kiya usko windows environment variable mai path mai ja k link save kya.(system-level dependency).
Whisper: OpenAI ka Whisper model audio transcription ke liye install kiya.

Environment Variables
In environment variables ko .env file mein set kiya:

MONGO_URI: MongoDB connection string.
CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET: Cloudinary ke liye.
Gemini_API_KEY: Gemini API ke liye.
WHISPER_MODEL: Whisper model ka naam (default: base).
PORT: Server port (default: 8000).


program ko run kese kren :
uv run uvicorn main:app --reload
phir ek file banai hai jis ka name test_voice_agent.py hai . us mai recorded voice ka path day k voice mai testing ki.
phir us file ko server chalane k bad python test_voice_agent ko run kya 



ffmpeg install karein (system pe, e.g., apt-get install ffmpeg ya brew install ffmpeg).
Server chalayein:python main.py


Frontend se connect karein (http://localhost:3000) ya API endpoints test karein (e.g., Postman).


https://convertio.co/m4a-wav/ isko use kya mp3 ko wav mai convert krne k lye.

https://www.gyan.dev/ffmpeg/builds/ is link mai se ffmpeg-release-full.7z is ko down load kya phir us file ko extract kr k us mai se bin file mai gay or phir us bin file k path ka link ko windows environment variable mai ja k system variables k path mai new mai ja k link ko update kya.jis  mai whisper mai audio support hoti hai

Agla Kaam

Input validation ko mazboot karna (e.g., price ko float mein convert karna).
Error handling behtar karna (e.g., MongoDB connection errors).
Voice agent ke liye multi-turn conversation support add karna.
Unit tests likhna.
Audio files ka cleanup system banana.

A