let userWalletAddress = null;
let ws = null;
let currentFilter = "ALL";
let searchQuery = "";

function base64ToUint8Array(base64) {
    const binaryString = window.atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
}

async function connectPhantomWallet() {
    if ("solana" in window && window.solana.isPhantom) {
        try {
            const resp = await window.solana.connect();
            userWalletAddress = resp.publicKey.toString();
            
            const btn = document.getElementById("connect-wallet-btn");
            if (btn) {
                btn.innerText = `${userWalletAddress.slice(0, 4)}...${userWalletAddress.slice(-4)}`;
                btn.className = "bg-gradient-to-b from-white to-zinc-300 text-black font-extrabold px-5 py-2 rounded-xl text-xs shadow-[0_4px_15px_rgba(0,0,0,0.8)] border border-white hover:scale-105 transition-all duration-300";
            }
        } catch (err) {
            console.error("Wallet connection rejected:", err);
        }
    } else {
        window.open("https://phantom.app/", "_blank");
    }
}

async function executeQuickSwap(mintAddress, solAmount, isGraduated, event) {
    createLiquidRipple(event);
    if (!isGraduated) {
        window.open(`https://pump.fun/coin/${mintAddress}`, "_blank");
        return;
    }
    if (!userWalletAddress) {
        alert("Please connect your Phantom Wallet first!");
        await connectPhantomWallet();
        if (!userWalletAddress) return;
    }
    try {
        const response = await fetch("/api/jupiter/swap", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                userPublicKey: userWalletAddress,
                outputMint: mintAddress,
                solAmount: solAmount
            })
        });
        const data = await response.json();
        if (!data.swapTransaction) {
            alert("Jupiter quote unavailable for this token yet.");
            return;
        }
        const swapTransactionBuf = base64ToUint8Array(data.swapTransaction);
        const transaction = solanaWeb3.VersionedTransaction.deserialize(swapTransactionBuf);
        const { signature } = await window.solana.signAndSendTransaction(transaction);
        alert(`Swap Submitted! Tx: https://solscan.io/tx/${signature}`);
    } catch (error) {
        console.error("Swap error:", error);
        alert("Transaction failed or canceled.");
    }
}

// Viscous Amoeba Splash Effect
function createLiquidRipple(e) {
    if (!e || !e.currentTarget) return;
    const btn = e.currentTarget;
    const rect = btn.getBoundingClientRect();
    
    const splash = document.createElement("span");
    const diameter = Math.max(rect.width, rect.height) * 1.5;
    
    splash.style.width = splash.style.height = `${diameter}px`;
    splash.style.left = `${e.clientX - rect.left - diameter / 2}px`;
    splash.style.top = `${e.clientY - rect.top - diameter / 2}px`;
    splash.classList.add("liquid-splash");

    const existing = btn.getElementsByClassName("liquid-splash");
    Array.from(existing).forEach(el => el.remove());
    
    btn.appendChild(splash);

    setTimeout(() => {
        if (splash.parentNode === btn) {
            splash.remove();
        }
    }, 700);
}

async function loadCardMetadata(uri, mint) {
    if (!uri) return;
    let targetUri = uri;
    if (targetUri.startsWith("ipfs://")) {
        targetUri = `https://ipfs.io/ipfs/${targetUri.replace("ipfs://", "")}`;
    }
    try {
        const res = await fetch(`/api/metadata?uri=${encodeURIComponent(targetUri)}`);
        const data = await res.json();
        
        const imgEl = document.getElementById(`img-${mint}`);
        if (imgEl && data.image) {
            let imageUrl = data.image;
            if (imageUrl.startsWith("ipfs://")) {
                imageUrl = `https://ipfs.io/ipfs/${imageUrl.replace("ipfs://", "")}`;
            }
            imgEl.onload = () => {
                imgEl.classList.remove("hidden");
                const fallbackEl = document.getElementById(`fallback-icon-${mint}`);
                if (fallbackEl) fallbackEl.classList.add("hidden");
            };
            imgEl.src = imageUrl;
        }
    } catch (e) {}
}

function setFilter(filterType, btnElement) {
    currentFilter = filterType;
    
    document.querySelectorAll(".filter-btn").forEach(btn => {
        btn.className = "filter-btn text-zinc-400 bg-zinc-900/50 border border-zinc-700/50 hover:bg-zinc-800 hover:text-white px-5 py-2 rounded-xl font-bold transition-all duration-300";
    });
    
    if (btnElement) {
        btnElement.className = "filter-btn bg-gradient-to-b from-white to-zinc-300 text-black border-t border-white px-5 py-2 rounded-xl font-extrabold shadow-[0_4px_15px_rgba(0,0,0,0.8)] transition-all duration-300 scale-105";
    }
    applyCardFilters();
}

function handleSearch(query) {
    searchQuery = query.toLowerCase().trim();
    applyCardFilters();
}

function applyCardFilters() {
    const cards = document.querySelectorAll(".token-card");
    cards.forEach(card => {
        const isSafe = card.dataset.safe === "true";
        const isGraduated = card.dataset.graduated === "true";
        const textContent = card.innerText.toLowerCase();

        let matchesFilter = true;
        if (currentFilter === "SAFE" && !isSafe) matchesFilter = false;
        if (currentFilter === "RAYDIUM" && !isGraduated) matchesFilter = false;
        let matchesSearch = true;
        if (searchQuery && !textContent.includes(searchQuery)) matchesSearch = false;

        if (matchesFilter && matchesSearch) {
            card.classList.remove("hidden");
        } else {
            card.classList.add("hidden");
        }
    });
}

function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/feed`);

    ws.onmessage = (event) => {
        try {
            const token = JSON.parse(event.data);
            if (token.type === "token_mint") {
                renderTokenCard(token);
            }
        } catch (err) {
            console.error("WS Parse Error:", err);
        }
    };
    ws.onclose = () => setTimeout(initWebSocket, 3000);
}

function renderTokenCard(token) {
    const container = document.getElementById("cards-container");
    const placeholder = document.getElementById("connecting-placeholder");
    if (placeholder) {
        placeholder.remove();
    }

    const mint = token.mint || "";
    if (!mint || document.getElementById(`card-${mint}`)) return;

    const scoreNum = typeof token.score === "number" ? token.score : 0;
    const isSafe = token.is_safe || scoreNum >= 70;
    const isGraduated = token.is_graduated || false;

    const card = document.createElement("div");
    card.className = "token-card liquid-card-entry p-5 flex flex-col justify-between gap-4";
    card.id = `card-${mint}`;
    card.dataset.safe = isSafe;
    card.dataset.graduated = isGraduated;

    const trojanLink = `https://t.me/solana_trojanbot?start=r-solpulse-${mint}`;

    const externalIcon = `<svg class="w-4 h-4 transition-colors duration-300 stroke-[2.5]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>`;
    const botIcon = `<svg class="w-4 h-4 transition-colors duration-300 stroke-[2.5]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 2a2 2 0 0 1 2 2v2h3a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3V4a2 2 0 0 1 2-2zm-3 8h.01M15 10h.01M9 14h6"/></svg>`;

    card.innerHTML = `
        <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-3 min-w-0">
                <div class="w-11 h-11 rounded-xl bg-zinc-900 border border-zinc-700 border-t-zinc-500 flex items-center justify-center overflow-hidden shrink-0 shadow-[inset_0_2px_4px_rgba(0,0,0,0.6)]">
                    <img id="img-${mint}" 
                         class="w-full h-full object-cover hidden" 
                         onerror="this.classList.add('hidden'); document.getElementById('fallback-icon-${mint}').classList.remove('hidden');" 
                    />
                    <span id="fallback-icon-${mint}" class="text-xs font-black text-white uppercase tracking-wider">${(token.symbol || "???").slice(0, 3)}</span>
                </div>
                <div class="truncate">
                    <h3 class="font-extrabold text-base text-white truncate tracking-tight">${token.name || "Unnamed Token"}</h3>
                    <p class="text-xs font-bold text-zinc-400 tracking-wide">$${token.symbol || "???"}</p>
                </div>
            </div>
            
            <span class="text-xs font-mono-bold px-3 py-1.5 rounded-lg shrink-0 ${scoreNum >= 85 ? 'badge-score-safe' : 'badge-score-neutral'}">
                ${scoreNum.toFixed(0)}%
            </span>
        </div>

        <div class="bg-black border border-zinc-800 rounded-lg px-3 py-2 flex items-center justify-between shadow-[inset_0_2px_6px_rgba(0,0,0,0.9)]">
            <span class="text-[11px] font-mono-bold text-zinc-300 truncate tracking-wider select-all" title="${mint}">
                ${mint}
            </span>
        </div>

        <div class="grid grid-cols-2 gap-2.5 pt-1">
            <button onclick="window.executeQuickSwap('${mint}', 0.1, ${isGraduated}, event)" 
                    class="liquid-btn text-xs py-2.5 rounded-lg flex items-center justify-center gap-2">
                <span>${isGraduated ? 'Buy 0.1 SOL' : 'Pump.fun'}</span>
                ${externalIcon}
            </button>
            <a href="${trojanLink}" 
               target="_blank" 
               onclick="window.createLiquidRipple(event)"
               class="liquid-btn text-xs py-2.5 rounded-lg flex items-center justify-center gap-2">
                <span>Trojan Bot</span>
                ${botIcon}
            </a>
        </div>
    `;

    container.prepend(card);
    applyCardFilters();
    loadCardMetadata(token.uri, mint);
}

window.connectPhantomWallet = connectPhantomWallet;
window.executeQuickSwap = executeQuickSwap;
window.setFilter = setFilter;
window.handleSearch = handleSearch;
window.createLiquidRipple = createLiquidRipple;

document.addEventListener("DOMContentLoaded", initWebSocket);