import asyncio
import json
import random
import sqlite3
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from loguru import logger

# ----------------- CONFIGURATION -----------------
SOLANA_FEE_WALLET = "39VttoJxF782iP7sUkGXLXAi6voYtQqkJKcUucjbiY5f"
TELEGRAM_BOT_TOKEN = "8873189532:AAH-skWsB-PvcBjSUBHj4pKD7BDzsrhVraE"
TELEGRAM_CHAT_ID = "7251785751"

TROJAN_REF = "solpulse"
TELEGRAM_MIN_SCORE = 85.0
TELEGRAM_COOLDOWN_SECONDS = 900
LAST_TELEGRAM_SENT_TIME = 0.0

JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API = "https://quote-api.jup.ag/v6/swap"
WSOL_MINT = "So11111111111111111111111111111111111111112"

clients: list[WebSocket] = []

# ----------------- RATE LIMITING -----------------
IP_REQUEST_LOGS = defaultdict(list)
RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW = 60

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    asyncio.create_task(listen_pump_fun())
    yield

app = FastAPI(title="SolPulse Pro", version="18.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.middleware("http")
async def server_guard_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()
    
    IP_REQUEST_LOGS[client_ip] = [
        t for t in IP_REQUEST_LOGS[client_ip] if now - t < RATE_LIMIT_WINDOW
    ]
    
    if len(IP_REQUEST_LOGS[client_ip]) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")
        
    IP_REQUEST_LOGS[client_ip].append(now)
    return await call_next(request)

# ----------------- FIREWALL & DB -----------------
class TokenFirewall:
    @staticmethod
    def inspect(token_data: dict) -> tuple[bool, str]:
        mint = token_data.get("mint", "")
        name = str(token_data.get("name", "")).strip()
        symbol = str(token_data.get("symbol", "")).strip()

        if not mint or not name or not symbol:
            return False, "Missing metadata"
        if token_data.get("freezeAuthority") is not None:
            return False, "Active freeze authority"
        if token_data.get("devHoldingPct", 0) > 15.0:
            return False, "Excessive dev holding"
        if len(symbol) > 10 or len(name) > 60:
            return False, "Malicious length"

        return True, "PASSED"

def init_db():
    conn = sqlite3.connect("solpulse.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mint TEXT UNIQUE,
            name TEXT,
            symbol TEXT,
            uri TEXT,
            status TEXT,
            score REAL,
            is_graduated INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_token_to_db(data: dict, status: str, score: float, is_graduated: bool = False):
    try:
        conn = sqlite3.connect("solpulse.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO tokens (mint, name, symbol, uri, status, score, is_graduated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get("mint"), 
            data.get("name"), 
            data.get("symbol"), 
            data.get("uri"), 
            status, 
            score, 
            1 if is_graduated else 0
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Error: {e}")

class AIAdvancedAnalyzer:
    @staticmethod
    def score_token(token_data: dict) -> tuple[bool, float, str]:
        name = str(token_data.get("name", "")).strip()
        symbol = str(token_data.get("symbol", "")).strip()
        uri = str(token_data.get("uri", "")).strip()
        
        score = 40.0
        blacklist = ["test", "scam", "rug", "fake", "nsfw", "pool", "airdrop", "free", "claim", "pump"]
        if any(bad in f"{name.lower()} {symbol.lower()}" for bad in blacklist):
            return False, 10.0, "Blacklisted Keywords"

        if uri and (uri.startswith("http") or uri.startswith("ipfs://")):
            score += 25.0
        else:
            return False, 20.0, "Invalid Metadata URI"
            
        if symbol.isupper() and 2 <= len(symbol) <= 6:
            score += 15.0
        if token_data.get("image") or "ipfs" in uri or "arweave" in uri:
            score += 10.0
        if 3 <= len(name) <= 25:
            score += 10.0

        is_elite = score >= 70.0
        reason = "Verified High Quality" if score >= 85.0 else ("Verified Safe" if is_elite else "Filtered")
        return is_elite, score, reason

async def send_telegram_alert(token_data: dict, score: float, is_graduated: bool = False):
    global LAST_TELEGRAM_SENT_TIME
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        return
        
    now = time.time()
    if score < TELEGRAM_MIN_SCORE and not is_graduated:
        return
    if (now - LAST_TELEGRAM_SENT_TIME) < TELEGRAM_COOLDOWN_SECONDS:
        return
        
    LAST_TELEGRAM_SENT_TIME = now

    symbol = token_data.get("symbol", "???").replace("_", "\\_").replace("*", "\\*")
    name = token_data.get("name", "Unnamed").replace("_", "\\_").replace("*", "\\*")
    mint = token_data.get("mint", "")
    
    header = "💎 HIGH-CONFIDENCE RAYDIUM MIGRATION" if is_graduated else "🔥 HIGH SCORE ALERT (85-100%)"
    trade_url = f"https://pump.fun/coin/{mint}?ref={SOLANA_FEE_WALLET}"
    
    message = (
        f"*{header}*\n\n"
        f"📌 *{name}* (`${symbol}`)\n"
        f"🎯 Quality Score: `{score:.1f}/100`\n"
        f"🔑 Mint: `{mint}`\n\n"
        f"🛒 [Trade on Pump.fun]({trade_url})\n"
        f"🤖 [Trade on Trojan](https://t.me/solana_trojanbot?start=r-{TROJAN_REF}-{mint})"
    )
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
            )
        except Exception as e:
            logger.error(f"Telegram error: {e}")

# ----------------- BACKGROUND PUMP.FUN LISTENER -----------------
async def listen_pump_fun():
    uri = "wss://pumpportal.fun/api/data"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=None) as websocket:
                await websocket.send(json.dumps({"method": "subscribeNewToken"}))
                
                async for message in websocket:
                    data = json.loads(message)
                    passed, firewall_reason = TokenFirewall.inspect(data)
                    if not passed:
                        continue

                    tx_type = data.get("txType", "")
                    is_migration = tx_type == "migrate" or data.get("vTokensInBondingCurve") == 0
                    
                    if tx_type == "create" or "mint" in str(data).lower() or is_migration:
                        is_elite, score, reason = AIAdvancedAnalyzer.score_token(data)
                        if is_migration:
                            reason = "Graduated to Raydium"
                            score = max(score, 90.0)
                            is_elite = True
                        
                        save_token_to_db(data, reason, score, is_graduated=is_migration)
                        
                        payload = {
                            "type": "token_mint",
                            "mint": data.get("mint"),
                            "name": data.get("name", "Unnamed"),
                            "symbol": data.get("symbol", "???"),
                            "uri": data.get("uri", ""),
                            "is_safe": is_elite,
                            "score": float(score),
                            "reason": reason,
                            "is_graduated": is_migration,
                            "timestamp": time.strftime("%H:%M:%S")
                        }
                        
                        for client in clients:
                            try:
                                await client.send_json(payload)
                            except Exception:
                                pass

                        if score >= TELEGRAM_MIN_SCORE:
                            asyncio.create_task(send_telegram_alert(data, score, is_graduated=is_migration))

        except Exception as e:
            logger.error(f"PumpPortal connection error: {e}")
            await asyncio.sleep(3)

# ----------------- API ENDPOINTS -----------------

@app.get("/api/metadata")
async def fetch_metadata(uri: str = Query(...)):
    if not uri:
        return JSONResponse({"image": "", "twitter": "", "telegram": "", "website": ""})
    
    target_url = uri
    if target_url.startswith("ipfs://"):
        target_url = f"https://ipfs.io/ipfs/{target_url.replace('ipfs://', '')}"

    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
        try:
            res = await client.get(target_url)
            if res.status_code == 200:
                data = res.json()
                img = data.get("image", "")
                if img.startswith("ipfs://"):
                    img = f"https://ipfs.io/ipfs/{img.replace('ipfs://', '')}"
                
                return JSONResponse({
                    "image": img,
                    "twitter": data.get("twitter", ""),
                    "telegram": data.get("telegram", ""),
                    "website": data.get("website", "")
                })
        except Exception:
            pass

    return JSONResponse({"image": "", "twitter": "", "telegram": "", "website": ""})

class SwapRequest(BaseModel):
    userPublicKey: str
    outputMint: str
    solAmount: float

@app.post("/api/jupiter/swap")
async def generate_jupiter_swap(req: SwapRequest):
    lamports = int(req.solAmount * 1_000_000_000)
    
    async with httpx.AsyncClient() as client:
        try:
            quote_res = await client.get(
                JUPITER_QUOTE_API,
                params={
                    "inputMint": WSOL_MINT,
                    "outputMint": req.outputMint,
                    "amount": lamports,
                    "slippageBps": 100
                }
            )
            quote_data = quote_res.json()
            
            if "error" in quote_data:
                raise HTTPException(status_code=400, detail="Unable to fetch swap quote")

            swap_res = await client.post(
                JUPITER_SWAP_API,
                json={
                    "quoteResponse": quote_data,
                    "userPublicKey": req.userPublicKey,
                    "wrapAndUnwrapSol": True,
                    "feeAccount": SOLANA_FEE_WALLET
                }
            )
            swap_data = swap_res.json()
            return JSONResponse({"swapTransaction": swap_data.get("swapTransaction")})

        except Exception as e:
            logger.error(f"Jupiter error: {e}")
            raise HTTPException(status_code=500, detail="Jupiter Swap routing failed")

# ----------------- DASHBOARD FRONTEND -----------------

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SOLPULSE | Liquid Glass Pro</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://unpkg.com/@solana/web3.js@latest/lib/index.iife.min.js"></script>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body class="min-h-screen text-zinc-100 flex flex-col antialiased selection:bg-white selection:text-black relative">

        <!-- Liquid Background Blobs -->
        <div class="liquid-bg-container">
            <div class="liquid-blob liquid-blob-1"></div>
            <div class="liquid-blob liquid-blob-2"></div>
        </div>

        <!-- HEADER -->
        <header class="sticky top-0 z-50 glass-panel border-b border-white/10 px-6 py-4 mb-6">
            <div class="max-w-7xl mx-auto flex justify-between items-center relative z-10">
                <div class="flex items-center gap-3">
                    <h1 class="text-xl font-bold tracking-wider text-white">SOLPULSE</h1>
                </div>

                <div class="flex items-center gap-3">
                    <button id="connect-wallet-btn" onclick="window.connectPhantomWallet()" class="bg-white text-black font-semibold px-4 py-1.5 rounded-full text-xs shadow-lg hover:bg-zinc-200 transition-all duration-300">
                        Connect Wallet
                    </button>
                </div>
            </div>
        </header>

        <!-- MAIN DASHBOARD -->
        <main class="max-w-7xl mx-auto px-6 flex-1 w-full flex flex-col gap-6 pb-12 relative z-10">
            
            <div class="flex flex-col sm:flex-row justify-between items-stretch sm:items-center gap-4">
                <div class="flex items-center gap-2 p-1 rounded-full glass-panel border-white/10 text-xs self-start">
                    <button onclick="window.setFilter('ALL', this)" class="filter-btn glass-pill-active px-4 py-1.5 rounded-full font-medium transition-all duration-300">All Mints</button>
                    <button onclick="window.setFilter('SAFE', this)" class="filter-btn text-zinc-400 hover:text-white px-4 py-1.5 rounded-full font-medium transition-all duration-300">Verified Safe</button>
                    <button onclick="window.setFilter('RAYDIUM', this)" class="filter-btn text-zinc-400 hover:text-white px-4 py-1.5 rounded-full font-medium transition-all duration-300">Raydium Migrations</button>
                </div>

                <div class="relative min-w-[280px]">
                    <input type="text" id="search-input" oninput="window.handleSearch(this.value)" placeholder="Search mint, symbol, name..." 
                           class="w-full glass-panel px-4 py-2 rounded-full text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-white/30 transition-all duration-300">
                </div>
            </div>

            <!-- STREAM FEED CARDS -->
            <div id="cards-container" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div id="connecting-placeholder" class="col-span-full glass-panel rounded-2xl p-12 text-center text-zinc-500 text-sm">
                    Connecting to live Solana stream...
                </div>
            </div>
        </main>

        <script src="/static/script.js"></script>
    </body>
    </html>
    """

@app.websocket("/ws/feed")
async def websocket_feed(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.remove(websocket)